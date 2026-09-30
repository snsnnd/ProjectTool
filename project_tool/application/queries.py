"""查询逻辑：项目状态、日志、工作量（读取 ServiceContext）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from project_tool.domain.enums import Lifecycle, MilestoneStatus, TaskStatus
from project_tool.domain.errors import NotFound
from project_tool.domain.timeutil import parse_time_spec
from project_tool.graph.dependency import is_computed_blocked
from project_tool.graph.project_graph import milestone_summary, task_summary

TERMINAL_TASK_STATUSES = {TaskStatus.DONE, TaskStatus.CANCELLED}


def event_summary(record: dict[str, Any], include_payload: bool = True) -> dict[str, Any]:
    summary = {
        "id": record.get("id"),
        "occurred_at": record.get("occurred_at"),
        "event_type": record.get("event_type"),
        "entity_type": record.get("entity_type"),
        "entity_id": record.get("entity_id"),
        "actor_id": record.get("actor_id"),
    }
    if include_payload:
        summary["payload"] = record.get("payload", {})
    return summary


def project_status(ctx, recent_limit: int = 10) -> dict[str, Any]:
    tasks = {task.id: task for task in ctx.store.list_models("task")}
    milestones = ctx.store.list_models("milestone")
    goals = ctx.store.list_models("goal")

    status_counts: dict[str, int] = {status.value: 0 for status in TaskStatus}
    for task in tasks.values():
        if task.lifecycle == Lifecycle.ACTIVE:
            status_counts[task.status.value] += 1

    active_milestones = [
        milestone
        for milestone in milestones
        if milestone.status == MilestoneStatus.ACTIVE and milestone.lifecycle == Lifecycle.ACTIVE
    ]
    active_milestones.sort(key=lambda milestone: milestone.id)
    milestone_views = [milestone_summary(milestone, tasks) for milestone in active_milestones]

    # 归属用**名字**而不是 ID：blocked 列表里只有短 ID 解决不了「这条属于哪块」。
    # 直接把名字放进条目，而不是往 status 里塞一份完整的 areas 列表
    # （V1-A 的决定：pjt status 不列举所有 Area，避免信息过载）。
    area_names = {
        area.id: area.name
        for area in cast(list[Any], ctx.store.list_models("area"))
        if getattr(area, "lifecycle", None) == Lifecycle.ACTIVE
    }
    milestone_titles = {
        milestone.id: milestone.title for milestone in milestones
    }

    blocked: list[dict[str, Any]] = []
    for task in sorted(tasks.values(), key=lambda item: item.id):
        if task.lifecycle != Lifecycle.ACTIVE or task.status in TERMINAL_TASK_STATUSES:
            continue
        is_blocked, blockers = is_computed_blocked(task, tasks)
        if is_blocked:
            blocked.append(
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "area_id": task.area_id,
                    "area_name": area_names.get(task.area_id) if task.area_id else None,
                    "milestone_id": task.milestone_id,
                    "milestone_title": (
                        milestone_titles.get(task.milestone_id) if task.milestone_id else None
                    ),
                    "blocked_by": blockers,
                }
            )

    recent = [
        event_summary(record)
        for record in ctx.events.iter_records(newest_first=True)[:recent_limit]
    ]

    workloads: list[dict[str, Any]] = []
    for member in sorted(ctx.store.list_models("member"), key=lambda item: item.id):
        if not getattr(member, "active", False) or member.lifecycle != Lifecycle.ACTIVE:
            continue
        owned = [
            task
            for task in tasks.values()
            if member.id in task.owner_ids
            and task.lifecycle == Lifecycle.ACTIVE
            and task.status not in TERMINAL_TASK_STATUSES
        ]
        workloads.append(
            {
                "member_id": member.id,
                "handle": member.handle,
                "display_name": member.display_name,
                "active_tasks": len(owned),
                "doing": sum(1 for task in owned if task.status == TaskStatus.DOING),
                "blocked": sum(1 for task in owned if task.status == TaskStatus.BLOCKED),
            }
        )

    links = [
        {
            "id": link.id,
            "name": link.name,
            "kind": link.target.kind.value,
            "mode": link.mode.value,
            "enabled": link.enabled,
            "locator": link.target.locator,
        }
        for link in ctx.store.list_models("link")
        if link.lifecycle == Lifecycle.ACTIVE
    ]

    return {
        "project": ctx.opened.project.to_record(),
        "goals": [
            {"id": goal.id, "title": goal.title, "status": goal.status.value}
            for goal in sorted(goals, key=lambda item: item.id)
            if goal.lifecycle == Lifecycle.ACTIVE
        ],
        "milestones": milestone_views,
        "active_milestone": milestone_views[0] if milestone_views else None,
        "tasks": status_counts,
        "blocked": blocked,
        "recent_events": recent,
        "members": workloads,
        "links": links,
    }


def log_list(
    ctx,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_type: str | None = None,
    member: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    full_entity_id = None
    if entity_id:
        found = ctx.store.find(entity_id)
        full_entity_id = found[1] if found else str(entity_id).upper()

    actor_id = None
    if member:
        actor_id = ctx.member_id(member)

    since_dt = parse_time_spec(since) if since else None
    until_dt = parse_time_spec(until) if until else None
    limit = max(1, min(int(limit), 500))

    records = ctx.events.iter_records(newest_first=True)
    matched: list[dict[str, Any]] = []
    for record in records:
        if cursor and str(record.get("id", "")) >= cursor:
            continue
        if entity_type and record.get("entity_type") != entity_type:
            continue
        if full_entity_id and record.get("entity_id") != full_entity_id:
            continue
        if event_type:
            actual = str(record.get("event_type", ""))
            if actual != event_type and not actual.startswith(event_type + "."):
                continue
        if actor_id and record.get("actor_id") != actor_id:
            continue
        occurred_at = record.get("occurred_at")
        if since_dt or until_dt:
            try:
                moment = datetime.fromisoformat(str(occurred_at))
            except ValueError:
                moment = None
            if moment is not None:
                if since_dt and moment < since_dt:
                    continue
                if until_dt and moment > until_dt:
                    continue
        matched.append(record)

    page = matched[:limit]
    next_cursor = page[-1]["id"] if len(matched) > limit and page else None
    return {
        "events": [event_summary(record) for record in page],
        "count": len(page),
        "next_cursor": next_cursor,
    }


def member_workload(ctx, member_id: str) -> dict[str, Any]:
    record = ctx.store.get_raw("member", member_id)
    if record is None:
        raise NotFound(f"member {member_id} not found")
    tasks = {task.id: task for task in ctx.store.list_models("task")}
    owned = [task for task in tasks.values() if member_id in task.owner_ids]
    by_status: dict[str, list[dict[str, Any]]] = {}
    for task in sorted(owned, key=lambda item: item.id):
        by_status.setdefault(task.status.value, []).append(task_summary(task, tasks))
    return {
        "member": {
            "id": record["id"],
            "handle": record.get("handle"),
            "display_name": record.get("display_name"),
            "active": record.get("active", True),
        },
        "total": len(owned),
        "by_status": by_status,
    }
