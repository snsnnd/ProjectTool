"""pjt doctor：项目完整性检查。"""

from __future__ import annotations

from typing import Any

from project_tool.domain.enums import Lifecycle, TaskStatus
from project_tool.domain.errors import ProjectToolError
from project_tool.domain.hashing import verify_rev
from project_tool.domain.ids import PREFIX_BY_TYPE
from project_tool.graph.dependency import detect_cycles
from project_tool.storage.object_store import MODEL_BY_TYPE


def run_doctor(service) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors = 0
    warnings = 0

    def add(name: str, status: str, message: str, details: Any = None) -> None:
        nonlocal errors, warnings
        entry: dict[str, Any] = {"name": name, "status": status, "message": message}
        if details is not None:
            entry["details"] = details
        checks.append(entry)
        if status == "error":
            errors += 1
        elif status == "warning":
            warnings += 1

    project = service.opened.project
    add("project", "ok", f"{project.name} ({project.id}), schema {project.schema_version}")

    # ---- objects ----
    records_by_type: dict[str, list[dict[str, Any]]] = {}
    alive_ids: dict[str, set[str]] = {}
    all_ids: dict[str, set[str]] = {}
    total_objects = 0
    for obj_type in MODEL_BY_TYPE:
        try:
            records = service.store.list_raw(obj_type, include_deleted=True)
        except ProjectToolError as exc:
            add(f"objects.{obj_type}", "error", f"cannot read {obj_type} objects: {exc.message}")
            records_by_type[obj_type] = []
            continue
        total_objects += len(records)
        records_by_type[obj_type] = records
        all_ids[obj_type] = {record.get("id", "") for record in records}
        alive_ids[obj_type] = {
            record.get("id", "")
            for record in records
            if record.get("lifecycle") != Lifecycle.DELETED.value
        }

        problems: list[str] = []
        prefix = PREFIX_BY_TYPE[obj_type]
        for record in records:
            object_id = str(record.get("id", ""))
            if not object_id.startswith(prefix + "-"):
                problems.append(f"{object_id or '<missing id>'}: id prefix should be {prefix}-")
            if record.get("type") != obj_type:
                problems.append(f"{object_id}: type should be {obj_type!r}")
            if record.get("project_id") != project.id:
                problems.append(f"{object_id}: project_id mismatch")
            if not record.get("rev") or not verify_rev(record):
                problems.append(f"{object_id}: rev mismatch (content modified?)")
        if problems:
            add(f"objects.{obj_type}", "error", f"{len(problems)} problem(s) in {obj_type} objects", problems)
        else:
            add(f"objects.{obj_type}", "ok", f"{len(records)} {obj_type} object(s)")

    # ---- references ----
    ref_errors: list[str] = []
    ref_warnings: list[str] = []

    def check_ref(kind: str, ref: str | None, source: str) -> None:
        if not ref:
            return
        if ref in all_ids.get(kind, set()):
            if ref not in alive_ids.get(kind, set()):
                ref_warnings.append(f"{source}: {kind} {ref} is deleted/archived")
            return
        ref_errors.append(f"{source}: missing {kind} {ref}")

    for record in records_by_type.get("task", []):
        source = record.get("id", "?")
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        check_ref("milestone", record.get("milestone_id"), source)
        check_ref("task", record.get("parent_task_id"), source)
        for owner in record.get("owner_ids", []) or []:
            check_ref("member", owner, source)
        for dep in record.get("dependencies", []) or []:
            check_ref("task", dep.get("task_id"), source)

    for record in records_by_type.get("milestone", []):
        source = record.get("id", "?")
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        for goal_id in record.get("goal_ids", []) or []:
            check_ref("goal", goal_id, source)

    for record in records_by_type.get("goal", []):
        source = record.get("id", "?")
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        check_ref("goal", record.get("parent_goal_id"), source)

    for record in records_by_type.get("update", []):
        source = record.get("id", "?")
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        for task_id in record.get("task_ids", []) or []:
            check_ref("task", task_id, source)
        check_ref("milestone", record.get("milestone_id"), source)

    for record in records_by_type.get("decision", []):
        source = record.get("id", "?")
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        for task_id in record.get("related_task_ids", []) or []:
            check_ref("task", task_id, source)
        check_ref("decision", record.get("supersedes_id"), source)

    if ref_errors:
        add("references", "error", f"{len(ref_errors)} broken reference(s)", ref_errors)
    elif ref_warnings:
        add("references", "warning", f"{len(ref_warnings)} reference(s) to deleted objects", ref_warnings)
    else:
        add("references", "ok", "all references valid")

    # ---- dependency cycles ----
    try:
        tasks = {task.id: task for task in service.store.list_models("task")}
    except ProjectToolError as exc:
        tasks = {}
        add("dependencies", "error", f"cannot load tasks: {exc.message}")
    else:
        cycles = detect_cycles(tasks)
        if cycles:
            add("dependencies", "error", f"{len(cycles)} dependency cycle(s)", cycles)
        else:
            add("dependencies", "ok", f"{len(tasks)} task(s), no cycles")

        blocked_overrun = [
            task.id
            for task in tasks.values()
            if task.status == TaskStatus.BLOCKED and task.lifecycle == Lifecycle.ACTIVE
        ]
        if blocked_overrun:
            add("blocked", "ok", f"{len(blocked_overrun)} manually blocked task(s)", blocked_overrun)

    # ---- members ----
    handles: dict[str, str] = {}
    duplicate_handles: list[str] = []
    for record in records_by_type.get("member", []):
        handle = str(record.get("handle", "")).lower()
        if handle in handles:
            duplicate_handles.append(handle)
        handles[handle] = record.get("id", "?")
    if duplicate_handles:
        add("members", "error", f"duplicate handle(s): {', '.join(sorted(set(duplicate_handles)))}")
    elif not handles:
        add("members", "warning", "no members defined; run 'pjt member add'")
    else:
        add("members", "ok", f"{len(handles)} member(s)")

    # ---- events ----
    event_problems: list[str] = []
    orphan_events: list[str] = []
    event_count = 0
    orphan_statuses = {Lifecycle.DELETED.value}
    try:
        event_records = service.events.iter_records()
    except ProjectToolError as exc:
        event_records = []
        add("events", "error", f"cannot read events: {exc.message}")
    else:
        event_count = len(event_records)
        for record in event_records:
            event_id = record.get("id", "?")
            if record.get("project_id") != project.id:
                event_problems.append(f"{event_id}: project_id mismatch")
            entity_type = record.get("entity_type")
            entity_id = record.get("entity_id")
            if entity_type == "project":
                continue
            if entity_type and entity_type not in all_ids:
                event_problems.append(f"{event_id}: unknown entity_type {entity_type!r}")
                continue
            if entity_id and entity_id not in all_ids.get(entity_type, set()):
                orphan_events.append(f"{event_id}: entity {entity_id} missing")
        if event_problems:
            add("events", "error", f"{len(event_problems)} problem(s)", event_problems)
        elif orphan_events:
            add("events", "warning", f"{len(orphan_events)} event(s) reference missing objects", orphan_events)
        else:
            add("events", "ok", f"{event_count} event(s)")

    # ---- derived state / staging ----
    labels_path = service.paths.labels_json
    if not labels_path.is_file():
        add("refs.labels", "warning", "refs/labels.json missing (derived, will rebuild on next label change)")
    else:
        add("refs.labels", "ok", "labels ref present")

    state_path = service.paths.state_json
    if not state_path.is_file():
        add("state", "warning", "state/state.json missing (derived, safe to rebuild)")
    else:
        add("state", "ok", "derived state present")

    staging = service.paths.transactions
    leftovers = [path.name for path in staging.iterdir()] if staging.is_dir() else []
    if leftovers:
        add("transactions", "warning", f"{len(leftovers)} leftover staging dir(s); safe to delete", leftovers)
    else:
        add("transactions", "ok", "no leftover staging")

    return {
        "ok": errors == 0,
        "checks": checks,
        "summary": {
            "objects": total_objects,
            "events": event_count,
            "errors": errors,
            "warnings": warnings,
        },
    }
