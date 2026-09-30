"""pjt CLI：所有客户端能力的唯一命令行入口。"""

from __future__ import annotations

import json as jsonlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from project_tool import __version__
from project_tool.application.service import ProjectService
from project_tool.domain.errors import InvalidArgument, ProjectToolError
from project_tool.domain.ids import short_id
from project_tool.domain.timeutil import format_time

app = typer.Typer(
    name="pjt",
    help="Local-first, Git-aware project state and collaboration system.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

task_app = typer.Typer(help="Task management", no_args_is_help=True)
goal_app = typer.Typer(help="Goal management", no_args_is_help=True)
milestone_app = typer.Typer(help="Milestone management", no_args_is_help=True)
member_app = typer.Typer(help="Member management", no_args_is_help=True)
update_app = typer.Typer(help="Progress updates", no_args_is_help=True)
decision_app = typer.Typer(help="Decision records", no_args_is_help=True)
link_app = typer.Typer(help="Linked projects", no_args_is_help=True)

app.add_typer(task_app, name="task")
app.add_typer(goal_app, name="goal")
app.add_typer(milestone_app, name="milestone")
app.add_typer(member_app, name="member")
app.add_typer(update_app, name="update")
app.add_typer(decision_app, name="decision")
app.add_typer(link_app, name="link")


class CliState:
    def __init__(self, json_out: bool, porcelain: bool, actor: str | None, project: str | None):
        self.json_out = json_out
        self.porcelain = porcelain
        self.actor = actor
        self.project = project


@app.callback()
def main_callback(
    ctx: typer.Context,
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable JSON output")] = False,
    porcelain: Annotated[bool, typer.Option("--porcelain", help="Stable script-friendly output")] = False,
    as_member: Annotated[Optional[str], typer.Option("--as", help="Actor for this command (handle or id)")] = None,
    project: Annotated[Optional[str], typer.Option("-C", "--project", help="Project path")] = None,
    version: Annotated[bool, typer.Option("--version", help="Show version and exit")] = False,
) -> None:
    if version:
        console.print(f"project-tool {__version__}")
        raise typer.Exit()
    ctx.obj = CliState(json_out=json_out, porcelain=porcelain, actor=as_member, project=project)


# --------------------------------------------------------------------- helpers


def get_service(state: CliState) -> ProjectService:
    return ProjectService.open(state.project, actor=state.actor)


def fail(state: CliState, exc: ProjectToolError) -> None:
    if state.json_out:
        typer.echo(jsonlib.dumps({"id": "cli", "error": exc.to_error()}, ensure_ascii=False, indent=2))
    else:
        err_console.print(f"[red]{exc.code}[/red] {exc.message}")
        if exc.details:
            err_console.print(f"[dim]{jsonlib.dumps(exc.details, ensure_ascii=False)}[/dim]")
    raise typer.Exit(exc.exit_code)


def emit(
    state: CliState,
    result: Any,
    render=None,
    porcelain_render=None,
) -> None:
    if state.json_out:
        payload = {"id": "cli", "result": result}
        typer.echo(jsonlib.dumps(payload, ensure_ascii=False, indent=2, default=str))
    elif state.porcelain and porcelain_render is not None:
        porcelain_render(result)
    elif render is not None:
        render(result)
    else:
        typer.echo(jsonlib.dumps(result, ensure_ascii=False, indent=2, default=str))


def execute(
    ctx: typer.Context,
    method: str,
    params: dict[str, Any],
    render=None,
    porcelain_render=None,
):
    state: CliState = ctx.obj
    try:
        service = get_service(state)
        result = service.call(method, params)
    except ProjectToolError as exc:
        fail(state, exc)
    except OSError as exc:
        err_console.print(f"[red]IO_ERROR[/red] {exc}")
        raise typer.Exit(1)
    emit(state, result, render=render, porcelain_render=porcelain_render)
    return result


def _sid(value: str | None) -> str:
    if not value:
        return "-"
    return short_id(value)


def _ts(value: str | None) -> str:
    return format_time(value) if value else ""


def _bar(progress: float, width: int = 20) -> str:
    filled = max(0, min(width, int(round(progress * width))))
    return "█" * filled + "░" * (width - filled)


def _event_detail(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    if "from" in payload and "to" in payload:
        return f"{payload['from']} → {payload['to']}"
    if "member_id" in payload:
        return _sid(payload["member_id"])
    if "target_id" in payload:
        return f"depends on {_sid(payload['target_id'])}"
    if "label" in payload:
        return str(payload["label"])
    if "suppressed" in payload:
        return ""
    for key in ("title", "summary", "name", "handle", "lifecycle", "fields"):
        if key in payload:
            value = payload[key]
            return ", ".join(value) if isinstance(value, list) else str(value)
    return ""


def read_text_argument(text: str | None) -> str:
    if text:
        return text
    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            return data
    editor = os.environ.get("EDITOR")
    if editor:
        descriptor, path = tempfile.mkstemp(suffix=".md", prefix="pjt-update-")
        os.close(descriptor)
        subprocess.call(f"{editor} {path}", shell=True)
        try:
            content = Path(path).read_text(encoding="utf-8").strip()
        finally:
            os.unlink(path)
        if content:
            return content
    raise InvalidArgument("no text provided (pass TEXT, pipe stdin, or set $EDITOR)")


# ------------------------------------------------------------------ renderers


def render_init(result: dict[str, Any]) -> None:
    project = result["project"]
    console.print(f"[green]Initialized[/green] {project['name']} ({project['id']})")
    console.print(f"  path      {result['root']}")
    console.print(f"  device    {result['device_id']}")
    console.print("  next      pjt member add <handle> --name \"...\"")


def render_status(result: dict[str, Any]) -> None:
    project = result["project"]
    console.print(f"[bold]{project['name']}[/bold]  [dim]({project['id']}, {project['status']})[/dim]")
    if project.get("description"):
        console.print(f"  {project['description']}")

    milestone = result.get("active_milestone")
    if milestone:
        pct = f"{milestone['progress'] * 100:.0f}%"
        console.print(
            f"\n[bold]Active milestone[/bold]  {milestone['title']} "
            f"{_bar(milestone['progress'])} {pct}"
        )
        counts = milestone.get("task_status_counts") or {}
        if counts:
            console.print("  " + "  ".join(f"{key}={value}" for key, value in sorted(counts.items())))

    tasks = result.get("tasks") or {}
    non_zero = {key: value for key, value in tasks.items() if value}
    console.print("\n[bold]Tasks[/bold]  " + ("  ".join(f"{key} {value}" for key, value in non_zero.items()) or "none"))

    blocked = result.get("blocked") or []
    if blocked:
        console.print("\n[bold red]Computed blocked[/bold red]")
        for item in blocked:
            console.print(f"  {_sid(item['id'])}  {item['title']}")
            console.print(f"    [dim]waiting for {', '.join(_sid(t) for t in item['blocked_by'])}[/dim]")

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
                f"  [dim]{_ts(event['occurred_at'])}[/dim]  "
                f"{_sid(event.get('entity_id'))}  {event['event_type']}  {_event_detail(event)}"
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
            f"[dim]{_ts(event['occurred_at'])}[/dim]  "
            f"{_sid(event.get('entity_id')):<12} {event['event_type']}  {_event_detail(event)}"
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
        console.print(f"  [{colors[status]}]{status.upper():<7}[/{colors[status]}] {check['name']:<20} {check['message']}")
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
        f"errors={summary['errors']} warnings={summary['warnings']}"
    )


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
            _sid(task["id"]),
            status_text,
            task["priority"],
            str(task.get("weight", 1)),
            task["title"],
            ",".join(_sid(owner) for owner in task.get("owner_ids") or []) or "-",
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
        console.print(f"  milestone  {_sid(task['milestone_id'])}")
    if task.get("parent_task_id"):
        console.print(f"  parent     {_sid(task['parent_task_id'])}")
    if task.get("owner_ids"):
        console.print(f"  owners     {', '.join(_sid(owner) for owner in task['owner_ids'])}")
    if task.get("labels"):
        console.print(f"  labels     {', '.join(task['labels'])}")
    if task.get("started_at"):
        console.print(f"  started    {_ts(task['started_at'])}")
    if task.get("completed_at"):
        console.print(f"  completed  {_ts(task['completed_at'])}")
    if task.get("due_at"):
        console.print(f"  due        {_ts(task['due_at'])}")
    if task.get("description"):
        console.print(f"\n  {task['description']}")
    if task.get("acceptance_criteria"):
        console.print("\n  [bold]Acceptance criteria[/bold]")
        for criterion in task["acceptance_criteria"]:
            console.print(f"    - {criterion}")
    if task.get("dependencies"):
        console.print("\n  [bold]Dependencies[/bold]")
        for dep in task["dependencies"]:
            console.print(f"    {dep['relation']:<12} {_sid(dep['task_id'])}")
    if task.get("computed_blocked"):
        console.print(
            f"\n  [red]computed blocked[/red] waiting for "
            f"{', '.join(_sid(item) for item in task['blocked_by'])}"
        )
    console.print(f"\n  [dim]rev {task.get('rev', '')}  v{task.get('version', 1)}[/dim]")


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
            console.print(f"    {_sid(task['id'])}  {task['title']}")


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
        root.add(f"Milestone: {milestone['title']} [dim]{milestone['progress'] * 100:.0f}%[/dim]")
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
                f"  [dim]{_sid(source)} depends_on "
                f"{', '.join(_sid(target) for target in sorted(targets))}[/dim]"
            )
    console.print(f"[dim]{len(nodes)} task(s), {len(graph.get('edges') or [])} edge(s)[/dim]")


