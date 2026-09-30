"""goal 子命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import ExpectedRev, console, execute
from project_tool.cli.render import render_goal_list

goal_app = typer.Typer(help="Goal management", no_args_is_help=True)


@goal_app.command("add")
def goal_add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument()],
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    criterion: Annotated[
        list[str] | None, typer.Option("--criterion", help="Success criterion (repeatable)")
    ] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
    status: Annotated[str, typer.Option("--status")] = "active",
) -> None:
    """Create a goal."""
    execute(
        ctx,
        "goal.create",
        {
            "title": title,
            "description": description,
            "parent_goal_id": parent,
            "success_criteria": criterion,
            "due_at": due,
            "status": status,
        },
        render=lambda r: console.print(f"[green]created[/green] {r['id']}  {r['title']}"),
    )


@goal_app.command("list")
def goal_list(
    ctx: typer.Context,
    status: Annotated[list[str] | None, typer.Option("--status", "-s")] = None,
    include_archived: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    """List goals."""
    execute(
        ctx,
        "goal.list",
        {"status": status, "include_archived": include_archived},
        render=render_goal_list,
    )


@goal_app.command("show")
def goal_show(ctx: typer.Context, goal_id: Annotated[str, typer.Argument()]) -> None:
    """Show a goal."""
    execute(ctx, "goal.get", {"goal_id": goal_id})


@goal_app.command("edit")
def goal_edit(
    ctx: typer.Context,
    goal_id: Annotated[str, typer.Argument()],
    title: Annotated[str | None, typer.Option("--title")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    criterion: Annotated[list[str] | None, typer.Option("--criterion")] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
    parent: Annotated[str | None, typer.Option("--parent", help="Set parent goal")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Edit a goal."""
    params: dict = {
        "goal_id": goal_id,
        "title": title,
        "description": description,
        "success_criteria": criterion,
        "status": status,
        "expected_rev": expected_rev,
    }
    if due is not None:
        params["due_at"] = due
    if parent is not None:
        params["parent_goal_id"] = parent
    execute(ctx, "goal.update", params, render=lambda r: console.print(f"{r['id']} updated"))


@goal_app.command("achieve")
def goal_achieve(ctx: typer.Context, goal_id: Annotated[str, typer.Argument()]) -> None:
    """Mark goal achieved."""
    execute(
        ctx,
        "goal.set_status",
        {"goal_id": goal_id, "status": "achieved"},
        render=lambda r: console.print(f"{r['id']} -> achieved"),
    )


@goal_app.command("drop")
def goal_drop(ctx: typer.Context, goal_id: Annotated[str, typer.Argument()]) -> None:
    """Drop a goal."""
    execute(
        ctx,
        "goal.set_status",
        {"goal_id": goal_id, "status": "dropped"},
        render=lambda r: console.print(f"{r['id']} -> dropped"),
    )


@goal_app.command("archive")
def goal_archive(
    ctx: typer.Context,
    goal_id: Annotated[str, typer.Argument()],
    rev: ExpectedRev = None,
) -> None:
    """Archive a goal (lifecycle=archived)."""
    execute(
        ctx,
        "goal.archive",
        {"goal_id": goal_id, "expected_rev": rev},
        render=lambda r: console.print(f"{r['id']} archived"),
    )


@goal_app.command("restore")
def goal_restore(
    ctx: typer.Context,
    goal_id: Annotated[str, typer.Argument()],
    rev: ExpectedRev = None,
) -> None:
    """Restore an archived goal."""
    execute(
        ctx,
        "goal.restore",
        {"goal_id": goal_id, "expected_rev": rev},
        render=lambda r: console.print(f"{r['id']} restored"),
    )
