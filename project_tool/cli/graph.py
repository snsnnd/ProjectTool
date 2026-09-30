"""graph 命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import CliState, execute, fail
from project_tool.cli.render import (
    render_link_resolution,
    render_project_graph,
    render_task_graph,
)
from project_tool.domain.errors import InvalidArgument


def graph(
    ctx: typer.Context,
    scope: Annotated[str, typer.Argument(help="project|tasks|milestone|projects")] = "project",
    target: Annotated[str | None, typer.Argument(help="Milestone id for `graph milestone`")] = None,
) -> None:
    """Show project graph (project tree / task tree / links)."""
    if scope == "project":
        execute(ctx, "graph.project", {}, render=render_project_graph)
    elif scope == "tasks":
        execute(
            ctx,
            "graph.tasks",
            {"milestone_id": target},
            render=lambda result: render_task_graph(result, "Tasks"),
        )
    elif scope == "milestone":
        if not target:
            state: CliState = ctx.obj
            fail(state, InvalidArgument("graph milestone requires a milestone id"))
        execute(
            ctx,
            "graph.tasks",
            {"milestone_id": target},
            render=lambda result: render_task_graph(result, f"Milestone {target}"),
        )
    elif scope == "projects":
        execute(ctx, "graph.links", {}, render=render_link_resolution)
    else:
        cli_state: CliState = ctx.obj
        fail(
            cli_state,
            InvalidArgument(f"unknown graph scope: {scope!r} (project|tasks|milestone|projects)"),
        )
