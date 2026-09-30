"""`pjt task ready`：补齐 inbox→ready 的 CLI 缺口（V1-A 任务 1）。

覆盖：
- 从 inbox / blocked / review / done / cancelled 进入 ready
- CLI 只做薄适配（真的调用 Service 方法，不复制业务规则）
- 事件契约
- --json 输出
- computed blocked 不被 task ready 破坏
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from project_tool.application.services.task import TaskService
from project_tool.cli.main import app
from project_tool.storage import init_project, open_project

runner = CliRunner()


def invoke(args):
    return runner.invoke(app, args)


def init(tmp_path, name="Demo"):
    init_project(tmp_path, name=name)
    return tmp_path


def add_task(tmp_path, title="T1", **kwargs):
    result = invoke(["--json", "-C", str(tmp_path), "task", "add", title])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["result"]


def get_task(tmp_path, task_id):
    result = invoke(["--json", "-C", str(tmp_path), "task", "show", task_id])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["result"]


def read_events(tmp_path):
    events = []
    for path in sorted((tmp_path / ".pjt" / "events").rglob("EVT-*.json")):
        events.append(json.loads(path.read_text(encoding="utf-8")))
    return events


def test_task_ready_from_inbox(tmp_path):
    init(tmp_path)
    task = add_task(tmp_path, "Refine the plan")
    assert task["status"] == "inbox"

    result = invoke(["-C", str(tmp_path), "task", "ready", task["id"]])
    assert result.exit_code == 0, result.output

    assert get_task(tmp_path, task["id"])["status"] == "ready"


def test_task_ready_from_blocked_and_review(tmp_path):
    init(tmp_path)
    for source, command in (
        ("blocked", "block"),
        ("review", "review"),
        ("done", "done"),
        ("cancelled", "cancel"),
    ):
        task = add_task(tmp_path, f"task from {source}")
        for step in (command, "ready"):
            result = invoke(["-C", str(tmp_path), "task", step, task["id"]])
            assert result.exit_code == 0, f"{source}->{step}: {result.output}"
        assert get_task(tmp_path, task["id"])["status"] == "ready"


def test_task_ready_uses_service(tmp_path, monkeypatch):
    """CLI 必须是薄适配：调用 task.set_status，而不是自己写状态规则。"""
    init(tmp_path)
    task = add_task(tmp_path, "T1")

    calls: list[tuple] = []
    original = TaskService.task_set_status

    def spy(self, task_id, status, expected_rev=None):
        calls.append((task_id, status, expected_rev))
        return original(self, task_id, status, expected_rev=expected_rev)

    monkeypatch.setattr(TaskService, "task_set_status", spy)

    result = invoke(["-C", str(tmp_path), "task", "ready", task["id"]])
    assert result.exit_code == 0, result.output
    assert calls == [(task["id"], "ready", None)]

    rev = get_task(tmp_path, task["id"])["rev"]
    result = invoke(
        ["-C", str(tmp_path), "task", "block", task["id"], "--expected-rev", rev]
    )
    assert result.exit_code == 0, result.output
    result = invoke(
        ["-C", str(tmp_path), "task", "ready", task["id"], "--expected-rev", rev]
    )
    assert result.exit_code == 5, result.output
    assert calls[-1] == (task["id"], "ready", rev)


def test_task_ready_event(tmp_path):
    init(tmp_path)
    task = add_task(tmp_path, "T1")
    assert invoke(["-C", str(tmp_path), "task", "ready", task["id"]]).exit_code == 0

    events = [event for event in read_events(tmp_path) if event["entity_id"] == task["id"]]
    assert [event["event_type"] for event in events] == ["task.created", "task.status_changed"]

    status_event = events[-1]
    assert status_event["entity_type"] == "task"
    assert status_event["payload"] == {"from": "inbox", "to": "ready"}
    assert status_event["base_rev"] == events[0]["new_rev"]
    assert status_event["new_rev"] != status_event["base_rev"]


def test_task_ready_json_output(tmp_path):
    init(tmp_path)
    task = add_task(tmp_path, "T1")

    result = invoke(["--json", "-C", str(tmp_path), "task", "ready", task["id"]])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == "cli"
    assert payload["result"]["id"] == task["id"]
    assert payload["result"]["status"] == "ready"
    assert "computed_blocked" in payload["result"]


def test_task_ready_is_idempotent_without_event(tmp_path):
    init(tmp_path)
    task = add_task(tmp_path, "T1")
    assert invoke(["-C", str(tmp_path), "task", "ready", task["id"]]).exit_code == 0
    before = len(read_events(tmp_path))
    assert invoke(["-C", str(tmp_path), "task", "ready", task["id"]]).exit_code == 0
    assert len(read_events(tmp_path)) == before


def test_task_ready_keeps_computed_blocked_read_only(tmp_path):
    """ready + 未完成依赖 => computed_blocked=true，但 status 仍为 ready。"""
    init(tmp_path)
    first = add_task(tmp_path, "upstream")
    second = add_task(tmp_path, "downstream")
    assert invoke(
        ["-C", str(tmp_path), "task", "depend", second["id"], first["id"]]
    ).exit_code == 0
    assert invoke(["-C", str(tmp_path), "task", "ready", second["id"]]).exit_code == 0

    view = get_task(tmp_path, second["id"])
    assert view["status"] == "ready"
    assert view["computed_blocked"] is True
    assert view["blocked_by"] == [first["id"]]

    # 依赖完成后 computed_blocked 自行消失，status 从未被自动改写。
    assert invoke(["-C", str(tmp_path), "task", "done", first["id"]]).exit_code == 0
    view = get_task(tmp_path, second["id"])
    assert view["status"] == "ready"
    assert view["computed_blocked"] is False


@pytest.mark.parametrize("command", ["start", "block", "review", "done", "cancel", "ready"])
def test_task_status_shortcuts_accept_expected_rev(tmp_path, command):
    init(tmp_path)
    task = add_task(tmp_path, "T1")
    stale = "sha256:" + "0" * 64
    result = invoke(
        ["--json", "-C", str(tmp_path), "task", command, task["id"], "--expected-rev", stale]
    )
    assert result.exit_code == 5, result.output
    assert json.loads(result.output)["error"]["code"] == "REVISION_CONFLICT"
    assert get_task(tmp_path, task["id"])["status"] == "inbox"


def test_task_ready_unknown_task_exit_code(tmp_path):
    init(tmp_path)
    result = invoke(["--json", "-C", str(tmp_path), "task", "ready", "TSK-01K8H2MBQX"])
    assert result.exit_code == 4
    assert json.loads(result.output)["error"]["code"] == "NOT_FOUND"


def test_task_ready_does_not_corrupt_project(tmp_path):
    from project_tool.application.service import ProjectService

    init(tmp_path)
    task = add_task(tmp_path, "T1")
    assert invoke(["-C", str(tmp_path), "task", "ready", task["id"]]).exit_code == 0

    result = invoke(["--json", "-C", str(tmp_path), "doctor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result"]["summary"]["errors"] == 0

    service = ProjectService(open_project(tmp_path))
    assert service.call("task.get", {"task_id": task["id"]})["status"] == "ready"
