"""EFW dogfooding 破坏性验证（只在 .pjt 的临时副本上运行）。

用法：
    python destructive_checks.py <real_pjt_dir> <work_dir>

覆盖：expected_rev 冲突 / rev 篡改 / 断链 / 层级环 / 陈旧锁 /
未提交事务 / COMMIT 后部分 apply + 恢复幂等 / Event 不可变性。
脚本不会写入 <real_pjt_dir>。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import project_tool.storage.recovery as recovery
from project_tool.application.service import ProjectService
from project_tool.domain.errors import ProjectIOError, RevisionConflict
from project_tool.domain.hashing import compute_rev
from project_tool.integrations import filesystem
from project_tool.storage import recover_all, scan_transactions
from project_tool.storage.local_state import lock_path

SOURCE = Path(sys.argv[1]).resolve()
WORK = Path(sys.argv[2]).resolve()
WORK.mkdir(parents=True, exist_ok=True)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def fresh(name: str) -> Path:
    root = WORK / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    shutil.copytree(SOURCE, root / ".pjt")
    return root


def first_task_id(svc: ProjectService) -> str:
    return svc.call("task.list", {})[0]["id"]


def hash_tree(paths) -> dict[str, str]:
    result: dict[str, str] = {}
    for base in (paths.objects, paths.events, paths.state):
        for path in sorted(base.rglob("*.json")):
            result[str(path.relative_to(paths.pjt))] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["project.json"] = hashlib.sha256(paths.project_json.read_bytes()).hexdigest()
    return result


# ---------------------------------------------------------------- 1 expected_rev
root = fresh("expected_rev")
svc = ProjectService.open(root)
tid = first_task_id(svc)
before = svc.call("task.get", {"task_id": tid})
svc.call("task.add_label", {"task_id": tid, "label": "race-window"})
try:
    svc.call(
        "task.set_status",
        {"task_id": tid, "status": "doing", "expected_rev": before["rev"]},
    )
    check("expected_rev conflict", False, "no RevisionConflict raised")
except RevisionConflict:
    check("expected_rev conflict", True, "REVISION_CONFLICT raised")

# ------------------------------------------------------------- 2 rev corruption
root = fresh("rev_corruption")
svc = ProjectService.open(root)
tid = first_task_id(svc)
path = svc.store.path_for("task", tid)
record = json.loads(path.read_text(encoding="utf-8"))
record["title"] += " TAMPERED"
filesystem.write_json(path, record)
doctor = svc.call("project.doctor", {})
task_check = next(c for c in doctor["checks"] if c["name"] == "objects.task")
check(
    "rev corruption detected",
    doctor["ok"] is False
    and any("rev mismatch" in detail for detail in task_check.get("details", [])),
)

# ------------------------------------------------------------ 3 broken reference
root = fresh("broken_reference")
svc = ProjectService.open(root)
tid = first_task_id(svc)
record = svc.store.get_raw("task", tid)
record["milestone_id"] = "MLS-01K8H2ZZZ0000000000000000"
record["rev"] = compute_rev(record)
filesystem.write_json(svc.store.path_for("task", tid), record)
doctor = svc.call("project.doctor", {})
ref_check = next(c for c in doctor["checks"] if c["name"] == "references")
check("broken reference detected", doctor["ok"] is False and ref_check["status"] == "error")

# ---------------------------------------------------------- 4 hierarchy cycle
root = fresh("hierarchy_cycle")
svc = ProjectService.open(root)
tasks = svc.call("task.list", {})
a, b = tasks[0]["id"], tasks[1]["id"]
for tid, parent in ((a, b), (b, a)):
    record = svc.store.get_raw("task", tid)
    record["parent_task_id"] = parent
    record["rev"] = compute_rev(record)
    filesystem.write_json(svc.store.path_for("task", tid), record)
doctor = svc.call("project.doctor", {})
hier = next(c for c in doctor["checks"] if c["name"] == "hierarchy")
check("hierarchy cycle detected", doctor["ok"] is False and hier["status"] == "error")

# ------------------------------------------------------------- 5 stale lock
root = fresh("stale_lock")
svc = ProjectService.open(root)
lock = lock_path(svc.paths)
lock.parent.mkdir(parents=True, exist_ok=True)
lock.write_text(
    json.dumps({"pid": 999_999_999, "lock_id": "LCK-DOGFOOD", "created_at": time.time() - 3600}),
    encoding="utf-8",
)
doctor = svc.call("project.doctor", {})
lock_check = next(c for c in doctor["checks"] if c["name"] == "write.lock")
repaired = svc.call("project.recover", {})
check(
    "stale lock detected & cleaned",
    lock_check["repairable"] is True and repaired["count"] == 0 and not lock.exists(),
)

# ------------------------------------------------------- 6 uncommitted staging
root = fresh("uncommitted_txn")
svc = ProjectService.open(root)
txn = svc.paths.transactions / "TXN-DOGFOOD-ORPHAN"
filesystem.write_json(txn / "staged" / "objects" / "tasks" / "TSK-FAKE.json", {"id": "TSK-FAKE"})
doctor = svc.call("project.doctor", {})
txn_check = next(c for c in doctor["checks"] if c["name"] == "transactions")
assert txn_check["repairable"] is True
results = recover_all(svc.paths)
doctor = svc.call("project.doctor", {})
txn_check = next(c for c in doctor["checks"] if c["name"] == "transactions")
check(
    "uncommitted staging discarded",
    results[0].action == "discarded" and txn_check["status"] == "ok",
)

# -------------------------------------- 7 partial apply + idempotent recovery
root = fresh("partial_apply")
svc = ProjectService.open(root)
before_tasks = len(svc.call("task.list", {}))

real_replace = os.replace
counter = {"n": 0}


def crash_after_first(src, dst):
    target = str(dst).replace("\\", "/")
    canonical = "/staged/" not in target and ("/objects/" in target or "/events/" in target)
    if canonical:
        counter["n"] += 1
        if counter["n"] > 1:
            raise OSError("dogfood injected crash")
    return real_replace(src, dst)


recovery.os.replace = crash_after_first
try:
    try:
        svc.call("task.create", {"title": "dogfood interrupted task"})
        check("crash injection", False, "commit unexpectedly succeeded")
    except ProjectIOError:
        check("crash injection", True, "ProjectIOError raised")
finally:
    recovery.os.replace = real_replace

scans = scan_transactions(svc.paths)
check(
    "partial transaction scan",
    len(scans) == 1 and scans[0].committed and scans[0].repairable,
    f"status={scans[0].status if scans else 'none'}",
)
results = recover_all(svc.paths)
after_tasks = len(svc.call("task.list", {}))
doctor = svc.call("project.doctor", {})
check(
    "roll-forward recovery",
    results[0].action == "rolled_forward"
    and after_tasks == before_tasks + 1
    and doctor["ok"] is True,
)

baseline = hash_tree(svc.paths)
for _ in range(3):
    repeat = recover_all(svc.paths)
    assert all(r.action != "error" for r in repeat)
check("recovery idempotent", hash_tree(svc.paths) == baseline)

# -------------------------------------------------------- 8 event immutability
root = fresh("event_immutability")
svc = ProjectService.open(root)
before_hashes = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(svc.paths.events.rglob("EVT-*.json"))
}
tid = first_task_id(svc)
svc.call("task.add_label", {"task_id": tid, "label": "immutability-check"})
svc.call("task.create", {"title": "immutability probe"})
after_hashes = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(svc.paths.events.rglob("EVT-*.json"))
}
unchanged = all(after_hashes.get(name) == digest for name, digest in before_hashes.items())
check("event immutability", unchanged and len(after_hashes) > len(before_hashes))

# ---------------------------------------------------------------------- result
print()
if failures:
    print(f"RESULT: FAIL ({len(failures)}): {', '.join(failures)}")
    sys.exit(1)
print("RESULT: PASS (all destructive checks)")
