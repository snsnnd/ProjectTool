"""link 子命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import ExpectedRev, console, execute
from project_tool.cli.render import render_link_list

link_app = typer.Typer(help="Linked projects", no_args_is_help=True)


@link_app.command("add")
def link_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument()],
    locator: Annotated[str, typer.Argument(help="Relative path or URL")],
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="local_project|remote_project|git_repository|external"),
    ] = None,
    mode: Annotated[str, typer.Option("--mode", help="reference|aggregate")] = "reference",
    project_id: Annotated[str | None, typer.Option("--project-id")] = None,
) -> None:
    """Link another project (relative path / URL / project id only)."""
    execute(
        ctx,
        "link.add",
        {"name": name, "locator": locator, "kind": kind, "mode": mode, "project_id": project_id},
        render=lambda r: console.print(f"[green]linked[/green] {r['name']} -> {r['target']['locator']}"),
    )


@link_app.command("list")
def link_list(ctx: typer.Context) -> None:
    """List linked projects."""
    execute(
        ctx,
        "link.list",
        {},
        render=render_link_list,
    )


@link_app.command("show")
def link_show(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Show a link."""
    execute(ctx, "link.get", {"name": name})


@link_app.command("resolve")
def link_resolve(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Resolve a link target on this machine."""
    execute(
        ctx,
        "link.resolve",
        {"name": name},
        render=lambda r: console.print(
            f"{r['name']}: resolved={r['resolved']} "
            f"path={r.get('path', '-')} project={r.get('project', {})} error={r.get('error', '-')}"
        ),
    )


@link_app.command("edit")
def link_edit(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument()],
    locator: Annotated[str | None, typer.Option("--locator", help="Relative path or URL")] = None,
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="local_project|remote_project|git_repository|external"),
    ] = None,
    mode: Annotated[str | None, typer.Option("--mode", help="reference|aggregate")] = None,
    enable: Annotated[bool | None, typer.Option("--enable/--disable")] = None,
    project_id: Annotated[str | None, typer.Option("--project-id")] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Edit a linked project."""
    params: dict = {
        "name": name,
        "kind": kind,
        "mode": mode,
        "enabled": enable,
        "expected_rev": expected_rev,
    }
    if locator is not None:
        params["locator"] = locator
    if project_id is not None:
        params["project_id"] = project_id
    execute(ctx, "link.update", params, render=lambda r: console.print(f"{r['name']} updated"))


@link_app.command("remove")
def link_remove(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Remove a link."""
    execute(ctx, "link.remove", {"name": name}, render=lambda r: console.print(f"{r['name']} removed"))
