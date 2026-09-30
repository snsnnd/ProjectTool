"""decision 子命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import ExpectedRev, console, execute, read_text_argument, sid
from project_tool.cli.render import render_decision_list, render_events

decision_app = typer.Typer(help="Decision records", no_args_is_help=True)


@decision_app.command("add")
def decision_add(
    ctx: typer.Context,
    title: Annotated[
        str | None, typer.Argument(help="Decision title; omit to use $EDITOR/stdin")
    ] = None,
    title_option: Annotated[
        str | None, typer.Option("--title", help="Decision title (same as positional)")
    ] = None,
    context: Annotated[str, typer.Option("--context")] = "",
    decision: Annotated[str, typer.Option("--decision")] = "",
    rationale: Annotated[str, typer.Option("--rationale")] = "",
    alternative: Annotated[
        list[str] | None,
        typer.Option("--alternative", help="Alternative name or name::reason (repeatable)"),
    ] = None,
    consequence: Annotated[
        list[str] | None, typer.Option("--consequence", help="Consequence (repeatable)")
    ] = None,
    task: Annotated[
        list[str] | None, typer.Option("--task", "-t", help="Related task (repeatable)")
    ] = None,
    status: Annotated[str, typer.Option("--status")] = "draft",
) -> None:
    """Record an architecture/engineering decision."""
    title_text = title_option or title
    if not title_text:
        title_text = read_text_argument(None).splitlines()[0].strip()
    alternatives: list[str | dict[str, str]] = []
    for item in alternative or []:
        if "::" in item:
            name, reason = item.split("::", 1)
            alternatives.append({"name": name.strip(), "reason_not_selected": reason.strip()})
        else:
            alternatives.append(item)
    execute(
        ctx,
        "decision.create",
        {
            "title": title_text,
            "context": context,
            "decision": decision,
            "rationale": rationale,
            "alternatives": alternatives,
            "consequences": consequence,
            "related_task_ids": task,
            "status": status,
        },
        render=lambda r: console.print(f"[green]recorded[/green] {r['id']}  {r['title']}"),
    )


@decision_app.command("list")
def decision_list(
    ctx: typer.Context,
    status: Annotated[list[str] | None, typer.Option("--status", "-s")] = None,
) -> None:
    """List decisions."""
    execute(
        ctx,
        "decision.list",
        {"status": status},
        render=render_decision_list,
    )


@decision_app.command("show")
def decision_show(ctx: typer.Context, decision_id: Annotated[str, typer.Argument()]) -> None:
    """Show a decision."""
    execute(ctx, "decision.get", {"decision_id": decision_id})


@decision_app.command("edit")
def decision_edit(
    ctx: typer.Context,
    decision_id: Annotated[str, typer.Argument()],
    title: Annotated[str | None, typer.Option("--title")] = None,
    context: Annotated[str | None, typer.Option("--context")] = None,
    decision: Annotated[str | None, typer.Option("--decision")] = None,
    rationale: Annotated[str | None, typer.Option("--rationale")] = None,
    alternative: Annotated[
        list[str] | None, typer.Option("--alternative", help="name::reason (repeatable)")
    ] = None,
    consequence: Annotated[list[str] | None, typer.Option("--consequence")] = None,
    task: Annotated[list[str] | None, typer.Option("--task", "-t", help="Replace related tasks")] = None,
    expected_rev: ExpectedRev = None,
) -> None:
    """Edit a decision."""
    alternatives: list[str | dict[str, str]] = []
    for item in alternative or []:
        if "::" in item:
            name, reason = item.split("::", 1)
            alternatives.append({"name": name.strip(), "reason_not_selected": reason.strip()})
        else:
            alternatives.append(item)
    execute(
        ctx,
        "decision.update",
        {
            "decision_id": decision_id,
            "title": title,
            "context": context,
            "decision": decision,
            "rationale": rationale,
            "alternatives": alternatives or None,
            "consequences": consequence,
            "related_task_ids": task,
            "expected_rev": expected_rev,
        },
        render=lambda r: console.print(f"{r['id']} updated"),
    )


@decision_app.command("accept")
def decision_accept(ctx: typer.Context, decision_id: Annotated[str, typer.Argument()]) -> None:
    """Accept a decision."""
    execute(
        ctx,
        "decision.accept",
        {"decision_id": decision_id},
        render=lambda r: console.print(f"{r['id']} -> accepted"),
    )


@decision_app.command("reject")
def decision_reject(ctx: typer.Context, decision_id: Annotated[str, typer.Argument()]) -> None:
    """Reject a decision."""
    execute(
        ctx,
        "decision.reject",
        {"decision_id": decision_id},
        render=lambda r: console.print(f"{r['id']} -> rejected"),
    )


@decision_app.command("supersede")
def decision_supersede(
    ctx: typer.Context,
    old_id: Annotated[str, typer.Argument(help="Decision being replaced")],
    new_id: Annotated[str, typer.Argument(help="Decision that replaces it")],
) -> None:
    """Supersede OLD decision with NEW decision."""
    execute(
        ctx,
        "decision.supersede",
        {"old_id": old_id, "new_id": new_id},
        render=lambda r: console.print(
            f"{sid(r['superseded']['id'])} superseded by {sid(r['superseded_by']['id'])}"
        ),
    )


@decision_app.command("history")
def decision_history(ctx: typer.Context, decision_id: Annotated[str, typer.Argument()]) -> None:
    """Show decision event history."""
    execute(ctx, "decision.history", {"decision_id": decision_id}, render=render_events)
