"""milestone 子命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import ExpectedRev, bar, console, execute
from project_tool.cli.render import render_milestone_list, render_milestone_show

milestone_app = typer.Typer(help="Milestone management", no_args_is_help=True)


@milestone_app.command("add")
def milestone_add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument()],
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    goal: Annotated[list[str] | None, typer.Option("--goal", "-g", help="Goal id (repeatable)")] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
    status: Annotated[str, typer.Option("--status")] = "planned",
) -> None:
    """Create a milestone."""
    execute(
        ctx,
        "milestone.create",
        {"title": title, "description": description, "goal_ids": goal, "due_at": due, "status": status},
        render=lambda r: console.print(f"[green]created[/green] {r['id']}  {r['title']}"),
    )


@milestone_app.command("list")
def milestone_list(
    ctx: typer.Context,
    status: Annotated[list[str] | None, typer.Option("--status", "-s")] = None,
    include_archived: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    """List milestones with derived progress."""
    execute(
        ctx,
        "milestone.list",
        {"status": status, "include_archived": include_archived},
        render=render_milestone_list,
    )


@milestone_app.command("show")
def milestone_show(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Show milestone details and progress."""
    execute(
        ctx,
        "milestone.get",
        {"milestone_id": milestone_id},
        render=render_milestone_show,
    )


@milestone_app.command("edit")
def milestone_edit(
    ctx: typer.Context,
    milestone_id: Annotated[str, typer.Argument()],
    title: Annotated[str | None, typer.Option("--title")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    goal: Annotated[list[str] | None, typer.Option("--goal", "-g")] = None,
    due: Annotated[str | None, typer.Option("--due")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Edit a milestone."""
    params: dict = {
        "milestone_id": milestone_id,
        "title": title,
        "description": description,
        "goal_ids": goal,
        "status": status,
        "expected_rev": expected_rev,
    }
    if due is not None:
        params["due_at"] = due
    execute(ctx, "milestone.update", params, render=lambda r: console.print(f"{r['id']} updated"))


@milestone_app.command("activate")
def milestone_activate(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Activate a milestone."""
    execute(
        ctx,
        "milestone.activate",
        {"milestone_id": milestone_id},
        render=lambda r: console.print(f"{r['id']} -> active"),
    )


@milestone_app.command("close")
def milestone_close(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Close a milestone."""
    execute(
        ctx,
        "milestone.close",
        {"milestone_id": milestone_id},
        render=lambda r: console.print(f"{r['id']} -> closed"),
    )


@milestone_app.command("cancel")
def milestone_cancel(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Cancel a milestone."""
    execute(
        ctx,
        "milestone.cancel",
        {"milestone_id": milestone_id},
        render=lambda r: console.print(f"{r['id']} -> cancelled"),
    )


@milestone_app.command("progress")
def milestone_progress(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Show derived milestone progress."""
    execute(
        ctx,
        "milestone.progress",
        {"milestone_id": milestone_id},
        render=lambda r: console.print(
            f"{bar(r['progress'])} {r['progress'] * 100:.0f}%  "
            f"({r['done_weight']}/{r['total_weight']} weight)"
        ),
    )
