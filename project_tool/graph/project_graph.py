"""项目图构建：任务树、项目树、依赖图。纯函数，不接触 I/O。"""

from __future__ import annotations

from typing import Any

from project_tool.domain.enums import DependencyRelation, Lifecycle, MilestoneStatus, TaskStatus
from project_tool.domain.link import Link
from project_tool.domain.milestone import Milestone
from project_tool.domain.project import Project
from project_tool.domain.goal import Goal
from project_tool.domain.task import Task
from project_tool.graph.dependency import is_computed_blocked


def task_summary(task: Task, tasks: dict[str, Task]) -> dict[str, Any]:
    blocked, blocked_by_ids = is_computed_blocked(task, tasks)
    return {
        "id": task.id,
        "short_id": task.id,
        "title": task.title,
        "status": task.status.value,
        "priority": task.priority.value,
        "weight": task.weight,
        "milestone_id": task.milestone_id,
        "parent_task_id": task.parent_task_id,
        "owner_ids": list(task.owner_ids),
        "labels": list(task.labels),
        "computed_blocked": blocked,
        "blocked_by": blocked_by_ids,
        "lifecycle": task.lifecycle.value,
    }


def build_task_graph(
    tasks: dict[str, Task],
    milestone_id: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    selected = {
        task_id: task
        for task_id, task in tasks.items()
        if (milestone_id is None or task.milestone_id == milestone_id)
        and (include_archived or task.lifecycle == Lifecycle.ACTIVE)
    }
    ids = set(selected)
    nodes = [task_summary(task, tasks) for task in _sorted_tasks(selected.values())]
    edges: list[dict[str, str]] = []
    for task in selected.values():
        if task.parent_task_id in ids:
            edges.append({"from": task.parent_task_id, "to": task.id, "kind": "contains"})
        for dep in task.dependencies:
            if dep.task_id in ids:
                edges.append({"from": task.id, "to": dep.task_id, "kind": dep.relation.value})
    return {"nodes": nodes, "edges": edges}


def build_dependency_graph(
    tasks: dict[str, Task],
    task_id: str | None = None,
    depth: int = 5,
) -> dict[str, Any]:
    if task_id is not None:
        root = tasks.get(task_id)
        if root is None:
            selected: dict[str, Task] = {}
        else:
            selected = {task_id: root}
            seen = {task_id}
            frontier: list[tuple[str, int]] = [(task_id, 0)]
            while frontier:
                node, level = frontier.pop(0)
                if level >= depth:
                    continue
                current = tasks.get(node)
                if current is None:
                    continue
                for dep in current.dependencies:
                    if dep.task_id not in seen:
                        seen.add(dep.task_id)
                        target = tasks.get(dep.task_id)
                        if target is not None:
                            selected[dep.task_id] = target
                        frontier.append((dep.task_id, level + 1))
    else:
        selected = tasks

    ids = set(selected)
    nodes = [task_summary(task, tasks) for task in _sorted_tasks(selected.values())]
    edges: list[dict[str, str]] = []
    for task in selected.values():
        for dep in task.dependencies:
            if dep.relation == DependencyRelation.DEPENDS_ON and dep.task_id in ids:
                edges.append({"from": task.id, "to": dep.task_id, "kind": dep.relation.value})
    return {"nodes": nodes, "edges": edges}


def milestone_summary(milestone: Milestone, tasks: dict[str, Task]) -> dict[str, Any]:
    done_weight = 0
    total_weight = 0
    task_ids: list[str] = []
    status_counts: dict[str, int] = {}
    for task in tasks.values():
        if task.milestone_id != milestone.id or task.lifecycle != Lifecycle.ACTIVE:
            continue
        task_ids.append(task.id)
        status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1
        if task.status == TaskStatus.CANCELLED:
            continue
        total_weight += task.weight
        if task.status == TaskStatus.DONE:
            done_weight += task.weight
    progress = round(done_weight / total_weight, 4) if total_weight else 0.0
    return {
        "id": milestone.id,
        "title": milestone.title,
        "status": milestone.status.value,
        "goal_ids": list(milestone.goal_ids),
        "due_at": milestone.due_at.isoformat() if milestone.due_at else None,
        "task_ids": sorted(task_ids),
        "task_status_counts": status_counts,
        "done_weight": done_weight,
        "total_weight": total_weight,
        "progress": progress,
        "empty": total_weight == 0,
    }


def build_project_tree(
    project: Project,
    goals: list[Goal],
    milestones: list[Milestone],
    tasks: dict[str, Task],
    links: list[Link],
) -> dict[str, Any]:
    active_goals = [g for g in goals if g.lifecycle == Lifecycle.ACTIVE]
    active_milestones = [m for m in milestones if m.lifecycle == Lifecycle.ACTIVE]
    active_links = [link for link in links if link.lifecycle == Lifecycle.ACTIVE and link.enabled]

    milestones_by_goal: dict[str, list[str]] = {}
    for milestone in active_milestones:
        for goal_id in milestone.goal_ids:
            milestones_by_goal.setdefault(goal_id, []).append(milestone.id)

    return {
        "project": {"id": project.id, "name": project.name, "status": project.status.value},
        "goals": [
            {
                "id": goal.id,
                "title": goal.title,
                "status": goal.status.value,
                "milestone_ids": milestones_by_goal.get(goal.id, []),
            }
            for goal in active_goals
        ],
        "milestones": [milestone_summary(m, tasks) for m in active_milestones],
        "links": [
            {
                "id": link.id,
                "name": link.name,
                "kind": link.target.kind.value,
                "mode": link.mode.value,
                "enabled": link.enabled,
            }
            for link in active_links
        ],
    }


def _sorted_tasks(tasks) -> list[Task]:
    return sorted(tasks, key=lambda task: task.id)
