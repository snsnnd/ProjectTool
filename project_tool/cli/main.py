"""pjt CLI 根入口：全局选项、子命令注册、统一错误处理。

拆分后的命令模块：

```text
cli/project.py    init / status / doctor / migrate
cli/task.py       pjt task ...
cli/area.py       pjt area ...
cli/artifact.py   pjt artifact ...
cli/git.py        pjt git ...
cli/goal.py       pjt goal ...
cli/milestone.py  pjt milestone ...
cli/member.py     pjt member ...
cli/update.py     pjt update ...
cli/decision.py   pjt decision ...
cli/link.py       pjt link ...
cli/log.py        pjt log
cli/graph.py      pjt graph
```

CLI 只调用 Application Service，不直接访问 storage。
"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool import __version__
from project_tool.cli import (
    area,
    artifact,
    decision,
    goal,
    interface,
    link,
    member,
    milestone,
    task,
    update,
)
from project_tool.cli import git as git_module
from project_tool.cli import graph as graph_module
from project_tool.cli import log as log_module
from project_tool.cli import project as project_module
from project_tool.cli.common import CliState, console, err_console
from project_tool.domain.errors import ProjectToolError

app = typer.Typer(
    name="pjt",
    help="Local-first, Git-aware project state and collaboration system.",
    add_completion=False,
    # invoke_without_command 让 `pjt --version` / `pjt --help` 不被「缺少子命令」挡掉；
    # 无子命令时在 callback 里手动打印 help（与 no_args_is_help 等价但 exit code 稳定为 0）。
    invoke_without_command=True,
)


@app.callback()
def main_callback(
    ctx: typer.Context,
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable JSON output")] = False,
    porcelain: Annotated[bool, typer.Option("--porcelain", help="Stable script-friendly output")] = False,
    as_member: Annotated[
        str | None, typer.Option("--as", help="Actor for this command (handle or id)")
    ] = None,
    project: Annotated[str | None, typer.Option("-C", "--project", help="Project path")] = None,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit")] = False,
) -> None:
    if version:
        console.print(f"project-tool {__version__}")
        raise typer.Exit()
    ctx.obj = CliState(json_out=json_out, porcelain=porcelain, actor=as_member, project=project)
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


app.command()(project_module.init)
app.command()(project_module.status)
app.command()(project_module.doctor)
app.command()(project_module.migrate)

app.add_typer(task.task_app, name="task")
app.add_typer(area.area_app, name="area")
app.add_typer(artifact.artifact_app, name="artifact")
app.add_typer(interface.interface_app, name="interface")
app.add_typer(git_module.git_app, name="git")
app.add_typer(project_module.project_app, name="project")
app.add_typer(goal.goal_app, name="goal")
app.add_typer(milestone.milestone_app, name="milestone")
app.add_typer(member.member_app, name="member")
app.add_typer(update.update_app, name="update")
app.add_typer(decision.decision_app, name="decision")
app.add_typer(link.link_app, name="link")

app.command()(log_module.log)
app.command()(graph_module.graph)


def main() -> None:
    try:
        app()
    except ProjectToolError as exc:
        err_console.print(f"[red]{exc.code}[/red] {exc.message}")
        raise SystemExit(exc.exit_code) from exc


if __name__ == "__main__":
    main()


def cli_surface() -> list[dict]:
    """导出完整的 CLI 命令树（机器可读）。

    为什么不只靠 `--help`：`--help` 是给人看的文本，没有稳定的字段名，
    脚本解析它就会脆。KC 这类平台包装需要**结构化**的命令清单，
    才能生成自己的界面 / 文档 / 校验用户的输入。

    每一项：
      path        ["area", "set-owner"]，顶层命令就是单元素
      method      对应的 registry method 名（能对上就一定对上；不暴露的
                  命令 method 为 null）
      summary     一句话说明（来自命令 docstring 的首行）
      params      [{name, flag, required, is_flag, help, choices}]
    """
    from typer.main import get_command

    def walk(cmd, prefix: list[str], out: list[dict]) -> None:
        if isinstance(cmd, typer.core.TyperGroup):
            if prefix:
                out.append(
                    {
                        "path": prefix,
                        # 分组节点不是可执行命令，别和「未映射的命令」混在一起
                        "kind": "group",
                        "method": None,
                        "summary": _summary(cmd),
                        "params": [],
                    }
                )
            for name in sorted(cmd.commands):
                walk(cmd.commands[name], prefix + [name], out)
            return
        params = []
        for param in getattr(cmd, "params", []):
            opts = getattr(param, "opts", []) or []
            if not opts or opts[0] in ("--help", "--install-completion"):
                continue
            params.append(
                {
                    "name": param.name,
                    # typer 对位置参数的 opts 是参数名本身，不是 --flag
                    "flag": opts[0] if opts[0].startswith("-") else None,
                    "positional": not opts[0].startswith("-"),
                    "required": bool(getattr(param, "required", False)),
                    "is_flag": bool(getattr(param, "is_flag", False)),
                    "multiple": bool(getattr(param, "multiple", False)),
                    "help": (getattr(param, "help", "") or "").strip(),
                }
            )
        out.append(
            {
                "path": prefix,
                "kind": "command",
                "method": _method_for_command(prefix),
                # 分派到多个 method 的命令（如 `pjt graph <scope>`）放这里
                "also_calls": CLI_METHOD_FANOUT.get(" ".join(prefix), []),
                "summary": _summary(cmd),
                "params": params,
            }
        )

    entries: list[dict] = []
    walk(get_command(app), [], entries)
    return sorted(entries, key=lambda item: item["path"])


def _summary(cmd) -> str:
    doc = (getattr(cmd, "help", "") or "").strip()
    return doc.splitlines()[0] if doc else ""


#: 一条命令按运行时分派到**多个** method（`pjt graph <scope>` 就是这种）。
#: 单个 `method` 字段表达不了这种情况，硬塞一个等于骗人。
CLI_METHOD_FANOUT: dict[str, list[str]] = {
    # `pjt graph <scope>` 的 scope 是 project|tasks|milestone|projects，实际 dispatch 到
    # graph.project / graph.tasks（tasks 与 milestone 两个 scope 都走它）/ graph.links。
    # graph.dependencies **没有任何 CLI 入口**（只在 registry 里，KC 走 API 用）。
    "graph": ["graph.project", "graph.tasks", "graph.links"],
}


def _method_for_command(path: list[str]) -> str | None:
    """命令路径 -> registry method 名（单一时）。

    映射是**显式维护**的：CLI 的动词是人话（add/edit/show），method 名是
    领域名（create/update/get），两者不是机械对应。猜错比返回 null 更糟，
    所以对不上的就返回 null；分派到多个 method 的走 `CLI_METHOD_FANOUT`。
    """
    return CLI_METHOD_MAP.get(".".join(path))


#: `pjt <path>` -> `registry method`。**只列能确定的**；其余返回 null。
CLI_METHOD_MAP: dict[str, str] = {
    "init": "project.init",
    "status": "project.status",
    "doctor": "project.doctor",
    "migrate": "project.migrate",
    "log": "log.list",
    "area.add": "area.create",
    "area.list": "area.list",
    "area.show": "area.get",
    "area.edit": "area.update",
    "area.archive": "area.archive",
    "area.restore": "area.restore",
    "area.tasks": "area.tasks",
    "area.set-parent": "area.set_parent",
    "area.set-owner": "area.set_owner",
    "area.match-path": "area.match_path",
    "area.activity": "area.activity",
    "area.history": "area.history",
    "artifact.add": "artifact.create",
    "artifact.list": "artifact.list",
    "artifact.show": "artifact.get",
    "artifact.edit": "artifact.update",
    "artifact.attach": "artifact.attach",
    "artifact.detach": "artifact.detach",
    "artifact.remove": "artifact.remove",
    "artifact.verify": "artifact.verify",
    "artifact.history": "artifact.history",
    "decision.add": "decision.create",
    "decision.list": "decision.list",
    "decision.show": "decision.get",
    "decision.edit": "decision.update",
    "decision.accept": "decision.accept",
    "decision.reject": "decision.reject",
    "decision.supersede": "decision.supersede",
    "decision.history": "decision.history",
    "goal.add": "goal.create",
    "goal.list": "goal.list",
    "goal.show": "goal.get",
    "goal.edit": "goal.update",
    "goal.achieve": "goal.set_status",
    "goal.drop": "goal.set_status",
    "area.tree": "area.list",
    "goal.archive": "goal.archive",
    "goal.restore": "goal.restore",
    "interface.init": "interface.init",
    "interface.list": "interface.list",
    "interface.show": "interface.show",
    "interface.register": "interface.register",
    "interface.check": "interface.check",
    "interface.sync": "interface.sync",
    "git.status": "git.status",
    "git.log": "git.log",
    "git.link-commit": "git.link_commit",
    "link.add": "link.add",
    "link.list": "link.list",
    "link.show": "link.get",
    "link.edit": "link.update",
    "link.remove": "link.remove",
    "link.resolve": "link.resolve",
    "link.status": "link.status",
    "link.map-local": "link.map_local_path",
    "link.unmap-local": "link.unmap_local_path",
    "member.add": "member.add",
    "member.list": "member.list",
    "member.show": "member.get",
    "member.edit": "member.update",
    "member.use": "member.use",
    "member.map-git": "member.map_git_identity",
    "member.deactivate": "member.deactivate",
    "member.activate": "member.activate",
    "member.workload": "member.workload",
    "member.activity": "member.activity",
    "milestone.add": "milestone.create",
    "milestone.list": "milestone.list",
    "milestone.show": "milestone.get",
    "milestone.edit": "milestone.update",
    "milestone.activate": "milestone.activate",
    "milestone.close": "milestone.close",
    "milestone.cancel": "milestone.cancel",
    "milestone.progress": "milestone.progress",
    "project.show": "project.get",
    "project.edit": "project.update",
    "task.add": "task.create",
    "task.list": "task.list",
    "task.show": "task.get",
    "task.edit": "task.update",
    "task.ready": "task.set_status",
    "task.start": "task.set_status",
    "task.block": "task.set_status",
    "task.review": "task.set_status",
    "task.done": "task.set_status",
    "task.cancel": "task.set_status",
    "task.archive": "task.archive",
    "task.restore": "task.restore",
    "task.delete": "task.delete",
    "task.assign": "task.assign",
    "task.unassign": "task.unassign",
    "task.depend": "task.add_dependency",
    "task.undepend": "task.remove_dependency",
    "task.label": "task.add_label",
    "task.unlabel": "task.remove_label",
    "task.move": "task.move_milestone",
    "task.move-area": "task.move_area",
    "task.set-parent": "task.set_parent",
    "task.artifacts": "task.related_artifacts",
    "task.related-updates": "task.related_updates",
    "task.history": "task.history",
    "task.next": "task.next",
    "task.claim": "task.claim",
    "task.release": "task.release",
    "task.related-interfaces": "task.related_interfaces",
    "update.add": "update.create",
    "update.list": "update.list",
    "update.show": "update.get",
    "update.edit": "update.update",
    "update.archive": "update.archive",
    "update.history": "update.history",
}
