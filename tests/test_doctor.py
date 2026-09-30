from __future__ import annotations

import json

from project_tool.integrations import filesystem


def test_clean_project_is_ok(service, seeded):
    result = service.call("project.doctor", {})
    assert result["ok"] is True
    assert result["summary"]["errors"] == 0
    names = {check["name"] for check in result["checks"]}
    assert "objects.task" in names
    assert "dependencies" in names
    assert "events" in names


def test_tampered_object_reported(service, seeded):
    task_id = seeded["task"]["id"]
    path = service.store.path_for("task", task_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "tampered without rev update"
    filesystem.write_json(path, record)

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    task_check = next(check for check in result["checks"] if check["name"] == "objects.task")
    assert task_check["status"] == "error"
    assert any("rev mismatch" in detail for detail in task_check["details"])


def test_missing_reference_reported(service, seeded):
    milestone_id = seeded["milestone"]["id"]
    (service.paths.object_dir("milestone") / f"{milestone_id}.json").unlink()

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    ref_check = next(check for check in result["checks"] if check["name"] == "references")
    assert ref_check["status"] == "error"
    assert any(milestone_id in detail for detail in ref_check["details"])


def test_dependency_cycle_reported(service):
    a = service.call("task.create", {"title": "A"})["id"]
    b = service.call("task.create", {"title": "B"})["id"]
    service.call("task.add_dependency", {"task_id": a, "target_id": b})
    # bypass service validation to simulate corrupted data
    record_a = service.store.get_raw("task", a)
    record_b = service.store.get_raw("task", b)
    record_a["dependencies"] = [{"task_id": b, "relation": "depends_on"}]
    record_b["dependencies"] = [{"task_id": a, "relation": "depends_on"}]
    from project_tool.domain.hashing import compute_rev

    for record in (record_a, record_b):
        record["rev"] = compute_rev(record)
        filesystem.write_json(service.store.path_for("task", record["id"]), record)

    result = service.call("project.doctor", {})
    assert result["ok"] is False
    dep_check = next(check for check in result["checks"] if check["name"] == "dependencies")
    assert dep_check["status"] == "error"


def test_staging_leftover_warns(service):
    staging = service.paths.transactions / "TXN-LEFTOVER"
    staging.mkdir(parents=True)
    result = service.call("project.doctor", {})
    check = next(check for check in result["checks"] if check["name"] == "transactions")
    assert check["status"] == "warning"
    assert result["ok"] is True
