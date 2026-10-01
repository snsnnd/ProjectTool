"""CLI 公共设施：状态、执行、统一错误映射。

CLI 只允许调用 Application Service，禁止直接访问 storage / filesystem。
"""

from __future__ import annotations

import json as jsonlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console

from project_tool.application.service import ProjectService
from project_tool.domain.errors import InvalidArgument, ProjectToolError
from project_tool.domain.ids import short_id
from project_tool.domain.timeutil import format_time

console = Console()
err_console = Console(stderr=True)

# 统一并发门：与 Service 的 expected_rev contract 一一对应（docs/09-v1a-design.md §4.5）。
ExpectedRev = Annotated[
    str | None,
    typer.Option("--expected-rev", help="Fail with REVISION_CONFLICT if the object rev differs"),
]


def key_values(items) -> dict[str, str]:
    """把重复的 `key=value` 选项解析成 dict。

    给 `--external-id kc_user=u_1 --external-id email=a@b.c` 这类选项用。
    - 缺 `=`、key 空、value 含 `=`（如 URL）都按「只 split 一次」处理
    - 同一个 key 出现多次时后者覆盖前者（一次调用内即可预期）
    - 空列表返回空 dict，调用方可以据此判断「用户没传」
    """
    out: dict[str, str] = {}
    for item in items or []:
        text = str(item)
        if "=" not in text:
            raise InvalidArgument(
                f"expected key=value, got {text!r} (e.g. --external-id kc_user=u_12345)"
            )
        key, _, value = text.partition("=")
        key = key.strip()
        if not key:
            raise InvalidArgument(f"empty key in {text!r}")
        out[key] = value.strip()
    return out


def key_values_or_fail(state: CliState, items, option: str) -> dict[str, str] | None:
    """和 `key_values` 一样，但把 `InvalidArgument` 走**正常错误通道**。

    为什么需要它：params 字典是在**调用点**构造的，也就是在 `execute()` 的
    try 之外。所以直接调 `key_values()` 抛出的异常会绕过 `execute` 的
    统一处理，变成裸 traceback（`--json` 模式下甚至不是合法的错误包）。
    """
    try:
        parsed = key_values(items)
    except ProjectToolError as exc:
        fail(state, exc)
    if not items:
        return None
    if not parsed:
        fail(state, InvalidArgument(f"{option} needs at least one key=value pair"))
    return parsed


class CliState:
    def __init__(self, json_out: bool, porcelain: bool, actor: str | None, project: str | None):
        self.json_out = json_out
        self.porcelain = porcelain
        self.actor = actor
        self.project = project


def get_service(state: CliState) -> ProjectService:
    return ProjectService.open(state.project, actor=state.actor)


def fail(state: CliState, exc: ProjectToolError) -> NoReturn:
    if state.json_out:
        typer.echo(
            jsonlib.dumps({"id": "cli", "error": exc.to_error()}, ensure_ascii=False, indent=2)
        )
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
        raise typer.Exit(1) from exc
    emit(state, result, render=render, porcelain_render=porcelain_render)
    return result


def sid(value: str | None) -> str:
    if not value:
        return "-"
    return short_id(value)


def ts(value: str | None) -> str:
    return format_time(value) if value else ""


def bar(progress: float, width: int = 20) -> str:
    filled = max(0, min(width, int(round(progress * width))))
    return "█" * filled + "░" * (width - filled)


def event_detail(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    if "from" in payload and "to" in payload:
        return f"{payload['from']} → {payload['to']}"
    if "member_id" in payload:
        return sid(payload["member_id"])
    if "target_id" in payload:
        return f"depends on {sid(payload['target_id'])}"
    if "label" in payload:
        return str(payload["label"])
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
