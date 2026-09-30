"""decision.* 方法：一等对象 + supersede 链环检测。"""

from __future__ import annotations

from typing import Any, cast

from pydantic import ValidationError

from project_tool.application.context import ServiceContext, as_list, enum_value
from project_tool.domain.decision import Alternative, Decision
from project_tool.domain.enums import DecisionStatus, Lifecycle
from project_tool.domain.errors import InvalidArgument
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import optional_text, optional_title, require_title


class DecisionService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    def decision_create(
        self,
        title,
        context="",
        decision="",
        rationale="",
        alternatives=None,
        consequences=None,
        related_task_ids=None,
        status="draft",
    ) -> dict[str, Any]:
        title_text = require_title(title, "decision title")
        now = now_local()
        record = Decision(
            id=new_id("decision"),
            project_id=self.ctx.opened.project.id,
            title=title_text,
            status=enum_value(DecisionStatus, status, "status"),
            context=optional_text(context, "context"),
            decision=optional_text(decision, "decision"),
            rationale=optional_text(rationale, "rationale"),
            alternatives=self._alternatives(alternatives),
            consequences=[str(item) for item in as_list(consequences)],
            related_task_ids=self.ctx.refs("task", related_task_ids),
            created_at=now,
            updated_at=now,
        )
        return self.ctx.save(
            record, None, "decision.created", {"title": record.title}, is_create=True
        )

    def decision_get(self, decision_id) -> dict[str, Any]:
        return self.ctx.load("decision", decision_id).model_dump(mode="json")

    def decision_list(
        self,
        status=None,
        include_archived=False,
        include_deleted=False,
    ) -> list[dict[str, Any]]:
        wanted = {enum_value(DecisionStatus, item, "status").value for item in as_list(status)}
        result = []
        for model in self.ctx.store.list_models("decision", include_deleted=include_deleted):
            decision = cast(Decision, model)
            if decision.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if decision.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if wanted and decision.status.value not in wanted:
                continue
            result.append(decision.model_dump(mode="json"))
        return result

    def decision_update(
        self,
        decision_id,
        title=None,
        context=None,
        decision=None,
        rationale=None,
        alternatives=None,
        consequences=None,
        related_task_ids=None,
        expected_rev=None,
    ) -> dict[str, Any]:
        record = self.ctx.load("decision", decision_id)
        base = self.ctx.require_expected_rev("decision", record, expected_rev)
        fields: list[str] = []
        if title is not None:
            record.title = optional_title(title)
            fields.append("title")
        if context is not None:
            record.context = optional_text(context, "context")
            fields.append("context")
        if decision is not None:
            record.decision = optional_text(decision, "decision")
            fields.append("decision")
        if rationale is not None:
            record.rationale = optional_text(rationale, "rationale")
            fields.append("rationale")
        if alternatives is not None:
            record.alternatives = self._alternatives(alternatives)
            fields.append("alternatives")
        if consequences is not None:
            record.consequences = [str(item) for item in as_list(consequences)]
            fields.append("consequences")
        if related_task_ids is not None:
            record.related_task_ids = self.ctx.refs("task", related_task_ids)
            fields.append("related_task_ids")
        if not fields:
            return record.model_dump(mode="json")
        return self.ctx.save(record, base, "decision.updated", {"fields": fields})

    def decision_accept(self, decision_id, expected_rev=None) -> dict[str, Any]:
        return self._set_status(decision_id, DecisionStatus.ACCEPTED, expected_rev)

    def decision_reject(self, decision_id, expected_rev=None) -> dict[str, Any]:
        return self._set_status(decision_id, DecisionStatus.REJECTED, expected_rev)

    def decision_supersede(self, old_id, new_id, expected_rev=None) -> dict[str, Any]:
        old = self.ctx.load("decision", old_id)
        old_base = self.ctx.require_expected_rev("decision", old, expected_rev)
        new = self.ctx.load("decision", new_id)
        if old.id == new.id:
            raise InvalidArgument("a decision cannot supersede itself")
        self.ctx.validate_decision_supersede(old.id, new.id)
        new_base = new.rev
        old_status = old.status
        old.status = DecisionStatus.SUPERSEDED
        new.supersedes_id = old.id
        old_record = self.ctx.prepare(old, is_create=False)
        new_record = self.ctx.prepare(new, is_create=False)
        from project_tool.storage import EventSpec, ObjectChange

        events = [
            EventSpec(
                "decision.status_changed",
                "decision",
                old.id,
                {"from": old_status.value, "to": DecisionStatus.SUPERSEDED.value},
                old_base,
                old_record["rev"],
            ),
            EventSpec(
                "decision.updated",
                "decision",
                new.id,
                {"fields": ["supersedes_id"]},
                new_base,
                new_record["rev"],
            ),
        ]
        self.ctx.commit(
            [
                ObjectChange("decision", old.id, old_record, old_base),
                ObjectChange("decision", new.id, new_record, new_base),
            ],
            events,
        )
        return {"superseded": old_record, "superseded_by": new_record}

    def decision_history(self, decision_id) -> dict[str, Any]:
        return self.ctx.history("decision", decision_id)

    def _set_status(
        self, decision_id, status: DecisionStatus, expected_rev: str | None = None
    ) -> dict[str, Any]:
        record = self.ctx.load("decision", decision_id)
        base = self.ctx.require_expected_rev("decision", record, expected_rev)
        if record.status == status:
            return record.model_dump(mode="json")
        old = record.status
        record.status = status
        return self.ctx.save(
            record,
            base,
            "decision.status_changed",
            {"from": old.value, "to": status.value},
        )

    @staticmethod
    def _alternatives(value) -> list[Alternative]:
        result: list[Alternative] = []
        for item in as_list(value):
            try:
                if isinstance(item, str):
                    result.append(Alternative(name=item))
                elif isinstance(item, dict):
                    result.append(Alternative.model_validate(item))
                else:
                    raise InvalidArgument("alternatives must be strings or objects")
            except ValidationError as exc:
                raise InvalidArgument(f"invalid alternative {item!r}: {exc}") from None
        return result
