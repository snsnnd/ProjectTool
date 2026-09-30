"""ProjectService：组合领域服务 + 显式 registry dispatch。

对外协议与 V0 完全兼容：

```python
service = ProjectService.open(path)
result = service.call("task.create", {"title": "..."})
response = service.handle("task.create", {...}, request_id="req-1")
```

具体业务逻辑位于 `application/services/*`，共享 `ServiceContext`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from project_tool.application.context import ServiceContext, resolve_actor
from project_tool.application.registry import MethodSpec, build_registry
from project_tool.application.services.area import AreaService
from project_tool.application.services.artifact import ArtifactService
from project_tool.application.services.decision import DecisionService
from project_tool.application.services.goal import GoalService
from project_tool.application.services.graph import GraphService
from project_tool.application.services.link import LinkService
from project_tool.application.services.log import LogService
from project_tool.application.services.member import MemberService
from project_tool.application.services.milestone import MilestoneService
from project_tool.application.services.project import CAPABILITIES_FEATURES, ProjectServiceGroup
from project_tool.application.services.system import SystemService
from project_tool.application.services.task import TaskService
from project_tool.application.services.update import UpdateService
from project_tool.domain.errors import (
    InvalidArgument,
    ProjectToolError,
    SchemaMigrationRequired,
)
from project_tool.storage import open_project
from project_tool.version import SCHEMA_VERSION

PROTOCOL_VERSION = 1

# 维护类方法：不受 schema 写入门限制。
# - project.init     在打开项目之前执行，没有 schema 可言
# - project.migrate  正是「把 schema 抬到当前版本」的那一步本身
# - project.recover  只重放已 staged 的字节，不会在 1.0 项目里写出 1.1 对象
#                    （崩溃残留必须总能恢复，不能被写入门挡住）
SCHEMA_GATE_EXEMPT = frozenset({"project.init", "project.migrate", "project.recover"})


class ProjectService:
    def __init__(self, opened, actor_id: str | None = None):
        self.ctx = ServiceContext(opened, actor_id)
        self.opened = opened
        self.paths = opened.paths
        self.store = self.ctx.store
        self.events = self.ctx.events

        self.system = SystemService(self.ctx)
        self.project = ProjectServiceGroup(self.ctx)
        self.goals = GoalService(self.ctx)
        self.milestones = MilestoneService(self.ctx)
        self.tasks = TaskService(self.ctx)
        self.areas = AreaService(self.ctx, self.tasks)
        self.members = MemberService(self.ctx)
        self.updates = UpdateService(self.ctx)
        self.decisions = DecisionService(self.ctx)
        self.artifacts = ArtifactService(self.ctx)
        self.links = LinkService(self.ctx)
        self.logs = LogService(self.ctx)
        self.graphs = GraphService(self.ctx, self.links)

        self.registry: dict[str, MethodSpec] = build_registry(self)

    # ------------------------------------------------------------------ 入口

    @classmethod
    def open(cls, root: str | Path | None = None, actor: str | None = None) -> ProjectService:
        return cls(open_project(root), actor_id=actor)

    @staticmethod
    def project_init(path, name=None, description="", slug=None) -> dict[str, Any]:
        return ProjectServiceGroup.project_init(
            path, name=name, description=description, slug=slug
        )

    @property
    def actor_id(self) -> str | None:
        return self.ctx.actor_id

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        if not isinstance(params, dict):
            raise InvalidArgument("params must be an object")
        spec = self.registry.get(str(method))
        if spec is None:
            raise InvalidArgument(f"unknown method: {method!r}")
        if spec.mutating and spec.name not in SCHEMA_GATE_EXEMPT:
            self._require_current_schema(spec.name)
        return spec.handler(**params)

    def handle(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        request_id: str = "req",
    ) -> dict[str, Any]:
        try:
            return {"id": request_id, "result": self.call(method, params)}
        except ProjectToolError as exc:
            return {"id": request_id, "error": exc.to_error()}

    # ---------------------------------------------------------------- 能力发现

    def _require_current_schema(self, method: str) -> None:
        """Schema 写入门：项目头声明的 schema 必须已经是当前工具的版本。

        没有这道门就会出现「project.json 说 1.0，里面却已经有 1.1 对象」的不一致状态，
        而 `schema_version` 也就失去了作为兼容性声明的意义。
        读路径不受影响（1.0 项目照常可读，正是为了让人能跑 `pjt migrate`）。
        """
        current = self.ctx.opened.project.schema_version
        if current == SCHEMA_VERSION:
            return
        raise SchemaMigrationRequired(
            f"{method} requires schema {SCHEMA_VERSION} but this project is {current}; "
            "run 'pjt migrate' first",
            project_schema=current,
            tool_schema=SCHEMA_VERSION,
        )

    def system_capabilities(self) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "schema_version": SCHEMA_VERSION,
            "methods": sorted(self.registry),
            "features": dict(CAPABILITIES_FEATURES),
        }

    # ------------------------------------------------------------ 兼容私有 helper

    def _member_id(self, ref: str) -> str:
        """保留给旧调用方（queries 已迁移到 ctx）。"""
        return self.ctx.member_id(ref)


__all__ = ["ProjectService", "resolve_actor"]
