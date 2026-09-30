"""task.* 方法：创建、查询、状态机、分配、依赖、标签、层级。"""

from __future__ import annotations

from typing import Any, cast

from project_tool.application.context import (
    UNSET,
    ServiceContext,
    as_list,
    enum_value,
    normalize_labels,
)
from project_tool.domain.enums import DependencyRelation, Lifecycle, Priority, TaskStatus
from project_tool.domain.errors import DependencyCycle, InvalidArgument, NotFound
from project_tool.domain.ids import new_id
from project_tool.domain.task import Dependency, Task
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
        priority=None,
        parent=None,
        include_archived=False,
        include_deleted=False,
    ) -> list[dict[str, Any]]:
        wanted_status = {enum_value(TaskStatus, item, "status").value for item in as_list(status)}
        wanted_priority = {enum_value(Priority, item, "priority").value for item in as_list(priority)}
        owner_id = self.ctx.member_id(owner) if owner else None
        milestone_id = self.ctx.ref_or_none("milestone", milestone, allow_deleted=True) if milestone else None
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
            if parent_id and task.parent_task_id != parent_id:
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
