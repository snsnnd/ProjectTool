"""system.* 方法。"""

from __future__ import annotations

from typing import Any

from project_tool import __version__
from project_tool.version import SCHEMA_VERSION


class SystemService:
    def __init__(self, ctx):
        self.ctx = ctx

    def system_info(self) -> dict[str, Any]:
        return {
            "tool": "project-tool",
            "version": __version__,
            "schema_version": SCHEMA_VERSION,
            "project_id": self.ctx.opened.project.id,
        }
