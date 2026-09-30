"""project.* 方法：打开、读取、更新（带 expected_rev）、状态、doctor、迁移、恢复。"""

from __future__ import annotations

from typing import Any

import project_tool.application.queries as queries
from project_tool.application.context import ServiceContext
from project_tool.application.doctor import run_doctor
from project_tool.domain.enums import ProjectStatus
from project_tool.domain.errors import InvalidArgument
from project_tool.domain.validation import optional_text, optional_title
from project_tool.storage import (
    WriteLock,
    init_project,
    recover_all,
)
from project_tool.storage.migrations import PROJECT_SCHEMA_FIELD
from project_tool.storage.migrations import migrate as run_migration
from project_tool.version import SCHEMA_VERSION

CAPABILITIES_FEATURES = {
    "area": True,
    "artifact": True,
    "git": True,
    "search": False,
    "web": False,
    "remote": False,
    "sync": False,
}


class ProjectServiceGroup:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    # ------------------------------------------------------------------- init

    @staticmethod
    def project_init(path, name=None, description="", slug=None) -> dict[str, Any]:
        opened = init_project(path, name=name, description=description, slug=slug)
        return {
            "root": str(opened.paths.root),
            "project": opened.project.to_record(),
            "device_id": opened.device_id,
        }

    # ------------------------------------------------------------------- read

    def project_open(self) -> dict[str, Any]:
        project = self.ctx.opened.project
        return {
            "root": str(self.ctx.paths.root),
            "project": project.to_record(),
            "device_id": self.ctx.opened.device_id,
            "actor": self.ctx.actor_id,
            "schema_version": project.schema_version,
        }

    def project_get(self) -> dict[str, Any]:
        return self.ctx.opened.project.to_record()

    def project_status(self, recent: int = 10) -> dict[str, Any]:
        return queries.project_status(self.ctx, recent_limit=int(recent))

    def project_doctor(self) -> dict[str, Any]:
        return run_doctor(self.ctx)

    def project_migrate(self) -> dict[str, Any]:
        result = run_migration(self.ctx.opened)
        if result.get("needs_project_bump"):
            self.ctx.opened.project.schema_version = SCHEMA_VERSION
            record = self.ctx.save_project(
                "project.migrated",
                {"fields": [PROJECT_SCHEMA_FIELD], "from": result["from"], "to": result["to"]},
            )
            result["project_schema_version"] = record[PROJECT_SCHEMA_FIELD]
        return result

    # ------------------------------------------------------------------ write

    def project_update(
        self,
        expected_rev: str | None = None,
        name=None,
        description=None,
        status=None,
        metadata=None,
    ) -> dict[str, Any]:
        project = self.ctx.opened.project
        self.ctx.require_expected_rev("project", project, expected_rev)
        fields: list[str] = []
        if name is not None:
            project.name = optional_title(name, "project name")
            fields.append("name")
        if description is not None:
            project.description = optional_text(description, "project description")
            fields.append("description")
        if status is not None:
            project.status = _project_status(status)
            fields.append("status")
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise InvalidArgument("metadata must be an object")
            project.metadata = dict(metadata)
            fields.append("metadata")
        if not fields:
            return project.to_record()
        return self.ctx.save_project("project.updated", {"fields": fields})

    def project_recover(self) -> dict[str, Any]:
        with WriteLock(self.ctx.paths):
            results = recover_all(self.ctx.paths)
        return {
            "count": len(results),
            "recovered": [
                {
                    "transaction_id": result.transaction_id,
                    "action": result.action,
                    "detail": result.detail,
                }
                for result in results
            ],
        }


def _project_status(value) -> ProjectStatus:
    try:
        return ProjectStatus(value)
    except ValueError:
        allowed = ", ".join(item.value for item in ProjectStatus)
        raise InvalidArgument(f"invalid status: {value!r} (allowed: {allowed})") from None
