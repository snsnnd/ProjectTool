"""Decision：一等对象，记录为什么这样决定。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from project_tool.domain.base import BaseObject
from project_tool.domain.enums import DecisionStatus


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    reason_not_selected: str = ""


class Decision(BaseObject):
    type: Literal["decision"] = "decision"

    title: str
    status: DecisionStatus = DecisionStatus.DRAFT

    context: str = ""
    decision: str = ""
    rationale: str = ""

    alternatives: list[Alternative] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)

    related_task_ids: list[str] = Field(default_factory=list)
    supersedes_id: str | None = None
