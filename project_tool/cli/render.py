"""CLI 输出渲染。"""

from __future__ import annotations

import unicodedata
from typing import Any

import typer
from rich.padding import Padding
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from project_tool.cli.common import bar, console, event_detail, sid, ts
from project_tool.domain.ids import short_id


def display_width(text: str) -> int:
    """终端显示宽度：全角字符（中文/日文/emoji）算 2 列。"""
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in str(text)
    )


def ellipsis(text: str, width: int) -> str:
    """按显示宽度截断并加省略号（中文按 2 列算）。

    终端表格里的长标题必须**截断**而不是折行——折行会让每个任务占两行，
    十几个任务就没法扫了（V0.1 dogfooding 报告 P3-7 的实际观感）。
    要看完整标题用 `pjt task show`，要程序处理用 `--json` / `--porcelain`。
    """
    text = str(text)
    if width <= 1:
        return ""
    if display_width(text) <= width:
        return text
    kept: list[str] = []
    used = 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if used + char_width > width - 1:
            break
        kept.append(char)
        used += char_width
    return "".join(kept) + "…"


def render_init(result: dict[str, Any]) -> None:
    project = result["project"]
    console.print(f"[green]Initialized[/green] {project['name']} ({project['id']})")
    console.print(f"  path      {result['root']}")
    console.print(f"  device    {result['device_id']}")
    console.print('  next      pjt member add <handle> --name "..."')


def render_status(result: dict[str, Any]) -> None:
    project = result["project"]
    console.print(
        f"[bold]{project['name']}[/bold]  [dim]({project['id']}, {project['status']})[/dim]"
    )
    if project.get("description"):
        console.print(f"  {project['description']}")

    milestone = result.get("active_milestone")
    if milestone:
        pct = f"{milestone['progress'] * 100:.0f}%"
        console.print(
            f"\n[bold]Active milestone[/bold]  {milestone['title']} "
            f"{bar(milestone['progress'])} {pct}"
        )
        counts = milestone.get("task_status_counts") or {}
        if counts:
            console.print(
                "  " + "  ".join(f"{key}={value}" for key, value in sorted(counts.items()))
            )

    tasks = result.get("tasks") or {}
    non_zero = {key: value for key, value in tasks.items() if value}
    console.print(
        "\n[bold]Tasks[/bold]  "
        + ("  ".join(f"{key} {value}" for key, value in non_zero.items()) or "none")
    )

    blocked = result.get("blocked") or []
    if blocked:
        console.print("\n[bold red]Computed blocked[/bold red]")
        for item in blocked:
            where = " · ".join(
                part
                for part in (item.get("area_name"), item.get("milestone_title"))
                if part
            )
            suffix = f"  [dim]{ellipsis(where, 40)}[/dim]" if where else ""
            console.print(f"  {sid(item['id'])}  {ellipsis(item['title'], 60)}{suffix}")
            console.print(
                f"    [dim]waiting for {', '.join(sid(t) for t in item['blocked_by'])}[/dim]"
            )

    members = result.get("members") or []
    if members:
        console.print("\n[bold]Members[/bold]")
        for member in members:
            console.print(
                f"  {member['handle']:<14} {member['active_tasks']} active"
                f"  (doing {member['doing']}, blocked {member['blocked']})"
            )

    links = result.get("links") or []
    if links:
        console.print("\n[bold]Linked projects[/bold]")
        for link in links:
            console.print(f"  {link['name']:<14} {link['kind']}  {link['locator'] or ''}")

    events = result.get("recent_events") or []
    if events:
        console.print("\n[bold]Recent activity[/bold]")
        for event in events:
            console.print(
                f"  [dim]{ts(event['occurred_at'])}[/dim]  "
                f"{sid(event.get('entity_id'))}  {event['event_type']}  {event_detail(event)}"
            )


def porcelain_status(result: dict[str, Any]) -> None:
    project = result["project"]
    typer.echo(f"project\t{project['id']}\t{project['name']}\t{project['status']}")
    milestone = result.get("active_milestone")
    typer.echo(
        "milestone\t-\t-\t-"
        if not milestone
        else f"milestone\t{milestone['id']}\t{milestone['title']}\t{milestone['progress']}"
    )
    for key, value in sorted((result.get("tasks") or {}).items()):
        typer.echo(f"task_count\t{key}\t{value}")


