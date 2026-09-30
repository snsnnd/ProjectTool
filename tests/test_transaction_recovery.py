"""事务故障注入与恢复测试（V0.1 最关键的失败模式覆盖）。

注入点（monkeypatch，全部 deterministic）：
- staged 对象写失败        -> transaction.filesystem.write_json
- manifest 写失败          -> transaction.write_manifest
- COMMIT marker 写失败     -> transaction.write_commit_marker
- apply 第 N 个写入后崩溃  -> recovery.os.replace
- state.json 更新失败      -> transaction.write_state
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

import project_tool.storage.recovery as recovery_module
import project_tool.storage.transaction as transaction_module
from project_tool.application.service import ProjectService
from project_tool.domain.errors import ProjectIOError
from project_tool.domain.hashing import compute_rev
from project_tool.integrations import filesystem
from project_tool.storage import recover_all, scan_transactions


def crash_on_apply(monkeypatch, fail_after: int) -> dict:
    real_replace = os.replace

    calls = {"count": 0}

    def fake_replace(src, dst):
        target = str(dst).replace("\\", "/")
        is_canonical = "/staged/" not in target and (
            "/objects/" in target or "/events/" in target or target.endswith("project.json")
        )
        if is_canonical:
            calls["count"] += 1
            if calls["count"] > fail_after:
                raise OSError("injected: apply crash")
        return real_replace(src, dst)

    monkeypatch.setattr(recovery_module.os, "replace", fake_replace)
    return calls


def snapshot_tree(paths) -> dict[str, str]:
    result: dict[str, str] = {}
    for base in (paths.objects, paths.events, paths.state):
        if base.is_dir():
            for path in sorted(base.rglob("*.json")):
                result[str(path.relative_to(paths.pjt))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    result["project.json"] = hashlib.sha256(paths.project_json.read_bytes()).hexdigest()
    return result


# --------------------------------------------------------------------- 写前失败


def test_staged_write_failure_leaves_no_trace(service, monkeypatch):
    real_write = filesystem.write_json

    def fake_write(path, data, indent: int = 2):
        if "/staged/" in str(path).replace("\\", "/"):
            raise OSError("injected: staged write failure")
        return real_write(path, data, indent=indent)

    monkeypatch.setattr(transaction_module.filesystem, "write_json", fake_write)
    with pytest.raises(OSError):
        service.call("task.create", {"title": "never"})

    assert service.call("task.list", {}) == []
    assert list(service.paths.transactions.iterdir()) == []
    assert service.call("project.doctor", {})["ok"] is True


def test_manifest_write_failure_cleans_staging(service, monkeypatch):
    def boom(txn_dir, manifest):
        raise ProjectIOError("injected: manifest failure")

    monkeypatch.setattr(transaction_module, "write_manifest", boom)
    with pytest.raises(ProjectIOError):
        service.call("task.create", {"title": "never"})

    assert service.call("task.list", {}) == []
    assert list(service.paths.transactions.iterdir()) == []
    assert service.call("project.doctor", {})["ok"] is True


def test_commit_marker_failure_cleans_staging(service, monkeypatch):
    def boom(txn_dir, txn_id):
        raise ProjectIOError("injected: commit marker failure")

    monkeypatch.setattr(transaction_module, "write_commit_marker", boom)
    with pytest.raises(ProjectIOError):
        service.call("task.create", {"title": "never"})

    assert service.call("task.list", {}) == []
    assert list(service.paths.transactions.iterdir()) == []
    assert service.call("project.doctor", {})["ok"] is True


# ------------------------------------------------------------------- 部分 apply


def test_crash_after_first_apply_rolls_forward(service, monkeypatch):
    crash_on_apply(monkeypatch, fail_after=1)
    with pytest.raises(ProjectIOError):
        service.call("task.create", {"title": "Crashy"})
    monkeypatch.undo()

    scans = scan_transactions(service.paths)
    assert len(scans) == 1
    assert scans[0].committed is True
    assert scans[0].repairable is True

    results = recover_all(service.paths)
    assert results[0].action == "rolled_forward"

    tasks = service.call("task.list", {})
    assert [task["title"] for task in tasks] == ["Crashy"]
    events = service.call("log.list", {"event_type": "task.created"})
    assert events["count"] == 1
    assert service.call("project.doctor", {})["ok"] is True
    assert list(service.paths.transactions.iterdir()) == []


def test_crash_midway_multiple_objects(service, monkeypatch):
    first = service.call("decision.create", {"title": "Old", "status": "accepted"})["id"]
    second = service.call("decision.create", {"title": "New"})["id"]

    crash_on_apply(monkeypatch, fail_after=2)
    with pytest.raises(ProjectIOError):
        service.call("decision.supersede", {"old_id": first, "new_id": second})
    monkeypatch.undo()

    results = recover_all(service.paths)
    assert results[0].action == "rolled_forward"

    old = service.call("decision.get", {"decision_id": first})
    new = service.call("decision.get", {"decision_id": second})
    assert old["status"] == "superseded"
    assert new["supersedes_id"] == first
    assert service.call("project.doctor", {})["ok"] is True


def test_crash_before_events_applied(service, monkeypatch):
    # task.create = [object, event]；fail_after=1 -> 对象已应用、事件未应用
    crash_on_apply(monkeypatch, fail_after=1)
    with pytest.raises(ProjectIOError):
        service.call("task.create", {"title": "NoEventYet"})
    monkeypatch.undo()

    assert service.call("log.list", {"event_type": "task.created"})["count"] == 0
    recover_all(service.paths)
    assert service.call("log.list", {"event_type": "task.created"})["count"] == 1
    assert service.call("project.doctor", {})["ok"] is True


def test_recovery_is_idempotent(service, monkeypatch):
    crash_on_apply(monkeypatch, fail_after=1)
    with pytest.raises(ProjectIOError):
        service.call("task.create", {"title": "Idem"})
    monkeypatch.undo()

    recover_all(service.paths)
    baseline = snapshot_tree(service.paths)
    for _ in range(3):
        results = recover_all(service.paths)
        assert all(result.action != "error" for result in results)
        assert snapshot_tree(service.paths) == baseline


def test_state_update_failure_recovered(service, monkeypatch):
    def boom(paths, last_transaction_id=None):
        raise ProjectIOError("injected: state failure")

    monkeypatch.setattr(transaction_module, "write_state", boom)
    with pytest.raises(ProjectIOError):
        service.call("task.create", {"title": "StateCrash"})
    monkeypatch.undo()

    # 对象与事件已经 apply，仅派生 state 未更新；事务目录保留
    assert service.call("task.list", {})[0]["title"] == "StateCrash"
    scans = scan_transactions(service.paths)
    assert len(scans) == 1
    assert scans[0].status == "applied"
    assert scans[0].repairable is True

    recover_all(service.paths)
    assert list(service.paths.transactions.iterdir()) == []
    assert service.call("project.doctor", {})["ok"] is True


# ------------------------------------------------------------------- 丢弃/冲突


def test_uncommitted_staging_discarded(service):
    txn_dir = service.paths.transactions / "TXN-UNCOMMITTED-TEST"
    filesystem.write_json(
        txn_dir / "staged" / "objects" / "tasks" / "TSK-FAKE.json",
        {"id": "TSK-FAKE", "type": "task"},
    )
    scans = scan_transactions(service.paths)
    assert scans[0].status == "uncommitted"
    assert scans[0].repairable is True

    results = recover_all(service.paths)
    assert results[0].action == "discarded"
    assert not txn_dir.exists()
    assert not (service.paths.object_dir("task") / "TSK-FAKE.json").exists()


def test_invalid_manifest_without_commit_discarded(service):
    txn_dir = service.paths.transactions / "TXN-BADJSON-TEST"
    txn_dir.mkdir(parents=True)
    (txn_dir / "manifest.json").write_text("{not json", encoding="utf-8")

    scans = scan_transactions(service.paths)
    assert scans[0].status == "invalid"
    assert scans[0].repairable is True
    results = recover_all(service.paths)
    assert results[0].action == "discarded"
    assert not txn_dir.exists()


def test_invalid_manifest_with_commit_kept_for_manual(service):
    txn_dir = service.paths.transactions / "TXN-BADCOMMIT-TEST"
    txn_dir.mkdir(parents=True)
    filesystem.atomic_write_text(txn_dir / "COMMIT", "TXN-BADCOMMIT-TEST\n")
    (txn_dir / "manifest.json").write_text("{not json", encoding="utf-8")

    scans = scan_transactions(service.paths)
    assert scans[0].status == "invalid"
    assert scans[0].repairable is False

    results = recover_all(service.paths)
    assert results[0].action == "error"
    assert txn_dir.exists()

    doctor = service.call("project.doctor", {})
    assert doctor["ok"] is False
    check = next(item for item in doctor["checks"] if item["name"] == "transactions")
    assert check["status"] == "error"
    assert check["repairable"] is False


def test_conflict_during_recovery_reports_error(service, monkeypatch):
    task = service.call("task.create", {"title": "T"})

    crash_on_apply(monkeypatch, fail_after=0)
    with pytest.raises(ProjectIOError):
        service.call("task.add_label", {"task_id": task["id"], "label": "x"})
    monkeypatch.undo()

    # 第三方直接改写了 canonical 对象（不经过事务）
    path = service.store.path_for("task", task["id"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "third party"
    record["rev"] = compute_rev(record)
    filesystem.write_json(path, record)

    results = recover_all(service.paths)
    assert results[0].action == "error"
    assert "rev mismatch" in results[0].detail
    assert (service.paths.transactions / results[0].transaction_id).exists()


# ------------------------------------------------------------------- doctor 集成


def test_doctor_reports_recoverable_transaction_then_repair(service):
    txn_dir = service.paths.transactions / "TXN-DOCTOR-TEST"
    filesystem.write_json(
        txn_dir / "staged" / "objects" / "tasks" / "TSK-DOCTOR.json",
        {"id": "TSK-DOCTOR", "type": "task"},
    )

    doctor = service.call("project.doctor", {})
    check = next(item for item in doctor["checks"] if item["name"] == "transactions")
    assert check["status"] == "warning"
    assert check["repairable"] is True

    recovered = service.call("project.recover", {})
    assert recovered["recovered"][0]["action"] == "discarded"

    doctor = service.call("project.doctor", {})
    check = next(item for item in doctor["checks"] if item["name"] == "transactions")
    assert check["status"] == "ok"


# ------------------------------------------- 新对象类型走同一条事务/恢复路径（V1-A）


def test_area_create_crash_rolls_forward(service, monkeypatch, tmp_path):
    """Area 与既有对象共用 staged/manifest/COMMIT 协议，不允许旁路写入。"""
    crash_on_apply(monkeypatch, fail_after=0)
    with pytest.raises(ProjectIOError):
        service.call("area.create", {"name": "Core"})
    monkeypatch.undo()

    from project_tool.storage import recover_all, scan_transactions

    scans = scan_transactions(service.paths)
    assert scans and scans[0].status == "prepared"
    results = recover_all(service.paths)
    assert [r.action for r in results] == ["rolled_forward"]
    assert not scan_transactions(service.paths)

    reopened = ProjectService(service.opened)
    assert [row["name"] for row in reopened.call("area.list")] == ["Core"]
    assert reopened.call("project.doctor")["ok"] is True
    # 幂等
    assert not recover_all(service.paths)


def test_artifact_attach_crash_rolls_forward(service, monkeypatch, tmp_path):
    (tmp_path / "studio_core").mkdir()
    (tmp_path / "studio_core" / "debug.py").write_text("x = 1\n", encoding="utf-8")
    artifact = service.call(
        "artifact.create", {"name": "debug transport", "kind": "file", "locator": "studio_core/debug.py"}
    )
    task = service.call("task.create", {"title": "loopback test"})

    crash_on_apply(monkeypatch, fail_after=0)
    with pytest.raises(ProjectIOError):
        service.call("artifact.attach", {"artifact_id": artifact["id"], "task": task["id"]})
    monkeypatch.undo()

    from project_tool.storage import recover_all, scan_transactions

    assert scan_transactions(service.paths)[0].status == "prepared"
    assert [r.action for r in recover_all(service.paths)] == ["rolled_forward"]

    reopened = ProjectService(service.opened)
    attached = reopened.call("artifact.get", {"artifact_id": artifact["id"]})
    assert attached["related_task_ids"] == [task["id"]]
    assert reopened.call("project.doctor")["ok"] is True
