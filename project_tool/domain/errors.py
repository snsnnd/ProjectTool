"""统一错误模型：错误码 + CLI 退出码。"""

from __future__ import annotations

from typing import Any


class ProjectToolError(Exception):
    code = "INTERNAL"
    exit_code = 1

    def __init__(self, message: str = "", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_error(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidArgument(ProjectToolError):
    code = "INVALID_ARGUMENT"
    exit_code = 3


class NotFound(ProjectToolError):
    code = "NOT_FOUND"
    exit_code = 4


class AlreadyExists(ProjectToolError):
    code = "ALREADY_EXISTS"
    exit_code = 3


class Conflict(ProjectToolError):
    code = "CONFLICT"
    exit_code = 5


class RevisionConflict(ProjectToolError):
    code = "REVISION_CONFLICT"
    exit_code = 5

    def __init__(
        self,
        message: str,
        expected_rev: str | None = None,
        actual_rev: str | None = None,
        entity_id: str | None = None,
    ):
        details = {"expected_rev": expected_rev, "actual_rev": actual_rev, "entity_id": entity_id}
        super().__init__(message, details)


class Claimed(ProjectToolError):
    """task 已被他人认领（V1-C）。

    和 `RevisionConflict` 分开是刻意的：rev 冲突是**事后**发现（写不进去），
    而认领冲突是**事前**告知（动手前就知道该找谁）。agent 应该按前者重试，
    按后者换任务 —— 混成一个码会让调用方分不清该重试还是该放弃。
    """

    code = "CLAIMED"
    exit_code = 6

    def __init__(
        self,
        message: str,
        member_id: str | None = None,
        expires_at: str | None = None,
        task_id: str | None = None,
    ):
        super().__init__(
            message,
            {"member_id": member_id, "expires_at": expires_at, "task_id": task_id},
        )


class DependencyCycle(ProjectToolError):
    code = "DEPENDENCY_CYCLE"
    exit_code = 3


class HierarchyCycle(ProjectToolError):
    code = "HIERARCHY_CYCLE"
    exit_code = 3


class BrokenLink(ProjectToolError):
    code = "BROKEN_LINK"
    exit_code = 3


class PermissionDenied(ProjectToolError):
    code = "PERMISSION_DENIED"
    exit_code = 6


class AuthRequired(ProjectToolError):
    code = "AUTH_REQUIRED"
    exit_code = 6


class RemoteUnavailable(ProjectToolError):
    code = "REMOTE_UNAVAILABLE"
    exit_code = 7


class SyncConflict(ProjectToolError):
    code = "SYNC_CONFLICT"
    exit_code = 8


class SchemaUnsupported(ProjectToolError):
    code = "SCHEMA_UNSUPPORTED"
    exit_code = 9


class SchemaMigrationRequired(ProjectToolError):
    """项目 schema 落后于工具：读允许，写被拦住，必须先 `pjt migrate`。"""

    code = "SCHEMA_MIGRATION_REQUIRED"
    exit_code = 9

    def __init__(
        self,
        message: str,
        project_schema: str | None = None,
        tool_schema: str | None = None,
    ):
        super().__init__(
            message,
            {"project_schema_version": project_schema, "tool_schema_version": tool_schema},
        )


class ProjectCorrupted(ProjectToolError):
    code = "PROJECT_CORRUPTED"
    exit_code = 9


class GitError(ProjectToolError):
    code = "GIT_ERROR"
    exit_code = 1


class ProjectIOError(ProjectToolError):
    code = "IO_ERROR"
    exit_code = 1


class InternalError(ProjectToolError):
    code = "INTERNAL"
    exit_code = 1
