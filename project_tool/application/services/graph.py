"""graph.* 方法。"""

from __future__ import annotations

from typing import Any, cast

from project_tool.application.context import ServiceContext
from project_tool.domain.goal import Goal
from project_tool.domain.link import Link
from project_tool.domain.milestone import Milestone
from project_tool.graph import project_graph


class GraphService:
    def __init__(self, ctx: ServiceContext, link_service):
        self.ctx = ctx
        self.links = link_service

    def graph_project(self) -> dict[str, Any]:
        return project_graph.build_project_tree(
            self.ctx.opened.project,
            cast(list[Goal], self.ctx.store.list_models("goal")),
            cast(list[Milestone], self.ctx.store.list_models("milestone")),
            self.ctx.tasks_by_id(),
            cast(list[Link], self.ctx.store.list_models("link")),
        )

    def graph_tasks(self, milestone_id=None, include_archived=False) -> dict[str, Any]:
        return project_graph.build_task_graph(
            self.ctx.tasks_by_id(),
            self.ctx.ref_or_none("milestone", milestone_id, allow_deleted=True)
            if milestone_id
            else None,
            bool(include_archived),
        )

    def graph_dependencies(self, task_id=None, depth=5) -> dict[str, Any]:
        resolved = (
            self.ctx.resolve_ref("task", task_id, allow_deleted=True) if task_id else None
        )
        return project_graph.build_dependency_graph(
            self.ctx.tasks_by_id(), resolved, int(depth)
        )

    def graph_links(self) -> list[dict[str, Any]]:
        return [
            self.links.link_resolve(link.id)
            for link in self.ctx.store.list_models("link")
        ]
