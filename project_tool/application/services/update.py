"""update.* 方法。"""

from __future__ import annotations

from typing import Any, cast

from project_tool.application.context import UNSET, ServiceContext, as_list
from project_tool.domain.enums import Lifecycle
from project_tool.domain.errors import InvalidArgument
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.domain.update import Update
from project_tool.domain.validation import optional_text, optional_title


class UpdateService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    def update_create(
        self,
        summary=None,
        body="",
        task_ids=None,
        milestone_id=None,
        blockers=None,
        next_steps=None,
    ) -> dict[str, Any]:
        body = optional_text(body, "body")
        summary_text = str(summary or "").strip()
        if not summary_text:
            lines = [line for line in body.strip().splitlines() if line.strip()]
            if not lines:
                raise InvalidArgument("update needs a summary or non-empty body")
            summary_text = lines[0].strip()
        summary_text = optional_title(summary_text, "summary")
        now = now_local()
        update = Update(
            id=new_id("update"),
            project_id=self.ctx.opened.project.id,
            summary=summary_text,
            body=body,
            task_ids=self.ctx.refs("task", task_ids),
            milestone_id=self.ctx.assert_milestone_open(milestone_id),
            blockers=[str(item) for item in as_list(blockers)],
            next_steps=[str(item) for item in as_list(next_steps)],
            created_at=now,
            updated_at=now,
        )
        return self.ctx.save(
            update, None, "update.created", {"summary": update.summary}, is_create=True
        )

    def update_get(self, update_id) -> dict[str, Any]:
        return self.ctx.load("update", update_id).model_dump(mode="json")

    def update_list(
        self,
        task=None,
        milestone=None,
        include_archived=False,
        include_deleted=False,
    ) -> list[dict[str, Any]]:
        task_id = self.ctx.resolve_ref("task", task, allow_deleted=True) if task else None
        milestone_id = (
            self.ctx.ref_or_none("milestone", milestone, allow_deleted=True) if milestone else None
        )
        result = []
        for model in self.ctx.store.list_models("update", include_deleted=include_deleted):
            update = cast(Update, model)
            if update.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if update.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if task_id and task_id not in update.task_ids:
                continue
            if milestone_id and update.milestone_id != milestone_id:
                continue
            result.append(update.model_dump(mode="json"))
        return result

    def update_update(
        self,
        update_id,
        summary=None,
        body=None,
        task_ids=None,
        milestone_id=UNSET,
        blockers=None,
        next_steps=None,
    ) -> dict[str, Any]:
        update = self.ctx.load("update", update_id)
        fields: list[str] = []
        if summary is not None:
            update.summary = optional_title(summary, "summary")
            fields.append("summary")
        if body is not None:
            update.body = optional_text(body, "body")
            fields.append("body")
        if task_ids is not None:
            update.task_ids = self.ctx.refs("task", task_ids)
            fields.append("task_ids")
        if milestone_id is not UNSET:
            update.milestone_id = self.ctx.assert_milestone_open(
                milestone_id, current=update.milestone_id
            )
            fields.append("milestone_id")
        if blockers is not None:
            update.blockers = [str(item) for item in as_list(blockers)]
            fields.append("blockers")
        if next_steps is not None:
            update.next_steps = [str(item) for item in as_list(next_steps)]
            fields.append("next_steps")
        if not fields:
            return update.model_dump(mode="json")
        return self.ctx.save(update, update.rev, "update.updated", {"fields": fields})

    def update_archive(self, update_id) -> dict[str, Any]:
        return self.ctx.set_lifecycle("update", update_id, Lifecycle.ARCHIVED, "object.archived")

    def update_history(self, update_id) -> dict[str, Any]:
        return self.ctx.history("update", update_id)
