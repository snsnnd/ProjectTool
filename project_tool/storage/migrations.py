"""Schema 版本校验与迁移入口（V0：仅支持 1.x，无实际迁移步骤）。"""

from __future__ import annotations

from typing import Any

from project_tool.domain.errors import SchemaUnsupported
from project_tool.version import SCHEMA_VERSION


def migrate(opened) -> dict[str, Any]:
    current = opened.project.schema_version
    supported_major = SCHEMA_VERSION.split(".")[0]
    if current.split(".")[0] != supported_major:
        raise SchemaUnsupported(
            f"cannot migrate schema {current}: this tool supports {SCHEMA_VERSION}.x"
        )
    if current == SCHEMA_VERSION:
        return {
            "from": current,
            "to": SCHEMA_VERSION,
            "applied": [],
            "message": "already up to date",
        }
    return {
        "from": current,
        "to": SCHEMA_VERSION,
        "applied": [],
        "message": f"no migration steps registered from {current} to {SCHEMA_VERSION}",
    }