def render_events(result: dict[str, Any]) -> None:
    events = result.get("events") or []
    if not events:
        console.print("[dim]no events[/dim]")
        return
    for event in events:
        console.print(
            f"[dim]{ts(event['occurred_at'])}[/dim]  "
            f"{sid(event.get('entity_id')):<12} {event['event_type']}  {event_detail(event)}"
        )
    if result.get("next_cursor"):
        console.print(f"[dim]next_cursor {result['next_cursor']}[/dim]")


def porcelain_events(result: dict[str, Any]) -> None:
    for event in result.get("events") or []:
        typer.echo(
            "\t".join(
                [
                    str(event.get("occurred_at") or ""),
                    str(event.get("event_type") or ""),
                    str(event.get("entity_id") or ""),
                    str(event.get("actor_id") or ""),
                ]
            )
        )


def render_doctor(result: dict[str, Any]) -> None:
    colors = {"ok": "green", "warning": "yellow", "error": "red"}
    for check in result.get("checks") or []:
        status = check["status"]
        repairable = " [cyan](repairable)[/cyan]" if check.get("repairable") else ""
        console.print(
            f"  [{colors[status]}]{status.upper():<7}[/{colors[status]}] "
            f"{check['name']:<20} {check['message']}{repairable}"
        )
        if status != "ok" and check.get("details"):
            details = check["details"]
            if isinstance(details, list):
                for detail in details[:10]:
                    console.print(f"          [dim]{detail}[/dim]")
            elif isinstance(details, dict):
                for detail in list(details)[:10]:
                    console.print(f"          [dim]{detail}[/dim]")
    summary = result["summary"]
    verdict = "[green]OK[/green]" if result["ok"] else "[red]ERRORS[/red]"
    console.print(
        f"\n{verdict}  objects={summary['objects']} events={summary['events']} "
        f"errors={summary['errors']} warnings={summary['warnings']} "
        f"repairable={summary.get('repairable', 0)}"
    )


def render_recover(result: dict[str, Any]) -> None:
    if not result.get("count"):
        console.print("[dim]nothing to recover[/dim]")
        return
    for item in result["recovered"]:
        console.print(f"  {item['transaction_id']}  {item['action']}  [dim]{item['detail']}[/dim]")


