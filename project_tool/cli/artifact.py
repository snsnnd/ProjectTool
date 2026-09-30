"""artifact 子命令：工程产物的引用（V1-A）。

Artifact 只是 reference：本模块的命令**不会**创建、修改、移动或删除
被引用的工程文件。`pjt artifact remove` 只删除 Project Tool 里的引用对象。
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from project_tool.cli.common import ExpectedRev, console, execute, sid
from project_tool.cli.render import (
    render_artifact_list,
    render_artifact_show,
    render_artifact_verify,
    render_events,
)

artifact_app = typer.Typer(help="Artifact references (no content storage)", no_args_is_help=True)


def _metadata(pairs: list[str] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in pairs or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise typer.BadParameter(f"metadata must be KEY=VALUE, got {item!r}")
        result[key] = value
    return result


@artifact_app.command("add")
def artifact_add(
    ctx: typer.Context,
    kind: Annotated[str, typer.Argument(help="file|url|git_commit|git_branch|report|document|…")],
    locator: Annotated[str, typer.Argument(help="Reference (project-relative path for 'file')")],
    name: Annotated[str | None, typer.Option("--name", help="Display name (default: locator)")] = None,
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    task: Annotated[list[str] | None, typer.Option("--task", "-t", help="Related task")] = None,
    decision: Annotated[list[str] | None, typer.Option("--decision")] = None,
    milestone: Annotated[list[str] | None, typer.Option("--milestone", "-m")] = None,
    goal: Annotated[list[str] | None, typer.Option("--goal", "-g")] = None,
    meta: Annotated[
        list[str] | None, typer.Option("--meta", help="KEY=VALUE (repeatable)")
    ] = None,
) -> None:
    """Reference an artifact (nothing is copied or written)."""
    execute(
        ctx,
        "artifact.create",
        {
            "kind": kind,
            "locator": locator,
            "name": name,
            "description": description,
            "task": task,
            "decision": decision,
            "milestone": milestone,
            "goal": goal,
            "metadata": _metadata(meta) or None,
        },
        render=lambda r: console.print(
            f"[green]referenced[/green] {r['id']}  {r['kind']}  {r['locator']}"
        ),
    )


@artifact_app.command("list")
def artifact_list(
    ctx: typer.Context,
    kind: Annotated[list[str] | None, typer.Option("--kind", help="Filter by kind (repeatable)")] = None,
    task: Annotated[str | None, typer.Option("--task", "-t")] = None,
    decision: Annotated[str | None, typer.Option("--decision")] = None,
    milestone: Annotated[str | None, typer.Option("--milestone", "-m")] = None,
    goal: Annotated[str | None, typer.Option("--goal", "-g")] = None,
    include_archived: Annotated[bool, typer.Option("--all", help="Include archived")] = False,
) -> None:
    """List artifact references."""
    execute(
        ctx,
        "artifact.list",
        {
            "kind": kind,
            "task": task,
            "decision": decision,
            "milestone": milestone,
            "goal": goal,
            "include_archived": include_archived,
        },
        render=render_artifact_list,
    )


@artifact_app.command("show")
def artifact_show(ctx: typer.Context, artifact_id: Annotated[str, typer.Argument()]) -> None:
    """Show an artifact reference."""
    execute(ctx, "artifact.get", {"artifact_id": artifact_id}, render=render_artifact_show)


@artifact_app.command("edit")
def artifact_edit(
    ctx: typer.Context,
    artifact_id: Annotated[str, typer.Argument()],
    name: Annotated[str | None, typer.Option("--name")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    kind: Annotated[str | None, typer.Option("--kind")] = None,
    locator: Annotated[str | None, typer.Option("--locator")] = None,
    meta: Annotated[list[str] | None, typer.Option("--meta", help="KEY=VALUE (repeatable)")] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Edit an artifact reference."""
    params: dict = {
        "artifact_id": artifact_id,
        "name": name,
        "description": description,
        "kind": kind,
        "expected_rev": expected_rev,
    }
    if locator is not None:
        params["locator"] = locator
    if meta:
        params["metadata"] = _metadata(meta)
    execute(ctx, "artifact.update", params, render=lambda r: console.print(f"{r['id']} updated"))


