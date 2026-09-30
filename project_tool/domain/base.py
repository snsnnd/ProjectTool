"""所有领域对象共享的 Header。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from project_tool.domain.enums import Lifecycle
from project_tool.version import SCHEMA_VERSION


class BaseObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    id: str
    type: str
    project_id: str

    version: int = 1
    rev: str = ""

    lifecycle: Lifecycle = Lifecycle.ACTIVE

    created_at: datetime
    updated_at: datetime

    created_by: str | None = None
    updated_by: str | None = None

    def to_record(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
