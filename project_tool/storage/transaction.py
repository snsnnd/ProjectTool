"""事务：staging -> 原子 rename；写前校验 base_rev。"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from project_tool.domain.errors import RevisionConflict
from project_tool.domain.event import Event
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.integrations import filesystem
from project_tool.storage.project_store import write_state

PROJECT_TYPE = "project"


@dataclass
class ObjectChange:
    obj_type: str
    object_id: str
    record: dict[str, Any]
    base_rev: str | None = None


@dataclass
class EventSpec:
    event_type: str
    entity_type: str
    entity_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    base_rev: str | None = None
    new_rev: str | None = None


class Transaction:
    def __init__(self, opened, actor_id: str | None = None):
        self.opened = opened
        self.paths = opened.paths
        self.project_id = opened.project.id
        self.actor_id = actor_id

    def commit(self, changes: list[ObjectChange], event_specs: list[EventSpec]) -> str:
        txn_id = new_id("transaction")
        staging = self.paths.transactions / txn_id
        occurred_at = now_local()
        writes: list[tuple[Path, Path]] = []
        try:
            for change in changes:
                final = self._final_path(change.obj_type, change.object_id)
                if change.obj_type != PROJECT_TYPE:
                    current_rev = self._current_rev(final)
                    if change.base_rev != current_rev:
                        raise RevisionConflict(
                            f"{change.obj_type} {change.object_id} was modified concurrently",
                            expected_rev=change.base_rev,
                            actual_rev=current_rev,
                            entity_id=change.object_id,
                        )
                staged = staging / final.relative_to(self.paths.pjt)
                filesystem.write_json(staged, change.record)
                writes.append((staged, final))

            for spec in event_specs:
                event = Event(
                    id=new_id("event"),
                    transaction_id=txn_id,
                    event_type=spec.event_type,
                    project_id=self.project_id,
                    entity_type=spec.entity_type,
                    entity_id=spec.entity_id,
                    actor_id=self.actor_id,
                    device_id=self.opened.device_id,
                    occurred_at=occurred_at,
                    base_rev=spec.base_rev,
                    new_rev=spec.new_rev,
                    payload=spec.payload,
                )
                final = self.paths.event_dir(occurred_at) / f"{event.id}.json"
                staged = staging / final.relative_to(self.paths.pjt)
                filesystem.write_json(staged, event.to_record())
                writes.append((staged, final))

            for staged, final in writes:
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, final)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        write_state(self.paths, last_transaction_id=txn_id)
        return txn_id

    def _final_path(self, obj_type: str, object_id: str) -> Path:
        if obj_type == PROJECT_TYPE:
            return self.paths.project_json
        return self.paths.object_dir(obj_type) / f"{object_id}.json"

    def _current_rev(self, path: Path) -> str | None:
        if not path.is_file():
            return None
        record = filesystem.read_json(path)
        rev = record.get("rev") if isinstance(record, dict) else None
        return rev if isinstance(rev, str) else None
