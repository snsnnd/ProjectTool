"""Milestone：不保存 task 数组，Task 通过 milestone_id 反向引用。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from project_tool.domain.base import BaseObject
from project_tool.domain.enums import MilestoneStatus


class Milestone(BaseObject):
    type: Literal["milestone"] = "milestone"

    title: str
    description: str = ""
    status: MilestoneStatus = MilestoneStatus.PLANNED

    goal_ids: list[str] = Field(default_factory=list)
    due_at: datetime | None = None
