"""Application Service：CLI / Web / SDK 共享的唯一入口，所有写操作经由事务。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from project_tool import __version__
from project_tool.application import doctor as doctor_module
from project_tool.application import queries
from project_tool.domain.decision import Alternative, Decision
from project_tool.domain.enums import (
    DecisionStatus,
    DependencyRelation,
    GoalStatus,
    Lifecycle,
    LinkKind,
    LinkMode,
    MilestoneStatus,
    Priority,
    ProjectStatus,
    TaskStatus,
)
from project_tool.domain.errors import (
    AlreadyExists,
    DependencyCycle,
    InvalidArgument,
    NotFound,
    ProjectToolError,
    RevisionConflict,
)
from project_tool.domain.goal import Goal
from project_tool.domain.hashing import compute_rev
from project_tool.domain.ids import new_id
from project_tool.domain.link import Link, LinkTarget
from project_tool.domain.member import GitIdentity, Member
from project_tool.domain.milestone import Milestone
from project_tool.domain.task import Dependency, Task
from project_tool.domain.timeutil import now_local, parse_datetime
from project_tool.domain.update import Update
from project_tool.graph import dependency as dependency_graph
from project_tool.graph import project_graph
from project_tool.integrations import filesystem
from project_tool.storage import (
    EventSpec,
    EventStore,
    ObjectChange,
    ObjectStore,
    Transaction,
    WriteLock,
    init_project,
    open_project,
)
from project_tool.storage.migrations import migrate as run_migration
from project_tool.version import SCHEMA_VERSION

UNSET: Any = object()

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _enum(enum_cls, value, field_name: str = "value"):
    try:
        return enum_cls(value)
    except ValueError:
        allowed = ", ".join(item.value for item in enum_cls)
        raise InvalidArgument(f"invalid {field_name}: {value!r} (allowed: {allowed})") from None


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _dedupe(items: list) -> list:
    seen: set = set()
    result: list = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _normalize_labels(labels) -> list[str]:
    result: list[str] = []
    for label in _as_list(labels):
        text = str(label).strip()
        if text and text not in result:
            result.append(text)
    return result


def _resolve_member_id(store: ObjectStore, ref: str) -> str:
    text = str(ref or "").strip()
    if not text:
        raise InvalidArgument("member reference must not be empty")
    if text.upper().startswith("MBR-"):
        return store.resolve("member", text)
    record = store.find_by_handle(text)
    if record is not None:
        return record["id"]
    try:
        return store.resolve("member", text)
    except ProjectToolError:
        raise NotFound(f"member {ref!r} not found (by handle or id)") from None


def resolve_actor(opened, explicit: str | None = None) -> str | None:
    store = ObjectStore(opened.paths)
    for candidate in (explicit, os.environ.get("PJT_ACTOR"), opened.local.actor):
        if not candidate:
            continue
        try:
            return _resolve_member_id(store, str(candidate))
        except ProjectToolError:
            continue
    members = sorted(store.list_models("member"), key=lambda member: member.id)
    for member in members:
        if getattr(member, "active", False) and member.lifecycle == Lifecycle.ACTIVE:
            return member.id
    return None


class ProjectService:
    def __init__(self, opened, actor_id: str | None = None):
        self.opened = opened
        self.paths = opened.paths
        self.store = ObjectStore(opened.paths)
        self.events = EventStore(opened.paths)
        self.actor_id = resolve_actor(opened, actor_id)

    # ------------------------------------------------------------------ entry

    @classmethod
    def open(cls, root: str | Path | None = None, actor: str | None = None) -> "ProjectService":
        return cls(open_project(root), actor_id=actor)

    @staticmethod
    def project_init(path, name=None, description="", slug=None) -> dict[str, Any]:
        opened = init_project(path, name=name, description=description, slug=slug)
        return {
            "root": str(opened.paths.root),
            "project": opened.project.to_record(),
            "device_id": opened.device_id,
        }

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        if not isinstance(params, dict):
            raise InvalidArgument("params must be an object")
        if not method or method.startswith("_") or "." not in method:
            raise InvalidArgument(f"unknown method: {method!r}")
        handler = getattr(self, method.replace(".", "_"), None)
        if handler is None or not callable(handler):
            raise InvalidArgument(f"unknown method: {method!r}")
        return handler(**params)

    def handle(self, method: str, params: dict[str, Any] | None = None, request_id: str = "req") -> dict[str, Any]:
        try:
            return {"id": request_id, "result": self.call(method, params)}
        except ProjectToolError as exc:
            return {"id": request_id, "error": exc.to_error()}

    # ------------------------------------------------------------- core write

    def _prepare(self, model, base_rev: str | None) -> dict[str, Any]:
        now = now_local()
        if base_rev is None:
            model.version = 1
            model.created_at = now
            model.created_by = self.actor_id
        else:
            model.version = int(model.version) + 1
        model.updated_at = now
        model.updated_by = self.actor_id
        record = model.model_dump(mode="json")
        record["rev"] = compute_rev(record)
        model.rev = record["rev"]
        return record

    def _commit(self, changes: list[ObjectChange], events: list[EventSpec]) -> str:
        with WriteLock(self.paths):
            return Transaction(self.opened, self.actor_id).commit(changes, events)

    def _save(self, model, base_rev: str | None, event_type: str, payload: dict | None = None) -> dict[str, Any]:
        record = self._prepare(model, base_rev)
        spec = EventSpec(event_type, model.type, model.id, payload or {}, base_rev, record["rev"])
        self._commit([ObjectChange(model.type, model.id, record, base_rev)], [spec])
        return record

    def _save_project(self, event_type: str, payload: dict | None = None) -> dict[str, Any]:
        project = self.opened.project
        project.updated_at = now_local()
        record = project.to_record()
        self._commit(
            [ObjectChange("project", project.id, record, None)],
            [EventSpec(event_type, "project", project.id, payload or {})],
        )
        return record

    def _load(self, obj_type: str, ref: str):
        return self.store.load_model(obj_type, ref)

    def _ref_or_none(self, obj_type: str, ref):
        if ref is None or ref == "":
            return None
        return self.store.resolve(obj_type, ref)

    def _refs(self, obj_type: str, refs) -> list[str]:
        return _dedupe([self.store.resolve(obj_type, ref) for ref in _as_list(refs)])

    def _owner_ids(self, refs) -> list[str]:
        return _dedupe([_resolve_member_id(self.store, ref) for ref in _as_list(refs)])

    def _member_id(self, ref: str) -> str:
        return _resolve_member_id(self.store, ref)

    def _dt(self, value):
        try:
            return parse_datetime(value)
        except ValueError as exc:
            raise InvalidArgument(str(exc)) from None

    def _tasks_by_id(self, include_deleted: bool = False) -> dict[str, Task]:
        return {task.id: task for task in self.store.list_models("task", include_deleted=include_deleted)}

    def _task_view(self, task: Task) -> dict[str, Any]:
        tasks = self._tasks_by_id(include_deleted=True)
        blocked, blockers = dependency_graph.is_computed_blocked(task, tasks)
        record = task.model_dump(mode="json")
        record["computed_blocked"] = blocked
        record["blocked_by"] = blockers
        return record

    def _rebuild_labels(self) -> None:
        labels: set[str] = set()
        for task in self.store.list_models("task"):
            if task.lifecycle == Lifecycle.ACTIVE:
                labels.update(task.labels)
        filesystem.write_json(self.paths.labels_json, {"schema_version": SCHEMA_VERSION, "labels": sorted(labels)})

    # ------------------------------------------------------- system / project

    def system_info(self) -> dict[str, Any]:
        return {
            "tool": "project-tool",
            "version": __version__,
            "schema_version": SCHEMA_VERSION,
            "project_id": self.opened.project.id,
        }

    def project_open(self) -> dict[str, Any]:
        return {
            "root": str(self.paths.root),
            "project": self.opened.project.to_record(),
            "device_id": self.opened.device_id,
            "actor": self.actor_id,
            "schema_version": SCHEMA_VERSION,
        }

    def project_get(self) -> dict[str, Any]:
        return self.opened.project.to_record()

    def project_update(self, name=None, description=None, status=None, metadata=None) -> dict[str, Any]:
        project = self.opened.project
        fields: list[str] = []
        if name is not None:
            if not str(name).strip():
                raise InvalidArgument("project name must not be empty")
            project.name = str(name)
            fields.append("name")
        if description is not None:
            project.description = str(description)
            fields.append("description")
        if status is not None:
            project.status = _enum(ProjectStatus, status, "status")
            fields.append("status")
        if metadata is not None:
            project.metadata = dict(metadata)
            fields.append("metadata")
        if not fields:
            return project.to_record()
        self._save_project("project.updated", {"fields": fields})
        return project.to_record()

    def project_status(self, recent: int = 10) -> dict[str, Any]:
        return queries.project_status(self, recent_limit=int(recent))

    def project_doctor(self) -> dict[str, Any]:
        return doctor_module.run_doctor(self)

    def project_migrate(self) -> dict[str, Any]:
        return run_migration(self.opened)

    # ------------------------------------------------------------------- goal

    def goal_create(
        self,
        title,
        description="",
        parent_goal_id=None,
        success_criteria=None,
        due_at=None,
        status="active",
    ) -> dict[str, Any]:
        if not str(title or "").strip():
            raise InvalidArgument("goal title is required")
        now = now_local()
        goal = Goal(
            id=new_id("goal"),
            project_id=self.opened.project.id,
            title=str(title).strip(),
            description=description or "",
            status=_enum(GoalStatus, status, "status"),
            parent_goal_id=self._ref_or_none("goal", parent_goal_id),
            success_criteria=[str(item) for item in _as_list(success_criteria)],
            due_at=self._dt(due_at),
            created_at=now,
            updated_at=now,
        )
        return self._save(goal, None, "goal.created", {"title": goal.title})

    def goal_get(self, goal_id) -> dict[str, Any]:
        return self._load("goal", goal_id).model_dump(mode="json")

    def goal_list(self, status=None, include_archived=False, include_deleted=False) -> list[dict[str, Any]]:
        wanted = {_enum(GoalStatus, item, "status").value for item in _as_list(status)}
        result = []
        for goal in self.store.list_models("goal", include_deleted=include_deleted):
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
    ) -> dict[str, Any]:
        goal = self._load("goal", goal_id)
        base = goal.rev
        fields: list[str] = []
        if title is not None:
            goal.title = str(title)
            fields.append("title")
        if description is not None:
            goal.description = str(description)
            fields.append("description")
        if success_criteria is not None:
            goal.success_criteria = [str(item) for item in _as_list(success_criteria)]
            fields.append("success_criteria")
        if due_at is not UNSET:
            goal.due_at = self._dt(due_at)
            fields.append("due_at")
        if parent_goal_id is not UNSET:
            new_parent = self._ref_or_none("goal", parent_goal_id)
            if new_parent == goal.id:
                raise InvalidArgument("a goal cannot be its own parent")
            goal.parent_goal_id = new_parent
            fields.append("parent_goal_id")
        if status is not None:
            goal.status = _enum(GoalStatus, status, "status")
            fields.append("status")
        if not fields:
            return goal.model_dump(mode="json")
        return self._save(goal, base, "goal.updated", {"fields": fields})

    def goal_set_status(self, goal_id, status) -> dict[str, Any]:
        goal = self._load("goal", goal_id)
        new_status = _enum(GoalStatus, status, "status")
        if goal.status == new_status:
            return goal.model_dump(mode="json")
        old = goal.status
        goal.status = new_status
        return self._save(
            goal,
            goal.rev,
            "goal.status_changed",
            {"from": old.value, "to": new_status.value},
        )

    def goal_archive(self, goal_id) -> dict[str, Any]:
        return self._set_lifecycle("goal", goal_id, Lifecycle.ARCHIVED, "object.archived")

    def goal_restore(self, goal_id) -> dict[str, Any]:
        return self._set_lifecycle("goal", goal_id, Lifecycle.ACTIVE, "object.restored")

    # -------------------------------------------------------------- milestone

    def milestone_create(self, title, description="", goal_ids=None, due_at=None, status="planned") -> dict[str, Any]:
        if not str(title or "").strip():
            raise InvalidArgument("milestone title is required")
        now = now_local()
        milestone = Milestone(
            id=new_id("milestone"),
            project_id=self.opened.project.id,
            title=str(title).strip(),
            description=description or "",
            status=_enum(MilestoneStatus, status, "status"),
            goal_ids=self._refs("goal", goal_ids),
            due_at=self._dt(due_at),
            created_at=now,
            updated_at=now,
        )
        return self._save(milestone, None, "milestone.created", {"title": milestone.title})

    def milestone_get(self, milestone_id) -> dict[str, Any]:
        milestone = self._load("milestone", milestone_id)
        view = project_graph.milestone_summary(milestone, self._tasks_by_id())
        view["description"] = milestone.description
        return view

    def milestone_list(self, status=None, include_archived=False, include_deleted=False) -> list[dict[str, Any]]:
        wanted = {_enum(MilestoneStatus, item, "status").value for item in _as_list(status)}
        result = []
        for milestone in self.store.list_models("milestone", include_deleted=include_deleted):
            if milestone.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if milestone.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if wanted and milestone.status.value not in wanted:
                continue
            result.append(project_graph.milestone_summary(milestone, self._tasks_by_id()))
        return result

    def milestone_update(
        self,
        milestone_id,
        title=None,
        description=None,
        goal_ids=None,
        due_at=UNSET,
        status=None,
    ) -> dict[str, Any]:
        milestone = self._load("milestone", milestone_id)
        base = milestone.rev
        fields: list[str] = []
        if title is not None:
            milestone.title = str(title)
            fields.append("title")
        if description is not None:
            milestone.description = str(description)
            fields.append("description")
        if goal_ids is not None:
            milestone.goal_ids = self._refs("goal", goal_ids)
            fields.append("goal_ids")
        if due_at is not UNSET:
            milestone.due_at = self._dt(due_at)
            fields.append("due_at")
        if status is not None:
            milestone.status = _enum(MilestoneStatus, status, "status")
            fields.append("status")
        if not fields:
            return milestone.model_dump(mode="json")
        return self._save(milestone, base, "milestone.updated", {"fields": fields})

    def milestone_activate(self, milestone_id) -> dict[str, Any]:
        return self._set_milestone_status(milestone_id, MilestoneStatus.ACTIVE, "milestone.activated")

    def milestone_close(self, milestone_id) -> dict[str, Any]:
        return self._set_milestone_status(milestone_id, MilestoneStatus.CLOSED, "milestone.closed")

    def milestone_cancel(self, milestone_id) -> dict[str, Any]:
        return self._set_milestone_status(milestone_id, MilestoneStatus.CANCELLED, "milestone.cancelled")

    def milestone_progress(self, milestone_id) -> dict[str, Any]:
        milestone = self._load("milestone", milestone_id)
        return project_graph.milestone_summary(milestone, self._tasks_by_id())

    def _set_milestone_status(self, milestone_id, status: MilestoneStatus, event_type: str) -> dict[str, Any]:
        milestone = self._load("milestone", milestone_id)
        if milestone.status == status:
            return milestone.model_dump(mode="json")
        old = milestone.status
        milestone.status = status
        return self._save(milestone, milestone.rev, event_type, {"from": old.value, "to": status.value})

    # ------------------------------------------------------------------- task

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
        if not str(title or "").strip():
            raise InvalidArgument("task title is required")
        try:
            weight_value = int(weight)
        except (TypeError, ValueError):
            raise InvalidArgument(f"weight must be an integer, got {weight!r}") from None
        if weight_value < 1:
            raise InvalidArgument("weight must be >= 1")
        now = now_local()
        task = Task(
            id=new_id("task"),
            project_id=self.opened.project.id,
            title=str(title).strip(),
            description=description or "",
            status=_enum(TaskStatus, status, "status"),
            priority=_enum(Priority, priority, "priority"),
            weight=weight_value,
            milestone_id=self._ref_or_none("milestone", milestone_id),
            parent_task_id=self._ref_or_none("task", parent_task_id),
            owner_ids=self._owner_ids(owner_ids),
            labels=_normalize_labels(labels),
            acceptance_criteria=[str(item) for item in _as_list(acceptance_criteria)],
            due_at=self._dt(due_at),
            created_at=now,
            updated_at=now,
        )
        return self._save(task, None, "task.created", {"title": task.title})

    def task_get(self, task_id) -> dict[str, Any]:
        return self._task_view(self._load("task", task_id))

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
        wanted_status = {_enum(TaskStatus, item, "status").value for item in _as_list(status)}
        wanted_priority = {_enum(Priority, item, "priority").value for item in _as_list(priority)}
        owner_id = self._member_id(owner) if owner else None
        milestone_id = self._ref_or_none("milestone", milestone) if milestone else None
        parent_id = self._ref_or_none("task", parent) if parent else None
        tasks = self._tasks_by_id(include_deleted=include_deleted)
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
    ) -> dict[str, Any]:
        task = self._load("task", task_id)
        base = task.rev
        fields: list[str] = []
        if title is not None:
            task.title = str(title)
            fields.append("title")
        if description is not None:
            task.description = str(description)
            fields.append("description")
        if priority is not None:
            task.priority = _enum(Priority, priority, "priority")
            fields.append("priority")
        if weight is not None:
            try:
                task.weight = int(weight)
            except (TypeError, ValueError):
                raise InvalidArgument(f"weight must be an integer, got {weight!r}") from None
            if task.weight < 1:
                raise InvalidArgument("weight must be >= 1")
            fields.append("weight")
        if milestone_id is not UNSET:
            task.milestone_id = self._ref_or_none("milestone", milestone_id)
            fields.append("milestone_id")
        if parent_task_id is not UNSET:
            new_parent = self._ref_or_none("task", parent_task_id)
            if new_parent == task.id:
                raise InvalidArgument("a task cannot be its own parent")
            self._validate_parent_chain(task.id, new_parent)
            task.parent_task_id = new_parent
            fields.append("parent_task_id")
        if owner_ids is not None:
            task.owner_ids = self._owner_ids(owner_ids)
            fields.append("owner_ids")
        if labels is not None:
            task.labels = _normalize_labels(labels)
            fields.append("labels")
        if acceptance_criteria is not None:
            task.acceptance_criteria = [str(item) for item in _as_list(acceptance_criteria)]
            fields.append("acceptance_criteria")
        if due_at is not UNSET:
            task.due_at = self._dt(due_at)
            fields.append("due_at")
        if not fields:
            return self._task_view(task)
        self._save(task, base, "task.updated", {"fields": fields})
        if "labels" in fields:
            self._rebuild_labels()
        return self._task_view(task)

    def task_set_status(self, task_id, status, expected_rev=None) -> dict[str, Any]:
        task = self._load("task", task_id)
        if expected_rev and task.rev != expected_rev:
            raise RevisionConflict(
                f"task {task.id} rev mismatch",
                expected_rev=expected_rev,
                actual_rev=task.rev,
                entity_id=task.id,
            )
        new_status = _enum(TaskStatus, status, "status")
        old = task.status
        if old == new_status:
            return self._task_view(task)
        task.status = new_status
        now = now_local()
        if new_status == TaskStatus.DOING and task.started_at is None:
            task.started_at = now
        if new_status == TaskStatus.DONE:
            task.completed_at = now
        elif old == TaskStatus.DONE:
            task.completed_at = None
        self._save(task, task.rev, "task.status_changed", {"from": old.value, "to": new_status.value})
        return self._task_view(task)

    def task_assign(self, task_id, member) -> dict[str, Any]:
        task = self._load("task", task_id)
        member_id = self._member_id(member)
        if member_id in task.owner_ids:
            return self._task_view(task)
        task.owner_ids.append(member_id)
        self._save(task, task.rev, "task.assigned", {"member_id": member_id})
        return self._task_view(task)

    def task_unassign(self, task_id, member) -> dict[str, Any]:
        task = self._load("task", task_id)
        member_id = self._member_id(member)
        if member_id not in task.owner_ids:
            raise NotFound(f"task {task.id} has no owner {member_id}")
        task.owner_ids = [owner for owner in task.owner_ids if owner != member_id]
        self._save(task, task.rev, "task.unassigned", {"member_id": member_id})
        return self._task_view(task)

    def task_add_dependency(self, task_id, target_id, relation="depends_on") -> dict[str, Any]:
        task = self._load("task", task_id)
        target = self.store.resolve("task", target_id)
        if target == task.id:
            raise InvalidArgument("a task cannot depend on itself")
        relation_enum = _enum(DependencyRelation, relation, "relation")
        if any(dep.task_id == target for dep in task.dependencies):
            return self._task_view(task)
        if relation_enum == DependencyRelation.DEPENDS_ON:
            cycle = dependency_graph.would_create_cycle(
                self._tasks_by_id(include_deleted=True), task.id, target
            )
            if cycle:
                raise DependencyCycle(
                    f"dependency {task.id} -> {target} would create a cycle",
                    {"cycle": cycle},
                )
        task.dependencies.append(Dependency(task_id=target, relation=relation_enum))
        self._save(
            task,
            task.rev,
            "task.dependency_added",
            {"target_id": target, "relation": relation_enum.value},
        )
        return self._task_view(task)

    def task_remove_dependency(self, task_id, target_id) -> dict[str, Any]:
        task = self._load("task", task_id)
        target = self.store.resolve("task", target_id)
        remaining = [dep for dep in task.dependencies if dep.task_id != target]
        if len(remaining) == len(task.dependencies):
            raise NotFound(f"task {task.id} has no dependency on {target}")
        task.dependencies = remaining
        self._save(task, task.rev, "task.dependency_removed", {"target_id": target})
        return self._task_view(task)

    def task_add_label(self, task_id, label) -> dict[str, Any]:
        text = str(label or "").strip()
        if not text:
            raise InvalidArgument("label must not be empty")
        task = self._load("task", task_id)
        if text in task.labels:
            return self._task_view(task)
        task.labels.append(text)
        self._save(task, task.rev, "task.label_added", {"label": text})
        self._rebuild_labels()
        return self._task_view(task)

    def task_remove_label(self, task_id, label) -> dict[str, Any]:
        text = str(label or "").strip()
        task = self._load("task", task_id)
        if text not in task.labels:
            raise NotFound(f"task {task.id} has no label {text!r}")
        task.labels = [item for item in task.labels if item != text]
        self._save(task, task.rev, "task.label_removed", {"label": text})
        self._rebuild_labels()
        return self._task_view(task)

    def task_move_milestone(self, task_id, milestone_id) -> dict[str, Any]:
        task = self._load("task", task_id)
        old_value = task.milestone_id
        new_value = self._ref_or_none("milestone", milestone_id)
        if old_value == new_value:
            return self._task_view(task)
        task.milestone_id = new_value
        self._save(
            task,
            task.rev,
            "task.updated",
            {"fields": ["milestone_id"], "from": old_value, "to": new_value},
        )
        return self._task_view(task)

    def task_set_parent(self, task_id, parent_task_id) -> dict[str, Any]:
        task = self._load("task", task_id)
        new_parent = self._ref_or_none("task", parent_task_id)
        if new_parent == task.id:
            raise InvalidArgument("a task cannot be its own parent")
        self._validate_parent_chain(task.id, new_parent)
        if task.parent_task_id == new_parent:
            return self._task_view(task)
        task.parent_task_id = new_parent
        self._save(task, task.rev, "task.updated", {"fields": ["parent_task_id"]})
        return self._task_view(task)

    def task_archive(self, task_id) -> dict[str, Any]:
        return self._set_lifecycle("task", task_id, Lifecycle.ARCHIVED, "object.archived")

    def task_restore(self, task_id) -> dict[str, Any]:
        return self._set_lifecycle("task", task_id, Lifecycle.ACTIVE, "object.restored")

    def task_delete(self, task_id) -> dict[str, Any]:
        return self._set_lifecycle("task", task_id, Lifecycle.DELETED, "object.deleted")

    def task_related_updates(self, task_id) -> list[dict[str, Any]]:
        full_id = self.store.resolve("task", task_id)
        return [
            update.model_dump(mode="json")
            for update in self.store.list_models("update")
            if full_id in update.task_ids
        ]

    def task_history(self, task_id) -> dict[str, Any]:
        return self._history("task", task_id)

    # ----------------------------------------------------------------- member

    def member_add(
        self,
        handle,
        display_name=None,
        roles=None,
        git_names=None,
        git_emails=None,
        external_ids=None,
    ) -> dict[str, Any]:
        normalized = str(handle or "").strip().lower()
        if not _HANDLE_RE.match(normalized):
            raise InvalidArgument(
                f"invalid handle {handle!r}: use lowercase letters, digits, '.', '_' or '-'"
            )
        if self.store.find_by_handle(normalized) is not None:
            raise AlreadyExists(f"member handle {normalized!r} already exists")
        now = now_local()
        member = Member(
            id=new_id("member"),
            project_id=self.opened.project.id,
            display_name=str(display_name or handle).strip(),
            handle=normalized,
            roles=_dedupe([str(role) for role in _as_list(roles)]),
            git=GitIdentity(
                names=_dedupe([str(name) for name in _as_list(git_names)]),
                emails=_dedupe([str(email) for email in _as_list(git_emails)]),
            ),
            external_ids={str(key): str(value) for key, value in dict(external_ids or {}).items()},
            active=True,
            created_at=now,
            updated_at=now,
        )
        record = self._save(member, None, "member.added", {"handle": member.handle})
        if self.opened.local.actor is None:
            self.opened.local.actor = member.id
            self.opened.save_local()
        return record

    def member_get(self, member) -> dict[str, Any]:
        return self._load("member", self._member_id(member)).model_dump(mode="json")

    def member_list(self, include_inactive=True, include_archived=False, include_deleted=False) -> list[dict[str, Any]]:
        result = []
        for member in self.store.list_models("member", include_deleted=include_deleted):
            if member.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if member.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            if not include_inactive and not member.active:
                continue
            result.append(member.model_dump(mode="json"))
        return result

    def member_update(
        self,
        member,
        display_name=None,
        roles=None,
        git_names=None,
        git_emails=None,
        external_ids=None,
        active=None,
    ) -> dict[str, Any]:
        loaded = self._load("member", self._member_id(member))
        fields: list[str] = []
        if display_name is not None:
            loaded.display_name = str(display_name)
            fields.append("display_name")
        if roles is not None:
            loaded.roles = _dedupe([str(role) for role in _as_list(roles)])
            fields.append("roles")
        if git_names is not None:
            loaded.git.names = _dedupe([str(name) for name in _as_list(git_names)])
            fields.append("git.names")
        if git_emails is not None:
            loaded.git.emails = _dedupe([str(email) for email in _as_list(git_emails)])
            fields.append("git.emails")
        if external_ids is not None:
            loaded.external_ids = {str(key): str(value) for key, value in dict(external_ids).items()}
            fields.append("external_ids")
        if active is not None:
            loaded.active = bool(active)
            fields.append("active")
        if not fields:
            return loaded.model_dump(mode="json")
        return self._save(loaded, loaded.rev, "member.updated", {"fields": fields})

    def member_deactivate(self, member) -> dict[str, Any]:
        loaded = self._load("member", self._member_id(member))
        if not loaded.active:
            return loaded.model_dump(mode="json")
        loaded.active = False
        return self._save(loaded, loaded.rev, "member.deactivated", {})

    def member_activate(self, member) -> dict[str, Any]:
        loaded = self._load("member", self._member_id(member))
        if loaded.active:
            return loaded.model_dump(mode="json")
        loaded.active = True
        return self._save(loaded, loaded.rev, "member.activated", {})

    def member_workload(self, member) -> dict[str, Any]:
        return queries.member_workload(self, self._member_id(member))

    def member_activity(self, member, limit=20) -> dict[str, Any]:
        return queries.log_list(self, member=member, limit=limit)

    def member_use(self, member) -> dict[str, Any]:
        member_id = self._member_id(member)
        record = self.store.get_raw("member", member_id)
        self.opened.local.actor = member_id
        self.opened.save_local()
        self.actor_id = member_id
        return {"actor": member_id, "handle": record.get("handle") if record else None}

    def member_map_git_identity(self, member, name=None, email=None) -> dict[str, Any]:
        loaded = self._load("member", self._member_id(member))
        if name:
            if name not in loaded.git.names:
                loaded.git.names.append(str(name))
        if email:
            if email not in loaded.git.emails:
                loaded.git.emails.append(str(email))
        return self._save(loaded, loaded.rev, "member.updated", {"fields": ["git"]})

    # ----------------------------------------------------------------- update

    def update_create(
        self,
        summary=None,
        body="",
        task_ids=None,
        milestone_id=None,
        blockers=None,
        next_steps=None,
    ) -> dict[str, Any]:
        body = body or ""
        summary_text = str(summary or "").strip()
        if not summary_text:
            lines = [line for line in body.strip().splitlines() if line.strip()]
            if not lines:
                raise InvalidArgument("update needs a summary or non-empty body")
            summary_text = lines[0].strip()
        now = now_local()
        update = Update(
            id=new_id("update"),
            project_id=self.opened.project.id,
            summary=summary_text,
            body=body,
            task_ids=self._refs("task", task_ids),
            milestone_id=self._ref_or_none("milestone", milestone_id),
            blockers=[str(item) for item in _as_list(blockers)],
            next_steps=[str(item) for item in _as_list(next_steps)],
            created_at=now,
            updated_at=now,
        )
        return self._save(update, None, "update.created", {"summary": update.summary})

    def update_get(self, update_id) -> dict[str, Any]:
        return self._load("update", update_id).model_dump(mode="json")

    def update_list(self, task=None, milestone=None, include_archived=False, include_deleted=False) -> list[dict[str, Any]]:
        task_id = self.store.resolve("task", task) if task else None
        milestone_id = self._ref_or_none("milestone", milestone) if milestone else None
        result = []
        for update in self.store.list_models("update", include_deleted=include_deleted):
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
        update = self._load("update", update_id)
        fields: list[str] = []
        if summary is not None:
            update.summary = str(summary)
            fields.append("summary")
        if body is not None:
            update.body = str(body)
            fields.append("body")
        if task_ids is not None:
            update.task_ids = self._refs("task", task_ids)
            fields.append("task_ids")
        if milestone_id is not UNSET:
            update.milestone_id = self._ref_or_none("milestone", milestone_id)
            fields.append("milestone_id")
        if blockers is not None:
            update.blockers = [str(item) for item in _as_list(blockers)]
            fields.append("blockers")
        if next_steps is not None:
            update.next_steps = [str(item) for item in _as_list(next_steps)]
            fields.append("next_steps")
        if not fields:
            return update.model_dump(mode="json")
        return self._save(update, update.rev, "update.updated", {"fields": fields})

    def update_archive(self, update_id) -> dict[str, Any]:
        return self._set_lifecycle("update", update_id, Lifecycle.ARCHIVED, "object.archived")

    def update_history(self, update_id) -> dict[str, Any]:
        return self._history("update", update_id)

    # --------------------------------------------------------------- decision

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
        if not str(title or "").strip():
            raise InvalidArgument("decision title is required")
        now = now_local()
        record = Decision(
            id=new_id("decision"),
            project_id=self.opened.project.id,
            title=str(title).strip(),
            status=_enum(DecisionStatus, status, "status"),
            context=context or "",
            decision=decision or "",
            rationale=rationale or "",
            alternatives=self._alternatives(alternatives),
            consequences=[str(item) for item in _as_list(consequences)],
            related_task_ids=self._refs("task", related_task_ids),
            created_at=now,
            updated_at=now,
        )
        return self._save(record, None, "decision.created", {"title": record.title})

    def decision_get(self, decision_id) -> dict[str, Any]:
        return self._load("decision", decision_id).model_dump(mode="json")

    def decision_list(self, status=None, include_archived=False, include_deleted=False) -> list[dict[str, Any]]:
        wanted = {_enum(DecisionStatus, item, "status").value for item in _as_list(status)}
        result = []
        for decision in self.store.list_models("decision", include_deleted=include_deleted):
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
    ) -> dict[str, Any]:
        record = self._load("decision", decision_id)
        fields: list[str] = []
        if title is not None:
            record.title = str(title)
            fields.append("title")
        if context is not None:
            record.context = str(context)
            fields.append("context")
        if decision is not None:
            record.decision = str(decision)
            fields.append("decision")
        if rationale is not None:
            record.rationale = str(rationale)
            fields.append("rationale")
        if alternatives is not None:
            record.alternatives = self._alternatives(alternatives)
            fields.append("alternatives")
        if consequences is not None:
            record.consequences = [str(item) for item in _as_list(consequences)]
            fields.append("consequences")
        if related_task_ids is not None:
            record.related_task_ids = self._refs("task", related_task_ids)
            fields.append("related_task_ids")
        if not fields:
            return record.model_dump(mode="json")
        return self._save(record, record.rev, "decision.updated", {"fields": fields})

    def decision_accept(self, decision_id) -> dict[str, Any]:
        return self._set_decision_status(decision_id, DecisionStatus.ACCEPTED)

    def decision_reject(self, decision_id) -> dict[str, Any]:
        return self._set_decision_status(decision_id, DecisionStatus.REJECTED)

    def decision_supersede(self, old_id, new_id) -> dict[str, Any]:
        old = self._load("decision", old_id)
        new = self._load("decision", new_id)
        if old.id == new.id:
            raise InvalidArgument("a decision cannot supersede itself")
        old_base = old.rev
        new_base = new.rev
        old_status = old.status
        old.status = DecisionStatus.SUPERSEDED
        new.supersedes_id = old.id
        old_record = self._prepare(old, old_base)
        new_record = self._prepare(new, new_base)
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
        self._commit(
            [
                ObjectChange("decision", old.id, old_record, old_base),
                ObjectChange("decision", new.id, new_record, new_base),
            ],
            events,
        )
        return {"superseded": old_record, "superseded_by": new_record}

    def decision_history(self, decision_id) -> dict[str, Any]:
        return self._history("decision", decision_id)

    def _set_decision_status(self, decision_id, status: DecisionStatus) -> dict[str, Any]:
        record = self._load("decision", decision_id)
        if record.status == status:
            return record.model_dump(mode="json")
        old = record.status
        record.status = status
        return self._save(
            record,
            record.rev,
            "decision.status_changed",
            {"from": old.value, "to": status.value},
        )

    @staticmethod
    def _alternatives(value) -> list[Alternative]:
        result: list[Alternative] = []
        for item in _as_list(value):
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

    # ------------------------------------------------------------------- link

    def link_add(self, name, locator=None, kind=None, mode="reference", project_id=None) -> dict[str, Any]:
        link_name = str(name or "").strip()
        if not link_name:
            raise InvalidArgument("link name is required")
        existing = self._find_link_by_name(link_name, include_deleted=True)
        if existing is not None:
            raise AlreadyExists(f"link {link_name!r} already exists")
        link_kind = self._infer_link_kind(kind, locator)
        self._validate_locator(link_kind, locator)
        now = now_local()
        link = Link(
            id=new_id("link"),
            project_id=self.opened.project.id,
            name=link_name,
            target=LinkTarget(kind=link_kind, project_id=project_id, locator=locator),
            mode=_enum(LinkMode, mode, "mode"),
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        return self._save(link, None, "link.added", {"name": link.name, "kind": link_kind.value})

    def link_get(self, name) -> dict[str, Any]:
        return self._link(name).model_dump(mode="json")

    def link_list(self, include_archived=False, include_deleted=False) -> list[dict[str, Any]]:
        result = []
        for link in self.store.list_models("link", include_deleted=include_deleted):
            if link.lifecycle == Lifecycle.DELETED and not include_deleted:
                continue
            if link.lifecycle == Lifecycle.ARCHIVED and not include_archived:
                continue
            result.append(link.model_dump(mode="json"))
        return result

    def link_update(
        self,
        name,
        locator=UNSET,
        kind=None,
        mode=None,
        enabled=None,
        project_id=UNSET,
    ) -> dict[str, Any]:
        link = self._link(name)
        fields: list[str] = []
        if locator is not UNSET:
            self._validate_locator(link.target.kind, locator)
            link.target.locator = locator
            fields.append("target.locator")
        if kind is not None:
            link.target.kind = _enum(LinkKind, kind, "kind")
            self._validate_locator(link.target.kind, link.target.locator)
            fields.append("target.kind")
        if mode is not None:
            link.mode = _enum(LinkMode, mode, "mode")
            fields.append("mode")
        if enabled is not None:
            link.enabled = bool(enabled)
            fields.append("enabled")
        if project_id is not UNSET:
            link.target.project_id = project_id
            fields.append("target.project_id")
        if not fields:
            return link.model_dump(mode="json")
        return self._save(link, link.rev, "link.updated", {"fields": fields})

    def link_remove(self, name) -> dict[str, Any]:
        link = self._link(name)
        if link.lifecycle == Lifecycle.DELETED:
            return link.model_dump(mode="json")
        link.lifecycle = Lifecycle.DELETED
        return self._save(link, link.rev, "link.removed", {})

    def link_resolve(self, name) -> dict[str, Any]:
        link = self._link(name)
        result: dict[str, Any] = {
            "id": link.id,
            "name": link.name,
            "kind": link.target.kind.value,
            "mode": link.mode.value,
            "enabled": link.enabled,
            "locator": link.target.locator,
            "project_id": link.target.project_id,
            "resolved": False,
        }
        if link.target.kind == LinkKind.LOCAL_PROJECT:
            mapped = self.opened.local.links.get(link.name, {}).get("path")
            locator = mapped or link.target.locator
            if locator:
                target_root = Path(locator)
                if not target_root.is_absolute():
                    target_root = self.paths.root / target_root
                target_root = target_root.resolve()
                result["path"] = str(target_root)
                project_file = target_root / ".pjt" / "project.json"
                if project_file.is_file():
                    try:
                        data = filesystem.read_json(project_file)
                        result["resolved"] = True
                        result["project"] = {"id": data.get("id"), "name": data.get("name")}
                    except ProjectToolError as exc:
                        result["error"] = exc.message
        elif link.target.kind in (LinkKind.REMOTE_PROJECT, LinkKind.GIT_REPOSITORY, LinkKind.EXTERNAL):
            result["resolved"] = bool(link.target.locator or link.target.project_id)
        if not result["resolved"] and "error" not in result:
            result["error"] = "target not found"
        return result

    def link_status(self, name) -> dict[str, Any]:
        return self.link_resolve(name)

    def _find_link_by_name(self, name: str, include_deleted: bool = False):
        wanted = str(name or "").strip().lower()
        for link in self.store.list_models("link", include_deleted=include_deleted):
            if link.name.lower() == wanted:
                return link
        return None

    def _link(self, ref) -> Link:
        text = str(ref or "").strip()
        if not text:
            raise InvalidArgument("link reference must not be empty")
        by_name = self._find_link_by_name(text, include_deleted=True)
        if by_name is not None:
            return by_name
        return self.store.load_model("link", text)

    @staticmethod
    def _infer_link_kind(kind, locator) -> LinkKind:
        if kind:
            return _enum(LinkKind, kind, "kind")
        text = str(locator or "")
        if text.startswith("http://") or text.startswith("https://"):
            return LinkKind.REMOTE_PROJECT
        return LinkKind.LOCAL_PROJECT

    @staticmethod
    def _validate_locator(kind: LinkKind, locator) -> None:
        if kind != LinkKind.LOCAL_PROJECT:
            return
        text = str(locator or "").strip()
        if not text:
            raise InvalidArgument("local_project link requires a relative locator path")
        if Path(text).is_absolute() or _WINDOWS_DRIVE_RE.match(text) or text.startswith("\\\\"):
            raise InvalidArgument(
                "absolute paths are not allowed in .pjt objects; "
                "map machine-specific paths in .pjt/local/local.toml"
            )

    # -------------------------------------------------------------------- log

    def log_list(self, **filters) -> dict[str, Any]:
        return queries.log_list(self, **filters)

    def log_get(self, event_id) -> dict[str, Any]:
        return self.events.get(event_id)

    def log_entity(self, entity_type, entity_id, **rest) -> dict[str, Any]:
        return queries.log_list(self, entity_type=entity_type, entity_id=entity_id, **rest)

    def log_member(self, member, **rest) -> dict[str, Any]:
        return queries.log_list(self, member=member, **rest)

    def log_since(self, since, **rest) -> dict[str, Any]:
        return queries.log_list(self, since=since, **rest)

    # ------------------------------------------------------------------ graph

    def graph_project(self) -> dict[str, Any]:
        return project_graph.build_project_tree(
            self.opened.project,
            self.store.list_models("goal"),
            self.store.list_models("milestone"),
            self._tasks_by_id(),
            self.store.list_models("link"),
        )

    def graph_tasks(self, milestone_id=None, include_archived=False) -> dict[str, Any]:
        return project_graph.build_task_graph(
            self._tasks_by_id(),
            self._ref_or_none("milestone", milestone_id) if milestone_id else None,
            bool(include_archived),
        )

    def graph_dependencies(self, task_id=None, depth=5) -> dict[str, Any]:
        resolved = self.store.resolve("task", task_id) if task_id else None
        return project_graph.build_dependency_graph(self._tasks_by_id(), resolved, int(depth))

    def graph_links(self) -> list[dict[str, Any]]:
        return [self.link_resolve(link.id) for link in self.store.list_models("link")]

    # ------------------------------------------------------------- internals

    def _set_lifecycle(self, obj_type: str, ref, lifecycle: Lifecycle, event_type: str) -> dict[str, Any]:
        model = self._load(obj_type, ref)
        if model.lifecycle == lifecycle:
            return model.model_dump(mode="json")
        model.lifecycle = lifecycle
        return self._save(model, model.rev, event_type, {"lifecycle": lifecycle.value})

    def _history(self, entity_type: str, ref) -> dict[str, Any]:
        full_id = self.store.resolve(entity_type, ref)
        events = [
            queries.event_summary(record)
            for record in self.events.iter_records()
            if record.get("entity_id") == full_id
        ]
        return {"events": events, "count": len(events), "next_cursor": None}

    def _validate_parent_chain(self, task_id: str, parent_id: str | None) -> None:
        seen = {task_id}
        current = parent_id
        hops = 0
        while current is not None:
            if current in seen:
                raise InvalidArgument("parent chain would contain a cycle")
            seen.add(current)
            hops += 1
            if hops > 1000:
                raise InvalidArgument("parent chain too deep; possible corruption")
            record = self.store.get_raw("task", current)
            current = record.get("parent_task_id") if record else None
