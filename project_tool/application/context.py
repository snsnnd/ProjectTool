"""Service 共享上下文：对象解析、校验、写路径公共能力。

所有领域服务（`application/services/*`）共享同一个 ServiceContext。
写操作统一经由 `commit()`（WriteLock + Transaction），派生缓存的刷新也
集中在这里，避免领域服务触碰存储细节。
"""

from __future__ import annotations

import os
import re
from typing import Any, cast

import project_tool.application.queries as queries
from project_tool.domain.enums import Lifecycle
from project_tool.domain.errors import (
    HierarchyCycle,
    InvalidArgument,
    NotFound,
    ProjectToolError,
)
from project_tool.domain.hashing import compute_rev
from project_tool.domain.task import Task
from project_tool.domain.timeutil import now_local, parse_datetime
from project_tool.graph import dependency as dependency_graph
from project_tool.integrations import filesystem
from project_tool.storage import (
    EventSpec,
    EventStore,
    ObjectChange,
    ObjectStore,
    Transaction,
    WriteLock,
)
from project_tool.version import SCHEMA_VERSION

UNSET: Any = object()

WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

MAX_CHAIN_HOPS = 1000
CLOSED_MILESTONE_STATUSES = {"closed", "cancelled"}


def enum_value(enum_cls, value, field_name: str = "value"):
    try:
        return enum_cls(value)
    except ValueError:
        allowed = ", ".join(item.value for item in enum_cls)
        raise InvalidArgument(f"invalid {field_name}: {value!r} (allowed: {allowed})") from None


def as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def dedupe(items: list) -> list:
    seen: set = set()
    result: list = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def normalize_labels(labels) -> list[str]:
    result: list[str] = []
    for label in as_list(labels):
        text = str(label).strip()
        if text and text not in result:
            result.append(text)
    return result


def resolve_member_id(store: ObjectStore, ref: str) -> str:
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
            return resolve_member_id(store, str(candidate))
        except ProjectToolError:
            continue
    members = sorted(store.list_models("member"), key=lambda member: member.id)
    for member in members:
        if getattr(member, "active", False) and member.lifecycle == Lifecycle.ACTIVE:
            return member.id
    return None


