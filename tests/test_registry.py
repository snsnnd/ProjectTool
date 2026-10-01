from __future__ import annotations

import pytest

from project_tool.domain.errors import InvalidArgument
from project_tool.version import SCHEMA_VERSION


def test_capabilities_exposes_methods_and_features(service):
    caps = service.call("system.capabilities", {})
    assert caps["protocol_version"] == 1
    assert caps["schema_version"] == SCHEMA_VERSION
    for name in (
        "project.get",
        "project.update",
        "project.recover",
        "area.create",
        "area.list",
        "artifact.create",
        "artifact.verify",
        "task.related_artifacts",
        "git.available",
        "git.status",
        "git.log",
        "git.link_commit",
        "task.create",
        "task.move_area",
        "task.set_status",
        "system.capabilities",
    ):
        assert name in caps["methods"]
    assert caps["methods"] == sorted(caps["methods"])
    assert set(caps["features"]) == {
        "area",
        "artifact",
        "git",
        "search",
        "web",
        "remote",
        "sync",
    }
    # 已落地：area / artifact / git（只读感知）
    assert caps["features"]["area"] is True
    assert caps["features"]["artifact"] is True
    assert caps["features"]["git"] is True
    # 明确不做 / 未做：serverless 决定砍掉 remote 与 sync
    assert not any(
        caps["features"][name] for name in ("search", "web", "remote", "sync")
    )


def test_registry_covers_every_declared_domain(service):
    categories = {spec.category for spec in service.registry.values()}
    assert {"system", "project", "area", "artifact", "task", "milestone", "goal",
            "member", "update", "decision", "link", "git", "log", "graph"} <= categories


def test_registry_specs_have_metadata(service):
    spec = service.registry["task.set_status"]
    assert spec.mutating is True
    assert spec.category == "task"
    assert spec.description
    read_spec = service.registry["task.get"]
    assert read_spec.mutating is False
    assert all(callable(item.handler) for item in service.registry.values())


def test_registry_names_unique(service):
    names = list(service.registry)
    assert len(names) == len(set(names))


def test_unknown_method_rejected(service):
    with pytest.raises(InvalidArgument):
        service.call("task.explode", {})
    with pytest.raises(InvalidArgument):
        service.call("nonsense", {})


def test_handle_returns_error_payload(service):
    response = service.handle("task.get", {"task_id": "TSK-01K8H2MBQX"}, request_id="r1")
    assert response["id"] == "r1"
    assert response["error"]["code"] == "NOT_FOUND"


def test_handle_returns_result_payload(service):
    response = service.handle("system.info", {}, request_id="r2")
    assert response["id"] == "r2"
    assert response["result"]["tool"] == "project-tool"


# ------------------------------------------------------- CLI / registry 对齐


def test_every_cli_method_map_target_exists(tmp_path):
    """CLI_METHOD_MAP 里的 method 名必须是真实存在的 registry method。

    这条防的是「文档/映射表慢慢和代码脱节」——手写的映射表迟早会错，
    而错成不存在的 method 只会让调用方在运行时才发现。
    """
    from project_tool.application.service import ProjectService
    from project_tool.cli.main import CLI_METHOD_FANOUT, CLI_METHOD_MAP
    from project_tool.storage import init_project, open_project

    init_project(tmp_path, name="Map")
    available = set(
        ProjectService(open_project(tmp_path)).call("system.capabilities", {})["methods"]
    )
    missing = {
        path: method for path, method in CLI_METHOD_MAP.items() if method not in available
    }
    assert missing == {}, f"CLI_METHOD_MAP points at non-existent methods: {missing}"
    missing_fanout = {
        path: [m for m in methods if m not in available]
        for path, methods in CLI_METHOD_FANOUT.items()
    }
    missing_fanout = {k: v for k, v in missing_fanout.items() if v}
    assert missing_fanout == {}, missing_fanout


