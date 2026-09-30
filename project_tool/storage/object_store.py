"""对象读写：一个对象一个文件；短 ID 解析。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from project_tool.domain.area import Area
from project_tool.domain.artifact import Artifact
from project_tool.domain.base import BaseObject
from project_tool.domain.decision import Decision
from project_tool.domain.errors import InvalidArgument, NotFound, ProjectCorrupted
from project_tool.domain.goal import Goal
from project_tool.domain.ids import (
    CROCKFORD,
    PREFIX_BY_TYPE,
    TYPE_BY_PREFIX,
)
from project_tool.domain.link import Link
from project_tool.domain.member import Member
from project_tool.domain.milestone import Milestone
from project_tool.domain.task import Task
from project_tool.domain.update import Update

MODEL_BY_TYPE: dict[str, type[BaseObject]] = {
    "goal": Goal,
    "milestone": Milestone,
    "area": Area,
    "task": Task,
    "artifact": Artifact,
    "member": Member,
    "update": Update,
    "decision": Decision,
    "link": Link,
}

_CROCKFORD_CHARS = set(CROCKFORD)


class ObjectStore:
    def __init__(self, paths):
        self.paths = paths

    def dir_for(self, obj_type: str) -> Path:
        return self.paths.object_dir(obj_type)

    def path_for(self, obj_type: str, object_id: str) -> Path:
        return self.dir_for(obj_type) / f"{object_id}.json"

    def exists(self, obj_type: str, object_id: str) -> bool:
        return self.path_for(obj_type, object_id).is_file()

    def get_raw(self, obj_type: str, object_id: str) -> dict | None:
        path = self.path_for(obj_type, object_id)
        if not path.is_file():
            return None
        return self._read_record(path)

    def load_raw(self, obj_type: str, ref: str) -> tuple[str, dict]:
        object_id = self.resolve(obj_type, ref)
        record = self.get_raw(obj_type, object_id)
        if record is None:
            raise NotFound(f"{obj_type} {ref!r} not found")
        return object_id, record

    def load_model(self, obj_type: str, ref: str) -> BaseObject:
        object_id, record = self.load_raw(obj_type, ref)
        return self._to_model(obj_type, record)

    def list_raw(self, obj_type: str, include_deleted: bool = False) -> list[dict]:
        records: list[dict] = []
        directory = self.dir_for(obj_type)
        if not directory.is_dir():
            return records
        for path in sorted(directory.glob("*.json")):
            record = self._read_record(path)
            if not include_deleted and record.get("lifecycle") == "deleted":
                continue
            records.append(record)
        return records

    def list_models(self, obj_type: str, include_deleted: bool = False) -> list[BaseObject]:
        return [self._to_model(obj_type, record) for record in self.list_raw(obj_type, include_deleted)]

    def ids(self, obj_type: str, include_deleted: bool = False) -> list[str]:
        return [record["id"] for record in self.list_raw(obj_type, include_deleted)]

    def count(self, obj_type: str, include_deleted: bool = False) -> int:
        return len(self.list_raw(obj_type, include_deleted))

    def resolve(self, obj_type: str, ref: str) -> str:
        """完整 ID 或项目内无歧义的短 ID -> 完整 ID。"""
        text = str(ref or "").strip().upper()
        if not text:
            raise InvalidArgument("empty id reference")
        prefix = PREFIX_BY_TYPE[obj_type]
        if "-" in text:
            given_prefix, part = text.split("-", 1)
            if given_prefix != prefix:
                raise InvalidArgument(
                    f"expected a {prefix}- id for {obj_type}, got {ref!r}"
                )
        else:
            part = text
        if not part or any(char not in _CROCKFORD_CHARS for char in part):
            raise InvalidArgument(f"invalid id: {ref!r}")
        matches = sorted(path.stem for path in self.dir_for(obj_type).glob(f"{prefix}-{part}*.json"))
        if not matches:
            raise NotFound(f"{obj_type} {ref!r} not found")
        if len(matches) > 1:
            raise InvalidArgument(
                f"ambiguous id {ref!r}: matches {len(matches)} {obj_type} objects "
                f"({', '.join(matches[:3])} ...)"
            )
        return matches[0]

    def find(self, ref: str) -> tuple[str, str] | None:
        """跨类型查找（全 ID 或任意短 ID），返回 (obj_type, id)。"""
        text = str(ref or "").strip().upper()
        if not text:
            return None
        if "-" in text:
            prefix, part = text.split("-", 1)
            obj_type = TYPE_BY_PREFIX.get(prefix)
            if obj_type is None or obj_type == "project":
                return None
            try:
                return obj_type, self.resolve(obj_type, text)
            except (NotFound, InvalidArgument):
                return None
        matches: list[tuple[str, str]] = []
        for obj_type in MODEL_BY_TYPE:
            try:
                matches.append((obj_type, self.resolve(obj_type, text)))
            except (NotFound, InvalidArgument):
                continue
        if len(matches) == 1:
            return matches[0]
        return None

    def find_by_handle(self, handle: str) -> dict | None:
        wanted = str(handle or "").strip().lower()
        for record in self.list_raw("member"):
            if str(record.get("handle", "")).lower() == wanted:
                return record
        return None

    def find_by_name(self, obj_type: str, name: str) -> dict | None:
        """按名称大小写不敏感查找（Area 用；名称不唯一，返回 None 交由调用方报错）。"""
        wanted = str(name or "").strip().casefold()
        if not wanted:
            return None
        found: dict | None = None
        for record in self.list_raw(obj_type):
            if str(record.get("name", "")).strip().casefold() != wanted:
                continue
            if found is not None:
                return None
            found = record
        return found

    def _read_record(self, path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectCorrupted(f"cannot read object file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ProjectCorrupted(f"object file {path} is not a JSON object")
        return data

    def _to_model(self, obj_type: str, record: dict) -> BaseObject:
        model_cls = MODEL_BY_TYPE[obj_type]
        try:
            return model_cls.model_validate(record)
        except ValidationError as exc:
            raise ProjectCorrupted(
                f"invalid {obj_type} object {record.get('id')}: {exc}"
            ) from exc
