"""Goal：项目为什么存在。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from project_tool.domain.base import BaseObject
from project_tool.domain.enums import GoalStatus


class Goal(BaseObject):
    type: Literal["goal"] = "goal"

    title: str
    description: str = ""
    status: GoalStatus = GoalStatus.ACTIVE

    parent_goal_id: str | None = None

    success_criteria: list[str] = Field(default_factory=list)
    due_at: datetime | None = None
