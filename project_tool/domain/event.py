"""Event：不可变历史，append-only。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from project_tool.version import SCHEMA_VERSION


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION

    id: str
    transaction_id: str
    event_type: str
    project_id: str

    entity_type: str
    entity_id: str | None = None

    actor_id: str | None = None
    device_id: str | None = None

    occurred_at: datetime

    base_rev: str | None = None
    new_rev: str | None = None

    payload: dict[str, Any] = Field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
