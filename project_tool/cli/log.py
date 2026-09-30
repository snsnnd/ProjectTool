"""log 命令。"""

from __future__ import annotations

from typing import Annotated

import typer

from project_tool.cli.common import execute
from project_tool.cli.render import porcelain_events, render_events


def log(
    ctx: typer.Context,
    task: Annotated[str | None, typer.Option("--task", "-t", help="Filter by task")] = None,
    member: Annotated[str | None, typer.Option("--member", "-m", help="Filter by actor")] = None,
    event_type: Annotated[str | None, typer.Option("--type", help="Event type (prefix ok)")] = None,
    since: Annotated[str | None, typer.Option("--since", help="ISO time or 7d/24h/30m")] = None,
    until: Annotated[str | None, typer.Option("--until")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
) -> None:
    """Show project event history."""
    params: dict = {
        "event_type": event_type,
        "member": member,
        "since": since,
        "until": until,
        "limit": limit,
        "cursor": cursor,
    }
    if task:
        params["entity_type"] = "task"
        params["entity_id"] = task
    execute(ctx, "log.list", params, render=render_events, porcelain_render=porcelain_events)
