"""git 子命令：Git 只读感知。

**不写 Git 仓库**。`git link-commit` 只在 `.pjt` 里登记一条 `git_commit` Artifact。
不提供 clone / add / commit / checkout / merge / reset / clean——那些是 Git 的事。
"""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.table import Table

from project_tool.cli.common import console, execute, sid

git_app = typer.Typer(help="Git awareness (read-only; never writes the repository)", no_args_is_help=True)

AREA_CODES = {
    "ok": "green",
    "missing": "yellow",
    "unmerged": "red",
}


@git_app.command("status")
def git_status(
    ctx: typer.Context,
    area: Annotated[
        str | None, typer.Option("--area", "-a", help="Only files matching this area's patterns")
    ] = None,
    include_untracked: Annotated[
        bool, typer.Option("--untracked/--no-untracked", help="Include untracked files")
    ] = True,
    include_pjt: Annotated[
        bool,
        typer.Option(
            "--include-pjt/--no-pjt", help="Expand .pjt files (default: one summary line)"
        ),
    ] = False,
) -> None:
    """Show changed files in the project, with candidate areas and referencing artifacts.

    Candidate areas are **derived only** — this command never changes Area or Task.
    """
    # 真 renderer 交给 execute：--json 时 emit 自己跳过它并输出 RPC 包
    execute(
        ctx,
        "git.status",
        {"area": area, "include_untracked": include_untracked, "include_pjt": include_pjt},
        render=lambda result: _render_status(result, include_pjt=include_pjt),
    )


@git_app.command("log")
def git_log(
    ctx: typer.Context,
    task: Annotated[str | None, typer.Option("--task", "-t", help="Filter by PJT-Task trailer")] = None,
    path: Annotated[str | None, typer.Option("--path", help="Only commits touching this path")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 30,
) -> None:
    """Show commit history, optionally filtered by task trailer or path."""
    execute(
        ctx,
        "git.log",
        {"task": task, "path": path, "limit": limit},
        render=_render_log,
    )


@git_app.command("link-commit")
def git_link_commit(
    ctx: typer.Context,
    commit: Annotated[str, typer.Argument(help="Commit SHA or any ref git can resolve")],
    task: Annotated[
        str | None,
        typer.Option("--task", "-t", help="Attach to this task (default: read PJT-Task trailer)"),
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", help="Artifact name (default: commit subject)")
    ] = None,
) -> None:
    """Register a commit as a `git_commit` Artifact. Writes .pjt only, never the repo."""
    execute(
        ctx,
        "git.link_commit",
        {"commit": commit, "task": task, "name": name},
        render=_render_link,
    )


def _render_status(result: dict[str, Any], include_pjt: bool = False) -> None:
    if not result.get("available"):
        console.print(f"[yellow]git unavailable[/yellow]  {result.get('reason')}")
        return
    subdir = result.get("project_subdir")
    if subdir:
        console.print(
            f"[dim]git root {result['work_tree']}  ·  project subdir {subdir}[/dim]\n"
        )
    files = result.get("files") or []
    if not files:
        console.print("[green]working tree clean[/green] (no changed files in the project)")
    else:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Status")
        table.add_column("Path")
        table.add_column("Candidate areas", style="dim")
        table.add_column("Artifacts", style="dim")
        for item in files:
            code = AREA_CODES.get(item["status"], "yellow")
            table.add_row(
                f"[{code}]{item['status']}[/{code}]",
                item["path"],
                ", ".join(area["name"] for area in item["candidate_areas"]) or "-",
                ", ".join(art["name"] for art in item["referenced_by_artifacts"]) or "-",
            )
        console.print(table)
    pjt_changed = result.get("pjt_changed") or 0
    if pjt_changed and not include_pjt:
        counts = ", ".join(f"{k}={v}" for k, v in sorted((result.get("pjt_status_counts") or {}).items()))
        console.print(
            f"  [dim]+ {pjt_changed} .pjt file(s) ({counts}) — Project Tool's own canonical data; "
            f"commit them together (--include-pjt to expand)[/dim]"
        )
    unbound = result.get("unbound_areas") or []
    if unbound:
        console.print(
            f"[dim]{len(unbound)} area(s) have no path_patterns and never match: "
            + ", ".join(area["name"] for area in unbound)
            + "\nbind with: pjt area edit <area> --path-pattern <glob>[/dim]"
        )


def _render_log(result: dict[str, Any]) -> None:
    if not result.get("available"):
        console.print(f"[yellow]git unavailable[/yellow]  {result.get('reason')}")
        return
    commits = result.get("commits") or []
    if not commits:
        console.print(
            "[dim]no commits"
            + (f" with {result['task_id'][:12]} in its message" if result.get("task_id") else "")
            + "[/dim]"
        )
        return
    for commit in commits:
        linked = ", ".join(sid(item) for item in commit.get("linked_task_ids") or [])
        console.print(
            f"  {commit['short_sha']}  [dim]{commit['authored_at'][:10]}[/dim]  "
            f"{commit['subject']}"
            + (f"  [dim]↳ {linked}[/dim]" if linked else "")
        )


def _render_link(result: dict[str, Any]) -> None:
    artifact = result["artifact"]
    commit = result["commit"]
    verb = "linked" if result["created"] else "already linked"
    console.print(
        f"[green]{verb}[/green] {commit['short_sha']}  →  {sid(artifact['id'])}  "
        f"{artifact['locator']}"
    )
    console.print(f"  {commit['subject']}")
    if artifact["related_task_ids"]:
        console.print(f"  tasks: {', '.join(sid(t) for t in artifact['related_task_ids'])}")
    console.print("  [dim]the repository was not modified[/dim]")

