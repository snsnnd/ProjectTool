"""task.* 方法：创建、查询、状态机、分配、依赖、标签、层级。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from project_tool.application.context import (
    UNSET,
    ServiceContext,
    as_list,
    enum_value,
    normalize_labels,
)
from project_tool.domain.artifact import Artifact
from project_tool.domain.enums import DependencyRelation, Lifecycle, Priority, TaskStatus
from project_tool.domain.errors import Claimed, DependencyCycle, InvalidArgument, NotFound
from project_tool.domain.ids import new_id
from project_tool.domain.interfaces import parse_front_matter
from project_tool.domain.task import Claim, Dependency, Task, claim_view
from project_tool.domain.timeutil import now_local
from project_tool.domain.update import Update
from project_tool.domain.validation import (
    optional_text,
    optional_title,
    require_label,
    require_title,
)
from project_tool.graph import dependency as dependency_graph
from project_tool.graph import project_graph

#: 认领 TTL 上限（分钟）。上限存在是为了防止有人 claim 一个 task 然后
#: 把它占住一整年 —— 那不是协调，是软锁。
MAX_CLAIM_MINUTES = 8 * 60


class TaskService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    # ----------------------------------------------------------------- 创建

    def task_create(
        self,
        title,
        description="",
        priority="normal",
        weight=1,
        milestone_id=None,
        area_id=None,
        parent_task_id=None,
        owner_ids=None,
        labels=None,
        acceptance_criteria=None,
        due_at=None,
        status="inbox",
    ) -> dict[str, Any]:
        title_text = require_title(title, "task title")
        weight_value = self._weight(weight)
        now = now_local()
        task = Task(
            id=new_id("task"),
            project_id=self.ctx.opened.project.id,
            title=title_text,
            description=optional_text(description, "description"),
            status=enum_value(TaskStatus, status, "status"),
            priority=enum_value(Priority, priority, "priority"),
            weight=weight_value,
            milestone_id=self.ctx.assert_milestone_open(milestone_id),
            area_id=self.ctx.area_id(area_id),
            parent_task_id=self.ctx.ref_or_none("task", parent_task_id),
            owner_ids=self.ctx.owner_ids(owner_ids),
            labels=[require_label(item) for item in normalize_labels(labels)],
            acceptance_criteria=[str(item) for item in as_list(acceptance_criteria)],
            due_at=self.ctx.dt(due_at),
            created_at=now,
            updated_at=now,
        )
        return self.ctx.save(task, None, "task.created", {"title": task.title}, is_create=True)

    # ----------------------------------------------------------------- 查询

    def task_get(self, task_id) -> dict[str, Any]:
        return self.ctx.task_view(self.ctx.load("task", task_id))

    def task_list(
        self,
        status=None,
        owner=None,
        label=None,
        milestone=None,
        area=None,
        priority=None,
        parent=None,
        include_archived=False,
        include_deleted=False,
        unclaimed: bool = False,
        claimed_by=None,
    ) -> list[dict[str, Any]]:
        """列任务。

        `unclaimed=True` 只返回**没有有效认领**的任务（过期的不算占用）——
        这是「给我一件没人做的事」的查询，agent 拿它当待办入口。
        `claimed_by` 配合 `unclaimed` 一起用没有意义，单独传则只看某人的认领。
        """
        wanted_status = {enum_value(TaskStatus, item, "status").value for item in as_list(status)}
        wanted_priority = {enum_value(Priority, item, "priority").value for item in as_list(priority)}
        owner_id = self.ctx.member_id(owner) if owner else None
        milestone_id = self.ctx.ref_or_none("milestone", milestone, allow_deleted=True) if milestone else None
        area_id = self.ctx.area_id(area) if area else None
        parent_id = self.ctx.ref_or_none("task", parent, allow_deleted=True) if parent else None
        tasks = self.ctx.tasks_by_id(include_deleted=include_deleted)
        result = []
        for task in sorted(tasks.values(), key=lambda item: item.id):
            if task.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if task.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if wanted_status and task.status.value not in wanted_status:
                continue
            if wanted_priority and task.priority.value not in wanted_priority:
                continue
            if owner_id and owner_id not in task.owner_ids:
                continue
            if milestone_id and task.milestone_id != milestone_id:
                continue
            if area_id and task.area_id != area_id:
                continue
            if parent_id and task.parent_task_id != parent_id:
                continue
            # 认领过滤放在最后：它是**派生**判定（比较时间戳），
            # 过期的不算占用，所以不需要任何清理
            active_claim = claim_view(task.claim)
            if unclaimed and active_claim is not None:
                continue
            if claimed_by and (active_claim or {}).get("member_id") != self.ctx.member_id(
                claimed_by
            ):
                continue
            if label and label not in task.labels:
                continue
            result.append(project_graph.task_summary(task, tasks))
        return result

    def task_related_updates(self, task_id) -> list[dict[str, Any]]:
        full_id = self.ctx.resolve_ref("task", task_id, allow_deleted=True)
        return [
            cast(Update, update).model_dump(mode="json")
            for update in self.ctx.store.list_models("update")
            if full_id in cast(Update, update).task_ids
        ]

    def task_related_artifacts(self, task_id, include_deleted=False) -> list[dict[str, Any]]:
        """Task 关联的 Artifact（派生读：file scan `objects/artifacts/`，不建索引）。"""
        full_id = self.ctx.resolve_ref("task", task_id, allow_deleted=True)
        rows = []
        for model in self.ctx.store.list_models("artifact", include_deleted=include_deleted):
            artifact = cast(Artifact, model)
            if artifact.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if full_id in artifact.related_task_ids:
                rows.append(artifact.model_dump(mode="json"))
        return rows

    def task_history(self, task_id) -> dict[str, Any]:
        return self.ctx.history("task", task_id)

    # ----------------------------------------------------------------- 更新

    def task_update(
        self,
        task_id,
        title=None,
        description=None,
        priority=None,
        weight=None,
        milestone_id=UNSET,
        area_id=UNSET,
        parent_task_id=UNSET,
        owner_ids=None,
        labels=None,
        acceptance_criteria=None,
        due_at=UNSET,
        expected_rev=None,
    ) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        fields: list[str] = []
        if title is not None:
            task.title = optional_title(title)
            fields.append("title")
        if description is not None:
            task.description = optional_text(description, "description")
            fields.append("description")
        if priority is not None:
            task.priority = enum_value(Priority, priority, "priority")
            fields.append("priority")
        if weight is not None:
            task.weight = self._weight(weight)
            fields.append("weight")
        if milestone_id is not UNSET:
            task.milestone_id = self.ctx.assert_milestone_open(
                milestone_id, current=task.milestone_id
            )
            fields.append("milestone_id")
        if area_id is not UNSET:
            task.area_id = self.ctx.area_id(area_id)
            fields.append("area_id")
        if parent_task_id is not UNSET:
            new_parent = self.ctx.ref_or_none("task", parent_task_id)
            if new_parent == task.id:
                raise InvalidArgument("a task cannot be its own parent")
            self.ctx.validate_task_parent_chain(task.id, new_parent)
            task.parent_task_id = new_parent
            fields.append("parent_task_id")
        if owner_ids is not None:
            task.owner_ids = self.ctx.owner_ids(owner_ids)
            fields.append("owner_ids")
        if labels is not None:
            task.labels = [require_label(item) for item in normalize_labels(labels)]
            fields.append("labels")
        if acceptance_criteria is not None:
            task.acceptance_criteria = [str(item) for item in as_list(acceptance_criteria)]
            fields.append("acceptance_criteria")
        if due_at is not UNSET:
            task.due_at = self.ctx.dt(due_at)
            fields.append("due_at")
        if not fields:
            return self.ctx.task_view(task)
        self.ctx.save(task, base, "task.updated", {"fields": fields})
        if "labels" in fields:
            self.ctx.rebuild_labels()
        return self.ctx.task_view(task)

    def task_set_status(self, task_id, status, expected_rev=None) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        new_status = enum_value(TaskStatus, status, "status")
        old = task.status
        if old == new_status:
            return self.ctx.task_view(task)
        task.status = new_status
        now = now_local()
        if new_status == TaskStatus.DOING and task.started_at is None:
            task.started_at = now
        if new_status == TaskStatus.DONE:
            task.completed_at = now
        elif old == TaskStatus.DONE:
            task.completed_at = None
        self.ctx.save(
            task,
            base,
            "task.status_changed",
            {"from": old.value, "to": new_status.value},
        )
        return self.ctx.task_view(task)

    # ------------------------------------------------------------- 分配/依赖

    def task_assign(self, task_id, member, expected_rev=None) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        member_id = self.ctx.member_id(member, require_active=True)
        if member_id in task.owner_ids:
            return self.ctx.task_view(task)
        task.owner_ids.append(member_id)
        self.ctx.save(task, base, "task.assigned", {"member_id": member_id})
        return self.ctx.task_view(task)

    def task_unassign(self, task_id, member, expected_rev=None) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        member_id = self.ctx.member_id(member)
        if member_id not in task.owner_ids:
            raise NotFound(f"task {task.id} has no owner {member_id}")
        task.owner_ids = [owner for owner in task.owner_ids if owner != member_id]
        self.ctx.save(task, base, "task.unassigned", {"member_id": member_id})
        return self.ctx.task_view(task)

    def task_add_dependency(
        self, task_id, target_id, relation="depends_on", expected_rev=None
    ) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        target = self.ctx.resolve_ref("task", target_id)
        if target == task.id:
            raise InvalidArgument("a task cannot depend on itself")
        relation_enum = enum_value(DependencyRelation, relation, "relation")
        if any(dep.task_id == target for dep in task.dependencies):
            return self.ctx.task_view(task)
        if relation_enum == DependencyRelation.DEPENDS_ON:
            cycle = dependency_graph.would_create_cycle(
                self.ctx.tasks_by_id(include_deleted=True), task.id, target
            )
            if cycle:
                raise DependencyCycle(
                    f"dependency {task.id} -> {target} would create a cycle",
                    {"cycle": cycle},
                )
        task.dependencies.append(Dependency(task_id=target, relation=relation_enum))
        self.ctx.save(
            task,
            base,
            "task.dependency_added",
            {"target_id": target, "relation": relation_enum.value},
        )
        return self.ctx.task_view(task)

    def task_remove_dependency(self, task_id, target_id, expected_rev=None) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        target = self.ctx.resolve_ref("task", target_id, allow_deleted=True)
        remaining = [dep for dep in task.dependencies if dep.task_id != target]
        if len(remaining) == len(task.dependencies):
            raise NotFound(f"task {task.id} has no dependency on {target}")
        task.dependencies = remaining
        self.ctx.save(task, base, "task.dependency_removed", {"target_id": target})
        return self.ctx.task_view(task)

    # ------------------------------------------------------------- 标签/层级

    def task_add_label(self, task_id, label, expected_rev=None) -> dict[str, Any]:
        text = require_label(label)
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        if text in task.labels:
            return self.ctx.task_view(task)
        task.labels.append(text)
        self.ctx.save(task, base, "task.label_added", {"label": text})
        self.ctx.rebuild_labels()
        return self.ctx.task_view(task)

    def task_remove_label(self, task_id, label, expected_rev=None) -> dict[str, Any]:
        text = require_label(label)
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        if text not in task.labels:
            raise NotFound(f"task {task.id} has no label {text!r}")
        task.labels = [item for item in task.labels if item != text]
        self.ctx.save(task, base, "task.label_removed", {"label": text})
        self.ctx.rebuild_labels()
        return self.ctx.task_view(task)

    def task_move_milestone(self, task_id, milestone_id, expected_rev=None) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        old_value = task.milestone_id
        new_value = self.ctx.assert_milestone_open(milestone_id, current=old_value)
        if old_value == new_value:
            return self.ctx.task_view(task)
        task.milestone_id = new_value
        self.ctx.save(
            task,
            base,
            "task.updated",
            {"fields": ["milestone_id"], "from": old_value, "to": new_value},
        )
        return self.ctx.task_view(task)

    def task_move_area(self, task_id, area_id=None, expected_rev=None) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        old_value = task.area_id
        new_value = self.ctx.area_id(area_id)
        if old_value == new_value:
            return self.ctx.task_view(task)
        task.area_id = new_value
        self.ctx.save(
            task,
            base,
            "task.updated",
            {"fields": ["area_id"], "from": old_value, "to": new_value},
        )
        return self.ctx.task_view(task)

    def task_set_parent(self, task_id, parent_task_id, expected_rev=None) -> dict[str, Any]:
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev)
        new_parent = self.ctx.ref_or_none("task", parent_task_id)
        if new_parent == task.id:
            raise InvalidArgument("a task cannot be its own parent")
        self.ctx.validate_task_parent_chain(task.id, new_parent)
        if task.parent_task_id == new_parent:
            return self.ctx.task_view(task)
        task.parent_task_id = new_parent
        self.ctx.save(task, base, "task.updated", {"fields": ["parent_task_id"]})
        return self.ctx.task_view(task)

    # ------------------------------------------------------------- 生命周期

    def task_archive(self, task_id, expected_rev=None) -> dict[str, Any]:
        return self.ctx.set_lifecycle(
            "task", task_id, Lifecycle.ARCHIVED, "object.archived", expected_rev
        )

    def task_restore(self, task_id, expected_rev=None) -> dict[str, Any]:
        return self.ctx.set_lifecycle(
            "task", task_id, Lifecycle.ACTIVE, "object.restored", expected_rev
        )

    def task_delete(self, task_id, expected_rev=None) -> dict[str, Any]:
        return self.ctx.set_lifecycle(
            "task", task_id, Lifecycle.DELETED, "object.deleted", expected_rev
        )

    # ----------------------------------------------------------------- 内部

    @staticmethod
    def _weight(value) -> int:
        try:
            weight = int(value)
        except (TypeError, ValueError):
            raise InvalidArgument(f"weight must be an integer, got {value!r}") from None
        if weight < 1:
            raise InvalidArgument("weight must be >= 1")
        return weight

    def task_related_interfaces(self, task_id, area_scope: bool = True) -> dict[str, Any]:
        """和这个 task 相关的接口契约（**派生读，不建索引**）。

        为什么需要：agent 没有隐性知识 —— 它不知道 `store.updateModel` 什么时候
        能改、什么算破坏性变更。人靠记忆和口口相传，agent 只能读文档。
        所以「这个 task 碰了哪些契约」必须在**动手之前**就摆在它面前。

        三条来源，**可信度递减**：

        1. **显式关联**：Artifact（interface）的 `related_task_ids` 含本 task
           —— `pjt artifact attach --task`，最准确，是人明确说的
        2. **同 Area**：接口 front-matter 的 `area` == task 的 area
           —— 结构上的可能相关，不一定真相关，所以标 `reason="same_area"`
        3. **正文提及**：接口名出现在 task 标题/描述里
           —— 弱信号，只用来提示，标 `reason="mentioned"`

        每条都带 `reason`，让调用方自己决定信多少。**工具不合并、不排序成
        「最相关」** —— 那等于替人做判断。
        """
        full_id = self.ctx.resolve_ref("task", task_id, allow_deleted=True)
        task = self.ctx.load("task", full_id)
        haystack = f"{task.title} {task.description}".lower()

        rows: list[dict[str, Any]] = []
        for record in self.ctx.store.list_raw("artifact", include_deleted=False):
            metadata = record.get("metadata") or {}
            if metadata.get("interface") is not True:
                continue
            if record.get("lifecycle") == Lifecycle.DELETED.value:
                continue
            entry = self._interface_row(record)
            if entry is None:
                continue
            if full_id in (record.get("related_task_ids") or []):
                entry["reason"] = "linked"
                rows.append(entry)
            elif area_scope and task.area_id and entry.get("area_id") == task.area_id:
                entry["reason"] = "same_area"
                rows.append(entry)
            elif entry.get("name") and str(entry["name"]).lower() in haystack:
                entry["reason"] = "mentioned"
                rows.append(entry)

        # 显式关联排前面，其次同 Area，最后正文提及
        order = {"linked": 0, "same_area": 1, "mentioned": 2}
        rows.sort(key=lambda item: (order.get(item["reason"], 9), str(item.get("name") or "")))
        return {
            "task_id": full_id,
            "count": len(rows),
            "interfaces": rows,
            "note": (
                "reason 字段标明这条为什么被带出来：linked=显式关联，"
                "same_area=同 Area，mentioned=正文提及。工具不替你判断相关性。"
            ),
        }

    def _interface_row(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """从 Artifact + 它的 markdown 里抽出接口摘要（读不到就返回 None）。"""
        from pathlib import Path

        locator = str(record.get("locator") or "")
        row: dict[str, Any] = {
            "artifact_id": record.get("id"),
            "name": record.get("name"),
            "locator": locator,
            "area_id": (record.get("related_area_ids") or [None])[0],
            "status": None,
            "consumers": [],
            "readable": False,
        }
        path = self.ctx.paths.root / locator
        if not path.is_file():
            row["read_error"] = "document not found"
            return row
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            row["read_error"] = str(exc)
            return row
        data, _, error = parse_front_matter(text)
        if error is not None:
            row["read_error"] = error
            return row
        row["readable"] = True
        row["name"] = data.get("name") or row["name"]
        row["status"] = data.get("status")
        # ⚠ front-matter 的 `area` 是**名字**，而 `area_id` 必须保持 id ——
        # 上面按 area 匹配时要拿它和 task.area_id 比。混用会导致永远匹配不上。
        row["area"] = data.get("area")
        row["consumers"] = data.get("consumers") or []
        return row

    # ------------------------------------------------------------- 认领

    def task_claim(
        self, task_id, member=None, ttl_minutes: int = 30, note: str = ""
    ) -> dict[str, Any]:
        """认领一个 task（协调信号，不是锁，也不是权限门禁）。

        目的是把「有人在动这个」提前暴露出来。写入那一刻才发现冲突太晚了 ——
        人类撞了重试几秒，agent 撞了意味着整个任务已经做完、全部作废。

        语义：
        - 同一个人重复 claim = 续期（agent 干活可能超过 TTL）
        - 别人已认领 = `CLAIMED`，**不覆盖**。要抢得先 release，或等它过期
        - **TTL 必填且有上限**：agent 会崩，不能让它永久占住
        """
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev=None)
        member_id = self.ctx.member_id(member) if member else self.ctx.actor_id
        if not member_id:
            raise InvalidArgument(
                "cannot claim: no actor. run 'pjt member use <handle>' or set PJT_ACTOR"
            )
        minutes = max(1, min(int(ttl_minutes), MAX_CLAIM_MINUTES))
        now = now_local()

        current = claim_view(task.claim, now)
        if current is not None and current["member_id"] != member_id:
            raise Claimed(
                f"task {task.id} is claimed by {current['member_id']} until "
                f"{current['expires_at']}; release it or wait for expiry",
                member_id=current["member_id"],
                expires_at=current["expires_at"],
                task_id=task.id,
            )
        expires = now + timedelta(minutes=minutes)
        # 续期保留原 claimed_at，这样「从什么时候开始有人在动」不会因为续期被抹掉
        renewed = current is not None
        claimed_at = datetime.fromisoformat(current["claimed_at"]) if current else now
        task.claim = Claim(
            member_id=member_id,
            claimed_at=claimed_at,
            expires_at=expires,
            note=optional_text(note, "note"),
        )
        self.ctx.save(
            task,
            base,
            "task.claimed",
            {
                "member_id": member_id,
                "expires_at": expires.isoformat(),
                "ttl_minutes": minutes,
                "renewed": renewed,
            },
        )
        # 返回 task_view 而不是 save 的原始 record：认领的有效性是**派生**的，
        # 调用方不该拿到一个「看起来还没生效」的 claim 字段
        return self.ctx.task_view(task)

    def task_release(self, task_id, member=None) -> dict[str, Any]:
        """放弃认领。只有认领者本人（或未指定 member 时当前 actor）能放。"""
        task = self.ctx.load("task", task_id)
        base = self.ctx.require_expected_rev("task", task, expected_rev=None)
        current = claim_view(task.claim)
        if current is None:
            # 过期 = 本来就没有，不是错误：重复 release 是正常操作
            return self.ctx.task_view(task)
        if member is not None and self.ctx.member_id(member) != current["member_id"]:
            holder = self.ctx.store.get_raw("member", current["member_id"]) or {}
            raise InvalidArgument(
                f"task {task.id} is claimed by "
                f"{holder.get('handle') or current['member_id']}, not by {member!r}"
            )
        previous = current["member_id"]
        task.claim = None
        self.ctx.save(task, base, "task.released", {"member_id": previous})
        return self.ctx.task_view(task)
