"""Schema 版本校验与迁移。

V1-A（`SCHEMA_VERSION` 1.0 → 1.1）注册了两个**幂等**迁移步骤：

1. **补齐集合目录**：V0.1 项目没有 `objects/areas/`（以及未来的
   `objects/artifacts/`）。缺目录的项目照常打开，集合读作 `[]`；`pjt migrate`
   只创建空目录，不产生任何对象或事件。
2. **project.json 的 schema_version**：不匹配时走标准事务写路径
   （WriteLock → Transaction → `project.migrated` 事件），由调用方执行。

本模块只做**布局**修复与计划计算；写 project.json 需要 ServiceContext，
因此第 2 步由 `ProjectServiceGroup.project_migrate` 执行。
"""

from __future__ import annotations

from typing import Any

from project_tool.domain.errors import SchemaUnsupported
from project_tool.domain.ids import COLLECTION_BY_TYPE
from project_tool.integrations import filesystem
from project_tool.version import SCHEMA_VERSION

PROJECT_SCHEMA_FIELD = "schema_version"


def migrate(opened) -> dict[str, Any]:
    current = opened.project.schema_version
    supported_major = SCHEMA_VERSION.split(".")[0]
    if current.split(".")[0] != supported_major:
        raise SchemaUnsupported(
            f"cannot migrate schema {current}: this tool supports {SCHEMA_VERSION}.x"
        )

    applied = ensure_object_dirs(opened.paths)
    needs_project_bump = current != SCHEMA_VERSION

    if not applied and not needs_project_bump:
        message = "already up to date"
    else:
        parts = []
        if applied:
            parts.append(f"created object collection dir(s): {', '.join(applied)}")
        if needs_project_bump:
            parts.append(f"{PROJECT_SCHEMA_FIELD} {current} -> {SCHEMA_VERSION}")
        message = "; ".join(parts)

    return {
        "from": current,
        "to": SCHEMA_VERSION,
        "applied": applied,
        "needs_project_bump": needs_project_bump,
        "message": message,
    }


def ensure_object_dirs(paths) -> list[str]:
    """创建缺失的 `.pjt/objects/<collection>/` 空目录，返回新建的目录名。"""
    created: list[str] = []
    for collection in sorted(COLLECTION_BY_TYPE.values()):
        target = paths.objects / collection
        if not target.is_dir():
            filesystem.ensure_dir(target)
            created.append(collection)
    return created


__all__ = ["PROJECT_SCHEMA_FIELD", "ensure_object_dirs", "migrate"]
