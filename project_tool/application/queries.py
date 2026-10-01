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


# ==================================================================== Area 活跃度


def _member_by_git_identity(members: list[dict[str, Any]]) -> dict[str, str]:
    """git author name / email -> member id。

    依赖 V1-B 的 `Member.git`（`pjt member map-git` 填的）。没映射的 author
    会原样出现在 `unmapped_authors` 里，让人知道该去补映射，而不是让 commit
    变成「某个不明来源的人」。
    """
    table: dict[str, str] = {}
    for record in members:
        member_id = str(record.get("id") or "")
        if not member_id:
            continue
        identity = record.get("git") or {}
        for name in identity.get("names") or []:
            table[str(name).strip().lower()] = member_id
        for email in identity.get("emails") or []:
            table[str(email).strip().lower()] = member_id
    return table


def area_activity(ctx, days: int = 7, limit: int = 200, area=None) -> dict[str, Any]:
    """最近谁在哪个 Area 里动代码（**从 Git 推导，零新状态**）。

    ## 两半的信息量完全不同，必须分开呈现

    - **已提交历史**：跟着 Git 走，**所有人都能看到**。这是本方法的主体。
    - **未提交改动**：`git status` 只有本机可见。**别人的在途工作本工具看不到**，
      所以只报本机的，并明确标注——不能让人以为「没出现在这里就是没人动」。

    归因链：commit 的文件 -> `Area.path_patterns` 匹配出 Area ->
    commit 的 author name/email -> `Member.git` 匹配出 Member。
    任何一环匹配不上就如实说匹配不上，不猜。
    """
    from project_tool.domain.area_paths import match_any
    from project_tool.integrations import git as git_integration

    window = max(1, int(days))
    areas = [
        area_model
        for area_model in ctx.store.list_models("area")
        if getattr(area_model, "lifecycle", None) == Lifecycle.ACTIVE
    ]
    areas.sort(key=lambda item: item.name)
    wanted = ctx.area_id(area) if area else None
    if wanted:
        areas = [item for item in areas if item.id == wanted]
    bindable = [item for item in areas if item.path_patterns]

    availability = git_integration.availability(ctx.paths.root)
    result: dict[str, Any] = {
        "available": bool(availability.get("available")),
        "reason": availability.get("reason"),
        "days": window,
        "areas": [],
        "unmapped_authors": [],
        "unmapped_files": [],
        "local_uncommitted": [],
    }
    if not availability.get("available"):
        return result

    try:
        repo = git_integration.detect(ctx.paths.root)
    except git_integration.GitUnavailable as exc:
        result["reason"] = str(exc)
        return result

    # git root 相对 project root 的前缀（EFW 场景：.pjt 在 new/efw 下）
    prefix = _project_subdir_prefix(ctx, repo)
    # 空仓库上 `git log` 会直接失败。**空历史不等于 git 不可用**——新项目刚
    # `pjt init` 还没提交过是正常状态，应该照常返回「所有 Area 都没有活动」，
    # 而不是抛 traceback。
    commits = (
        repo.log(limit=max(1, int(limit)), with_files=True, since=f"{window}.days.ago")
        if repo.has_commits()
        else []
    )

    members = ctx.store.list_raw("member")
    identity = _member_by_git_identity(members)
    handle_by_id = {
        str(record.get("id")): record.get("handle") for record in members if record.get("id")
    }

    per_area: dict[str, dict[str, Any]] = {}
    unmapped_authors: dict[str, int] = {}
    unmapped_files: set[str] = set()

    for commit in commits:
        matched: dict[str, list[str]] = {}
        for raw_path in commit.get("files") or []:
            relative = raw_path
            if prefix and relative.startswith(prefix):
                relative = relative[len(prefix):]
            elif prefix:
                # 文件不在 project root 下（框架根上的其它目录），与 Area 无关
                continue
            hit = next(
                (item for item in bindable if match_any(item.path_patterns, relative)), None
            )
            if hit is None:
                if bindable:
                    unmapped_files.add(relative)
                continue
            matched.setdefault(hit.id, []).append(relative)

        author_key = (commit.get("author_email") or commit.get("author") or "").strip().lower()
        member_id = identity.get(author_key) or identity.get(
            (commit.get("author") or "").strip().lower()
        )
        if member_id is None:
            unmapped_authors[str(commit.get("author") or "?")] = (
                unmapped_authors.get(str(commit.get("author") or "?"), 0) + 1
            )

        for area_id, files in matched.items():
            bucket = per_area.setdefault(
                area_id,
                {"commits": 0, "files": set(), "people": {}},
            )
            bucket["commits"] += 1
            bucket["files"].update(files)
            if member_id:
                person = bucket["people"].setdefault(
                    member_id, {"commits": 0, "files": set()}
                )
                person["commits"] += 1
                person["files"].update(files)

    rows = []
    for area_model in areas:
        area_bucket = per_area.get(area_model.id)
        people = []
        if area_bucket:
            for member_id, data in sorted(
                area_bucket["people"].items(), key=lambda item: -item[1]["commits"]
            ):
                people.append(
                    {
                        "member_id": member_id,
                        "handle": handle_by_id.get(member_id, member_id),
                        "commits": data["commits"],
                        "files": sorted(data["files"]),
                    }
                )
        rows.append(
            {
                "area_id": area_model.id,
                "name": area_model.name,
                "owner_ids": list(area_model.owner_ids),
                "bound": bool(area_model.path_patterns),
                # 注意用 area_bucket：外层的 `bucket` 是遍历 commit 时的循环变量，
                # 循环结束后仍留着最后一次的值，会让所有 Area 都变成 active
                "active": bool(area_bucket),
                "commits": area_bucket["commits"] if area_bucket else 0,
                "files": sorted(area_bucket["files"]) if area_bucket else [],
                "people": people,
            }
        )

    result["areas"] = rows
    result["unmapped_authors"] = [
        {"author": author, "commits": count}
        for author, count in sorted(unmapped_authors.items(), key=lambda i: -i[1])
    ]
    result["unmapped_files"] = sorted(unmapped_files)
    result["local_uncommitted"] = _local_uncommitted(ctx, bindable, prefix)
    result["scanned_commits"] = len(commits)
    return result


