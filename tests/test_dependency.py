from __future__ import annotations

import pytest

from project_tool.domain.errors import DependencyCycle, NotFound


def _task(service, title):
    return service.call("task.create", {"title": title})["id"]


def test_cycle_detected(service):
    a = _task(service, "A")
    b = _task(service, "B")
    c = _task(service, "C")
    service.call("task.add_dependency", {"task_id": a, "target_id": b})
    service.call("task.add_dependency", {"task_id": b, "target_id": c})
    with pytest.raises(DependencyCycle):
        service.call("task.add_dependency", {"task_id": c, "target_id": a})


def test_self_dependency_rejected(service):
    a = _task(service, "A")
    from project_tool.domain.errors import InvalidArgument

    with pytest.raises(InvalidArgument):
        service.call("task.add_dependency", {"task_id": a, "target_id": a})


def test_duplicate_dependency_idempotent(service):
    a = _task(service, "A")
    b = _task(service, "B")
    service.call("task.add_dependency", {"task_id": a, "target_id": b})
    result = service.call("task.add_dependency", {"task_id": a, "target_id": b})
    assert len(result["dependencies"]) == 1


def test_remove_dependency(service):
    a = _task(service, "A")
    b = _task(service, "B")
    service.call("task.add_dependency", {"task_id": a, "target_id": b})
    service.call("task.remove_dependency", {"task_id": a, "target_id": b})
    assert service.call("task.get", {"task_id": a})["dependencies"] == []
    with pytest.raises(NotFound):
        service.call("task.remove_dependency", {"task_id": a, "target_id": b})


def test_computed_blocked_and_release(service):
    blocker = _task(service, "Blocker")
    dependent = _task(service, "Dependent")
    service.call("task.add_dependency", {"task_id": dependent, "target_id": blocker})
    view = service.call("task.get", {"task_id": dependent})
    assert view["computed_blocked"] is True
    assert view["blocked_by"] == [blocker]
    service.call("task.set_status", {"task_id": blocker, "status": "done"})
    view = service.call("task.get", {"task_id": dependent})
    assert view["computed_blocked"] is False


def test_cancelled_dependency_keeps_blocking(service):
    blocker = _task(service, "Blocker")
    dependent = _task(service, "Dependent")
    service.call("task.add_dependency", {"task_id": dependent, "target_id": blocker})
    service.call("task.set_status", {"task_id": blocker, "status": "cancelled"})
    view = service.call("task.get", {"task_id": dependent})
    assert view["computed_blocked"] is True


def test_manual_blocked_not_overwritten(service):
    task = _task(service, "Task")
    view = service.call("task.set_status", {"task_id": task, "status": "blocked"})
    assert view["status"] == "blocked"
    assert view["computed_blocked"] is False


def test_milestone_progress_weighted(service):
    milestone = service.call("milestone.create", {"title": "M"})
    a = service.call("task.create", {"title": "A", "milestone_id": milestone["id"], "weight": 1})["id"]
    b = service.call("task.create", {"title": "B", "milestone_id": milestone["id"], "weight": 2})["id"]
    c = service.call("task.create", {"title": "C", "milestone_id": milestone["id"], "weight": 2})["id"]
    service.call("task.set_status", {"task_id": a, "status": "done"})
    service.call("task.set_status", {"task_id": b, "status": "done"})
    progress = service.call("milestone.progress", {"milestone_id": milestone["id"]})
    assert progress["done_weight"] == 3
    assert progress["total_weight"] == 5
    assert abs(progress["progress"] - 0.6) < 1e-9
    service.call("task.set_status", {"task_id": c, "status": "cancelled"})
    progress = service.call("milestone.progress", {"milestone_id": milestone["id"]})
    assert progress["total_weight"] == 3
    assert progress["progress"] == 1.0
