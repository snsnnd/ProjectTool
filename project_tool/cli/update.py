"""update 子命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import ExpectedRev, console, execute, read_text_argument
from project_tool.cli.render import render_events, render_update_list

update_app = typer.Typer(help="Progress updates", no_args_is_help=True)


@update_app.command("add")
def update_add(
    ctx: typer.Context,
    text: Annotated[str | None, typer.Argument(help="Update text; omit to use $EDITOR/stdin")] = None,
    task: Annotated[list[str] | None, typer.Option("--task", "-t", help="Related task (repeatable)")] = None,
    milestone: Annotated[str | None, typer.Option("--milestone", "-m")] = None,
    summary: Annotated[str | None, typer.Option("--summary", "-s")] = None,
    blocker: Annotated[list[str] | None, typer.Option("--blocker", help="Blocker (repeatable)")] = None,
    next_step: Annotated[list[str] | None, typer.Option("--next", help="Next step (repeatable)")] = None,
) -> None:
    """Record a progress update."""
    body = read_text_argument(text)
    execute(
        ctx,
        "update.create",
        {
            "summary": summary,
            "body": body,
            "task_ids": task,
            "milestone_id": milestone,
            "blockers": blocker,
            "next_steps": next_step,
        },
        render=lambda r: console.print(f"[green]recorded[/green] {r['id']}  {r['summary']}"),
    )


@update_app.command("list")
def update_list(
    ctx: typer.Context,
    task: Annotated[str | None, typer.Option("--task", "-t")] = None,
    milestone: Annotated[str | None, typer.Option("--milestone", "-m")] = None,
) -> None:
    """List updates."""
    execute(
        ctx,
        "update.list",
        {"task": task, "milestone": milestone},
        render=render_update_list,
    )


@update_app.command("show")
def update_show(ctx: typer.Context, update_id: Annotated[str, typer.Argument()]) -> None:
    """Show an update."""
    execute(ctx, "update.get", {"update_id": update_id})


@update_app.command("edit")
def update_edit(
    ctx: typer.Context,
    update_id: Annotated[str, typer.Argument()],
    summary: Annotated[str | None, typer.Option("--summary")] = None,
    body: Annotated[str | None, typer.Option("--body")] = None,
    rev: ExpectedRev = None,
) -> None:
    """Edit a progress update."""
    execute(
        ctx,
        "update.update",
        {
            "update_id": update_id,
            "summary": summary,
            "body": body,
            "expected_rev": rev,
        },
        render=lambda r: console.print(f"{r['id']} updated  {r['summary']}"),
    )


@update_app.command("archive")
def update_archive(
    ctx: typer.Context,
    update_id: Annotated[str, typer.Argument()],
    rev: ExpectedRev = None,
) -> None:
    """Archive a progress update."""
    execute(
        ctx,
        "update.archive",
        {"update_id": update_id, "expected_rev": rev},
        render=lambda r: console.print(f"{r['id']} archived"),
    )


@update_app.command("history")
def update_history(ctx: typer.Context, update_id: Annotated[str, typer.Argument()]) -> None:
    """Show update event history."""
    execute(ctx, "update.history", {"update_id": update_id}, render=render_events)