def _project_subdir_prefix(ctx, repo) -> str:
    """project root 相对 git root 的 posix 前缀；同根时是空串。"""
    root = ctx.paths.root.resolve()
    work_tree = repo.work_tree.resolve()
    if root == work_tree:
        return ""
    try:
        return root.relative_to(work_tree).as_posix() + "/"
    except ValueError:
        return ""


def _local_uncommitted(ctx, bindable, prefix: str) -> list[dict[str, Any]]:
    """**本机**未提交改动按 Area 归类。

    只有本机可见——所以调用方必须把这一段标成「仅本机」，
    不然读者会误以为它代表了所有人。
    """
    from project_tool.domain.area_paths import match_any
    from project_tool.integrations import git as git_integration

    if not bindable:
        return []
    try:
        repo = git_integration.detect(ctx.paths.root)
        entries = repo.status()
    except git_integration.GitUnavailable:
        return []
    buckets: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path = entry.path
        if prefix:
            if not path.startswith(prefix):
                continue
            path = path[len(prefix):]
        hit = next(
            (item for item in bindable if match_any(item.path_patterns, path)), None
        )
        if hit is None:
            continue
        bucket = buckets.setdefault(hit.id, {"files": [], "codes": set()})
        bucket["files"].append(path)
        bucket["codes"].add(entry.status)
    rows = []
    for area_model in bindable:
        # 换个变量名：上面的 bucket 已经被 setdefault 推断成 dict，
        # 复用同名会让 mypy 认为这里在给非 Optional 赋 Optional
        local_bucket = buckets.get(area_model.id)
        if not local_bucket:
            continue
        rows.append(
            {
                "area_id": area_model.id,
                "name": area_model.name,
                "files": sorted(local_bucket["files"]),
                "codes": sorted(local_bucket["codes"]),
            }
        )
    return rows


# ==================================================================== 认领（claim）
#
# 判定逻辑在 `project_tool.domain.task`（领域层）——`project_graph` 和 `queries`
# 互相依赖，认领判定被两边都要用，放应用层必然成环。这里只做转发。
