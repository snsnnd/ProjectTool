"""project 级命令：init / status / doctor / migrate + `pjt project …`。"""

from __future__ import annotations

import json as jsonlib
from pathlib import Path
from typing import Annotated, Any

import typer

from project_tool.application.service import ProjectService
from project_tool.cli.common import CliState, ExpectedRev, console, emit, execute, fail
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


# ------------------------------------------------------------------ pjt project …

project_app = typer.Typer(help="Project record (rename / description / status)", no_args_is_help=True)


@project_app.command("show")
def project_show(ctx: typer.Context) -> None:
    """Show the project record (id, name, description, status, rev).

    用 `project.get`（扁平记录），与 `task show` / `goal show` 形状一致；
    `project.open` 那层 wrapper（root / device_id / actor）留给程序化调用。
    """
    execute(ctx, "project.get", {}, render=render_project_show)


@project_app.command("edit")
def project_edit(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Option("--name")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="planned|active|paused|completed|archived")
    ] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Edit the project record.

    `--expected-rev` guards against overwriting someone else's change.
    """
    params: dict = {
        "name": name,
        "description": description,
        "status": status,
        "expected_rev": expected_rev,
    }
    execute(ctx, "project.update", params, render=render_project_show)


def render_project_show(result: dict[str, Any]) -> None:
    # 兼容 project.open 的 wrapper 形状（其它调用方可能复用这个 renderer）
    project = result.get("project", result)
    console.print(f"[bold]{project['name']}[/bold]  [dim]({project['id']})[/dim]")
    console.print(f"  slug        {project['slug']}")
    console.print(f"  status      {project['status']}")
    if project.get("description"):
        console.print(f"  description {project['description']}")
    console.print(
        f"  [dim]schema {project['schema_version']}  rev {project.get('rev', '')}  "
        f"v{project.get('version', 1)}[/dim]"
    )
