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