class ServiceContext:
    def __init__(self, opened, actor_id: str | None = None):
        self.opened = opened
        self.paths = opened.paths
        self.store = ObjectStore(opened.paths)
        self.events = EventStore(opened.paths)
        self.actor_id = resolve_actor(opened, actor_id)

    # ------------------------------------------------------------------ 读取

    def load(self, obj_type: str, ref: str):
        return self.store.load_model(obj_type, ref)

    def load_record(self, obj_type: str, ref: str) -> dict[str, Any]:
        return self.store.load_raw(obj_type, ref)[1]

    def resolve_ref(self, obj_type: str, ref, allow_deleted: bool = False) -> str:
        if ref is None or ref == "":
            raise InvalidArgument("empty id reference")
        object_id = self.store.resolve(obj_type, ref)
        if not allow_deleted:
            record = self.store.get_raw(obj_type, object_id)
            if record is not None and record.get("lifecycle") == Lifecycle.DELETED.value:
                raise InvalidArgument(
                    f"{obj_type} {object_id} is deleted and cannot be referenced"
                )
        return object_id

    def ref_or_none(self, obj_type: str, ref, allow_deleted: bool = False):
        if ref is None or ref == "":
            return None
        return self.resolve_ref(obj_type, ref, allow_deleted=allow_deleted)

    def refs(self, obj_type: str, refs, allow_deleted: bool = False) -> list[str]:
        return dedupe(
            [self.resolve_ref(obj_type, ref, allow_deleted=allow_deleted) for ref in as_list(refs)]
        )

    def member_id(self, ref: str, require_active: bool = False) -> str:
        member_id = resolve_member_id(self.store, ref)
        if require_active:
            record = self.store.get_raw("member", member_id) or {}
            if record.get("lifecycle") == Lifecycle.DELETED.value:
                raise InvalidArgument(f"member {member_id} is deleted and cannot be assigned")
            if not record.get("active", False):
                handle = record.get("handle", member_id)
                raise InvalidArgument(f"member {handle} is inactive and cannot be assigned")
        return member_id

    def owner_ids(self, refs) -> list[str]:
        return dedupe([self.member_id(ref, require_active=True) for ref in as_list(refs)])

    def dt(self, value):
        try:
            return parse_datetime(value)
        except ValueError as exc:
            raise InvalidArgument(str(exc)) from None

    def tasks_by_id(self, include_deleted: bool = False) -> dict[str, Task]:
        tasks: dict[str, Task] = {}
        for model in self.store.list_models("task", include_deleted=include_deleted):
            task = cast(Task, model)
            tasks[task.id] = task
        return tasks

    def task_view(self, task: Task) -> dict[str, Any]:
        tasks = self.tasks_by_id(include_deleted=True)
        blocked, blockers = dependency_graph.is_computed_blocked(task, tasks)
        record = task.model_dump(mode="json")
        record["computed_blocked"] = blocked
        record["blocked_by"] = blockers
        return record

    def rebuild_labels(self) -> None:
        labels: set[str] = set()
        for model in self.store.list_models("task"):
            task = cast(Task, model)
            if task.lifecycle == Lifecycle.ACTIVE:
                labels.update(task.labels)
        filesystem.write_json(
            self.paths.labels_json,
            {"schema_version": SCHEMA_VERSION, "labels": sorted(labels)},
        )

    # ------------------------------------------------------------------ 写入

    def prepare(self, model, is_create: bool) -> dict[str, Any]:
        now = now_local()
        if is_create:
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

    def commit(self, changes: list[ObjectChange], events: list[EventSpec]) -> str:
        with WriteLock(self.paths):
            return Transaction(self.opened, self.actor_id).commit(changes, events)

    def save(
        self,
        model,
        base_rev: str | None,
        event_type: str,
        payload: dict | None = None,
        is_create: bool = False,
    ) -> dict[str, Any]:
        record = self.prepare(model, is_create)
        spec = EventSpec(event_type, model.type, model.id, payload or {}, base_rev, record["rev"])
        self.commit([ObjectChange(model.type, model.id, record, base_rev)], [spec])
        return record

    def save_project(self, event_type: str, payload: dict | None = None) -> dict[str, Any]:
        project = self.opened.project
        base_rev = project.rev or None
        record = self.prepare(project, is_create=False)
        spec = EventSpec(event_type, "project", project.id, payload or {}, base_rev, record["rev"])
        self.commit([ObjectChange("project", project.id, record, base_rev)], [spec])
        return record

    def set_lifecycle(
        self,
        obj_type: str,
        ref,
        lifecycle: Lifecycle,
        event_type: str,
    ) -> dict[str, Any]:
        model = self.load(obj_type, ref)
        if model.lifecycle == lifecycle:
            return model.model_dump(mode="json")
        model.lifecycle = lifecycle
        return self.save(model, model.rev, event_type, {"lifecycle": lifecycle.value})

    def history(self, entity_type: str, ref) -> dict[str, Any]:
        full_id = self.store.resolve(entity_type, ref)
        events = [
            queries.event_summary(record)
            for record in self.events.iter_records()
            if record.get("entity_id") == full_id
        ]
        return {"events": events, "count": len(events), "next_cursor": None}

    # ------------------------------------------------------------------ 校验

    def assert_milestone_open(self, milestone_id, current: str | None = None) -> str | None:
        if milestone_id is None or milestone_id == "":
            return None
        resolved = self.resolve_ref("milestone", milestone_id)
        if current is not None and resolved == current:
            return resolved
        record = self.store.get_raw("milestone", resolved) or {}
        status = record.get("status")
        if status in CLOSED_MILESTONE_STATUSES:
            raise InvalidArgument(
                f"milestone {resolved} is {status}; tasks cannot be assigned to it"
            )
        return resolved

    def validate_task_parent_chain(self, task_id: str, parent_id: str | None) -> None:
        self._validate_chain("task", task_id, parent_id, "parent_task_id")

    def validate_goal_parent_chain(self, goal_id: str, parent_id: str | None) -> None:
        self._validate_chain("goal", goal_id, parent_id, "parent_goal_id")

    def validate_decision_supersede(self, old_id: str, new_id: str) -> None:
        seen = {old_id}
        record = self.store.get_raw("decision", old_id) or {}
        current = record.get("supersedes_id")
        hops = 0
        while current is not None:
            if current == new_id:
                raise HierarchyCycle(
                    f"decision {new_id} cannot supersede {old_id}: supersede chain would cycle",
                    {"old_id": old_id, "new_id": new_id},
                )
            if current in seen:
                raise HierarchyCycle(
                    "decision supersede chain already contains a cycle",
                    {"entity_id": old_id},
                )
            seen.add(current)
            hops += 1
            if hops > MAX_CHAIN_HOPS:
                raise HierarchyCycle("decision supersede chain too deep; possible corruption")
            record = self.store.get_raw("decision", current) or {}
            current = record.get("supersedes_id")

    def _validate_chain(self, obj_type: str, entity_id: str, parent_id: str | None, field: str) -> None:
        seen = {entity_id}
        current = parent_id
        hops = 0
        while current is not None:
            if current in seen:
                raise HierarchyCycle(
                    f"{obj_type} hierarchy would contain a cycle",
                    {"entity_id": entity_id, "parent_id": parent_id},
                )
            seen.add(current)
            hops += 1
            if hops > MAX_CHAIN_HOPS:
                raise HierarchyCycle(f"{obj_type} hierarchy too deep; possible corruption")
            record = self.store.get_raw(obj_type, current)
            current = record.get(field) if record else None
