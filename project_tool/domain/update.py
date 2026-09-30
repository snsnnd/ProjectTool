"""Update：项目进展记录（今天发生了什么）。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from project_tool.domain.base import BaseObject


class Update(BaseObject):
    type: Literal["update"] = "update"

    summary: str
    body: str = ""

    task_ids: list[str] = Field(default_factory=list)
    milestone_id: str | None = None

    blockers: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