@artifact_app.command("attach")
def artifact_attach(
    ctx: typer.Context,
    artifact_id: Annotated[str, typer.Argument()],
    task: Annotated[list[str] | None, typer.Option("--task", "-t", help="Task id (repeatable)")] = None,
    decision: Annotated[list[str] | None, typer.Option("--decision")] = None,
    milestone: Annotated[list[str] | None, typer.Option("--milestone", "-m")] = None,
    goal: Annotated[list[str] | None, typer.Option("--goal", "-g")] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Attach an artifact to tasks / decisions / milestones / goals."""
    execute(
        ctx,
        "artifact.attach",
        {
            "artifact_id": artifact_id,
            "task": task,
            "decision": decision,
            "milestone": milestone,
            "goal": goal,
            "expected_rev": expected_rev,
        },
        render=_render_relations,
    )


@artifact_app.command("detach")
def artifact_detach(
    ctx: typer.Context,
    artifact_id: Annotated[str, typer.Argument()],
    task: Annotated[list[str] | None, typer.Option("--task", "-t", help="Task id (repeatable)")] = None,
    decision: Annotated[list[str] | None, typer.Option("--decision")] = None,
    milestone: Annotated[list[str] | None, typer.Option("--milestone", "-m")] = None,
    goal: Annotated[list[str] | None, typer.Option("--goal", "-g")] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Detach an artifact from tasks / decisions / milestones / goals."""
    execute(
        ctx,
        "artifact.detach",
        {
            "artifact_id": artifact_id,
            "task": task,
            "decision": decision,
            "milestone": milestone,
            "goal": goal,
            "expected_rev": expected_rev,
        },
        render=_render_relations,
    )


@artifact_app.command("remove")
def artifact_remove(
    ctx: typer.Context,
    artifact_id: Annotated[str, typer.Argument()],
    expected_rev: ExpectedRev = None,
) -> None:
    """Drop the Project Tool reference. Never touches the referenced file."""
    execute(
        ctx,
        "artifact.remove",
        {"artifact_id": artifact_id, "expected_rev": expected_rev},
        render=lambda r: console.print(
            f"{r['id']} removed (reference only; the referenced file is untouched)"
        ),
    )


@artifact_app.command("verify")
def artifact_verify(
    ctx: typer.Context,
    artifact_id: Annotated[
        str | None, typer.Argument(help="Artifact id; omit to verify all")
    ] = None,
) -> None:
    """Verify artifact references (read-only; no events, no network)."""
    rows = execute(ctx, "artifact.verify", {"artifact_id": artifact_id})
    render_artifact_verify(rows)
    if any(row.get("status") == "missing" for row in rows):
        console.print(
            "[dim]missing files are reported as warnings by 'pjt doctor' "
            "(branch switches and deletions are normal)[/dim]"
        )


@artifact_app.command("history")
def artifact_history(
    ctx: typer.Context,
    artifact_id: Annotated[str, typer.Argument()],
) -> None:
    """Show artifact event history."""
    execute(ctx, "artifact.history", {"artifact_id": artifact_id}, render=render_events)


def _render_relations(result: dict[str, Any]) -> None:
    parts = []
    for label, key in (
        ("task", "related_task_ids"),
        ("decision", "related_decision_ids"),
        ("milestone", "related_milestone_ids"),
        ("goal", "related_goal_ids"),
    ):
        items = result.get(key) or []
        if items:
            parts.append(f"{label}: {', '.join(sid(item) for item in items)}")
    console.print(f"{result['id']}  " + ("  ".join(parts) or "(no relations)"))
