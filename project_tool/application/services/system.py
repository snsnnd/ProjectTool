"""system.* 方法。"""

from __future__ import annotations

from typing import Any

from project_tool import __version__
from project_tool.version import SCHEMA_VERSION


def _reverse(commands) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in commands:
        method = item.get("method")
        if not method:
            continue
        out.setdefault(method, []).append(" ".join(item["path"]))
    for paths in out.values():
        paths.sort()
    return out


class SystemService:
    def __init__(self, ctx):
        self.ctx = ctx

    def system_cli(self) -> dict[str, Any]:
        """完整 CLI 命令树（机器可读）。

        给 KC 这类平台包装用：生成自己的界面 / 文档 / 输入校验。
        `--help` 是给人看的文本，没有稳定字段名，脚本解析它就会脆。
        """
        from project_tool.cli.main import CLI_METHOD_MAP, cli_surface

        commands = cli_surface()
        return {
            "count": len(commands),
            "commands": commands,
            # 反向表：method -> 有哪几条 CLI 路径（一个 method 可能有多条命令）
            "method_to_paths": _reverse(commands),
            # 只统计**可执行命令**：分组节点没有 method 很正常，
            # 混进来会让「未映射」这个信号失去意义
            "unmapped": sorted(
                " ".join(item["path"])
                for item in commands
                if item["kind"] == "command" and item["method"] is None
            ),
            "method_map_size": len(CLI_METHOD_MAP),
        }

    def system_info(self) -> dict[str, Any]:
        return {
            "tool": "project-tool",
            "version": __version__,
            "schema_version": SCHEMA_VERSION,
            "project_id": self.ctx.opened.project.id,
        }
