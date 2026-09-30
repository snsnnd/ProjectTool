"""CLI 输出渲染。"""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table
from rich.tree import Tree

from project_tool.cli.common import bar, console, event_detail, sid, ts
from project_tool.domain.ids import short_id


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
            console.print(f"  {sid(item['id'])}  {item['title']}")
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
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID", style="dim")
    table.add_column("Status")
    table.add_column("Priority")
    table.add_column("W")
    table.add_column("Title")
    table.add_column("Owners", style="dim")
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


def render_area_show(result: dict[str, Any]) -> None:
    console.print(f"[bold]{result['id']}[/bold]  {result['name']}  [dim]({result['lifecycle']})[/dim]")
    if result.get("parent_area_id"):
        console.print(f"  parent    {sid(result['parent_area_id'])}")
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
