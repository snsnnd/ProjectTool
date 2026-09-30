"""依赖图算法：环检测、computed blocked、传递依赖。"""

from __future__ import annotations

from project_tool.domain.enums import DependencyRelation, TaskStatus
from project_tool.domain.task import Task

TERMINAL_STATUSES = {TaskStatus.DONE, TaskStatus.CANCELLED}


def dependency_map(tasks: dict[str, Task]) -> dict[str, list[str]]:
    """A -> [B, ...]，表示 A depends_on B。"""
    graph: dict[str, list[str]] = {}
    for task_id, task in tasks.items():
        graph[task_id] = [
            dep.task_id for dep in task.dependencies if dep.relation == DependencyRelation.DEPENDS_ON
        ]
    return graph


def find_path(graph: dict[str, list[str]], start: str, goal: str) -> list[str] | None:
    if start == goal:
        return [start]
    visited = {start}
    stack: list[tuple[str, list[str]]] = [(start, [start])]
    while stack:
        node, path = stack.pop()
        for nxt in graph.get(node, []):
            if nxt == goal:
                return path + [nxt]
            if nxt not in visited:
                visited.add(nxt)
                stack.append((nxt, path + [nxt]))
    return None


def would_create_cycle(tasks: dict[str, Task], source_id: str, target_id: str) -> list[str] | None:
    """在 A -> B（A depends_on B）加入前检查：若 B 可达 A，则新边会成环。"""
    graph = dependency_map(tasks)
    path = find_path(graph, target_id, source_id)
    if path is None:
        return None
    return [source_id] + path


def detect_cycles(tasks: dict[str, Task]) -> list[list[str]]:
    graph = dependency_map(tasks)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    cycles: list[list[str]] = []

    for start in graph:
        if color[start] != WHITE:
            continue
        color[start] = GRAY
        path = [start]
        stack: list[tuple[str, object]] = [(start, iter(graph.get(start, [])))]
        while stack:
            node, iterator = stack[-1]
            advanced = False
            for nxt in iterator:  # type: ignore[union-attr]
                if nxt not in graph:
                    continue
                if color[nxt] == GRAY:
                    idx = path.index(nxt)
                    cycles.append(path[idx:] + [nxt])
                elif color[nxt] == WHITE:
                    color[nxt] = GRAY
                    path.append(nxt)
                    stack.append((nxt, iter(graph.get(nxt, []))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
                path.pop()
    return cycles


def blocked_by(task: Task, tasks: dict[str, Task]) -> list[str]:
    """computed blocked：依赖未 done（或依赖已消失）即阻塞；不改任务自身状态。"""
    if task.status in TERMINAL_STATUSES:
        return []
    result: list[str] = []
    for dep in task.dependencies:
        if dep.relation != DependencyRelation.DEPENDS_ON:
            continue
        target = tasks.get(dep.task_id)
        if target is None or target.status != TaskStatus.DONE:
            result.append(dep.task_id)
    return result


def is_computed_blocked(task: Task, tasks: dict[str, Task]) -> tuple[bool, list[str]]:
    blockers = blocked_by(task, tasks)
    return bool(blockers), blockers


def transitive_dependencies(tasks: dict[str, Task], root_id: str, depth: int = 5) -> list[tuple[int, str]]:
    """返回 (层级, task_id) 列表，仅沿 depends_on 边。"""
    result: list[tuple[int, str]] = []
    seen = {root_id}
    frontier = [(root_id, 0)]
    while frontier:
        node, level = frontier.pop(0)
        if level >= depth:
            continue
        task = tasks.get(node)
        if task is None:
            continue
        for dep in task.dependencies:
            if dep.relation != DependencyRelation.DEPENDS_ON:
                continue
            if dep.task_id in seen:
                continue
            seen.add(dep.task_id)
            result.append((level + 1, dep.task_id))
            frontier.append((dep.task_id, level + 1))
    return result
