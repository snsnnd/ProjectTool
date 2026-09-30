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
from project_tool.domain.errors import InvalidArgument, ProjectToolError
from project_tool.storage import open_project
from project_tool.version import SCHEMA_VERSION

PROTOCOL_VERSION = 1


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
        self.members = MemberService(self.ctx)
        self.updates = UpdateService(self.ctx)
        self.decisions = DecisionService(self.ctx)
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
