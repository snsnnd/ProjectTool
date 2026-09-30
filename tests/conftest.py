from __future__ import annotations

import pytest

from project_tool.application.service import ProjectService
from project_tool.storage import init_project, open_project


@pytest.fixture()
def root(tmp_path):
    return tmp_path


@pytest.fixture()
def project(root):
    init_project(root, name="Test Project", description="fixture")
    return open_project(root)


@pytest.fixture()
def service(project):
    return ProjectService(project)


@pytest.fixture()
def seeded(service):
    member = service.call("member.add", {"handle": "alice", "display_name": "Alice"})
    goal = service.call("goal.create", {"title": "Goal A"})
    milestone = service.call(
        "milestone.create",
        {"title": "Milestone A", "goal_ids": [goal["id"]], "status": "active"},
    )
    task = service.call(
        "task.create",
        {
            "title": "Task A",
            "milestone_id": milestone["id"],
            "owner_ids": [member["id"]],
            "priority": "high",
            "weight": 2,
        },
    )
    return {
        "member": member,
        "goal": goal,
        "milestone": milestone,
        "task": task,
    }
