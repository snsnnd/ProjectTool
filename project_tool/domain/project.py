"""Project 对象（存储于 .pjt/project.json）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from project_tool.domain.enums import ProjectStatus
from project_tool.version import SCHEMA_VERSION


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    id: str
    type: Literal["project"] = "project"

    name: str
    slug: str
    description: str = ""

    status: ProjectStatus = ProjectStatus.ACTIVE

    created_at: datetime
    updated_at: datetime

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project name must not be empty")
        return value

    def to_record(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
