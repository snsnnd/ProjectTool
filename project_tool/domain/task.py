"""Task：最核心对象。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from project_tool.domain.base import BaseObject
from project_tool.domain.enums import DependencyRelation, Priority, TaskStatus


class Claim(BaseModel):
    """一次认领（V1-C，面向多 agent / 多人并发）。

    **它不是锁，也不是权限门禁。** 目的是让「有人在动这个 task」在**动手之前**
    就可见，而不是等到写入那一刻撞 `REVISION_CONFLICT` —— 那时整个任务已经做完了。

    为什么人不会撞、agent 会撞：人改到一半会先问一句「有人在改吗」，agent 不会。
    人类撞了重试几秒钟；agent 撞了意味着读了代码、改了工作树、调了工具，全部作废。

    `expires_at` 是**必须的**：agent 会崩，锁不能等它释放。过期即失效，
    不需要任何清理任务 —— 判定是**派生**的（比较时间戳），所以不存在陈旧状态，
    和 `state.json` / `labels.json` 一样不进版本控制。
    """

    model_config = ConfigDict(extra="forbid")

    member_id: str
    claimed_at: datetime
    expires_at: datetime
    note: str = ""


class Dependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    relation: DependencyRelation = DependencyRelation.DEPENDS_ON


class Task(BaseObject):
    type: Literal["task"] = "task"

    title: str
    description: str = ""

    status: TaskStatus = TaskStatus.INBOX
    priority: Priority = Priority.NORMAL
    weight: int = Field(default=1, ge=1)

    milestone_id: str | None = None
    area_id: str | None = None
    parent_task_id: str | None = None

    owner_ids: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)

    # 当前认领（过期即视为无）。属于对象的**当前状态**，所以进版本控制；
    # 「是否过期」是派生的，不存。
    claim: Claim | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None
    due_at: datetime | None = None


def claim_is_active(claim: Claim | None, now: datetime | None = None) -> bool:
    """认领是否仍然有效。**派生判定** —— 不写任何地方，因此不会有陈旧状态。"""
    if claim is None:
        return False
    moment = now or datetime.now().astimezone()
    return claim.expires_at > moment


def claim_view(claim: Claim | None, now: datetime | None = None) -> dict | None:
    """认领的读视图。过期就返回 None —— 调用方不需要自己算时间。

    放在 domain 层而不是 application 层：`project_graph` 和 `queries` 互相
    依赖，任何一方再 import 另一方都会成环。领域判定属于领域。
    """
    if not claim_is_active(claim, now):
        return None
    assert claim is not None
    return {
        "member_id": claim.member_id,
        "claimed_at": claim.claimed_at.isoformat(),
        "expires_at": claim.expires_at.isoformat(),
        "note": claim.note,
    }