def render_task_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no tasks[/dim]")
        return
    # 只有 Title 列伸缩（ratio=1），其余列用 min_width 钉死——
    # 否则窄终端下 rich 会把每一列都压成 "inb…" / "nor…"，比折行更糟。
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID", style="dim", no_wrap=True, min_width=13)
    table.add_column("Status", no_wrap=True, min_width=8)
    table.add_column("Priority", no_wrap=True, min_width=8)
    table.add_column("W", no_wrap=True, min_width=1)
    table.add_column("Title", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("Owners", style="dim", no_wrap=True, min_width=13)
    for task in rows:
        status_text = task["status"]
        if task.get("computed_blocked"):
            status_text = f"{status_text} [red]![/red]"
        table.add_row(
            sid(task["id"]),
            status_text,
            task["priority"],
            str(task.get("weight", 1)),
            task["title"],
            ",".join(sid(owner) for owner in task.get("owner_ids") or []) or "-",
        )
    console.print(table)
    blocked = [task for task in rows if task.get("computed_blocked")]
    if blocked:
        console.print(f"[dim]{len(blocked)} task(s) computed blocked (marked !)[/dim]")


def porcelain_tasks(rows: list[dict[str, Any]]) -> None:
    for task in rows:
        typer.echo(
            "\t".join(
                [
                    task["id"],
                    task["status"],
                    task["priority"],
                    str(task.get("weight", 1)),
                    "1" if task.get("computed_blocked") else "0",
                    task["title"],
                ]
            )
        )


def render_task_show(task: dict[str, Any]) -> None:
    console.print(f"[bold]{task['id']}[/bold]  {task['title']}")
    console.print(
        f"  status={task['status']}  priority={task['priority']}  "
        f"weight={task['weight']}  lifecycle={task['lifecycle']}"
    )
    if task.get("milestone_id"):
        console.print(f"  milestone  {sid(task['milestone_id'])}")
    if task.get("area_id"):
        console.print(f"  area       {sid(task['area_id'])}")
    if task.get("parent_task_id"):
        console.print(f"  parent     {sid(task['parent_task_id'])}")
    if task.get("owner_ids"):
        console.print(f"  owners     {', '.join(sid(owner) for owner in task['owner_ids'])}")
    if task.get("labels"):
        console.print(f"  labels     {', '.join(task['labels'])}")
    if task.get("started_at"):
        console.print(f"  started    {ts(task['started_at'])}")
    if task.get("completed_at"):
        console.print(f"  completed  {ts(task['completed_at'])}")
    if task.get("due_at"):
        console.print(f"  due        {ts(task['due_at'])}")
    if task.get("description"):
        console.print(f"\n  {task['description']}")
    if task.get("acceptance_criteria"):
        console.print("\n  [bold]Acceptance criteria[/bold]")
        for criterion in task["acceptance_criteria"]:
            console.print(f"    - {criterion}")
    if task.get("dependencies"):
        console.print("\n  [bold]Dependencies[/bold]")
        for dep in task["dependencies"]:
            console.print(f"    {dep['relation']:<12} {sid(dep['task_id'])}")
    if task.get("computed_blocked"):
        console.print(
            f"\n  [red]computed blocked[/red] waiting for "
            f"{', '.join(sid(item) for item in task['blocked_by'])}"
        )
    console.print(f"\n  [dim]rev {task.get('rev', '')}  v{task.get('version', 1)}[/dim]")


def render_area_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no areas[/dim]")
        return
    for row in rows:
        console.print(
            f"{sid(row['id'])}  {row['name']:<16} "
            f"[dim]{row['task_count']} task(s)"
            f"{'  parent ' + sid(row['parent_area_id']) if row.get('parent_area_id') else ''}[/dim]"
        )


def render_git_available(result: dict[str, Any]) -> None:
    """裸 `pjt git`：Git 感知是否可用。"""
    if not result.get("available"):
        console.print("[yellow]git awareness unavailable[/yellow]")
        console.print(f"  [dim]{result.get('reason', '')}[/dim]")
        return
    console.print("[green]git awareness available[/green]  [dim](read-only)[/dim]")
    console.print(f"  work tree : {result.get('work_tree')}")
    if result.get("project_root_is_git_root"):
        console.print("  layout    : project root == git root")
    else:
        subdir = result.get("project_subdir")
        console.print(f"  layout    : project root is [bold]{subdir or '(unknown)'}[/bold] under git root")


def render_link_map(result: dict[str, Any]) -> None:
    console.print(f"[green]mapped[/green] {result['name']}  ->  {result['path']}")
    if not result.get("has_project"):
        console.print(
            f"  [yellow]note[/yellow] {result['note']}\n"
            f"        [dim]{result['probe']}[/dim]"
        )
    console.print("  [dim]stored in .pjt/local/local.toml (not committed)[/dim]")


def render_link_unmap(result: dict[str, Any]) -> None:
    if result.get("unmapped"):
        console.print(f"[green]unmapped[/green] {result['name']}  [dim]{result['path']}[/dim]")
    else:
        console.print(f"{result['name']} had no local path mapping")


def render_link_status(result: dict[str, Any]) -> None:
    """`pjt link status` —— 字段与 link.resolve 一致（V1-B.1：resolved 不许说谎）。

    `resolved=true` 只在真的读到了对方的 project.json 时出现；
    非 local_project 一律 resolved=false 并给出原因。
    """
    resolved = bool(result.get("resolved"))
    mark = "[green]resolved[/green]" if resolved else "[yellow]unresolved[/yellow]"
    console.print(
        f"[bold]{result.get('name', '')}[/bold]  {result.get('kind', '')}  {mark}"
        f"  [dim]{result.get('locator') or result.get('project_id') or ''}[/dim]"
    )
    if result.get("local_mapped"):
        console.print(f"  [dim]machine path from .pjt/local/local.toml: {result['local_path']}[/dim]")
    if resolved:
        peer = result.get("project") or {}
        console.print(f"  peer   : {peer.get('name', '')}  [dim]{peer.get('id', '')}[/dim]")
        if result.get("path"):
            console.print(f"  path   : {result['path']}")
    else:
        # 原因通常很长；用悬挂缩进，别让续行顶到最左边。
        console.print("  [dim]why  :[/dim]")
        console.print(
            Padding(
                Text(result.get("error", "unknown"), style="dim"),
                (0, 0, 0, 8),
            )
        )


def _status_badge(status: str | None, missing: bool) -> str:
    if missing:
        return "[red]unreadable[/red]"
    colors = {
        "draft": "dim",
        "review": "yellow",
        "agreed": "green",
        "deprecated": "magenta",
    }
    key = status or "?"
    color = colors.get(key, "red")
    return f"[{color}]{key}[/{color}]"


def render_interface_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no interface documents registered[/dim]")
        console.print("[dim]create one with: pjt interface init <name> --area <area>[/dim]")
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID", style="dim", no_wrap=True, min_width=13)
    table.add_column("Status", no_wrap=True, min_width=10)
    table.add_column("Name", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("Area", no_wrap=True, min_width=10)
    table.add_column("Consumers", style="dim", no_wrap=True, min_width=10)
    for row in rows:
        document = row.get("document") or {}
        bad = bool(row.get("read_error"))
        consumers = document.get("consumers") or []
        table.add_row(
            sid(row["id"]),
            _status_badge(document.get("status"), bad),
            ellipsis(row.get("name") or "", 46),
            ellipsis(", ".join(row.get("area_names") or []), 20) or "-",
            ellipsis(", ".join(str(item) for item in consumers), 24) or "-",
        )
    console.print(table)


def render_interface_show(result: dict[str, Any]) -> None:
    console.print(f"[green]registered[/green] {result['id']}  {result.get('name')}")
    console.print(f"  {result['locator']}")
    if result.get("area_names"):
        console.print(f"  area    {', '.join(result['area_names'])}")
    console.print(
        f"  [dim]next: edit the file, then 'pjt interface check {result.get('name')}'[/dim]"
    )


def render_interface_register(result: dict[str, Any]) -> None:
    console.print(f"[green]registered[/green] {result['id']}  {result.get('name')}")
    console.print(f"  {result['locator']}")
    if result.get("related_area_ids"):
        console.print(f"  area    {', '.join(result['related_area_ids'])}")


def render_interface_check(result: dict[str, Any]) -> None:
    rows = result.get("interfaces") or []
    if not rows:
        console.print("[dim]no interface documents registered[/dim]")
        return
    for row in rows:
        mark = "[green]OK[/green]" if row["ok"] else "[red]FAIL[/red]"
        status = (row.get("status") or "?")
        console.print(f"{mark} {sid(row['id'])}  {row['name']}  [dim]{status}[/dim]  {row['locator']}")
        for finding in row.get("findings") or []:
            level = finding["level"]
            color = "red" if level == "error" else "yellow"
            console.print(f"      [{color}]{level}[/{color}] {finding['message']}")
    summary = result.get("errors", 0)
    console.print(
        f"\n{'OK' if result.get('ok') else 'FAILED'}: "
        f"{len(rows)} document(s), {summary} error(s), {result.get('warnings', 0)} warning(s)"
    )


def render_area_activity(result: dict[str, Any]) -> None:
    """`pjt area activity`。

    两半信息量不同，**必须分开呈现**：已提交历史所有人都能看到，
    未提交改动只有本机可见。混在一起会让人以为「没出现就是没人动」。
    """
    if not result.get("available"):
        console.print("[yellow]git unavailable — cannot derive area activity[/yellow]")
        console.print(f"  [dim]{result.get('reason', '')}[/dim]")
        return

    days = result.get("days", 7)
    scanned = result.get("scanned_commits", 0)
    console.print(
        f"[bold]Area activity[/bold]  [dim]last {days}d, from {scanned} commit(s)[/dim]"
    )
    console.print()

    active = [row for row in result.get("areas") or [] if row.get("active")]
    idle = [row for row in result.get("areas") or [] if not row.get("active")]

    for row in active:
        owners = ", ".join(sid(item) for item in row.get("owner_ids") or []) or "unassigned"
        console.print(f"  [green]●[/green] [bold]{row['name']}[/bold]  [dim]owners: {owners}[/dim]")
        for person in row.get("people") or []:
            console.print(
                f"      {person['handle']}  [dim]{person['commits']} commit(s)[/dim]"
            )
            for path in person["files"][:6]:
                console.print(f"        [dim]{path}[/dim]")
            extra = len(person["files"]) - 6
            if extra > 0:
                console.print(f"        [dim]… +{extra} more[/dim]")
        if not row.get("people"):
            console.print(
                "      [yellow]author not mapped to a member[/yellow] "
                "[dim](run 'pjt member map-git <handle> --git-email …')[/dim]"
            )
        console.print()

    if idle:
        quiet = [row["name"] for row in idle if row.get("bound")]
        unbound = [row["name"] for row in idle if not row.get("bound")]
        if quiet:
            console.print(f"  [dim]no commits in {days}d: {', '.join(quiet)}[/dim]")
        if unbound:
            console.print(
                f"  [yellow]no path_patterns (code cannot map to this area): "
                f"{', '.join(unbound)}[/yellow]"
            )

    local = result.get("local_uncommitted") or []
    console.print()
    if local:
        console.print(
            "[bold]Uncommitted on THIS machine only[/bold] "
            "[dim](others' in-flight work is invisible here)[/dim]"
        )
        for row in local:
            console.print(f"  {row['name']}  [dim]{' '.join(row.get('codes') or [])}[/dim]")
            for path in row["files"][:8]:
                console.print(f"    [dim]{path}[/dim]")
    else:
        console.print("[bold]Uncommitted on THIS machine:[/bold] [dim]none in a bound area[/dim]")

    unmapped = result.get("unmapped_authors") or []
    if unmapped:
        console.print()
        console.print("[dim]authors with no Member.git mapping:[/dim]")
        for item in unmapped:
            console.print(f"  {item['author']}  [dim]{item['commits']} commit(s)[/dim]")


def render_area_owners(result: dict[str, Any]) -> None:
    owners = list(result.get("owner_ids") or [])
    if not owners:
        console.print(f"{result['id']}  owners: [yellow]unassigned[/yellow]")
        console.print("  [dim]set with: pjt area set-owner <area> --add <member>[/dim]")
        return
    # 多个 owner = 公共接口区，明说，别让人猜
    tail = "  [dim](shared interface area)[/dim]" if len(owners) > 1 else ""
    console.print(f"{result['id']}  owners: {', '.join(sid(item) for item in owners)}{tail}")


def render_area_matches(result: list[dict[str, Any]]) -> None:
    """`pjt area match-path` —— 哪些 Area 的 path_patterns 认领了这个路径（只读推导）。"""
    if not result:
        console.print("  [dim]no area claims this path[/dim]")
        return
    for match in result:
        console.print(f"  {sid(match['id'])}  {match['name']}")
        for pattern in match.get("patterns") or []:
            console.print(f"    [dim]{pattern}[/dim]")


def _owner_label(owners) -> str:
    owners = list(owners or [])
    if not owners:
        return "[yellow]unassigned[/yellow]"
    if len(owners) == 1:
        return sid(owners[0])
    return f"{sid(owners[0])} [dim]+{len(owners) - 1} shared[/dim]"


def render_area_show(result: dict[str, Any]) -> None:
    console.print(f"[bold]{result['id']}[/bold]  {result['name']}  [dim]({result['lifecycle']})[/dim]")
    if result.get("parent_area_id"):
        console.print(f"  parent    {sid(result['parent_area_id'])}")
    console.print(f"  owners    {_owner_label(result.get('owner_ids'))}")
    console.print(f"  tasks     {result['task_count']}")
    if result.get("description"):
        console.print(f"\n  {result['description']}")
    if result.get("task_count"):
        console.print(f"\n  [dim]list tasks with: pjt task list --area {result['name']}[/dim]")
    console.print(f"\n  [dim]rev {result.get('rev', '')}  v{result.get('version', 1)}[/dim]")


def render_artifact_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no artifacts[/dim]")
        return
    for row in rows:
        linked: list[str] = []
        for label, key in (
            ("task", "related_task_ids"),
            ("dec", "related_decision_ids"),
            ("mls", "related_milestone_ids"),
            ("gol", "related_goal_ids"),
        ):
            linked.extend(f"{label}:{sid(item)}" for item in row.get(key) or [])
        console.print(
            f"{sid(row['id'])}  {row['kind']:<12} {row['locator']}"
            + (f"  [dim]{' '.join(linked)}[/dim]" if linked else "")
        )


def render_artifact_show(result: dict[str, Any]) -> None:
    console.print(f"[bold]{result['id']}[/bold]  {result['name']}  [dim]({result['lifecycle']})[/dim]")
    console.print(f"  kind      {result['kind']}")
    console.print(f"  locator   {result['locator']}")
    if result.get("description"):
        console.print(f"\n  {result['description']}")
    groups = (
        ("Tasks", "related_task_ids"),
        ("Decisions", "related_decision_ids"),
        ("Milestones", "related_milestone_ids"),
        ("Goals", "related_goal_ids"),
    )
    for title, key in groups:
        items = result.get(key) or []
        if items:
            console.print(f"\n  [bold]{title}[/bold]")
            for item in items:
                console.print(f"    {sid(item)}")
    if result.get("metadata"):
        console.print(f"\n  [bold]metadata[/bold]  {result['metadata']}")
    console.print(f"\n  [dim]rev {result.get('rev', '')}  v{result.get('version', 1)}[/dim]")


def render_artifact_verify(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no artifacts[/dim]")
        return
    markers = {"ok": "green PASS", "missing": "yellow MISSING", "rejected": "red REJECTED",
               "skipped": "dim SKIP"}
    for row in rows:
        marker = markers.get(row.get("status", ""), str(row.get("status", "?")))
        detail = row.get("detail") or ""
        console.print(f"  [{marker}] {sid(row['id'])}  {row['kind']:<12} {row['locator']}")
        if detail:
            console.print(f"           [dim]{detail}[/dim]")


def render_member_workload(result: dict[str, Any]) -> None:
    member = result["member"]
    console.print(
        f"[bold]{member['handle']}[/bold]  {member['display_name']}  "
        f"[dim]({member['id']})[/dim]"
    )
    console.print(f"  total {result['total']} task(s)")
    for status, tasks in sorted((result.get("by_status") or {}).items()):
        console.print(f"\n  [bold]{status}[/bold] ({len(tasks)})")
        for task in tasks:
            console.print(f"    {sid(task['id'])}  {task['title']}")


def render_project_graph(tree_data: dict[str, Any]) -> None:
    project = tree_data["project"]
    root = Tree(f"[bold]{project['name']}[/bold] [dim]({project['id']})[/dim]")
    milestones = {item["id"]: item for item in tree_data.get("milestones") or []}
    used: set[str] = set()
    for goal in tree_data.get("goals") or []:
        node = root.add(f"Goal: {goal['title']} [dim]({goal['status']})[/dim]")
        for milestone_id in goal.get("milestone_ids") or []:
            milestone = milestones.get(milestone_id)
            if milestone:
                node.add(
                    f"Milestone: {milestone['title']} "
                    f"[dim]{milestone['progress'] * 100:.0f}%[/dim]"
                )
                used.add(milestone_id)
    for milestone in tree_data.get("milestones") or []:
        if milestone["id"] in used:
            continue
        root.add(
            f"Milestone: {milestone['title']} [dim]{milestone['progress'] * 100:.0f}%[/dim]"
        )
    areas = tree_data.get("areas") or []
    if areas:
        # Area 是与 Goal/Milestone 平级的独立分区：这里单独一节，不造假的 Goal->Area->Milestone。
        section = root.add("[bold]Areas[/bold] [dim](stable partitions)[/dim]")
        children: dict[str, list[dict[str, Any]]] = {}
        for area in areas:
            children.setdefault(area.get("parent_area_id") or "", []).append(area)
        known = {area["id"] for area in areas}

        def add_area(parent: Tree, area: dict[str, Any], seen: set[str]) -> None:
            label = f"{short_id(area['id'])}  {area['name']} [dim]{area['task_count']} task(s)[/dim]"
            if area["id"] in seen:
                parent.add(label + " [red](cycle)[/red]")
                return
            branch = parent.add(label)
            for child in sorted(children.get(area["id"], []), key=lambda i: i["name"].casefold()):
                add_area(branch, child, seen | {area["id"]})

        for area in sorted(children.get("", []), key=lambda i: i["name"].casefold()):
            add_area(section, area, set())
        orphans = [
            area
            for parent_id, items in children.items()
            if parent_id
            for area in items
            if parent_id not in known
        ]
        for area in sorted(orphans, key=lambda i: i["name"].casefold()):
            add_area(section, area, set())
    for link in tree_data.get("links") or []:
        root.add(f"Link: {link['name']} -> {link['kind']} [dim]({link['mode']})[/dim]")
    console.print(root)


def render_task_graph(graph: dict[str, Any], title: str) -> None:
    nodes = {node["id"]: node for node in graph.get("nodes") or []}
    if not nodes:
        console.print("[dim]no tasks[/dim]")
        return
    children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    has_parent: set[str] = set()
    dependency_edges: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in graph.get("edges") or []:
        if edge["kind"] == "contains" and edge["to"] in nodes:
            children[edge["from"]].append(edge["to"])
            has_parent.add(edge["to"])
        elif edge["kind"] == "depends_on" and edge["from"] in nodes and edge["to"] in nodes:
            dependency_edges[edge["from"]].append(edge["to"])
    root = Tree(f"[bold]{title}[/bold]")

    def add_node(parent: Tree, node_id: str, seen: set[str]) -> None:
        node = nodes[node_id]
        label = f"{short_id(node_id)} [dim]{node['status']}[/dim]  {node['title']}"
        if node.get("computed_blocked"):
            blockers = ", ".join(short_id(item) for item in node.get("blocked_by") or [])
            label += f"  [red](blocked by {blockers})[/red]"
        if node_id in seen:
            label += " [red](cycle)[/red]"
            parent.add(label)
            return
        branch = parent.add(label)
        for child in sorted(children.get(node_id, [])):
            add_node(branch, child, seen | {node_id})

    roots = sorted(node_id for node_id in nodes if node_id not in has_parent)
    for root_id in roots:
        add_node(root, root_id, set())
    console.print(root)

    for source, targets in sorted(dependency_edges.items()):
        if targets:
            console.print(
                f"  [dim]{sid(source)} depends_on "
                f"{', '.join(sid(target) for target in sorted(targets))}[/dim]"
            )
    console.print(f"[dim]{len(nodes)} task(s), {len(graph.get('edges') or [])} edge(s)[/dim]")


def render_goal_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no goals[/dim]")
        return
    for row in rows:
        console.print(f"{sid(row['id'])}  {row['status']:<10} {row['title']}")


def render_milestone_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no milestones[/dim]")
        return
    for row in rows:
        console.print(
            f"{sid(row['id'])}  {row['status']:<10} {bar(row['progress'])} "
            f"{row['progress'] * 100:3.0f}%  {row['title']}"
        )


def render_milestone_show(result: dict[str, Any]) -> None:
    console.print(f"[bold]{result['id']}[/bold]  {result['title']}  ({result['status']})")
    console.print(
        f"  {bar(result['progress'])} {result['progress'] * 100:.0f}%  "
        f"weight {result['done_weight']}/{result['total_weight']}"
    )
    console.print(f"  tasks {result['task_status_counts']}")


def render_member_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no members[/dim]")
        return
    for row in rows:
        state = "active" if row["active"] else "inactive"
        console.print(
            f"{row['handle']:<14} {row['display_name']:<12} {state:<9} {sid(row['id'])}"
        )


def render_update_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no updates[/dim]")
        return
    for row in rows:
        console.print(f"{sid(row['id'])}  [dim]{ts(row['created_at'])}[/dim]  {row['summary']}")


def render_decision_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no decisions[/dim]")
        return
    for row in rows:
        console.print(f"{sid(row['id'])}  {row['status']:<11} {row['title']}")


def render_link_list(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no links[/dim]")
        return
    for row in rows:
        console.print(
            f"{row['name']:<14} {row['target']['kind']:<16} "
            f"{row['mode']:<10} {row['target']['locator'] or ''}"
        )


def render_link_resolution(rows: list[dict[str, Any]]) -> None:
    if not rows:
        console.print("[dim]no linked projects[/dim]")
        return
    for row in rows:
        console.print(
            f"{row['name']:<14} {row['kind']:<16} "
            f"resolved={row['resolved']} {row.get('path', '')}"
        )