def test_system_cli_lists_every_command_with_a_resolvable_method(tmp_path):
    from project_tool.application.service import ProjectService
    from project_tool.storage import init_project, open_project

    init_project(tmp_path, name="Surface")
    service = ProjectService(open_project(tmp_path))
    surface = service.call("system.cli", {})
    available = set(service.call("system.capabilities", {})["methods"])

    commands = [c for c in surface["commands"] if c["kind"] == "command"]
    assert len(commands) > 100, f"only {len(commands)} commands found"
    for command in commands:
        targets = ([command["method"]] if command["method"] else []) + command.get("also_calls", [])
        assert targets, (
            f"{command['path']} 既没有 method 也没有 also_calls："
            f"CLI_METHOD_MAP 漏登记了。system.cli 是对外的机器可读命令面"
            f"（KC 靠它发现命令），漏登记的命令在别人眼里就没有落点。"
        )
        for target in targets:
            assert target in available, f"{command['path']} -> {target} not in registry"
        assert command["summary"], f"{command['path']} has no summary (missing docstring?)"


def test_capabilities_detail_is_backward_compatible(tmp_path):
    """detail=False 必须保持原有形状——不能为了加元信息破坏既有调用方。"""
    from project_tool.application.service import ProjectService
    from project_tool.storage import init_project, open_project

    init_project(tmp_path, name="Compat")
    service = ProjectService(open_project(tmp_path))
    plain = service.call("system.capabilities", {})
    assert set(plain) == {"protocol_version", "schema_version", "methods", "features"}

    detail = service.call("system.capabilities", {"detail": True})
    assert set(plain).issubset(set(detail))
    assert detail["specs"]["area.set_owner"]["mutating"] is True
    assert "area.set_owner" in detail["mutating_methods"]
    assert "area.list" in detail["read_only_methods"]
    # 两边必须互补且不重叠
    assert set(detail["read_only_methods"]) | set(detail["mutating_methods"]) == set(
        detail["methods"]
    )
    assert not set(detail["read_only_methods"]) & set(detail["mutating_methods"])


# ================================================================== 命令面脱节


#: 这些命令在 `cli/task.py` 里全部走同一个 `_set_status` wrapper
STATUS_SHORTCUTS = ("ready", "start", "block", "review", "done", "cancel")


def test_status_shortcuts_all_map_to_set_status():
    """状态快捷命令共用一个 wrapper，最容易和 `CLI_METHOD_MAP` 脱节。

    `task ready` 曾经被登记成 `task.list`。运行期无害——它照样 dispatch 到
    `set_status`——但 `system.cli` 是 KC 发现命令面的依据，外部消费者会
    按 `method` 生成界面，于是拿到一个与实际行为不符的方法名。
    """
    from project_tool.cli.main import CLI_METHOD_MAP

    for name in STATUS_SHORTCUTS:
        assert CLI_METHOD_MAP[f"task.{name}"] == "task.set_status", (
            f"task {name} 实际调 set_status，映射却写成 "
            f"{CLI_METHOD_MAP[f'task.{name}']}"
        )


def test_map_entries_point_at_methods_their_module_actually_calls():
    """映射到的 method 必须真的出现在对应 CLI 模块里，不能只是碰巧存在。

    这条比「method 在 registry 里」强：那只能证明目标有效，证明不了
    声明与行为一致，而后者正是 `task.ready` 出错的地方。
    """
    import pathlib

    from project_tool.cli.main import CLI_METHOD_MAP

    cli_dir = pathlib.Path(__file__).resolve().parent.parent / "project_tool" / "cli"
    sources = {p.stem: p.read_text(encoding="utf-8") for p in cli_dir.glob("*.py")}

    # 这些 method 由共享渲染器 / 根命令回调调用，源码里不出现字面量
    not_literal = {
        "project.init",  # cli/project.py 走 app.callback
        "log.list",  # cli/log.py
    }

    # 顶层命令的实现在别的模块：domain 名是命令名，模块名不是
    top_level_home = {
        "init": "project",
        "status": "project",
        "doctor": "project",
        "migrate": "project",
        "log": "log",
        "graph": "graph",
    }

    checked = 0
    for path, method in CLI_METHOD_MAP.items():
        if method in not_literal:
            continue
        domain = path.split(".", 1)[0] if "." in path else top_level_home[path]
        source = sources.get(domain, "")
        assert f'"{method}"' in source or f"'{method}'" in source, (
            f"CLI_METHOD_MAP 声明 {path} -> {method}，"
            f"但 cli/{domain}.py 里找不到对它的调用"
        )
        checked += 1
    assert checked > 90, f"只校验了 {checked} 条，映射表可能没被真正遍历"
