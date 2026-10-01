"""interface 子命令（V1-C）。

接口契约 = 工作树里一份**固定模板**的 markdown + 注册成 Artifact。
所以这里的命令刻意很薄：init 建骨架、list/show 读、check 查、sync 对齐 area。

**check 只报告不改写**——接口文档是多方沟通的产物，工具替人改契约
比不检查更糟。
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

from project_tool.cli.common import ExpectedRev, console, execute
from project_tool.cli.render import (
    render_interface_check,
    render_interface_list,
    render_interface_show,
)

interface_app = typer.Typer(
    help="Interface contracts (templated markdown documents, registered as artifacts)",
    no_args_is_help=True,
)


@interface_app.command("init")
def interface_init(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Interface name, e.g. store.updateModel")],
    area: Annotated[str | None, typer.Option("--area", help="Owning area (name or id)")] = None,
    kind: Annotated[
        str,
        typer.Option("--kind", help="module_api | store_api | event | protocol | other"),
    ] = "module_api",
    path: Annotated[
        str | None,
        typer.Option("--path", help="Target path (default docs/interfaces/<slug>.md)"),
    ] = None,
    owner: Annotated[
        list[str] | None, typer.Option("--owner", help="Maintainer (repeatable)")
    ] = None,
    consumer: Annotated[
        list[str] | None, typer.Option("--consumer", help="Consuming area/module (repeatable)")
    ] = None,
    summary: Annotated[str, typer.Option("--summary", help="One-line purpose")] = "",
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file")] = False,
) -> None:
    """Scaffold an interface document from the fixed template and register it."""
    result = execute(
        ctx,
        "interface.init",
        {
            "name": name,
            "area": area,
            "kind": kind,
            "path": path,
            "owners": owner,
            "consumers": consumer,
            "summary": summary,
            "force": force,
        },
        render=render_interface_show,
    )
    console.print(
        f"[dim]edit it with any editor, then run:[/dim] pjt interface check {name}\n"
    )
    return result


@interface_app.command("list")
def interface_list(
    ctx: typer.Context,
    area: Annotated[str | None, typer.Option("--area")] = None,
    status: Annotated[str | None, typer.Option("--status", help="draft|review|agreed|deprecated")] = None,
) -> None:
    """List registered interface documents."""
    execute(
        ctx,
        "interface.list",
        {"area": area, "status": status},
        render=render_interface_list,
    )


@interface_app.command("show")
def interface_show(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument()] = None,
    artifact: Annotated[str | None, typer.Option("--artifact", help="Artifact id")] = None,
) -> None:
    """Print one interface document verbatim."""
    execute(
        ctx,
        "interface.show",
        {"name": name, "artifact": artifact},
        render=lambda r: _print_document(r),
    )


def _print_document(result: dict[str, Any]) -> None:
    console.print(f"[dim]{result['locator']}[/dim]\n")
    # 原文照打，不走 rich 标记解析——文档里有 [brackets] 会吃掉样式
    from rich.text import Text

    console.print(Text(result["text"]))


@interface_app.command("check")
def interface_check(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="Check one; omit to check all")] = None,
    artifact: Annotated[str | None, typer.Option("--artifact")] = None,
) -> None:
    """Validate interface documents (front-matter + required sections). Read-only.

    有 error 时以退出码 1 结束，这样能直接当 CI 门禁用。
    """
    result = execute(
        ctx,
        "interface.check",
        {"name": name, "artifact": artifact},
        render=render_interface_check,
    )
    if isinstance(result, dict) and not result.get("ok", True):
        raise typer.Exit(code=1)
    return result


@interface_app.command("sync")
def interface_sync(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument()] = None,
    artifact: Annotated[str | None, typer.Option("--artifact")] = None,
    rev: ExpectedRev = None,
) -> None:
    """Align the artifact registration with the document's front-matter (area only)."""
    execute(
        ctx,
        "interface.sync",
        {"name": name, "artifact": artifact, "expected_rev": rev},
        render=lambda r: console.print(
            f"{r['id']} synced  area={','.join(r.get('related_area_ids') or []) or '(none)'}"
        ),
    )
