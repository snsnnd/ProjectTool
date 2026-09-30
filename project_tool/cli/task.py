"""task 子命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import console, execute, sid
from project_tool.cli.render import (
    porcelain_tasks,
    render_events,
    render_task_show,
    render_task_table,
)

task_app = typer.Typer(help="Task management", no_args_is_help=True)


@task_app.command("add")
def task_add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(help="Task title")],
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    owner: Annotated[
        list[str] | None, typer.Option("--owner", "-o", help="Owner member (repeatable)")
    ] = None,
    milestone: Annotated[str | None, typer.Option("--milestone", "-m")] = None,
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    priority: Annotated[str, typer.Option("--priority", "-p", help="critical|high|normal|low")] = "normal",
    weight: Annotated[int, typer.Option("--weight", "-w")] = 1,
    label: Annotated[list[str] | None, typer.Option("--label", "-l", help="Label (repeatable)")] = None,
    accept: Annotated[
        list[str] | None, typer.Option("--accept", help="Acceptance criterion (repeatable)")
    ] = None,
    due: Annotated[str | None, typer.Option("--due", help="Due datetime (ISO-8601)")] = None,
    status: Annotated[str, typer.Option("--status", help="Initial status")] = "inbox",
) -> None:
    """Create a task."""
    execute(
        ctx,
        "task.create",
        {
            "title": title,
            "description": description,
            "owner_ids": owner,
            "milestone_id": milestone,
            "parent_task_id": parent,
            "priority": priority,
            "weight": weight,
            "labels": label,
            "acceptance_criteria": accept,
            "due_at": due,
            "status": status,
        },
        render=lambda result: console.print(f"[green]created[/green] {result['id']}  {result['title']}"),
    )


@task_app.command("list")
def task_list(
    ctx: typer.Context,
    status: Annotated[
        list[str] | None, typer.Option("--status", "-s", help="Filter by status (repeatable)")
    ] = None,
    owner: Annotated[str | None, typer.Option("--owner", "-o")] = None,
    label: Annotated[str | None, typer.Option("--label", "-l")] = None,
    milestone: Annotated[str | None, typer.Option("--milestone", "-m")] = None,
    priority: Annotated[list[str] | None, typer.Option("--priority", "-p")] = None,
    parent: Annotated[str | None, typer.Option("--parent")] = None,
    include_archived: Annotated[bool, typer.Option("--all", help="Include archived tasks")] = False,
) -> None:
    """List tasks."""
    execute(
        ctx,
        "task.list",
        {
            "status": status,
            "owner": owner,
            "label": label,
            "milestone": milestone,
            "priority": priority,
            "parent": parent,
            "include_archived": include_archived,
        },
        render=render_task_table,
        porcelain_render=porcelain_tasks,
    )


@task_app.command("show")
def task_show(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task id (full or short)")],
) -> None:
    """Show task details."""
    execute(ctx, "task.get", {"task_id": task_id}, render=render_task_show)


def _set_status(ctx: typer.Context, task_id: str, target: str, expected_rev: str | None = None) -> None:
    execute(
        ctx,
        "task.set_status",
        {"task_id": task_id, "status": target, "expected_rev": expected_rev},
        render=lambda result: console.print(f"{result['id']} -> [bold]{result['status']}[/bold]"),
    )


@task_app.command("ready")
def task_ready(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    expected_rev: Annotated[
        str | None, typer.Option("--expected-rev", help="Fail if the task rev differs")
    ] = None,
) -> None:
    """Mark task as ready to start (from inbox, blocked or review)."""
    _set_status(ctx, task_id, "ready", expected_rev=expected_rev)


@task_app.command("start")
def task_start(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    expected_rev: Annotated[
        str | None, typer.Option("--expected-rev", help="Fail if the task rev differs")
    ] = None,
) -> None:
    """Mark task as doing."""
    _set_status(ctx, task_id, "doing", expected_rev=expected_rev)


@task_app.command("block")
def task_block(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    expected_rev: Annotated[
        str | None, typer.Option("--expected-rev", help="Fail if the task rev differs")
    ] = None,
) -> None:
    """Mark task as blocked."""
    _set_status(ctx, task_id, "blocked", expected_rev=expected_rev)


@task_app.command("review")
def task_review(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    expected_rev: Annotated[
        str | None, typer.Option("--expected-rev", help="Fail if the task rev differs")
    ] = None,
) -> None:
    """Mark task as ready for review."""
    _set_status(ctx, task_id, "review", expected_rev=expected_rev)


@task_app.command("done")
def task_done(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    expected_rev: Annotated[
        str | None, typer.Option("--expected-rev", help="Fail if the task rev differs")
    ] = None,
) -> None:
    """Mark task as done."""
    _set_status(ctx, task_id, "done", expected_rev=expected_rev)


@task_app.command("cancel")
def task_cancel(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    expected_rev: Annotated[
        str | None, typer.Option("--expected-rev", help="Fail if the task rev differs")
    ] = None,
) -> None:
    """Cancel task."""
    _set_status(ctx, task_id, "cancelled", expected_rev=expected_rev)


@task_app.command("assign")
def task_assign(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    member: Annotated[str, typer.Argument()],
) -> None:
    """Assign a member to a task."""
    execute(
        ctx,
        "task.assign",
        {"task_id": task_id, "member": member},
        render=lambda result: console.print(
            f"{result['id']} owners: {', '.join(sid(o) for o in result['owner_ids'])}"
        ),
    )


@task_app.command("unassign")
def task_unassign(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    member: Annotated[str, typer.Argument()],
) -> None:
    """Remove a member from a task."""
    execute(
        ctx,
        "task.unassign",
        {"task_id": task_id, "member": member},
        render=lambda result: console.print(
            f"{result['id']} owners: {', '.join(sid(o) for o in result['owner_ids']) or '-'}"
        ),
    )


@task_app.command("depend")
def task_depend(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task that depends")],
    target_id: Annotated[str, typer.Argument(help="Task being depended on")],
    relation: Annotated[
        str, typer.Option("--relation", help="depends_on|relates_to|duplicates")
    ] = "depends_on",
) -> None:
    """Add a dependency: TASK depends on TARGET."""
    execute(
        ctx,
        "task.add_dependency",
        {"task_id": task_id, "target_id": target_id, "relation": relation},
        render=lambda result: console.print(
            f"{result['id']} dependencies: "
            f"{', '.join(sid(dep['task_id']) for dep in result['dependencies']) or '-'}"
        ),
    )


@task_app.command("undepend")
def task_undepend(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    target_id: Annotated[str, typer.Argument()],
) -> None:
    """Remove a dependency."""
    execute(
        ctx,
        "task.remove_dependency",
        {"task_id": task_id, "target_id": target_id},
        render=lambda result: console.print(f"{result['id']} dependency removed"),
    )


@task_app.command("label")
def task_label(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    label: Annotated[str, typer.Argument()],
) -> None:
    """Add a label."""
    execute(
        ctx,
        "task.add_label",
        {"task_id": task_id, "label": label},
        render=lambda result: console.print(f"{result['id']} labels: {', '.join(result['labels'])}"),
    )


@task_app.command("unlabel")
def task_unlabel(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    label: Annotated[str, typer.Argument()],
) -> None:
    """Remove a label."""
    execute(
        ctx,
        "task.remove_label",
        {"task_id": task_id, "label": label},
        render=lambda result: console.print(
            f"{result['id']} labels: {', '.join(result['labels']) or '-'}"
        ),
    )


@task_app.command("move")
def task_move(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    milestone_id: Annotated[str | None, typer.Argument(help="Target milestone; omit to detach")] = None,
) -> None:
    """Move a task to another milestone (or detach)."""
    execute(
        ctx,
        "task.move_milestone",
        {"task_id": task_id, "milestone_id": milestone_id},
        render=lambda result: console.print(f"{result['id']} milestone: {sid(result.get('milestone_id'))}"),
    )


@task_app.command("archive")
def task_archive(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Archive a task."""
    execute(ctx, "task.archive", {"task_id": task_id}, render=lambda r: console.print(f"{r['id']} archived"))


@task_app.command("restore")
def task_restore(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Restore an archived task."""
    execute(ctx, "task.restore", {"task_id": task_id}, render=lambda r: console.print(f"{r['id']} restored"))


@task_app.command("delete")
def task_delete(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Soft-delete a task (lifecycle=deleted)."""
    execute(
        ctx,
        "task.delete",
        {"task_id": task_id},
        render=lambda r: console.print(f"{r['id']} deleted (recoverable)"),
    )


@task_app.command("history")
def task_history(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Show task event history."""
    execute(ctx, "task.history", {"task_id": task_id}, render=render_events)
