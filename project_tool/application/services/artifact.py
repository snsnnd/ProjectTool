"""artifact.* 方法：工程产物的引用（V1-A）。

绝对边界：
- 只存引用（kind + locator），不做 blob / CAS / snapshot / upload。
- **不修改任何被引用的工程文件**：`artifact.remove` 只软删除 Artifact 对象。
  本模块唯一的文件系统访问是 `verify_locator` 的存在性检查（只读）。
"""

from __future__ import annotations

from typing import Any, cast

from project_tool.application.context import UNSET, ServiceContext, enum_value
from project_tool.domain.artifact import RELATION_FIELDS, Artifact
from project_tool.domain.artifact_locator import check_locator, verify_locator
from project_tool.domain.enums import ArtifactKind, Lifecycle
from project_tool.domain.errors import InvalidArgument
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.domain.validation import optional_text, require_title


class ArtifactService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx
        self.gits: Any = None  # 由 ProjectService 组装时注入（避免循环依赖）

    # ----------------------------------------------------------------- 创建

    def artifact_create(
        self,
        kind,
        locator,
        name=None,
        description="",
        task=None,
        decision=None,
        milestone=None,
        goal=None,
        metadata=None,
    ) -> dict[str, Any]:
        artifact_kind = enum_value(ArtifactKind, kind, "kind")
        checked_locator = check_locator(artifact_kind, locator)
        display_name = require_title(name or checked_locator, "artifact name")
        now = now_local()
        artifact = Artifact(
            id=new_id("artifact"),
            project_id=self.ctx.opened.project.id,
            name=display_name,
            description=optional_text(description, "description"),
            kind=artifact_kind,
            locator=checked_locator,
            related_task_ids=self.ctx.refs("task", _as_list(task)),
            related_decision_ids=self.ctx.refs("decision", _as_list(decision)),
            related_milestone_ids=self.ctx.refs("milestone", _as_list(milestone)),
            related_goal_ids=self.ctx.refs("goal", _as_list(goal)),
            metadata=self._metadata(metadata),
            created_at=now,
            updated_at=now,
        )
        return self.ctx.save(
            artifact,
            None,
            "artifact.created",
            {"name": artifact.name, "kind": artifact_kind.value, "locator": checked_locator},
            is_create=True,
        )

    # ----------------------------------------------------------------- 查询

    def artifact_get(self, artifact_id) -> dict[str, Any]:
        return self._load(artifact_id).model_dump(mode="json")

    def artifact_list(
        self,
        kind=None,
        task=None,
        decision=None,
        milestone=None,
        goal=None,
        include_archived=False,
        include_deleted=False,
    ) -> list[dict[str, Any]]:
        wanted_kind = {enum_value(ArtifactKind, item, "kind").value for item in _as_list(kind)}
        task_id = self.ctx.ref_or_none("task", task, allow_deleted=True) if task else None
        decision_id = (
            self.ctx.ref_or_none("decision", decision, allow_deleted=True) if decision else None
        )
        milestone_id = (
            self.ctx.ref_or_none("milestone", milestone, allow_deleted=True) if milestone else None
        )
        goal_id = self.ctx.ref_or_none("goal", goal, allow_deleted=True) if goal else None
        result = []
        for model in self.ctx.store.list_models("artifact", include_deleted=include_deleted):
            artifact = cast(Artifact, model)
            if artifact.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if artifact.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if wanted_kind and artifact.kind.value not in wanted_kind:
                continue
            if task_id and task_id not in artifact.related_task_ids:
                continue
            if decision_id and decision_id not in artifact.related_decision_ids:
                continue
            if milestone_id and milestone_id not in artifact.related_milestone_ids:
                continue
            if goal_id and goal_id not in artifact.related_goal_ids:
                continue
            result.append(artifact.model_dump(mode="json"))
        return result

    def artifact_history(self, artifact_id) -> dict[str, Any]:
        return self.ctx.history("artifact", self._load(artifact_id).id)

    # ----------------------------------------------------------------- 更新

    def artifact_update(
        self,
        artifact_id,
        name=None,
        description=None,
        kind=None,
        locator=UNSET,
        metadata=None,
        expected_rev=None,
    ) -> dict[str, Any]:
        artifact = self._load(artifact_id)
        base = self.ctx.require_expected_rev("artifact", artifact, expected_rev)
        fields: list[str] = []
        new_kind = artifact.kind
        new_locator = artifact.locator
        if kind is not None:
            new_kind = enum_value(ArtifactKind, kind, "kind")
            fields.append("kind")
        if locator is not UNSET:
            new_locator = check_locator(new_kind, locator)
            fields.append("locator")
        elif kind is not None:
            # 换了 kind 就必须重新校验既有 locator，避免留下越界的引用。
            new_locator = check_locator(new_kind, artifact.locator)
        if name is not None:
            artifact.name = require_title(name, "artifact name")
            fields.append("name")
        if description is not None:
            artifact.description = optional_text(description, "description")
            fields.append("description")
        if metadata is not None:
            artifact.metadata = self._metadata(metadata)
            fields.append("metadata")
        if not fields:
            return artifact.model_dump(mode="json")
        artifact.kind = new_kind
        artifact.locator = new_locator
        self.ctx.save(artifact, base, "artifact.updated", {"fields": fields})
        return artifact.model_dump(mode="json")

    def artifact_remove(self, artifact_id, expected_rev=None) -> dict[str, Any]:
        """只移除 Project Tool 的引用对象；**绝不删除被引用的工程文件**。"""
        return self.ctx.set_lifecycle(
            "artifact",
            artifact_id,
            Lifecycle.DELETED,
            "artifact.removed",
            expected_rev,
        )

    # ------------------------------------------------------------- 关系绑定

    def artifact_attach(
        self,
        artifact_id,
        task=None,
        decision=None,
        milestone=None,
        goal=None,
        area=None,
        expected_rev=None,
    ) -> dict[str, Any]:
        return self._bind(
            artifact_id, task, decision, milestone, goal, area, expected_rev, attach=True
        )

    def artifact_detach(
        self,
        artifact_id,
        task=None,
        decision=None,
        milestone=None,
        goal=None,
        area=None,
        expected_rev=None,
    ) -> dict[str, Any]:
        return self._bind(
            artifact_id, task, decision, milestone, goal, area, expected_rev, attach=False
        )

    def _bind(
        self,
        artifact_id,
        task,
        decision,
        milestone,
        goal,
        area,
        expected_rev,
        attach: bool,
    ) -> dict[str, Any]:
        artifact = self._load(artifact_id)
        base = self.ctx.require_expected_rev("artifact", artifact, expected_rev)
        targets = {
            "task": (task, "task"),
            "decision": (decision, "decision"),
            "milestone": (milestone, "milestone"),
            "goal": (goal, "goal"),
            # area 用 area_id() 解析（它按 name 或 id 都认，并做循环校验），
            # 不用通用 resolve_ref——那会把 "core" 当成非法 id。
            "area": (area, "area"),
        }
        if not any(raw for raw, _ in targets.values()):
            raise InvalidArgument(
                "artifact.attach/detach needs at least one of: "
                "task, decision, milestone, goal, area"
            )
        changes: list[dict[str, Any]] = []
        for label, (raw, obj_type) in targets.items():
            if not raw:
                continue
            for ref in _as_list(raw):
                resolved = (
                    self.ctx.area_id(ref)
                    if obj_type == "area"
                    else self.ctx.resolve_ref(obj_type, ref)
                )
                field = _field_for(label)
                current = list(getattr(artifact, field))
                if attach and resolved in current:
                    continue
                if not attach and resolved not in current:
                    continue
                current = sorted(set(current) | {resolved}) if attach else [
                    item for item in current if item != resolved
                ]
                setattr(artifact, field, current)
                changes.append({"relation": label, "id": resolved, "attached": attach})
        if not changes:
            return artifact.model_dump(mode="json")
        self.ctx.save(
            artifact,
            base,
            "artifact.attached" if attach else "artifact.detached",
            {"relations": changes},
        )
        return artifact.model_dump(mode="json")

    # ----------------------------------------------------------------- 验证

    def artifact_verify(self, artifact_id=None) -> Any:
        """纯查询：**不产生事件**，不修改任何文件。"""
        if artifact_id is None or artifact_id == "":
            artifacts = self.artifact_list(include_archived=True)
        else:
            artifacts = [self.artifact_get(artifact_id)]
        return [self._verify_one(record) for record in artifacts]

    def _verify_one(self, record: dict[str, Any]) -> dict[str, Any]:
        kind = ArtifactKind(record["kind"])
        # git kind 由 Git Adapter 真正解析（V1-B 之前这里只校验格式）
        if self.gits is not None:
            delegated = self.gits.verify_locator(kind.value, record["locator"])
            if delegated is not None:
                return {
                    "id": record["id"],
                    "name": record["name"],
                    "kind": record["kind"],
                    "locator": record["locator"],
                    **delegated,
                }
        try:
            result = verify_locator(kind, record["locator"], self.ctx.paths.root)
        except InvalidArgument as exc:
            return {
                "id": record["id"],
                "name": record["name"],
                "kind": record["kind"],
                "locator": record["locator"],
                "status": "rejected",
                "exists": None,
                "path": None,
                "detail": exc.message,
            }
        return {
            "id": record["id"],
            "name": record["name"],
            "kind": record["kind"],
            "locator": record["locator"],
            **result,
        }

    # ----------------------------------------------------------------- 内部

    def _load(self, ref) -> Artifact:
        return cast(Artifact, self.ctx.load("artifact", ref))

    @staticmethod
    def _metadata(value) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise InvalidArgument("metadata must be an object")
        return {str(key): item for key, item in value.items()}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _field_for(label: str) -> str:
    for relation, field in RELATION_FIELDS:
        if relation == label:
            return field
    raise InvalidArgument(f"unknown artifact relation: {label!r}")
