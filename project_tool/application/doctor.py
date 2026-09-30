"""pjt doctor：项目完整性检查（含事务/锁/事件链/project rev）。

每个 check 带有 `repairable` 标记：true 表示可通过
`pjt doctor --repair`（`project.recover`）自动恢复。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from project_tool.domain.enums import Lifecycle
from project_tool.domain.errors import ProjectToolError
from project_tool.domain.hashing import verify_rev
from project_tool.domain.ids import COLLECTION_BY_TYPE, PREFIX_BY_TYPE
from project_tool.graph.dependency import detect_cycles
from project_tool.storage.local_state import lock_is_stale, process_alive, read_lock
from project_tool.storage.object_store import MODEL_BY_TYPE
from project_tool.storage.recovery import (
    STATUS_INVALID,
    scan_transactions,
)


def run_doctor(ctx) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    errors = 0
    warnings = 0
    repairable_count = 0

    def add(
        name: str,
        status: str,
        message: str,
        details: Any = None,
        repairable: bool = False,
    ) -> None:
        nonlocal errors, warnings, repairable_count
        entry: dict[str, Any] = {
            "name": name,
            "status": status,
            "message": message,
            "repairable": bool(repairable),
        }
        if details is not None:
            entry["details"] = details
        checks.append(entry)
        if status == "error":
            errors += 1
        elif status == "warning":
            warnings += 1
        if repairable:
            repairable_count += 1

    project = ctx.opened.project

    # ------------------------------------------------------------- project
    project_record = project.to_record()
    project_rev = project_record.get("rev") or ""
    if project.type != "project" or not project.id.startswith("PRJ-"):
        add("project", "error", "project.json header invalid (type/id)")
    elif not project_rev:
        add(
            "project",
            "warning",
            "project.json has no rev (legacy); it will be set on the next write",
        )
    elif not verify_rev(project_record):
        add("project", "error", "project.json rev mismatch (content modified?)")
    else:
        add("project", "ok", f"{project.name} ({project.id}), schema {project.schema_version}, rev ok")

    # ------------------------------------------------------------- objects
    records_by_type: dict[str, list[dict[str, Any]]] = {}
    all_ids: dict[str, set[str]] = {}
    alive_ids: dict[str, set[str]] = {}
    current_revs: dict[tuple[str, str], str | None] = {}
    total_objects = 0

    for obj_type in MODEL_BY_TYPE:
        try:
            records = ctx.store.list_raw(obj_type, include_deleted=True)
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
        for record in records:
            current_revs[(obj_type, str(record.get("id", "")))] = record.get("rev") or None

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

    # ------------------------------------------------------------- object layout
    # 旧项目（V0.1）没有 areas/ 等新集合目录：不是损坏，只是还没迁移。
    missing_collections = sorted(
        collection
        for collection in COLLECTION_BY_TYPE.values()
        if not (ctx.paths.objects / collection).is_dir()
    )
    if missing_collections:
        add(
            "objects.layout",
            "warning",
            f"missing object collection dir(s): {', '.join(missing_collections)}; "
            "run 'pjt migrate' (empty collections read as [] in the meantime)",
            missing_collections,
        )
    else:
        add("objects.layout", "ok", "all object collection dirs present")

    # ------------------------------------------------------------- references
    ref_errors: list[str] = []
    ref_warnings: list[str] = []

    def check_ref(kind: str, ref: str | None, source: str) -> None:
        if not ref:
            return
        if ref in all_ids.get(kind, set()):
            if ref not in alive_ids.get(kind, set()):
                ref_warnings.append(f"{source}: {kind} {ref} is deleted")
            return
        ref_errors.append(f"{source}: missing {kind} {ref}")

    for record in records_by_type.get("task", []):
        source = str(record.get("id", "?"))
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        check_ref("milestone", record.get("milestone_id"), source)
        check_ref("area", record.get("area_id"), source)
        check_ref("task", record.get("parent_task_id"), source)
        for owner in record.get("owner_ids", []) or []:
            check_ref("member", owner, source)
        for dep in record.get("dependencies", []) or []:
            check_ref("task", dep.get("task_id"), source)

    for record in records_by_type.get("area", []):
        source = str(record.get("id", "?"))
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        check_ref("area", record.get("parent_area_id"), source)

    for record in records_by_type.get("milestone", []):
        source = str(record.get("id", "?"))
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        for goal_id in record.get("goal_ids", []) or []:
            check_ref("goal", goal_id, source)

    for record in records_by_type.get("goal", []):
        source = str(record.get("id", "?"))
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        check_ref("goal", record.get("parent_goal_id"), source)

    for record in records_by_type.get("update", []):
        source = str(record.get("id", "?"))
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        for task_id in record.get("task_ids", []) or []:
            check_ref("task", task_id, source)
        check_ref("milestone", record.get("milestone_id"), source)

    for record in records_by_type.get("decision", []):
        source = str(record.get("id", "?"))
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

    # ------------------------------------------------------------- dependencies
    try:
        tasks = {task.id: task for task in ctx.store.list_models("task")}
    except ProjectToolError as exc:
        tasks = {}
        add("dependencies", "error", f"cannot load tasks: {exc.message}")
    else:
        cycles = detect_cycles(tasks)
        if cycles:
            add("dependencies", "error", f"{len(cycles)} dependency cycle(s)", cycles)
        else:
            add("dependencies", "ok", f"{len(tasks)} task(s), no cycles")

        hierarchy_cycles = _hierarchy_cycles(ctx, records_by_type)
        if hierarchy_cycles:
            add("hierarchy", "error", f"{len(hierarchy_cycles)} hierarchy cycle(s)", hierarchy_cycles)
        else:
            add("hierarchy", "ok", "goal/area/task/decision hierarchies acyclic")

    # ------------------------------------------------------------- members
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

    # ------------------------------------------------------------- events
    event_problems: list[str] = []
    orphan_events: list[str] = []
    event_count = 0
    chain_errors: list[str] = []
    legacy_chains = 0
    try:
        event_records = ctx.events.iter_records()
    except ProjectToolError as exc:
        event_records = []
        add("events", "error", f"cannot read events: {exc.message}")
    else:
        event_count = len(event_records)
        entity_events: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for record in event_records:
            event_id = record.get("id", "?")
            if record.get("project_id") != project.id:
                event_problems.append(f"{event_id}: project_id mismatch")
            entity_type = record.get("entity_type")
            entity_id = record.get("entity_id")
            if entity_type == "project":
                entity_events[("project", str(entity_id))].append(record)
                continue
            if entity_type and entity_type not in all_ids:
                event_problems.append(f"{event_id}: unknown entity_type {entity_type!r}")
                continue
            if entity_id and entity_id not in all_ids.get(entity_type, set()):
                orphan_events.append(f"{event_id}: entity {entity_id} missing")
                continue
            if entity_id:
                entity_events[(str(entity_type), str(entity_id))].append(record)

        if event_problems:
            add("events", "error", f"{len(event_problems)} problem(s)", event_problems)
        elif orphan_events:
            add(
                "events",
                "warning",
                f"{len(orphan_events)} event(s) reference missing objects",
                orphan_events,
            )
        else:
            add("events", "ok", f"{event_count} event(s)")

        chain_errors, legacy_chains, missing_events = _event_chain_check(
            entity_events, current_revs, project_rev
        )
        if chain_errors or missing_events:
            details = chain_errors + missing_events
            add("events.chain", "error", f"{len(details)} event chain problem(s)", details)
        elif legacy_chains:
            add(
                "events.chain",
                "warning",
                f"{legacy_chains} entity chain(s) without rev (legacy data)",
            )
        else:
            add("events.chain", "ok", "base_rev/new_rev chains consistent with objects")

    # ------------------------------------------------------------- transactions
    scans = scan_transactions(ctx.paths)
    if not scans:
        add("transactions", "ok", "no pending transactions")
    else:
        details = [f"{scan.transaction_id} [{scan.status}] {scan.detail}" for scan in scans]
        hard = [scan for scan in scans if not scan.repairable]
        if hard:
            add(
                "transactions",
                "error",
                f"{len(hard)} transaction(s) require manual inspection "
                f"({len(scans) - len(hard)} repairable)",
                details,
            )
        elif any(scan.status == STATUS_INVALID for scan in scans):
            add(
                "transactions",
                "warning",
                f"{len(scans)} invalid transaction(s); repair discards uncommitted staging",
                details,
                repairable=True,
            )
        else:
            add(
                "transactions",
                "warning",
                f"{len(scans)} recoverable transaction(s); run 'pjt doctor --repair'",
                details,
                repairable=True,
            )

    # ------------------------------------------------------------- write lock
    lock_info = read_lock(ctx.paths)
    lock_file = ctx.paths.locks / "write.lock"
    if lock_info is None:
        if lock_file.is_file():
            if lock_is_stale(ctx.paths):
                add(
                    "write.lock",
                    "warning",
                    "unparseable stale lock file; repair removes it",
                    repairable=True,
                )
            else:
                add("write.lock", "warning", "unparseable lock file is present")
        else:
            add("write.lock", "ok", "no active write lock")
    else:
        pid = lock_info.get("pid")
        if isinstance(pid, int) and process_alive(pid):
            add(
                "write.lock",
                "warning",
                f"held by live pid {pid} (host {lock_info.get('host', '?')})",
            )
        elif lock_is_stale(ctx.paths):
            add(
                "write.lock",
                "warning",
                "stale lock (owner process is gone); repair removes it",
                repairable=True,
            )
        else:
            add("write.lock", "warning", "lock present but owner just exited; retry later")

    # ------------------------------------------------------------- derived refs
    if not ctx.paths.labels_json.is_file():
        add("refs.labels", "warning", "refs/labels.json missing (derived)")
    else:
        add("refs.labels", "ok", "labels ref present")

    if not ctx.paths.state_json.is_file():
        add("state", "warning", "state/state.json missing (derived)")
    else:
        add("state", "ok", "derived state present")

    return {
        "ok": errors == 0,
        "checks": checks,
        "summary": {
            "objects": total_objects,
            "events": event_count,
            "errors": errors,
            "warnings": warnings,
            "repairable": repairable_count,
        },
    }


def _hierarchy_cycles(ctx, records_by_type: dict[str, list[dict[str, Any]]]) -> list[str]:
    found: list[str] = []

    for obj_type, field in (
        ("goal", "parent_goal_id"),
        ("area", "parent_area_id"),
        ("task", "parent_task_id"),
    ):
        parents = {
            str(record.get("id")): record.get(field)
            for record in records_by_type.get(obj_type, [])
            if record.get("lifecycle") != Lifecycle.DELETED.value
        }
        for start in parents:
            seen = {start}
            current = parents.get(start)
            while current is not None:
                if current in seen:
                    found.append(f"{obj_type} parent cycle at {start}")
                    break
                seen.add(current)
                if current not in parents:
                    break
                current = parents.get(current)

    decisions = {
        str(record.get("id")): record.get("supersedes_id")
        for record in records_by_type.get("decision", [])
    }
    for start in decisions:
        seen = {start}
        current = decisions.get(start)
        while current is not None:
            if current in seen:
                found.append(f"decision supersede cycle at {start}")
                break
            seen.add(current)
            current = decisions.get(current)

    return found


def _event_chain_check(
    entity_events: dict[tuple[str, str], list[dict[str, Any]]],
    current_revs: dict[tuple[str, str], str | None],
    project_rev: str,
) -> tuple[list[str], int, list[str]]:
    chain_errors: list[str] = []
    legacy_chains = 0
    missing_events: list[str] = []

    for key, records in entity_events.items():
        ordered = sorted(records, key=lambda record: str(record.get("id", "")))
        if any(record.get("new_rev") is None for record in ordered):
            legacy_chains += 1
            continue
        expected: str | None = None
        broken = False
        for record in ordered:
            base = record.get("base_rev")
            if base != expected:
                chain_errors.append(
                    f"{key[0]} {key[1]}: event {record.get('id')} base_rev {base!r} "
                    f"does not follow previous new_rev {expected!r}"
                )
                broken = True
                break
            expected = record.get("new_rev")
        if broken:
            continue
        current = project_rev or None if key[0] == "project" else current_revs.get(key)
        if current is not None and expected != current:
            chain_errors.append(
                f"{key[0]} {key[1]}: last event new_rev {expected!r} != current rev {current!r}"
            )

    for key in current_revs:
        if key not in entity_events:
            missing_events.append(f"{key[0]} {key[1]}: no events found for existing object")

    return chain_errors, legacy_chains, missing_events
