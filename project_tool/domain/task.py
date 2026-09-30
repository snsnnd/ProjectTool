"""Task：最核心对象。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from project_tool.domain.base import BaseObject
from project_tool.domain.enums import DependencyRelation, Priority, TaskStatus


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

    started_at: datetime | None = None
    completed_at: datetime | None = None
    due_at: datetime | None = None
