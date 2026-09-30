"""事件存储：append-only，按 年/月 分目录。"""

from __future__ import annotations

import json
from pathlib import Path

from project_tool.domain.errors import InvalidArgument, NotFound, ProjectCorrupted
from project_tool.domain.ids import CROCKFORD

_CROCKFORD_CHARS = set(CROCKFORD)


class EventStore:
    def __init__(self, paths):
        self.paths = paths

    def iter_records(self, newest_first: bool = False) -> list[dict]:
        base = self.paths.events
        if not base.is_dir():
            return []
        paths = sorted(base.rglob("EVT-*.json"), reverse=newest_first)
        return [self._read(path) for path in paths]

    def get(self, ref: str) -> dict:
        text = str(ref or "").strip().upper()
        if not text:
            raise InvalidArgument("empty event reference")
        if "-" in text:
            prefix, part = text.split("-", 1)
            if prefix != "EVT":
                raise InvalidArgument(f"expected an EVT- id, got {ref!r}")
        else:
            part = text
        if not part or any(char not in _CROCKFORD_CHARS for char in part):
            raise InvalidArgument(f"invalid event id: {ref!r}")
        matches = sorted(self.paths.events.rglob(f"EVT-{part}*.json"))
        if not matches:
            raise NotFound(f"event {ref!r} not found")
        if len(matches) > 1:
            raise InvalidArgument(f"ambiguous event id {ref!r}")
        return self._read(matches[0])

    def _read(self, path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectCorrupted(f"cannot read event file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ProjectCorrupted(f"event file {path} is not a JSON object")
        return data
