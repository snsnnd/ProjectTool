"""显式 method registry：RPC 名称 -> handler + 元数据。

取代 V0 的 `getattr(self, method.replace(".", "_"))` 动态分发，为
REST / SDK / 权限 / OpenAPI / 接口审计提供稳定基础。

未知 method 一律返回 INVALID_ARGUMENT；method 名称保持 V0 兼容。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MethodSpec:
    name: str
    handler: Callable[..., Any]
    mutating: bool
    category: str
    description: str = ""


def build_registry(service) -> dict[str, MethodSpec]:
    project = service.project
    goals = service.goals
    milestones = service.milestones
    areas = service.areas
    tasks = service.tasks
    members = service.members
    updates = service.updates
    decisions = service.decisions
    artifacts = service.artifacts
    links = service.links
    gits = service.git
    logs = service.logs
    graphs = service.graphs
    ifaces = service.interfaces

    specs = [
        # system
        MethodSpec("system.info", service.system.system_info, False, "system", "tool/protocol info"),
        MethodSpec(
            "system.capabilities", service.system_capabilities, False, "system", "capability discovery"
        ),
        MethodSpec(
            "system.cli", service.system.system_cli, False, "system", "full CLI command tree"
        ),
        # project
        MethodSpec("project.init", project.project_init, True, "project", "initialize a project"),
        MethodSpec("project.open", project.project_open, False, "project", "open summary"),
        MethodSpec("project.get", project.project_get, False, "project", "read project"),
        MethodSpec(
            "project.update", project.project_update, True, "project", "update project (expected_rev)"
        ),
        MethodSpec("project.status", project.project_status, False, "project", "status summary"),
        MethodSpec("project.doctor", project.project_doctor, False, "project", "integrity check"),
        MethodSpec("project.migrate", project.project_migrate, True, "project", "schema migration"),
        MethodSpec("project.recover", project.project_recover, True, "project", "transaction recovery"),
        # goal
        MethodSpec("goal.create", goals.goal_create, True, "goal", "create goal"),
        MethodSpec("goal.get", goals.goal_get, False, "goal", "read goal"),
        MethodSpec("goal.list", goals.goal_list, False, "goal", "list goals"),
        MethodSpec("goal.update", goals.goal_update, True, "goal", "update goal"),
        MethodSpec("goal.set_status", goals.goal_set_status, True, "goal", "change goal status"),
        MethodSpec("goal.archive", goals.goal_archive, True, "goal", "archive goal"),
        MethodSpec("goal.restore", goals.goal_restore, True, "goal", "restore goal"),
        # milestone
        MethodSpec("milestone.create", milestones.milestone_create, True, "milestone", "create milestone"),
        MethodSpec("milestone.get", milestones.milestone_get, False, "milestone", "read milestone"),
        MethodSpec("milestone.list", milestones.milestone_list, False, "milestone", "list milestones"),
        MethodSpec("milestone.update", milestones.milestone_update, True, "milestone", "update milestone"),
        MethodSpec(
            "milestone.activate", milestones.milestone_activate, True, "milestone", "activate milestone"
        ),
        MethodSpec("milestone.close", milestones.milestone_close, True, "milestone", "close milestone"),
        MethodSpec("milestone.cancel", milestones.milestone_cancel, True, "milestone", "cancel milestone"),
        MethodSpec(
            "milestone.progress", milestones.milestone_progress, False, "milestone", "derived progress"
        ),
        # area
        MethodSpec("area.create", areas.area_create, True, "area", "create area"),
        MethodSpec("area.get", areas.area_get, False, "area", "read area"),
        MethodSpec("area.list", areas.area_list, False, "area", "list areas"),
        MethodSpec("area.update", areas.area_update, True, "area", "update area"),
        MethodSpec("area.set_parent", areas.area_set_parent, True, "area", "set parent area"),
        MethodSpec(
            "area.set_owner", areas.area_set_owner, True, "area", "add/remove area owners"
        ),
        MethodSpec("area.archive", areas.area_archive, True, "area", "archive area"),
        MethodSpec("area.restore", areas.area_restore, True, "area", "restore area"),
        MethodSpec("area.tasks", areas.area_tasks, False, "area", "tasks in an area"),
        MethodSpec(
            "area.match_path", areas.area_match_path, False, "area", "areas matching a path"
        ),
        MethodSpec("area.history", areas.area_history, False, "area", "area event history"),
        MethodSpec(
            "area.activity", areas.area_activity, False, "area", "recent git activity per area"
        ),
        # task
        MethodSpec("task.create", tasks.task_create, True, "task", "create task"),
        MethodSpec("task.get", tasks.task_get, False, "task", "read task"),
        MethodSpec("task.list", tasks.task_list, False, "task", "list tasks"),
        MethodSpec("task.update", tasks.task_update, True, "task", "update task"),
        MethodSpec("task.set_status", tasks.task_set_status, True, "task", "change task status"),
        MethodSpec("task.assign", tasks.task_assign, True, "task", "assign owner"),
        MethodSpec("task.unassign", tasks.task_unassign, True, "task", "remove owner"),
        MethodSpec("task.add_dependency", tasks.task_add_dependency, True, "task", "add dependency"),
        MethodSpec("task.remove_dependency", tasks.task_remove_dependency, True, "task", "remove dependency"),
        MethodSpec("task.add_label", tasks.task_add_label, True, "task", "add label"),
        MethodSpec("task.remove_label", tasks.task_remove_label, True, "task", "remove label"),
        MethodSpec("task.move_milestone", tasks.task_move_milestone, True, "task", "move task to milestone"),
        MethodSpec("task.move_area", tasks.task_move_area, True, "task", "move task to area"),
        MethodSpec("task.set_parent", tasks.task_set_parent, True, "task", "set parent task"),
        MethodSpec("task.archive", tasks.task_archive, True, "task", "archive task"),
        MethodSpec("task.restore", tasks.task_restore, True, "task", "restore task"),
        MethodSpec("task.delete", tasks.task_delete, True, "task", "soft delete task"),
        MethodSpec("task.related_updates", tasks.task_related_updates, False, "task", "related updates"),
        MethodSpec(
            "task.related_artifacts",
            tasks.task_related_artifacts,
            False,
            "task",
            "related artifacts",
        ),
        MethodSpec("task.history", tasks.task_history, False, "task", "task event history"),
        # member
        MethodSpec("member.add", members.member_add, True, "member", "add member"),
        MethodSpec("member.get", members.member_get, False, "member", "read member"),
        MethodSpec("member.list", members.member_list, False, "member", "list members"),
        MethodSpec("member.update", members.member_update, True, "member", "update member"),
        MethodSpec("member.deactivate", members.member_deactivate, True, "member", "deactivate member"),
        MethodSpec("member.activate", members.member_activate, True, "member", "activate member"),
        MethodSpec("member.workload", members.member_workload, False, "member", "member workload"),
        MethodSpec("member.activity", members.member_activity, False, "member", "member activity"),
        MethodSpec("member.use", members.member_use, True, "member", "set local default actor"),
        MethodSpec(
            "member.map_git_identity", members.member_map_git_identity, True, "member", "map git identity"
        ),
        # update
        MethodSpec("update.create", updates.update_create, True, "update", "record update"),
        MethodSpec("update.get", updates.update_get, False, "update", "read update"),
        MethodSpec("update.list", updates.update_list, False, "update", "list updates"),
        MethodSpec("update.update", updates.update_update, True, "update", "update record"),
        MethodSpec("update.archive", updates.update_archive, True, "update", "archive update"),
        MethodSpec("update.history", updates.update_history, False, "update", "update history"),
        # decision
        MethodSpec("decision.create", decisions.decision_create, True, "decision", "record decision"),
        MethodSpec("decision.get", decisions.decision_get, False, "decision", "read decision"),
        MethodSpec("decision.list", decisions.decision_list, False, "decision", "list decisions"),
        MethodSpec("decision.update", decisions.decision_update, True, "decision", "update decision"),
        MethodSpec("decision.accept", decisions.decision_accept, True, "decision", "accept decision"),
        MethodSpec("decision.reject", decisions.decision_reject, True, "decision", "reject decision"),
        MethodSpec(
            "decision.supersede", decisions.decision_supersede, True, "decision", "supersede decision"
        ),
        MethodSpec("decision.history", decisions.decision_history, False, "decision", "decision history"),
        # artifact
        MethodSpec(
            "artifact.create", artifacts.artifact_create, True, "artifact", "reference an artifact"
        ),
        MethodSpec("artifact.get", artifacts.artifact_get, False, "artifact", "read artifact"),
        MethodSpec("artifact.list", artifacts.artifact_list, False, "artifact", "list artifacts"),
        MethodSpec("artifact.update", artifacts.artifact_update, True, "artifact", "update artifact"),
        MethodSpec(
            "artifact.remove", artifacts.artifact_remove, True, "artifact", "drop the reference only"
        ),
        MethodSpec(
            "artifact.attach", artifacts.artifact_attach, True, "artifact", "attach to task/decision"
        ),
        MethodSpec(
            "artifact.detach", artifacts.artifact_detach, True, "artifact", "detach from task/decision"
        ),
        MethodSpec("artifact.verify", artifacts.artifact_verify, False, "artifact", "verify locators"),
        MethodSpec(
            "artifact.history", artifacts.artifact_history, False, "artifact", "artifact event history"
        ),
        # link
        MethodSpec("link.add", links.link_add, True, "link", "add linked project"),
        MethodSpec("link.get", links.link_get, False, "link", "read link"),
        MethodSpec("link.list", links.link_list, False, "link", "list links"),
        MethodSpec("link.update", links.link_update, True, "link", "update link"),
        MethodSpec("link.remove", links.link_remove, True, "link", "remove link"),
        MethodSpec("link.resolve", links.link_resolve, False, "link", "resolve link locally"),
        MethodSpec("link.status", links.link_status, False, "link", "link status"),
        MethodSpec(
            "link.map_local_path",
            links.link_map_local_path,
            True,
            "link",
            "record a machine-local absolute path for a link (local.toml, no event)",
        ),
        MethodSpec(
            "link.unmap_local_path",
            links.link_unmap_local_path,
            True,
            "link",
            "drop a machine-local path mapping (local.toml, no event)",
        ),
        # git（只读感知；link_commit 只写 .pjt，不写仓库）
        # interface（V1-C）：工作树里的固定模板 markdown + Artifact 注册
        MethodSpec(
            "interface.init", ifaces.interface_init, True, "interface", "scaffold an interface doc"
        ),
        MethodSpec(
            "interface.list", ifaces.interface_list, False, "interface", "list interface docs"
        ),
        MethodSpec(
            "interface.show", ifaces.interface_show, False, "interface", "read one interface doc"
        ),
        MethodSpec(
            "interface.register",
            ifaces.interface_register,
            True,
            "interface",
            "register an existing markdown as an interface",
        ),
        MethodSpec(
            "interface.sync", ifaces.interface_sync, True, "interface", "align with front-matter"
        ),
        MethodSpec(
            "interface.check", ifaces.interface_check, False, "interface", "validate interface docs"
        ),
        MethodSpec("git.available", gits.git_available, False, "git", "git availability"),
        MethodSpec("git.status", gits.git_status, False, "git", "changed files + candidate areas"),
        MethodSpec("git.log", gits.git_log, False, "git", "commit history by task trailer"),
        MethodSpec(
            "git.link_commit", gits.git_link_commit, True, "git", "register a commit as an artifact"
        ),
        # log
        MethodSpec("log.list", logs.log_list, False, "log", "list events"),
        MethodSpec("log.get", logs.log_get, False, "log", "read event"),
        MethodSpec("log.entity", logs.log_entity, False, "log", "events by entity"),
        MethodSpec("log.member", logs.log_member, False, "log", "events by member"),
        MethodSpec("log.since", logs.log_since, False, "log", "events since time"),
        # graph
        MethodSpec("graph.project", graphs.graph_project, False, "graph", "project tree"),
        MethodSpec("graph.tasks", graphs.graph_tasks, False, "graph", "task graph"),
        MethodSpec("graph.dependencies", graphs.graph_dependencies, False, "graph", "dependency graph"),
        MethodSpec("graph.links", graphs.graph_links, False, "graph", "linked projects"),
    ]
    registry: dict[str, MethodSpec] = {}
    for spec in specs:
        if spec.name in registry:
            raise ValueError(f"duplicate method registration: {spec.name}")
        registry[spec.name] = spec
    return registry
