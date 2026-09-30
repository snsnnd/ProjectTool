from __future__ import annotations

import json
import os
import time

from project_tool.application.service import ProjectService
from project_tool.domain.hashing import compute_rev
from project_tool.integrations import filesystem
from project_tool.storage import init_project, open_project
from project_tool.storage.local_state import lock_path


def _check(result, name):
    return next(check for check in result["checks"] if check["name"] == name)


def test_clean_project_is_ok(service, seeded):
    result = service.call("project.doctor", {})
    assert result["ok"] is True
    assert result["summary"]["errors"] == 0
    names = {check["name"] for check in result["checks"]}
    assert "objects.task" in names
    assert "dependencies" in names
    assert "events" in names
    assert "events.chain" in names
    assert "transactions" in names
    assert "write.lock" in names


def test_tampered_object_reported(service, seeded):
    task_id = seeded["task"]["id"]
    path = service.store.path_for("task", task_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "tampered without rev update"
    filesystem.write_json(path, record)

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    task_check = _check(result, "objects.task")
    assert task_check["status"] == "error"
    assert any("rev mismatch" in detail for detail in task_check["details"])


def test_missing_reference_reported(service, seeded):
    milestone_id = seeded["milestone"]["id"]
    (service.paths.object_dir("milestone") / f"{milestone_id}.json").unlink()

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    ref_check = _check(result, "references")
    assert ref_check["status"] == "error"
    assert any(milestone_id in detail for detail in ref_check["details"])


def test_dependency_cycle_reported(service):
    first = service.call("task.create", {"title": "A"})["id"]
    second = service.call("task.create", {"title": "B"})["id"]
    service.call("task.add_dependency", {"task_id": first, "target_id": second})
    # bypass service validation to simulate corrupted data
    record_a = service.store.get_raw("task", first)
    record_b = service.store.get_raw("task", second)
    record_a["dependencies"] = [{"task_id": second, "relation": "depends_on"}]
    record_b["dependencies"] = [{"task_id": first, "relation": "depends_on"}]
    for record in (record_a, record_b):
        record["rev"] = compute_rev(record)
        filesystem.write_json(service.store.path_for("task", record["id"]), record)

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    dep_check = _check(result, "dependencies")
    assert dep_check["status"] == "error"


def test_hierarchy_cycle_reported(service):
    first = service.call("task.create", {"title": "A"})["id"]
    second = service.call("task.create", {"title": "B"})["id"]
    for task_id, parent in ((first, second), (second, first)):
        record = service.store.get_raw("task", task_id)
        record["parent_task_id"] = parent
        record["rev"] = compute_rev(record)
        filesystem.write_json(service.store.path_for("task", task_id), record)

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    check = _check(result, "hierarchy")
    assert check["status"] == "error"


def test_legacy_project_without_rev_warns(root):
    init_project(root, name="Legacy")
    path = root / ".pjt" / "project.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("rev", None)
    record.pop("version", None)
    filesystem.write_json(path, record)

    service = ProjectService(open_project(root))
    result = service.call("project.doctor", {})
    check = _check(result, "project")
    assert check["status"] == "warning"
    assert "no rev" in check["message"]


def test_event_chain_mismatch_reported(service, seeded):
    latest = sorted(service.paths.events.rglob("EVT-*.json"))[-1]
    record = json.loads(latest.read_text(encoding="utf-8"))
    record["new_rev"] = "sha256:deadbeef"
    filesystem.write_json(latest, record)

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    check = _check(result, "events.chain")
    assert check["status"] == "error"


def test_object_without_events_reported(service, seeded):
    record = service.store.get_raw("task", seeded["task"]["id"])
    clone = dict(record)
    clone["id"] = "TSK-01K8H2ZZZ0000000000000000"
    clone["rev"] = compute_rev(clone)
    filesystem.write_json(service.store.path_for("task", clone["id"]), clone)

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    check = _check(result, "events.chain")
    assert any("no events" in detail for detail in check["details"])


def _write_lock(paths, *, pid: int, created_at: float) -> None:
    path = lock_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": pid, "lock_id": "LCK-DOCTOR", "created_at": created_at}),
        encoding="utf-8",
    )


def test_doctor_reports_live_lock(service):
    _write_lock(service.paths, pid=os.getpid(), created_at=time.time() - 3600)
    result = service.call("project.doctor", {})
    check = _check(result, "write.lock")
    assert check["status"] == "warning"
    assert check["repairable"] is False
    lock_path(service.paths).unlink()


def test_doctor_reports_stale_lock_repairable(service):
    _write_lock(service.paths, pid=999_999_999, created_at=time.time() - 3600)
    result = service.call("project.doctor", {})
    check = _check(result, "write.lock")
    assert check["status"] == "warning"
    assert check["repairable"] is True
    assert result["summary"]["repairable"] >= 1
    lock_path(service.paths).unlink()


def test_doctor_reports_invalid_transaction(service):
    txn_dir = service.paths.transactions / "TXN-DOCTOR-INVALID"
    txn_dir.mkdir(parents=True)
    filesystem.atomic_write_text(txn_dir / "COMMIT", "TXN-DOCTOR-INVALID\n")
    (txn_dir / "manifest.json").write_text("{broken", encoding="utf-8")

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    check = _check(result, "transactions")
    assert check["status"] == "error"
    assert check["repairable"] is False
