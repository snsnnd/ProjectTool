"""milestone.* 方法。"""

from __future__ import annotations

from typing import Any, cast

from project_tool.application.context import UNSET, ServiceContext, as_list, enum_value
from project_tool.domain.enums import Lifecycle, MilestoneStatus
from project_tool.domain.ids import new_id
from project_tool.domain.milestone import Milestone
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import optional_text, optional_title, require_title
from project_tool.graph import project_graph


class MilestoneService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    def milestone_create(
        self,
        title,
        description="",
        goal_ids=None,
        due_at=None,
        status="planned",
    ) -> dict[str, Any]:
        title_text = require_title(title, "milestone title")
        now = now_local()
        milestone = Milestone(
            id=new_id("milestone"),
            project_id=self.ctx.opened.project.id,
            title=title_text,
            description=optional_text(description, "description"),
            status=enum_value(MilestoneStatus, status, "status"),
            goal_ids=self.ctx.refs("goal", goal_ids),
            due_at=self.ctx.dt(due_at),
            created_at=now,
            updated_at=now,
        )
        return self.ctx.save(
            milestone, None, "milestone.created", {"title": milestone.title}, is_create=True
        )

    def milestone_get(self, milestone_id) -> dict[str, Any]:
        milestone = self.ctx.load("milestone", milestone_id)
        return project_graph.milestone_summary(milestone, self.ctx.tasks_by_id())

    def milestone_list(
        self,
        status=None,
        include_archived=False,
        include_deleted=False,
    ) -> list[dict[str, Any]]:
        wanted = {enum_value(MilestoneStatus, item, "status").value for item in as_list(status)}
        result = []
        for model in self.ctx.store.list_models("milestone", include_deleted=include_deleted):
            milestone = cast(Milestone, model)
            if milestone.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if milestone.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if wanted and milestone.status.value not in wanted:
                continue
            result.append(project_graph.milestone_summary(milestone, self.ctx.tasks_by_id()))
        return result

    def milestone_update(
        self,
        milestone_id,
        title=None,
        description=None,
        goal_ids=None,
        due_at=UNSET,
        status=None,
        expected_rev=None,
    ) -> dict[str, Any]:
        milestone = self.ctx.load("milestone", milestone_id)
        base = self.ctx.require_expected_rev("milestone", milestone, expected_rev)
        fields: list[str] = []
        if title is not None:
            milestone.title = optional_title(title)
            fields.append("title")
        if description is not None:
            milestone.description = optional_text(description, "description")
            fields.append("description")
        if goal_ids is not None:
            milestone.goal_ids = self.ctx.refs("goal", goal_ids)
            fields.append("goal_ids")
        if due_at is not UNSET:
            milestone.due_at = self.ctx.dt(due_at)
            fields.append("due_at")
        if status is not None:
            milestone.status = enum_value(MilestoneStatus, status, "status")
            fields.append("status")
        if not fields:
            return milestone.model_dump(mode="json")
        return self.ctx.save(milestone, base, "milestone.updated", {"fields": fields})

    def milestone_activate(self, milestone_id, expected_rev=None) -> dict[str, Any]:
        return self._set_status(
            milestone_id, MilestoneStatus.ACTIVE, "milestone.activated", expected_rev
        )

    def milestone_close(self, milestone_id, expected_rev=None) -> dict[str, Any]:
        return self._set_status(
            milestone_id, MilestoneStatus.CLOSED, "milestone.closed", expected_rev
        )

    def milestone_cancel(self, milestone_id, expected_rev=None) -> dict[str, Any]:
        return self._set_status(
            milestone_id, MilestoneStatus.CANCELLED, "milestone.cancelled", expected_rev
        )

    def milestone_progress(self, milestone_id) -> dict[str, Any]:
        milestone = self.ctx.load("milestone", milestone_id)
        return project_graph.milestone_summary(milestone, self.ctx.tasks_by_id())

    def _set_status(
        self,
        milestone_id,
        status: MilestoneStatus,
        event_type: str,
        expected_rev: str | None = None,
    ) -> dict[str, Any]:
        milestone = self.ctx.load("milestone", milestone_id)
        base = self.ctx.require_expected_rev("milestone", milestone, expected_rev)
        if milestone.status == status:
            return milestone.model_dump(mode="json")
        old = milestone.status
        milestone.status = status
        return self.ctx.save(
            milestone,
            base,
            event_type,
            {"from": old.value, "to": status.value},
        )
