from __future__ import annotations

import pytest

from project_tool.application.service import ProjectService
from project_tool.storage import init_project, open_project


@pytest.fixture(autouse=True)
def _stable_rendering_width(monkeypatch):
    """固定 rich 的渲染宽度。

    rich 的 `Console.size` 每次渲染都读 `COLUMNS`。不固定的话，本地宽终端和 CI
    （80 列）的折行结果不同 —— 断言人类可读输出的测试会在 CI 上莫名其妙地失败，
    而被测代码其实完全正常。**所有 CLI 输出的断言都必须与终端宽度无关。**
    """
    monkeypatch.setenv("COLUMNS", "200")


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
