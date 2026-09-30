"""area.* 方法：稳定的项目分区 / 工作领域（V1-A）。

Area 没有 status / progress / due_at；它的生命周期只有 `lifecycle`
（active / archived / deleted），并可选一个父 Area 形成简单层级。
环检测复用 ServiceContext 的通用 `_validate_chain`，与 goal/task parent 同一套。
"""

from __future__ import annotations

from typing import Any, cast

from project_tool.application.context import UNSET, ServiceContext
from project_tool.domain.area import Area
from project_tool.domain.area_paths import match_any, normalize_path_patterns
from project_tool.domain.enums import Lifecycle
from project_tool.domain.errors import InvalidArgument
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import optional_text, require_title
from project_tool.graph import project_graph


class AreaService:
    def __init__(self, ctx: ServiceContext, task_service):
        self.ctx = ctx
        self.tasks = task_service

    # ----------------------------------------------------------------- 创建

    def area_create(
        self,
        name,
        description="",
        parent_area_id=None,
        path_patterns=None,
        expected_rev=None,
    ) -> dict[str, Any]:
        # expected_rev 在创建路径上无意义（对象还不存在），显式拒绝而不是静默忽略。
        if expected_rev is not None:
            raise InvalidArgument("expected_rev is not accepted when creating an area")
        name_text = require_title(name, "area name")
        parent = self.ctx.area_id(parent_area_id)
        now = now_local()
        area = Area(
            id=new_id("area"),
            project_id=self.ctx.opened.project.id,
            name=name_text,
            description=optional_text(description, "description"),
            parent_area_id=parent,
            path_patterns=normalize_path_patterns(path_patterns),
            created_at=now,
            updated_at=now,
        )
        return self.ctx.save(area, None, "area.created", {"name": area.name}, is_create=True)

    # ----------------------------------------------------------------- 查询

    def area_get(self, area_id) -> dict[str, Any]:
        area = self.ctx.load("area", self.ctx.require_area_id(area_id))
        return project_graph.area_summary(area, self.ctx.tasks_by_id())

    def area_list(
        self,
        parent=None,
        include_archived=False,
        include_deleted=False,
    ) -> list[dict[str, Any]]:
        parent_id = self.ctx.area_id(parent) if parent else None
        tasks = self.ctx.tasks_by_id()
        result = []
        for model in self.ctx.store.list_models("area", include_deleted=include_deleted):
            area = cast(Area, model)
            if area.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if area.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if parent_id and area.parent_area_id != parent_id:
                continue
            result.append(project_graph.area_summary(area, tasks))
        return result

    def area_tasks(self, area_id, include_archived=False) -> list[dict[str, Any]]:
        return self.tasks.task_list(area=area_id, include_archived=include_archived)

    # ----------------------------------------------------------------- 更新

    def area_update(
        self,
        area_id,
        name=None,
        description=None,
        parent_area_id=UNSET,
        path_patterns=UNSET,
        expected_rev=None,
    ) -> dict[str, Any]:
        area = self.ctx.load("area", self.ctx.require_area_id(area_id))
        base = self.ctx.require_expected_rev("area", area, expected_rev)
        fields: list[str] = []
        if name is not None:
            area.name = require_title(name, "area name")
            fields.append("name")
        if description is not None:
            area.description = optional_text(description, "description")
            fields.append("description")
        if parent_area_id is not UNSET:
            new_parent = self.ctx.area_id(parent_area_id)
            if new_parent == area.id:
                raise InvalidArgument("an area cannot be its own parent")
            self.ctx.validate_area_parent_chain(area.id, new_parent)
            area.parent_area_id = new_parent
            fields.append("parent_area_id")
        if path_patterns is not UNSET:
            area.path_patterns = normalize_path_patterns(path_patterns)
            fields.append("path_patterns")
        if not fields:
            return project_graph.area_summary(area, self.ctx.tasks_by_id())
        self.ctx.save(area, base, "area.updated", {"fields": fields})
        return project_graph.area_summary(area, self.ctx.tasks_by_id())

    def area_set_parent(self, area_id, parent_area_id, expected_rev=None) -> dict[str, Any]:
        area = self.ctx.load("area", self.ctx.require_area_id(area_id))
        base = self.ctx.require_expected_rev("area", area, expected_rev)
        new_parent = self.ctx.area_id(parent_area_id)
        if new_parent == area.id:
            raise InvalidArgument("an area cannot be its own parent")
        self.ctx.validate_area_parent_chain(area.id, new_parent)
        if area.parent_area_id == new_parent:
            return project_graph.area_summary(area, self.ctx.tasks_by_id())
        old = area.parent_area_id
        area.parent_area_id = new_parent
        self.ctx.save(
            area,
            base,
            "area.updated",
            {"fields": ["parent_area_id"], "from": old, "to": new_parent},
        )
        return project_graph.area_summary(area, self.ctx.tasks_by_id())

    def area_match_path(self, path) -> list[dict[str, Any]]:
        """哪些 Area 的 `path_patterns` 命中这个 project-relative 路径。

        只读推导（Git Adapter 用）：**不修改任何 Area，也不回写 `Task.area_id`**。
        没填 `path_patterns` 的 Area 永远不参与匹配。
        """
        normalized = str(path or "").replace("\\", "/").strip()
        if not normalized:
            raise InvalidArgument("path must not be empty")
        hits = []
        for model in self.ctx.store.list_models("area"):
            area = cast(Area, model)
            if area.lifecycle != Lifecycle.ACTIVE or not area.path_patterns:
                continue
            if match_any(area.path_patterns, normalized):
                hits.append(
                    {"id": area.id, "name": area.name, "patterns": list(area.path_patterns)}
                )
        return hits

    # ------------------------------------------------------------- 生命周期

    def area_archive(self, area_id, expected_rev=None) -> dict[str, Any]:
        return self.ctx.set_lifecycle(
            "area", self.ctx.require_area_id(area_id), Lifecycle.ARCHIVED, "object.archived", expected_rev
        )

    def area_restore(self, area_id, expected_rev=None) -> dict[str, Any]:
        return self.ctx.set_lifecycle(
            "area", self.ctx.require_area_id(area_id), Lifecycle.ACTIVE, "object.restored", expected_rev
        )

    def area_history(self, area_id) -> dict[str, Any]:
        area = self.ctx.load("area", self.ctx.require_area_id(area_id))
        return self.ctx.history("area", area.id)