def render_dependency_graph(graph: dict[str, Any]) -> None:
    render_task_graph(graph, "Dependencies")


# ------------------------------------------------------------------- commands


@app.command()
def init(
    ctx: typer.Context,
    path: Annotated[Optional[str], typer.Argument(help="Project directory (default: cwd)")] = None,
    name: Annotated[Optional[str], typer.Option("--name", help="Project name")] = None,
    description: Annotated[str, typer.Option("--description", "-d", help="Project description")] = "",
    slug: Annotated[Optional[str], typer.Option("--slug", help="Project slug")] = None,
) -> None:
    """Initialize a new .pjt project."""
    state: CliState = ctx.obj
    target = path or state.project or str(Path.cwd())
    try:
        result = ProjectService.project_init(target, name=name, description=description, slug=slug)
    except ProjectToolError as exc:
        fail(state, exc)
    emit(state, result, render=render_init)


@app.command()
def status(
    ctx: typer.Context,
    recent: Annotated[int, typer.Option("--recent", help="Recent event count")] = 10,
) -> None:
    """Show project status summary."""
    execute(ctx, "project.status", {"recent": recent}, render=render_status, porcelain_render=porcelain_status)


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check project integrity."""
    result = execute(ctx, "project.doctor", {}, render=render_doctor)
    if isinstance(result, dict) and not result.get("ok", True):
        raise typer.Exit(9)


@app.command()
def migrate(ctx: typer.Context) -> None:
    """Run schema migrations (V0: validate only)."""
    execute(ctx, "project.migrate", {}, render=lambda result: console.print(jsonlib.dumps(result, ensure_ascii=False)))


# ------------------------------------------------------------------ task cmds


@task_app.command("add")
def task_add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument(help="Task title")],
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    owner: Annotated[Optional[list[str]], typer.Option("--owner", "-o", help="Owner member (repeatable)")] = None,
    milestone: Annotated[Optional[str], typer.Option("--milestone", "-m")] = None,
    parent: Annotated[Optional[str], typer.Option("--parent")] = None,
    priority: Annotated[str, typer.Option("--priority", "-p", help="critical|high|normal|low")] = "normal",
    weight: Annotated[int, typer.Option("--weight", "-w")] = 1,
    label: Annotated[Optional[list[str]], typer.Option("--label", "-l", help="Label (repeatable)")] = None,
    accept: Annotated[Optional[list[str]], typer.Option("--accept", help="Acceptance criterion (repeatable)")] = None,
    due: Annotated[Optional[str], typer.Option("--due", help="Due datetime (ISO-8601)")] = None,
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
    status: Annotated[Optional[list[str]], typer.Option("--status", "-s", help="Filter by status (repeatable)")] = None,
    owner: Annotated[Optional[str], typer.Option("--owner", "-o")] = None,
    label: Annotated[Optional[str], typer.Option("--label", "-l")] = None,
    milestone: Annotated[Optional[str], typer.Option("--milestone", "-m")] = None,
    priority: Annotated[Optional[list[str]], typer.Option("--priority", "-p")] = None,
    parent: Annotated[Optional[str], typer.Option("--parent")] = None,
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


def _task_status_command(ctx: typer.Context, task_id: str, target: str) -> None:
    execute(
        ctx,
        "task.set_status",
        {"task_id": task_id, "status": target},
        render=lambda result: console.print(f"{result['id']} -> [bold]{result['status']}[/bold]"),
    )


@task_app.command("start")
def task_start(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Mark task as doing."""
    _task_status_command(ctx, task_id, "doing")


