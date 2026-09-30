from __future__ import annotations

import pytest

from project_tool.domain.errors import HierarchyCycle, InvalidArgument


def test_empty_titles_rejected(service):
    cases = [
        ("goal.create", {"title": "   "}),
        ("milestone.create", {"title": ""}),
        ("task.create", {"title": "\t"}),
        ("decision.create", {"title": ""}),
    ]
    for method, params in cases:
        with pytest.raises(InvalidArgument):
            service.call(method, params)


def test_long_title_rejected(service):
    with pytest.raises(InvalidArgument):
        service.call("task.create", {"title": "x" * 501})


def test_long_label_rejected(service, seeded):
    with pytest.raises(InvalidArgument):
        service.call("task.add_label", {"task_id": seeded["task"]["id"], "label": "x" * 65})


def test_empty_label_rejected(service, seeded):
    with pytest.raises(InvalidArgument):
        service.call("task.add_label", {"task_id": seeded["task"]["id"], "label": "  "})


def test_duplicate_labels_and_owners_dedupe(service, seeded):
    task = service.call(
        "task.update",
        {
            "task_id": seeded["task"]["id"],
            "labels": ["a", "a", "b"],
            "owner_ids": ["alice", "alice"],
        },
    )
    assert task["labels"] == ["a", "b"]
    assert task["owner_ids"] == [seeded["member"]["id"]]


def test_inactive_member_cannot_be_assigned(service, seeded):
    service.call("member.add", {"handle": "bob"})
    service.call("member.deactivate", {"member": "bob"})
    with pytest.raises(InvalidArgument):
        service.call("task.assign", {"task_id": seeded["task"]["id"], "member": "bob"})


def test_deleted_task_cannot_be_referenced(service):
    first = service.call("task.create", {"title": "A"})["id"]
    second = service.call("task.create", {"title": "B"})["id"]
    service.call("task.delete", {"task_id": second})
    with pytest.raises(InvalidArgument):
        service.call("task.add_dependency", {"task_id": first, "target_id": second})
    with pytest.raises(InvalidArgument):
        service.call("update.create", {"summary": "x", "task_ids": [second]})


def test_closed_milestone_rejects_new_tasks(service):
    closed = service.call("milestone.create", {"title": "Closed"})["id"]
    allowed = service.call("milestone.create", {"title": "Open"})["id"]
    task = service.call("task.create", {"title": "T", "milestone_id": allowed})["id"]
    service.call("milestone.close", {"milestone_id": closed})

    with pytest.raises(InvalidArgument):
        service.call("task.create", {"title": "Late", "milestone_id": closed})
    with pytest.raises(InvalidArgument):
        service.call("task.move_milestone", {"task_id": task, "milestone_id": closed})
    # 同值保持（no-op）仍然允许
    kept = service.call("task.update", {"task_id": task, "milestone_id": allowed})
    assert kept["milestone_id"] == allowed


def test_cancelled_milestone_rejects_new_tasks(service):
    cancelled = service.call("milestone.create", {"title": "C"})["id"]
    service.call("milestone.cancel", {"milestone_id": cancelled})
    with pytest.raises(InvalidArgument):
        service.call("task.create", {"title": "Late", "milestone_id": cancelled})


def test_done_task_can_still_be_edited(service, seeded):
    task_id = seeded["task"]["id"]
    service.call("task.set_status", {"task_id": task_id, "status": "done"})
    updated = service.call("task.add_label", {"task_id": task_id, "label": "post"})
    assert "post" in updated["labels"]


def test_goal_parent_cycle_rejected(service):
    first = service.call("goal.create", {"title": "G1"})["id"]
    second = service.call("goal.create", {"title": "G2", "parent_goal_id": first})["id"]
    with pytest.raises(HierarchyCycle):
        service.call("goal.update", {"goal_id": first, "parent_goal_id": second})
    with pytest.raises(InvalidArgument):
        service.call("goal.update", {"goal_id": first, "parent_goal_id": first})


def test_task_parent_cycle_rejected_via_update(service):
    first = service.call("task.create", {"title": "A"})["id"]
    second = service.call("task.create", {"title": "B", "parent_task_id": first})["id"]
    with pytest.raises(HierarchyCycle):
        service.call("task.update", {"task_id": first, "parent_task_id": second})


def test_decision_supersede_cycle_rejected(service):
    first = service.call("decision.create", {"title": "D1"})["id"]
    second = service.call("decision.create", {"title": "D2"})["id"]
    service.call("decision.supersede", {"old_id": second, "new_id": first})
    with pytest.raises(HierarchyCycle):
        service.call("decision.supersede", {"old_id": first, "new_id": second})


def test_decision_self_supersede_rejected(service):
    decision = service.call("decision.create", {"title": "D"})["id"]
    with pytest.raises(InvalidArgument):
        service.call("decision.supersede", {"old_id": decision, "new_id": decision})


def test_handle_validation(service):
    with pytest.raises(InvalidArgument):
        service.call("member.add", {"handle": "BAD HANDLE"})
    with pytest.raises(InvalidArgument):
        service.call("member.add", {"handle": "x" * 65})
    with pytest.raises(InvalidArgument):
        service.call("member.add", {"handle": "9invalid", "display_name": "x" * 501})


def test_long_description_rejected(service):
    with pytest.raises(InvalidArgument):
        service.call("task.create", {"title": "T", "description": "x" * 200_001})
