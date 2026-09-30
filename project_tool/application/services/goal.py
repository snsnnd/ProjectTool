"""goal.* 方法。"""

from __future__ import annotations

from typing import Any, cast

from project_tool.application.context import UNSET, ServiceContext, as_list, enum_value
from project_tool.domain.enums import GoalStatus, Lifecycle
from project_tool.domain.errors import InvalidArgument
from project_tool.domain.goal import Goal
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import optional_text, optional_title, require_title


class GoalService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    def goal_create(
        self,
        title,
        description="",
        parent_goal_id=None,
        success_criteria=None,
        due_at=None,
        status="active",
    ) -> dict[str, Any]:
        title_text = require_title(title, "goal title")
        parent = self.ctx.ref_or_none("goal", parent_goal_id)
        now = now_local()
        goal = Goal(
            id=new_id("goal"),
            project_id=self.ctx.opened.project.id,
            title=title_text,
            description=optional_text(description, "description"),
            status=enum_value(GoalStatus, status, "status"),
            parent_goal_id=parent,
            success_criteria=[str(item) for item in as_list(success_criteria)],
            due_at=self.ctx.dt(due_at),
            created_at=now,
            updated_at=now,
        )
        return self.ctx.save(goal, None, "goal.created", {"title": goal.title}, is_create=True)

    def goal_get(self, goal_id) -> dict[str, Any]:
        return self.ctx.load("goal", goal_id).model_dump(mode="json")

    def goal_list(self, status=None, include_archived=False, include_deleted=False) -> list[dict[str, Any]]:
        wanted = {enum_value(GoalStatus, item, "status").value for item in as_list(status)}
        result = []
        for model in self.ctx.store.list_models("goal", include_deleted=include_deleted):
            goal = cast(Goal, model)
            if goal.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if goal.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if wanted and goal.status.value not in wanted:
                continue
            result.append(goal.model_dump(mode="json"))
        return result

    def goal_update(
        self,
        goal_id,
        title=None,
        description=None,
        success_criteria=None,
        due_at=UNSET,
        parent_goal_id=UNSET,
        status=None,
        expected_rev=None,
    ) -> dict[str, Any]:
        goal = self.ctx.load("goal", goal_id)
        base = self.ctx.require_expected_rev("goal", goal, expected_rev)
        fields: list[str] = []
        if title is not None:
            goal.title = optional_title(title)
            fields.append("title")
        if description is not None:
            goal.description = optional_text(description, "description")
            fields.append("description")
        if success_criteria is not None:
            goal.success_criteria = [str(item) for item in as_list(success_criteria)]
            fields.append("success_criteria")
        if due_at is not UNSET:
            goal.due_at = self.ctx.dt(due_at)
            fields.append("due_at")
        if parent_goal_id is not UNSET:
            new_parent = self.ctx.ref_or_none("goal", parent_goal_id)
            if new_parent == goal.id:
                raise InvalidArgument("a goal cannot be its own parent")
            self.ctx.validate_goal_parent_chain(goal.id, new_parent)
            goal.parent_goal_id = new_parent
            fields.append("parent_goal_id")
        if status is not None:
            goal.status = enum_value(GoalStatus, status, "status")
            fields.append("status")
        if not fields:
            return goal.model_dump(mode="json")
        return self.ctx.save(goal, base, "goal.updated", {"fields": fields})

    def goal_set_status(self, goal_id, status, expected_rev=None) -> dict[str, Any]:
        goal = self.ctx.load("goal", goal_id)
        base = self.ctx.require_expected_rev("goal", goal, expected_rev)
        new_status = enum_value(GoalStatus, status, "status")
        if goal.status == new_status:
            return goal.model_dump(mode="json")
        old = goal.status
        goal.status = new_status
        return self.ctx.save(
            goal,
            base,
            "goal.status_changed",
            {"from": old.value, "to": new_status.value},
        )

    def goal_archive(self, goal_id, expected_rev=None) -> dict[str, Any]:
        return self.ctx.set_lifecycle(
            "goal", goal_id, Lifecycle.ARCHIVED, "object.archived", expected_rev
        )

    def goal_restore(self, goal_id, expected_rev=None) -> dict[str, Any]:
        return self.ctx.set_lifecycle(
            "goal", goal_id, Lifecycle.ACTIVE, "object.restored", expected_rev
        )
