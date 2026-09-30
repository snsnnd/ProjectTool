"""project 级命令：init / status / doctor / migrate。"""

from __future__ import annotations

import json as jsonlib
from pathlib import Path
from typing import Annotated

import typer

from project_tool.application.service import ProjectService
from project_tool.cli.common import CliState, console, emit, execute, fail
from project_tool.cli.render import (
    porcelain_status,
    render_doctor,
    render_init,
    render_recover,
    render_status,
)
from project_tool.domain.errors import ProjectToolError


def init(
    ctx: typer.Context,
    path: Annotated[str | None, typer.Argument(help="Project directory (default: cwd)")] = None,
    name: Annotated[str | None, typer.Option("--name", help="Project name")] = None,
    description: Annotated[str, typer.Option("--description", "-d", help="Project description")] = "",
    slug: Annotated[str | None, typer.Option("--slug", help="Project slug")] = None,
) -> None:
    """Initialize a new .pjt project."""
    state: CliState = ctx.obj
    target = path or state.project or str(Path.cwd())
    try:
        result = ProjectService.project_init(
            target, name=name, description=description, slug=slug
        )
    except ProjectToolError as exc:
        fail(state, exc)
    emit(state, result, render=render_init)


def status(
    ctx: typer.Context,
    recent: Annotated[int, typer.Option("--recent", help="Recent event count")] = 10,
) -> None:
    """Show project status summary."""
    execute(
        ctx,
        "project.status",
        {"recent": recent},
        render=render_status,
        porcelain_render=porcelain_status,
    )


def doctor(
    ctx: typer.Context,
    repair: Annotated[
        bool,
        typer.Option("--repair", help="Run transaction recovery / stale lock cleanup first"),
    ] = False,
) -> None:
    """Check project integrity."""
    if repair:
        execute(ctx, "project.recover", {}, render=render_recover)
    result = execute(ctx, "project.doctor", {}, render=render_doctor)
    if isinstance(result, dict) and not result.get("ok", True):
        raise typer.Exit(9)


def migrate(ctx: typer.Context) -> None:
    """Run schema migrations (create missing collections + bump project schema_version)."""
    execute(
        ctx,
        "project.migrate",
        {},
        render=lambda result: console.print(jsonlib.dumps(result, ensure_ascii=False)),
    )
