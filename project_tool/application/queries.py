"""查询逻辑：项目状态、日志、工作量（读取 ServiceContext）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from project_tool.domain.enums import Lifecycle, MilestoneStatus, TaskStatus
from project_tool.domain.errors import NotFound
from project_tool.domain.interfaces import parse_front_matter
from project_tool.domain.task import claim_view
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


# ==================================================================== 接口契约相关


def interface_rows(ctx) -> list[dict[str, Any]]:
    """所有已登记的接口 Artifact + 其 front-matter 摘要（读不到就带 read_error）。

    **一次扫描，两处复用**：`task.related_interfaces` 和 `task.next` 都需要
    「接口 + 它的文档内容」。各自扫一遍会迟早分叉，所以收在这里。
    """
    rows: list[dict[str, Any]] = []
    for record in ctx.store.list_raw("artifact", include_deleted=False):
        metadata = record.get("metadata") or {}
        if metadata.get("interface") is not True:
            continue
        if record.get("lifecycle") == Lifecycle.DELETED.value:
            continue
        row: dict[str, Any] = {
            "artifact_id": record.get("id"),
            "name": record.get("name"),
            "locator": record.get("locator"),
            # ⚠ front-matter 的 `area` 是**名字**；`area_id` 保持 id。
            #   两者混用会导致按 area 匹配永远不成立。
            "area": None,
            "area_id": (record.get("related_area_ids") or [None])[0],
            "status": None,
            "consumers": [],
            "readable": False,
            "related_task_ids": list(record.get("related_task_ids") or []),
        }
        path = ctx.paths.root / str(record.get("locator") or "")
        if not path.is_file():
            row["read_error"] = "document not found"
            rows.append(row)
            continue
        try:
            data, _, error = parse_front_matter(path.read_text(encoding="utf-8"))
        except OSError as exc:
            row["read_error"] = str(exc)
            rows.append(row)
            continue
        if error is not None:
            row["read_error"] = error
            rows.append(row)
            continue
        row["readable"] = True
        row["name"] = data.get("name") or row["name"]
        row["status"] = data.get("status")
        row["area"] = data.get("area")
        row["consumers"] = data.get("consumers") or []
        rows.append(row)
    return rows


_REASON_ORDER = {"linked": 0, "same_area": 1, "mentioned": 2}


def interfaces_for_task(
    ctx,
    task_id: str,
    task_area_id: str | None,
    task_text: str,
    area_scope: bool = True,
) -> list[dict[str, Any]]:
    """和某个 task 相关的接口契约，按可信度排序。

    三条来源，每条**标明为什么被带出来**：
      linked     显式关联（`pjt artifact attach --task`），最准，是人明确说的
      same_area  同 Area，结构上可能相关，不一定真相关
      mentioned  接口名出现在 task 标题/描述里，弱信号

    刻意不合并、不排成「最相关」一条 —— 那是替人做判断。
    """
    haystack = task_text.lower()
    rows: list[dict[str, Any]] = []
    for row in interface_rows(ctx):
        entry = {key: value for key, value in row.items() if key != "related_task_ids"}
        if task_id in row["related_task_ids"]:
            entry["reason"] = "linked"
        elif area_scope and task_area_id and row["area_id"] == task_area_id:
            entry["reason"] = "same_area"
        elif row.get("name") and str(row["name"]).lower() in haystack:
            entry["reason"] = "mentioned"
        else:
            continue
        rows.append(entry)
    rows.sort(
        key=lambda item: (_REASON_ORDER.get(item["reason"], 9), str(item.get("name") or ""))
    )
    return rows


# ==================================================================== next（开工简报）

#: 可以开工的状态。`doing` 不在其中 —— 那说明已经有人在做了，
#: 把它列进「下一步」等于推荐和别人撞车。
WORKABLE_STATUSES = (TaskStatus.INBOX, TaskStatus.READY, TaskStatus.BLOCKED)

#: 优先级排序（小的先做）。critical 排在 high 前面。
_PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


def task_next(
    ctx,
    area=None,
    include_claimed: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """下一件该做的事 + 开工简报（**只读**，不做任何写入）。

    为什么值得做成一条命令：agent 开工前的正确顺序是固定的
    「找活 → 认领 → **读契约** → 看这块最近谁在动」，而漏掉第三步的代价最大
    —— agent 没有隐性知识，它不知道某个接口什么时候能改、什么算破坏性变更。
    把只读的那部分收进一条命令，就不容易漏。

    刻意**不**在这里顺带 claim：认领是一个决定，不是查询的一部分。
    「看一眼」和「占下来」应该分开，否则想看不能看、想占得先查一遍。

    选择顺序（确定性，不随机）：
      1. 未被认领优先（过期的不算占用）
      2. 未被阻塞优先
      3. 优先级 critical > high > normal > low
      4. 创建早的优先（老坑先填）
    """
    wanted_area = ctx.area_id(area) if area else None
    tasks = ctx.tasks_by_id(include_deleted=False)
    now = datetime.now().astimezone()

    candidates: list[tuple[tuple, Any, dict[str, Any]]] = []
    skipped_claimed = 0
    for task in tasks.values():
        if task.lifecycle != Lifecycle.ACTIVE or task.status not in WORKABLE_STATUSES:
            continue
        if wanted_area is not None and task.area_id != wanted_area:
            continue
        active_claim = claim_view(task.claim, now)
        if active_claim is not None:
            skipped_claimed += 1
            if not include_claimed:
                continue
        blocked, blockers = is_computed_blocked(task, tasks)
        candidates.append(
            (
                (
                    active_claim is not None,   # False(0) 优先于 True(1)
                    blocked,                    # 未阻塞优先
                    _PRIORITY_ORDER.get(task.priority.value, 9),
                    task.created_at,
                    task.id,
                ),
                task,
                {"blocked": blocked, "blockers": blockers, "claim": active_claim},
            )
        )

    if not candidates:
        return {
            "found": False,
            "task": None,
            "reason": _no_candidate_reason(wanted_area, skipped_claimed),
            "candidates": 0,
            "skipped_claimed": skipped_claimed,
            "interfaces": [],
            "area_note": None,
        }

    candidates.sort(key=lambda item: item[0])
    _, chosen, facts = candidates[0]
    record = ctx.task_view(chosen)
    return {
        "found": True,
        "task": record,
        "reason": _why_chosen(chosen, facts, wanted_area),
        "candidates": len(candidates),
        "skipped_claimed": skipped_claimed,
        "interfaces": interfaces_for_task(
            ctx,
            chosen.id,
            chosen.area_id,
            f"{chosen.title} {chosen.description}",
        ),
        "area_note": _area_note(ctx, chosen.area_id),
        "next_step": (
            f"pjt task claim {record['id']} --agent <handle>   "
            "# 认领之后才开始改；先读上面的 interfaces"
        ),
    }


def _why_chosen(task, facts, wanted_area) -> str:
    bits = [f"status={task.status.value}", f"priority={task.priority.value}"]
    if wanted_area is not None:
        bits.append("在指定 area 内")
    if facts["blocked"]:
        # 进得了候选说明依赖已满足（否则 computed_blocked 会把它排掉）
        bits.append("依赖已满足")
    if facts["claim"] is None:
        bits.append("无人认领")
    else:
        bits.append(f"原认领已过期（原主 {facts['claim']['member_id'][:12]}…）")
    return "，".join(bits)


def _no_candidate_reason(wanted_area, skipped_claimed) -> str:
    where = f"（area={wanted_area}）" if wanted_area else ""
    if skipped_claimed:
        return (
            f"没有可开工的任务{where}，但有 {skipped_claimed} 个已被认领。"
            "加 --include-claimed 可以看见它们，或等认领过期。"
        )
    return (
        f"没有可开工的任务{where}。"
        "可开工 = 状态为 inbox/ready/blocked、lifecycle=active、依赖已满足。"
    )


def _area_note(ctx, area_id) -> dict[str, Any] | None:
    """这块最近谁在动 —— 但**只报已提交历史**，并说明未提交改动看不见。

    刻意不在这里塞 git log 的细节：`area.activity` 已经管那件事了，
    这里只提醒「别以为看到了全部」。
    """
    if not area_id:
        return None
    record = ctx.store.get_raw("area", area_id) or {}
    return {
        "area_id": area_id,
        "area": record.get("name"),
        "owners": list(record.get("owner_ids") or []),
        "see": "pjt area activity --days 3   # 看这块最近谁在动",
        "caveat": (
            "已提交历史跟着 Git 走，所有人都能看到；"
            "**未提交改动只有本机可见**——看不到别人的在途工作。"
        ),
    }
