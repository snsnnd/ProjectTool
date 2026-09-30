"""member 子命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import console, execute
from project_tool.cli.render import render_events, render_member_list, render_member_workload

member_app = typer.Typer(help="Member management", no_args_is_help=True)


@member_app.command("add")
def member_add(
    ctx: typer.Context,
    handle: Annotated[str, typer.Argument(help="Unique lowercase handle")],
    name: Annotated[str | None, typer.Option("--name", help="Display name")] = None,
    role: Annotated[list[str] | None, typer.Option("--role", help="Role (repeatable)")] = None,
    git_name: Annotated[
        list[str] | None, typer.Option("--git-name", help="Git author name (repeatable)")
    ] = None,
    git_email: Annotated[
        list[str] | None, typer.Option("--git-email", help="Git author email (repeatable)")
    ] = None,
) -> None:
    """Add a project member."""
    execute(
        ctx,
        "member.add",
        {
            "handle": handle,
            "display_name": name,
            "roles": role,
            "git_names": git_name,
            "git_emails": git_email,
        },
        render=lambda r: console.print(
            f"[green]added[/green] {r['handle']}  {r['display_name']}  ({r['id']})"
        ),
    )


@member_app.command("list")
def member_list(
    ctx: typer.Context,
    include_inactive: Annotated[bool, typer.Option("--all", help="Include inactive members")] = False,
) -> None:
    """List members."""
    execute(
        ctx,
        "member.list",
        {"include_inactive": include_inactive},
        render=render_member_list,
    )


@member_app.command("show")
def member_show(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Show a member."""
    execute(ctx, "member.get", {"member": member})


@member_app.command("edit")
def member_edit(
    ctx: typer.Context,
    member: Annotated[str, typer.Argument()],
    name: Annotated[str | None, typer.Option("--name")] = None,
    role: Annotated[list[str] | None, typer.Option("--role")] = None,
    git_name: Annotated[list[str] | None, typer.Option("--git-name")] = None,
    git_email: Annotated[list[str] | None, typer.Option("--git-email")] = None,
) -> None:
    """Edit a member."""
    execute(
        ctx,
        "member.update",
        {
            "member": member,
            "display_name": name,
            "roles": role,
            "git_names": git_name,
            "git_emails": git_email,
        },
        render=lambda r: console.print(f"{r['handle']} updated"),
    )


@member_app.command("deactivate")
def member_deactivate(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Deactivate a member."""
    execute(
        ctx,
        "member.deactivate",
        {"member": member},
        render=lambda r: console.print(f"{r['handle']} deactivated"),
    )


@member_app.command("activate")
def member_activate(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Activate a member."""
    execute(
        ctx,
        "member.activate",
        {"member": member},
        render=lambda r: console.print(f"{r['handle']} activated"),
    )


@member_app.command("workload")
def member_workload(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Show member workload."""
    execute(ctx, "member.workload", {"member": member}, render=render_member_workload)


@member_app.command("activity")
def member_activity(
    ctx: typer.Context,
    member: Annotated[str, typer.Argument()],
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
) -> None:
    """Show member recent activity."""
    execute(ctx, "member.activity", {"member": member, "limit": limit}, render=render_events)


@member_app.command("use")
def member_use(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Set default actor in .pjt/local/local.toml for this machine."""
    execute(
        ctx,
        "member.use",
        {"member": member},
        render=lambda r: console.print(f"default actor: {r['handle']} ({r['actor']})"),
    )
