"""事务：staging -> manifest -> COMMIT -> 原子 apply；写前校验 base_rev。

写路径（在调用方持有 WriteLock 时执行）：

```text
1 校验全部 base_rev（不匹配 -> REVISION_CONFLICT，未提交即丢弃）
2 写入 staged/（对象先、事件后）
3 落 manifest（state=prepared）并 fsync
4 落 COMMIT 标记并 fsync
5 roll-forward apply（对象与事件逐个 os.replace）
6 manifest -> applied，更新派生 state，删除事务目录
```

第 4 步之后崩溃：事务目录保留，`pjt doctor --repair` /
`project.recover` 会 roll-forward；第 4 步之前失败：直接清空 staging。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from project_tool.domain.errors import ProjectIOError, RevisionConflict
from project_tool.domain.event import Event
from project_tool.domain.ids import new_id
from project_tool.domain.timeutil import now_local
from project_tool.integrations import filesystem
from project_tool.integrations.filesystem import fsync_dir
from project_tool.storage.project_store import write_state
from project_tool.storage.recovery import (
    STAGED_DIR,
    STATE_APPLIED,
    STATE_PREPARED,
    apply_committed_writes,
    write_commit_marker,
    write_manifest,
)
from project_tool.version import SCHEMA_VERSION

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
        txn_dir = self.paths.transactions / txn_id
        staged_root = txn_dir / STAGED_DIR
        occurred_at = now_local()
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": txn_id,
            "state": STATE_PREPARED,
            "created_at": occurred_at.isoformat(),
            "actor_id": self.actor_id,
            "device_id": self.opened.device_id,
            "writes": [],
        }

        try:
            for change in changes:
                final = self._final_path(change.obj_type, change.object_id)
                current_rev = self._current_rev(final)
                base_rev = change.base_rev or None
                if base_rev != current_rev:
                    raise RevisionConflict(
                        f"{change.obj_type} {change.object_id} was modified concurrently",
                        expected_rev=change.base_rev,
                        actual_rev=current_rev,
                        entity_id=change.object_id,
                    )
                target = final.relative_to(self.paths.pjt).as_posix()
                filesystem.write_json(staged_root / Path(target), change.record)
                manifest["writes"].append(
                    {
                        "kind": "object",
                        "target": target,
                        "base_rev": base_rev,
                        "new_rev": change.record.get("rev"),
                    }
                )

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
                target = final.relative_to(self.paths.pjt).as_posix()
                filesystem.write_json(staged_root / Path(target), event.to_record())
                manifest["writes"].append(
                    {
                        "kind": "event",
                        "target": target,
                        "event_id": event.id,
                        "base_rev": None,
                        "new_rev": None,
                    }
                )

            fsync_dir(staged_root)
            write_manifest(txn_dir, manifest)
            write_commit_marker(txn_dir, txn_id)
        except BaseException:
            shutil.rmtree(txn_dir, ignore_errors=True)
            raise

        try:
            conflict = apply_committed_writes(self.paths, txn_dir, manifest)
        except OSError as exc:
            raise ProjectIOError(
                f"transaction {txn_id} committed but apply failed: {exc}; "
                "run 'pjt doctor --repair'"
            ) from exc
        if conflict:
            raise ProjectIOError(
                f"transaction {txn_id} cannot be applied: {conflict}; run 'pjt doctor'"
            )

        manifest["state"] = STATE_APPLIED
        manifest["applied_at"] = now_local().isoformat()
        try:
            write_manifest(txn_dir, manifest)
        except Exception:
            pass

        try:
            write_state(self.paths, last_transaction_id=txn_id)
        except Exception as exc:
            raise ProjectIOError(
                f"transaction {txn_id} applied but state update failed: {exc}; "
                "run 'pjt doctor --repair'"
            ) from exc

        shutil.rmtree(txn_dir, ignore_errors=True)
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
        return rev if isinstance(rev, str) and rev else None
