from __future__ import annotations

import hashlib
import re
from pathlib import Path

from project_tool.storage.event_store import EventStore

DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "08-events.md"


def event_hashes(paths) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths.events.rglob("EVT-*.json"))
    }


def test_events_are_immutable(service, seeded):
    before = event_hashes(service.paths)
    assert before

    task_id = seeded["task"]["id"]
    service.call("task.set_status", {"task_id": task_id, "status": "doing"})
    service.call("task.add_label", {"task_id": task_id, "label": "net"})
    service.call("task.assign", {"task_id": task_id, "member": "alice"})
    service.call("update.create", {"summary": "progress", "task_ids": [task_id]})
    service.call("decision.create", {"title": "D"})
    service.call("project.update", {"description": "updated"})

    after = event_hashes(service.paths)
    for name, digest in before.items():
        assert after[name] == digest, f"event {name} was modified"
    assert len(after) > len(before)


def test_event_store_has_no_mutation_api():
    assert not hasattr(EventStore, "update_event")
    assert not hasattr(EventStore, "delete_event")
    assert not hasattr(EventStore, "remove")


def test_task_status_changed_payload_contract(service, seeded):
    service.call("task.set_status", {"task_id": seeded["task"]["id"], "status": "doing"})
    events = service.call("log.list", {"event_type": "task.status_changed"})["events"]
    assert events[0]["payload"] == {"from": "inbox", "to": "doing"}


def test_task_updated_payload_contract(service, seeded):
    service.call("task.update", {"task_id": seeded["task"]["id"], "title": "Renamed"})
    events = service.call("log.list", {"event_type": "task.updated"})["events"]
    assert events[0]["payload"]["fields"] == ["title"]


def test_task_assigned_payload_contract(service, seeded):
    service.call("member.add", {"handle": "bob", "display_name": "Bob"})
    bob = service.call("member.get", {"member": "bob"})
    service.call("task.assign", {"task_id": seeded["task"]["id"], "member": "bob"})
    events = service.call("log.list", {"event_type": "task.assigned"})["events"]
    assert events[0]["payload"] == {"member_id": bob["id"]}


def test_dependency_added_payload_contract(service):
    first = service.call("task.create", {"title": "A"})["id"]
    second = service.call("task.create", {"title": "B"})["id"]
    service.call("task.add_dependency", {"task_id": first, "target_id": second})
    events = service.call("log.list", {"event_type": "task.dependency_added"})["events"]
    assert events[0]["payload"] == {"target_id": second, "relation": "depends_on"}


def test_project_updated_payload_contract(service):
    service.call("project.update", {"name": "Renamed"})
    events = service.call("log.list", {"event_type": "project.updated"})["events"]
    assert events[0]["payload"]["fields"] == ["name"]


# ================================================================== 事件类型闸门


#: 对象类型前缀——事件类型永远是 `<对象类型>.<动作>`
EVENT_TYPE_PREFIXES = frozenset(
    {
        "project", "goal", "milestone", "area", "task", "member", "update",
        "decision", "artifact", "link", "git", "object", "interface",
    }
)

#: 长得像事件、但其实是别的东西（字段路径、文件名、payload 键）
NOT_EVENT_TYPES = frozenset(
    {"project.json", "area.owners", "member.roles", "git.names", "git.emails"}
)


def _scan_event_types() -> set[str]:
    """从源码扫出所有真正 append 进事件的 event_type。

    事件类型散落在各 service 里，没有集中的 `EventType` 集合，所以这个
    扫描是唯一的登记闸门。两种朴素做法都会漏，所以都放弃了：

    - 按 `ctx.save` 的**位置参数**取（AST）：漏掉传给普通 helper 的
      （`milestone.activated`）、三元表达式里的（`artifact.attached`）、以及
      `Event(event_type=...)` 关键字传的（`project.initialized`）。只扫到 40 个。
    - 直接把所有 `"a.b"` 字面量都算事件：会把 123 个 registry method 名、
      `project.json`、`git.names` 一并算进来。

    折中办法：扫所有字面量，再用 **registry 的 method 名**减掉——method 名
    和事件类型不会同名，这一步同时排掉了 `service.py` 里的
    `SCHEMA_GATE_EXEMPT`。剩下只配一小份显式白名单。
    """
    import ast
    import pathlib
    import tempfile

    from project_tool.application.registry import build_registry
    from project_tool.application.service import ProjectService
    from project_tool.storage import init_project

    opened = init_project(pathlib.Path(tempfile.mkdtemp()), name="Scan")
    method_names = set(build_registry(ProjectService(opened)))

    root = pathlib.Path(__file__).resolve().parent.parent / "project_tool"
    found: set[str] = set()
    for sub in ("application", "storage"):
        for path in (root / sub).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                value = node.value
                head, _, tail = value.partition(".")
                # tail 必须是合法标识符，否则会扫进多行 docstring 和错误消息
                # （"""area.* 方法：……""" 的 head 是 area，会被误收）
                if not tail.replace("_", "").isalpha() or not tail.islower():
                    continue
                if head in EVENT_TYPE_PREFIXES and value not in NOT_EVENT_TYPES:
                    found.add(value)
    return found - method_names


def test_every_event_type_is_documented():
    """每个事件类型都必须在 docs/08-events.md 的表里登记。

    V1-C 加了 `task.claimed` / `task.released` / `artifact.added` 三个事件，
    代码里有、文档里没有——而 docs/08 自己写着「新增事件类型必须在本文件登记」。
    文档自称是事件契约，少登记一个就等于契约有洞，所以这里把它变成可执行的。
    """
    documented = set(
        re.findall(r"`([a-z_]+\.[a-z_]+)`", DOC_PATH.read_text(encoding="utf-8"))
    )
    missing = sorted(_scan_event_types() - documented)
    assert not missing, (
        "这些事件在代码里存在，但 docs/08-events.md 没有登记：\n  "
        + "\n  ".join(missing)
        + "\n新增事件类型必须在本文件登记（docs/08 §3）。"
    )
