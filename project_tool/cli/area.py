"""area 子命令：稳定的项目分区 / 工作领域。"""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.tree import Tree

from project_tool.cli.common import ExpectedRev, console, execute, sid
from project_tool.cli.render import (
    render_area_list,
    render_area_matches,
    render_area_owners,
    render_area_show,
    render_events,
    render_task_table,
)

area_app = typer.Typer(help="Areas (stable project partitions)", no_args_is_help=True)


@area_app.command("add")
def area_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Area name")],
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    parent: Annotated[str | None, typer.Option("--parent", help="Parent area (id or name)")] = None,
    path_pattern: Annotated[
        list[str] | None,
        typer.Option("--path-pattern", help="Project-relative glob (repeatable)"),
    ] = None,
) -> None:
    """Create an area."""
    execute(
        ctx,
        "area.create",
        {
            "name": name,
            "description": description,
            "parent_area_id": parent,
            "path_patterns": path_pattern,
        },
        render=lambda r: console.print(f"[green]created[/green] {r['id']}  {r['name']}"),
    )


@area_app.command("list")
def area_list(
    ctx: typer.Context,
    parent: Annotated[str | None, typer.Option("--parent", help="Only direct children of PARENT")] = None,
    include_archived: Annotated[bool, typer.Option("--all", help="Include archived areas")] = False,
) -> None:
    """List areas."""
    execute(
        ctx,
        "area.list",
        {"parent": parent, "include_archived": include_archived},
        render=render_area_list,
    )


@area_app.command("show")
def area_show(
    ctx: typer.Context,
    area_id: Annotated[str, typer.Argument(help="Area id, short id or name")],
) -> None:
    """Show an area summary."""
    execute(ctx, "area.get", {"area_id": area_id}, render=render_area_show)


@area_app.command("tree")
def area_tree(ctx: typer.Context) -> None:
    """Show the area hierarchy as a tree."""
    execute(ctx, "area.list", {"include_archived": True}, render=_render_area_tree)


def _render_area_tree(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no areas[/dim]")
        return
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for row in rows:
        by_parent.setdefault(row.get("parent_area_id"), []).append(row)
    known = {row["id"] for row in rows}
    root = Tree("[bold]Areas[/bold]")

    def add(parent_node, area, seen):
        label = f"{sid(area['id'])}  {area['name']}  [dim]{area['task_count']} task(s)[/dim]"
        if area.get("path_patterns"):
            label += f"  [dim]{len(area['path_patterns'])} path pattern(s)[/dim]"
        if area["lifecycle"] != "active":
            label += f"  [dim]({area['lifecycle']})[/dim]"
        if area["id"] in seen:
            parent_node.add(label + " [red](cycle)[/red]")
            return
        branch = parent_node.add(label)
        for child in sorted(
            by_parent.get(area["id"], []), key=lambda item: item["name"].casefold()
        ):
            add(branch, child, seen | {area["id"]})

    for area in sorted(by_parent.get(None, []), key=lambda item: item["name"].casefold()):
        add(root, area, set())
    orphans = [
        row
        for parent, items in by_parent.items()
        if parent
        for row in items
        if parent not in known
    ]
    for area in sorted(orphans, key=lambda item: item["name"].casefold()):
        add(root, area, set())
    console.print(root)


@area_app.command("edit")
def area_edit(
    ctx: typer.Context,
    area_id: Annotated[str, typer.Argument(help="Area id, short id or name")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    parent: Annotated[str | None, typer.Option("--parent", help="Set parent area; '' to detach")] = None,
    path_pattern: Annotated[
        list[str] | None,
        typer.Option(
            "--path-pattern",
            help="Project-relative glob bound to this area (repeatable; '' clears all)",
        ),
    ] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Edit an area."""
    params: dict = {
        "area_id": area_id,
        "name": name,
        "description": description,
        "expected_rev": expected_rev,
    }
    if parent is not None:
        params["parent_area_id"] = parent or None
    if path_pattern is not None:
        params["path_patterns"] = [p for p in path_pattern if p != ""]
    execute(ctx, "area.update", params, render=lambda r: console.print(f"{r['id']} updated"))


@area_app.command("archive")
def area_archive(
    ctx: typer.Context,
    area_id: Annotated[str, typer.Argument(help="Area id, short id or name")],
    expected_rev: ExpectedRev = None,
) -> None:
    """Archive an area (tasks keep their area reference)."""
    execute(
        ctx,
        "area.archive",
        {"area_id": area_id, "expected_rev": expected_rev},
        render=lambda r: console.print(f"{r['id']} archived"),
    )


@area_app.command("restore")
def area_restore(
    ctx: typer.Context,
    area_id: Annotated[str, typer.Argument(help="Area id, short id or name")],
    expected_rev: ExpectedRev = None,
) -> None:
    """Restore an archived area."""
    execute(
        ctx,
        "area.restore",
        {"area_id": area_id, "expected_rev": expected_rev},
        render=lambda r: console.print(f"{r['id']} restored"),
    )


@area_app.command("tasks")
def area_tasks(
    ctx: typer.Context,
    area_id: Annotated[str, typer.Argument()],
    include_archived: Annotated[bool, typer.Option("--include-archived")] = False,
) -> None:
    """List tasks belonging to an area."""
    execute(
        ctx,
        "area.tasks",
        {"area_id": area_id, "include_archived": include_archived},
        render=lambda r: render_task_table(r) if r else console.print("[dim]no tasks[/dim]"),
    )


@area_app.command("set-parent")
def area_set_parent(
    ctx: typer.Context,
    area_id: Annotated[str, typer.Argument()],
    parent: Annotated[str | None, typer.Option("--parent", help="Parent area id; omit to detach")] = None,
    rev: ExpectedRev = None,
) -> None:
    """Set (or clear) an area's parent area."""
    execute(
        ctx,
        "area.set_parent",
        {"area_id": area_id, "parent_area_id": parent, "expected_rev": rev},
        render=lambda r: console.print(f"{r['id']} parent -> {r.get('parent_area_id') or '(none)'}"),
    )


@area_app.command("match-path")
def area_match_path(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Project-relative path to match against path_patterns")],
) -> None:
    """Show which areas claim a path via their path_patterns (read-only)."""
    execute(ctx, "area.match_path", {"path": path}, render=render_area_matches)


@area_app.command("history")
def area_history(ctx: typer.Context, area_id: Annotated[str, typer.Argument()]) -> None:
    """Show area event history."""
    execute(ctx, "area.history", {"area_id": area_id}, render=render_events)


@area_app.command("set-owner")
def area_set_owner(
    ctx: typer.Context,
    area_id: Annotated[str, typer.Argument()],
    add: Annotated[
        list[str] | None, typer.Option("--add", help="Member to add as owner (repeatable)")
    ] = None,
    remove: Annotated[
        list[str] | None, typer.Option("--remove", help="Member to remove (repeatable)")
    ] = None,
    rev: ExpectedRev = None,
) -> None:
    """Add/remove the members responsible for an area.

    One owner = a private block; several owners = a shared interface area.
    """
    execute(
        ctx,
        "area.set_owner",
        {"area_id": area_id, "add": add, "remove": remove, "expected_rev": rev},
        render=render_area_owners,
    )
