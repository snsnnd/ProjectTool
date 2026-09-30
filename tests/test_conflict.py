from __future__ import annotations

import pytest

from project_tool.application.service import ProjectService
from project_tool.domain.errors import RevisionConflict
from project_tool.storage import EventSpec, ObjectChange, Transaction, WriteLock


def test_stale_change_rejected_at_commit(service, seeded):
    task_id = seeded["task"]["id"]
    original = service.store.get_raw("task", task_id)

    other = ProjectService(service.opened)
    other.call("task.add_label", {"task_id": task_id, "label": "racing"})

    with pytest.raises(RevisionConflict):
        with WriteLock(service.paths):
            Transaction(service.opened, service.actor_id).commit(
                [ObjectChange("task", task_id, {**original, "title": "stale write"}, original["rev"])],
                [EventSpec("task.updated", "task", task_id, {})],
            )


def test_create_race_rejected(service, seeded):
    task_id = seeded["task"]["id"]
    existing = service.store.get_raw("task", task_id)
    with pytest.raises(RevisionConflict):
        with WriteLock(service.paths):
            Transaction(service.opened, service.actor_id).commit(
                [ObjectChange("task", task_id, {**existing, "title": "duplicate"}, None)],
                [EventSpec("task.created", "task", task_id, {})],
            )


def test_transaction_cleans_staging(service, seeded):
    service.call("task.add_label", {"task_id": seeded["task"]["id"], "label": "x"})
    leftovers = list(service.paths.transactions.iterdir())
    assert leftovers == []
