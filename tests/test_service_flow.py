from __future__ import annotations

import pytest

from project_tool.domain.errors import AlreadyExists, InvalidArgument, NotFound, RevisionConflict


def test_full_flow_creates_events(service, seeded):
    events = service.call("log.list", {"limit": 100})["events"]
    types = [event["event_type"] for event in events]
    assert "member.added" in types
    assert "goal.created" in types
    assert "milestone.created" in types
    assert "task.created" in types


def test_rev_and_version_change_on_update(service, seeded):
    task_id = seeded["task"]["id"]
    before = service.call("task.get", {"task_id": task_id})
    after = service.call("task.add_label", {"task_id": task_id, "label": "net"})
    assert after["version"] == before["version"] + 1
    assert after["rev"] != before["rev"]
    assert after["labels"] == ["net"]


def test_status_transitions_set_timestamps(service, seeded):
    task_id = seeded["task"]["id"]
    doing = service.call("task.set_status", {"task_id": task_id, "status": "doing"})
    assert doing["started_at"] is not None
    assert doing["completed_at"] is None
    done = service.call("task.set_status", {"task_id": task_id, "status": "done"})
    assert done["completed_at"] is not None
    again = service.call("task.set_status", {"task_id": task_id, "status": "doing"})
    assert again["completed_at"] is None
    assert again["started_at"] == doing["started_at"]


def test_invalid_status(service, seeded):
    with pytest.raises(InvalidArgument):
        service.call("task.set_status", {"task_id": seeded["task"]["id"], "status": "finished"})


def test_lifecycle_archive_hides_from_list(service, seeded):
    task_id = seeded["task"]["id"]
    service.call("task.archive", {"task_id": task_id})
    assert service.call("task.list", {}) == []
    assert len(service.call("task.list", {"include_archived": True})) == 1
    service.call("task.restore", {"task_id": task_id})
    assert len(service.call("task.list", {})) == 1


def test_delete_is_soft(service, seeded):
    task_id = seeded["task"]["id"]
    service.call("task.delete", {"task_id": task_id})
    assert service.call("task.list", {}) == []
    deleted = service.call("task.get", {"task_id": task_id})
    assert deleted["lifecycle"] == "deleted"


def test_member_handle_unique_and_resolution(service, seeded):
    with pytest.raises(AlreadyExists):
        service.call("member.add", {"handle": "alice"})
    by_handle = service.call("member.get", {"member": "alice"})
    assert by_handle["id"] == seeded["member"]["id"]


def test_member_use_sets_local_actor(service, seeded):
    service.call("member.add", {"handle": "bob", "display_name": "Bob"})
    result = service.call("member.use", {"member": "bob"})
    assert service.opened.local.actor == result["actor"]


def test_update_decision_supersede(service, seeded):
    task_id = seeded["task"]["id"]
    update = service.call("update.create", {"summary": "halfway", "task_ids": [task_id]})
    related = service.call("task.related_updates", {"task_id": task_id})
    assert [item["id"] for item in related] == [update["id"]]

    first = service.call("decision.create", {"title": "Use TCP", "status": "accepted"})
    second = service.call("decision.create", {"title": "Use QUIC"})
    result = service.call("decision.supersede", {"old_id": first["id"], "new_id": second["id"]})
    assert result["superseded"]["status"] == "superseded"
    assert result["superseded_by"]["supersedes_id"] == first["id"]


def test_project_status_after_flow(service, seeded):
    service.call("task.set_status", {"task_id": seeded["task"]["id"], "status": "done"})
    status = service.call("project.status", {})
    assert status["tasks"]["done"] == 1
    assert status["active_milestone"]["progress"] == 1.0
    assert status["members"][0]["handle"] == "alice"


def test_unknown_method(service):
    with pytest.raises(InvalidArgument):
        service.call("task.explode", {})


def test_expected_rev_conflict(service, seeded):
    task = service.call("task.get", {"task_id": seeded["task"]["id"]})
    with pytest.raises(RevisionConflict):
        service.call(
            "task.set_status",
            {
                "task_id": task["id"],
                "status": "doing",
                "expected_rev": "sha256:stale",
            },
        )


def test_missing_object(service):
    with pytest.raises(NotFound):
        service.call("task.get", {"task_id": "TSK-01K8H2MBQX"})


def test_task_history_shape(service, seeded):
    task_id = seeded["task"]["id"]
    service.call("task.set_status", {"task_id": task_id, "status": "doing"})
    history = service.call("task.history", {"task_id": task_id})
    assert history["count"] >= 2
    assert all(event["entity_id"] == task_id for event in history["events"])
    assert history["next_cursor"] is None