@task_app.command("block")
def task_block(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Mark task as blocked."""
    _task_status_command(ctx, task_id, "blocked")


@task_app.command("review")
def task_review(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Mark task as ready for review."""
    _task_status_command(ctx, task_id, "review")


@task_app.command("done")
def task_done(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Mark task as done."""
    _task_status_command(ctx, task_id, "done")


@task_app.command("cancel")
def task_cancel(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Cancel task."""
    _task_status_command(ctx, task_id, "cancelled")


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
        render=lambda result: console.print(f"{result['id']} owners: {', '.join(_sid(o) for o in result['owner_ids'])}"),
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
        render=lambda result: console.print(f"{result['id']} owners: {', '.join(_sid(o) for o in result['owner_ids']) or '-'}"),
    )


@task_app.command("depend")
def task_depend(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task that depends")],
    target_id: Annotated[str, typer.Argument(help="Task being depended on")],
    relation: Annotated[str, typer.Option("--relation", help="depends_on|relates_to|duplicates")] = "depends_on",
) -> None:
    """Add a dependency: TASK depends on TARGET."""
    execute(
        ctx,
        "task.add_dependency",
        {"task_id": task_id, "target_id": target_id, "relation": relation},
        render=lambda result: console.print(
            f"{result['id']} dependencies: "
            f"{', '.join(_sid(dep['task_id']) for dep in result['dependencies']) or '-'}"
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
        render=lambda result: console.print(f"{result['id']} labels: {', '.join(result['labels']) or '-'}"),
    )


@task_app.command("move")
def task_move(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument()],
    milestone_id: Annotated[Optional[str], typer.Argument(help="Target milestone; omit to detach")] = None,
) -> None:
    """Move a task to another milestone (or detach)."""
    execute(
        ctx,
        "task.move_milestone",
        {"task_id": task_id, "milestone_id": milestone_id},
        render=lambda result: console.print(f"{result['id']} milestone: {_sid(result.get('milestone_id'))}"),
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
    execute(ctx, "task.delete", {"task_id": task_id}, render=lambda r: console.print(f"{r['id']} deleted (recoverable)"))


@task_app.command("history")
def task_history(ctx: typer.Context, task_id: Annotated[str, typer.Argument()]) -> None:
    """Show task event history."""
    execute(ctx, "task.history", {"task_id": task_id}, render=render_events)


# ------------------------------------------------------------------ goal cmds


@goal_app.command("add")
def goal_add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument()],
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    parent: Annotated[Optional[str], typer.Option("--parent")] = None,
    criterion: Annotated[Optional[list[str]], typer.Option("--criterion", help="Success criterion (repeatable)")] = None,
    due: Annotated[Optional[str], typer.Option("--due")] = None,
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
    status: Annotated[Optional[list[str]], typer.Option("--status", "-s")] = None,
    include_archived: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    """List goals."""
    execute(
        ctx,
        "goal.list",
        {"status": status, "include_archived": include_archived},
        render=lambda rows: (
            console.print("[dim]no goals[/dim]")
            if not rows
            else [console.print(f"{_sid(row['id'])}  {row['status']:<10} {row['title']}") for row in rows]
        ),
    )


@goal_app.command("show")
def goal_show(ctx: typer.Context, goal_id: Annotated[str, typer.Argument()]) -> None:
    """Show a goal."""
    execute(ctx, "goal.get", {"goal_id": goal_id})


@goal_app.command("edit")
def goal_edit(
    ctx: typer.Context,
    goal_id: Annotated[str, typer.Argument()],
    title: Annotated[Optional[str], typer.Option("--title")] = None,
    description: Annotated[Optional[str], typer.Option("--description", "-d")] = None,
    criterion: Annotated[Optional[list[str]], typer.Option("--criterion")] = None,
    due: Annotated[Optional[str], typer.Option("--due")] = None,
) -> None:
    """Edit a goal."""
    params: dict[str, Any] = {"goal_id": goal_id, "title": title, "description": description, "success_criteria": criterion}
    if due is not None:
        params["due_at"] = due
    execute(ctx, "goal.update", params, render=lambda r: console.print(f"{r['id']} updated"))


@goal_app.command("achieve")
def goal_achieve(ctx: typer.Context, goal_id: Annotated[str, typer.Argument()]) -> None:
    """Mark goal achieved."""
    execute(ctx, "goal.set_status", {"goal_id": goal_id, "status": "achieved"}, render=lambda r: console.print(f"{r['id']} -> achieved"))


@goal_app.command("drop")
def goal_drop(ctx: typer.Context, goal_id: Annotated[str, typer.Argument()]) -> None:
    """Drop a goal."""
    execute(ctx, "goal.set_status", {"goal_id": goal_id, "status": "dropped"}, render=lambda r: console.print(f"{r['id']} -> dropped"))


# ------------------------------------------------------------- milestone cmds


@milestone_app.command("add")
def milestone_add(
    ctx: typer.Context,
    title: Annotated[str, typer.Argument()],
    description: Annotated[str, typer.Option("--description", "-d")] = "",
    goal: Annotated[Optional[list[str]], typer.Option("--goal", "-g", help="Goal id (repeatable)")] = None,
    due: Annotated[Optional[str], typer.Option("--due")] = None,
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
    status: Annotated[Optional[list[str]], typer.Option("--status", "-s")] = None,
    include_archived: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    """List milestones with derived progress."""
    execute(
        ctx,
        "milestone.list",
        {"status": status, "include_archived": include_archived},
        render=lambda rows: (
            console.print("[dim]no milestones[/dim]")
            if not rows
            else [
                console.print(
                    f"{_sid(row['id'])}  {row['status']:<10} {_bar(row['progress'])} "
                    f"{row['progress'] * 100:3.0f}%  {row['title']}"
                )
                for row in rows
            ]
        ),
    )


@milestone_app.command("show")
def milestone_show(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Show milestone details and progress."""
    execute(
        ctx,
        "milestone.get",
        {"milestone_id": milestone_id},
        render=lambda r: (
            console.print(f"[bold]{r['id']}[/bold]  {r['title']}  ({r['status']})"),
            console.print(f"  {_bar(r['progress'])} {r['progress'] * 100:.0f}%  weight {r['done_weight']}/{r['total_weight']}"),
            console.print(f"  tasks {r['task_status_counts']}"),
        ),
    )


@milestone_app.command("edit")
def milestone_edit(
    ctx: typer.Context,
    milestone_id: Annotated[str, typer.Argument()],
    title: Annotated[Optional[str], typer.Option("--title")] = None,
    description: Annotated[Optional[str], typer.Option("--description", "-d")] = None,
    goal: Annotated[Optional[list[str]], typer.Option("--goal", "-g")] = None,
    due: Annotated[Optional[str], typer.Option("--due")] = None,
) -> None:
    """Edit a milestone."""
    params: dict[str, Any] = {"milestone_id": milestone_id, "title": title, "description": description, "goal_ids": goal}
    if due is not None:
        params["due_at"] = due
    execute(ctx, "milestone.update", params, render=lambda r: console.print(f"{r['id']} updated"))


@milestone_app.command("activate")
def milestone_activate(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Activate a milestone."""
    execute(ctx, "milestone.activate", {"milestone_id": milestone_id}, render=lambda r: console.print(f"{r['id']} -> active"))


@milestone_app.command("close")
def milestone_close(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Close a milestone."""
    execute(ctx, "milestone.close", {"milestone_id": milestone_id}, render=lambda r: console.print(f"{r['id']} -> closed"))


@milestone_app.command("cancel")
def milestone_cancel(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Cancel a milestone."""
    execute(ctx, "milestone.cancel", {"milestone_id": milestone_id}, render=lambda r: console.print(f"{r['id']} -> cancelled"))


@milestone_app.command("progress")
def milestone_progress(ctx: typer.Context, milestone_id: Annotated[str, typer.Argument()]) -> None:
    """Show derived milestone progress."""
    execute(
        ctx,
        "milestone.progress",
        {"milestone_id": milestone_id},
        render=lambda r: console.print(f"{_bar(r['progress'])} {r['progress'] * 100:.0f}%  ({r['done_weight']}/{r['total_weight']} weight)"),
    )


# ---------------------------------------------------------------- member cmds


@member_app.command("add")
def member_add(
    ctx: typer.Context,
    handle: Annotated[str, typer.Argument(help="Unique lowercase handle")],
    name: Annotated[Optional[str], typer.Option("--name", help="Display name")] = None,
    role: Annotated[Optional[list[str]], typer.Option("--role", help="Role (repeatable)")] = None,
    git_name: Annotated[Optional[list[str]], typer.Option("--git-name", help="Git author name (repeatable)")] = None,
    git_email: Annotated[Optional[list[str]], typer.Option("--git-email", help="Git author email (repeatable)")] = None,
) -> None:
    """Add a project member."""
    execute(
        ctx,
        "member.add",
        {
            "handle": handle,
            "display_name": name,
            "roles": role,
            "git_names": git_name,
            "git_emails": git_email,
        },
        render=lambda r: console.print(f"[green]added[/green] {r['handle']}  {r['display_name']}  ({r['id']})"),
    )


@member_app.command("list")
def member_list(
    ctx: typer.Context,
    include_inactive: Annotated[bool, typer.Option("--all", help="Include inactive members")] = False,
) -> None:
    """List members."""
    execute(
        ctx,
        "member.list",
        {"include_inactive": include_inactive},
        render=lambda rows: (
            console.print("[dim]no members[/dim]")
            if not rows
            else [
                console.print(
                    f"{row['handle']:<14} {row['display_name']:<12} "
                    f"{'active' if row['active'] else 'inactive':<9} {_sid(row['id'])}"
                )
                for row in rows
            ]
        ),
    )


@member_app.command("show")
def member_show(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Show a member."""
    execute(ctx, "member.get", {"member": member})


@member_app.command("edit")
def member_edit(
    ctx: typer.Context,
    member: Annotated[str, typer.Argument()],
    name: Annotated[Optional[str], typer.Option("--name")] = None,
    role: Annotated[Optional[list[str]], typer.Option("--role")] = None,
    git_name: Annotated[Optional[list[str]], typer.Option("--git-name")] = None,
    git_email: Annotated[Optional[list[str]], typer.Option("--git-email")] = None,
) -> None:
    """Edit a member."""
    execute(
        ctx,
        "member.update",
        {
            "member": member,
            "display_name": name,
            "roles": role,
            "git_names": git_name,
            "git_emails": git_email,
        },
        render=lambda r: console.print(f"{r['handle']} updated"),
    )


@member_app.command("deactivate")
def member_deactivate(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Deactivate a member."""
    execute(ctx, "member.deactivate", {"member": member}, render=lambda r: console.print(f"{r['handle']} deactivated"))


@member_app.command("activate")
def member_activate(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Activate a member."""
    execute(ctx, "member.activate", {"member": member}, render=lambda r: console.print(f"{r['handle']} activated"))


@member_app.command("workload")
def member_workload(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Show member workload."""
    execute(ctx, "member.workload", {"member": member}, render=render_member_workload)


@member_app.command("activity")
def member_activity(
    ctx: typer.Context,
    member: Annotated[str, typer.Argument()],
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
) -> None:
    """Show member recent activity."""
    execute(ctx, "member.activity", {"member": member, "limit": limit}, render=render_events)


@member_app.command("use")
def member_use(ctx: typer.Context, member: Annotated[str, typer.Argument()]) -> None:
    """Set default actor in .pjt/local/local.toml for this machine."""
    execute(ctx, "member.use", {"member": member}, render=lambda r: console.print(f"default actor: {r['handle']} ({r['actor']})"))


# ---------------------------------------------------------------- update cmds


@update_app.command("add")
def update_add(
    ctx: typer.Context,
    text: Annotated[Optional[str], typer.Argument(help="Update text; omit to use $EDITOR/stdin")] = None,
    task: Annotated[Optional[list[str]], typer.Option("--task", "-t", help="Related task (repeatable)")] = None,
    milestone: Annotated[Optional[str], typer.Option("--milestone", "-m")] = None,
    summary: Annotated[Optional[str], typer.Option("--summary", "-s")] = None,
    blocker: Annotated[Optional[list[str]], typer.Option("--blocker", help="Blocker (repeatable)")] = None,
    next_step: Annotated[Optional[list[str]], typer.Option("--next", help="Next step (repeatable)")] = None,
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
    task: Annotated[Optional[str], typer.Option("--task", "-t")] = None,
    milestone: Annotated[Optional[str], typer.Option("--milestone", "-m")] = None,
) -> None:
    """List updates."""
    execute(
        ctx,
        "update.list",
        {"task": task, "milestone": milestone},
        render=lambda rows: (
            console.print("[dim]no updates[/dim]")
            if not rows
            else [
                console.print(f"{_sid(row['id'])}  [dim]{_ts(row['created_at'])}[/dim]  {row['summary']}")
                for row in rows
            ]
        ),
    )


@update_app.command("show")
def update_show(ctx: typer.Context, update_id: Annotated[str, typer.Argument()]) -> None:
    """Show an update."""
    execute(ctx, "update.get", {"update_id": update_id})


# -------------------------------------------------------------- decision cmds


@decision_app.command("add")
def decision_add(
    ctx: typer.Context,
    title: Annotated[Optional[str], typer.Argument(help="Decision title; omit to use $EDITOR/stdin")] = None,
    context: Annotated[str, typer.Option("--context")] = "",
    decision: Annotated[str, typer.Option("--decision")] = "",
    rationale: Annotated[str, typer.Option("--rationale")] = "",
    alternative: Annotated[Optional[list[str]], typer.Option("--alternative", help="Alternative name or name::reason (repeatable)")] = None,
    consequence: Annotated[Optional[list[str]], typer.Option("--consequence", help="Consequence (repeatable)")] = None,
    task: Annotated[Optional[list[str]], typer.Option("--task", "-t", help="Related task (repeatable)")] = None,
    status: Annotated[str, typer.Option("--status")] = "draft",
) -> None:
    """Record an architecture/engineering decision."""
    title_text = title
    if not title_text:
        title_text = read_text_argument(None).splitlines()[0].strip()
    alternatives = []
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
    status: Annotated[Optional[list[str]], typer.Option("--status", "-s")] = None,
) -> None:
    """List decisions."""
    execute(
        ctx,
        "decision.list",
        {"status": status},
        render=lambda rows: (
            console.print("[dim]no decisions[/dim]")
            if not rows
            else [
                console.print(f"{_sid(row['id'])}  {row['status']:<11} {row['title']}")
                for row in rows
            ]
        ),
    )


@decision_app.command("show")
def decision_show(ctx: typer.Context, decision_id: Annotated[str, typer.Argument()]) -> None:
    """Show a decision."""
    execute(ctx, "decision.get", {"decision_id": decision_id})


@decision_app.command("accept")
def decision_accept(ctx: typer.Context, decision_id: Annotated[str, typer.Argument()]) -> None:
    """Accept a decision."""
    execute(ctx, "decision.accept", {"decision_id": decision_id}, render=lambda r: console.print(f"{r['id']} -> accepted"))


@decision_app.command("reject")
def decision_reject(ctx: typer.Context, decision_id: Annotated[str, typer.Argument()]) -> None:
    """Reject a decision."""
    execute(ctx, "decision.reject", {"decision_id": decision_id}, render=lambda r: console.print(f"{r['id']} -> rejected"))


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
        render=lambda r: console.print(f"{_sid(r['superseded']['id'])} superseded by {_sid(r['superseded_by']['id'])}"),
    )


# ------------------------------------------------------------------ link cmds


@link_app.command("add")
def link_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument()],
    locator: Annotated[str, typer.Argument(help="Relative path or URL")],
    kind: Annotated[Optional[str], typer.Option("--kind", help="local_project|remote_project|git_repository|external")] = None,
    mode: Annotated[str, typer.Option("--mode", help="reference|aggregate")] = "reference",
    project_id: Annotated[Optional[str], typer.Option("--project-id")] = None,
) -> None:
    """Link another project (relative path / URL / project id only)."""
    execute(
        ctx,
        "link.add",
        {"name": name, "locator": locator, "kind": kind, "mode": mode, "project_id": project_id},
        render=lambda r: console.print(f"[green]linked[/green] {r['name']} -> {r['target']['locator']}"),
    )


@link_app.command("list")
def link_list(ctx: typer.Context) -> None:
    """List linked projects."""
    execute(
        ctx,
        "link.list",
        {},
        render=lambda rows: (
            console.print("[dim]no links[/dim]")
            if not rows
            else [
                console.print(
                    f"{row['name']:<14} {row['target']['kind']:<16} "
                    f"{row['mode']:<10} {row['target']['locator'] or ''}"
                )
                for row in rows
            ]
        ),
    )


@link_app.command("show")
def link_show(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Show a link."""
    execute(ctx, "link.get", {"name": name})


@link_app.command("resolve")
def link_resolve(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Resolve a link target on this machine."""
    execute(
        ctx,
        "link.resolve",
        {"name": name},
        render=lambda r: console.print(
            f"{r['name']}: resolved={r['resolved']} "
            f"path={r.get('path', '-')} project={r.get('project', {})} error={r.get('error', '-')}"
        ),
    )


@link_app.command("remove")
def link_remove(ctx: typer.Context, name: Annotated[str, typer.Argument()]) -> None:
    """Remove a link."""
    execute(ctx, "link.remove", {"name": name}, render=lambda r: console.print(f"{r['name']} removed"))


# ------------------------------------------------------------- log / graph


@app.command()
def log(
    ctx: typer.Context,
    task: Annotated[Optional[str], typer.Option("--task", "-t", help="Filter by task")] = None,
    member: Annotated[Optional[str], typer.Option("--member", "-m", help="Filter by actor")] = None,
    event_type: Annotated[Optional[str], typer.Option("--type", help="Event type (prefix ok)")] = None,
    since: Annotated[Optional[str], typer.Option("--since", help="ISO time or 7d/24h/30m")] = None,
    until: Annotated[Optional[str], typer.Option("--until")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
    cursor: Annotated[Optional[str], typer.Option("--cursor")] = None,
) -> None:
    """Show project event history."""
    params: dict[str, Any] = {
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


@app.command()
def graph(
    ctx: typer.Context,
    scope: Annotated[str, typer.Argument(help="project|tasks|milestone|projects")] = "project",
    target: Annotated[Optional[str], typer.Argument(help="Milestone id for `graph milestone`")] = None,
) -> None:
    """Show project graph (project tree / task tree / links)."""
    if scope == "project":
        execute(ctx, "graph.project", {}, render=render_project_graph)
    elif scope == "tasks":
        execute(
            ctx,
            "graph.tasks",
            {"milestone_id": target},
            render=lambda result: render_task_graph(result, "Tasks"),
        )
    elif scope == "milestone":
        if not target:
            state: CliState = ctx.obj
            fail(state, InvalidArgument("graph milestone requires a milestone id"))
        execute(
            ctx,
            "graph.tasks",
            {"milestone_id": target},
            render=lambda result: render_task_graph(result, f"Milestone {target}"),
        )
    elif scope == "projects":
        execute(
            ctx,
            "graph.links",
            {},
            render=lambda rows: (
                console.print("[dim]no linked projects[/dim]")
                if not rows
                else [
                    console.print(
                        f"{row['name']:<14} {row['kind']:<16} resolved={row['resolved']} {row.get('path', '')}"
                    )
                    for row in rows
                ]
            ),
        )
    else:
        state: CliState = ctx.obj
        fail(state, InvalidArgument(f"unknown graph scope: {scope!r} (project|tasks|milestone|projects)"))


def main() -> None:
    try:
        app()
    except ProjectToolError as exc:
        err_console.print(f"[red]{exc.code}[/red] {exc.message}")
        raise SystemExit(exc.exit_code)


if __name__ == "__main__":
    main()
