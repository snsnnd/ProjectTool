"""本地状态：.pjt/local/local.toml 与写锁。"""

from __future__ import annotations

import json
import os
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from project_tool.domain.errors import Conflict
from project_tool.domain.ids import new_device_id
from project_tool.integrations import filesystem


@dataclass
class LocalState:
    device_id: str
    actor: str | None = None
    links: dict[str, dict[str, str]] = field(default_factory=dict)


def load_local(paths) -> LocalState:
    path: Path = paths.local_toml
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        section = data.get("local", {}) if isinstance(data, dict) else {}
        links = {
            str(name): {str(key): str(value) for key, value in (config or {}).items()}
            for name, config in (data.get("links", {}) or {}).items()
        }
        state = LocalState(
            device_id=str(section.get("device_id") or new_device_id()),
            actor=section.get("actor"),
            links=links,
        )
    else:
        state = LocalState(device_id=new_device_id())
    save_local(paths, state)
    return state


def save_local(paths, state: LocalState) -> None:
    lines = ["[local]", f"device_id = {json.dumps(state.device_id)}"]
    if state.actor:
        lines.append(f"actor = {json.dumps(state.actor)}")
    for name in sorted(state.links):
        lines.append("")
        lines.append(f"[links.{name}]")
        for key in sorted(state.links[name]):
            lines.append(f"{key} = {json.dumps(str(state.links[name][key]))}")
    filesystem.atomic_write_text(paths.local_toml, "\n".join(lines) + "\n")


class WriteLock:
    """基于 O_EXCL 锁文件的简单写锁；陈旧锁自动清理。"""

    def __init__(self, paths, timeout: float = 10.0, stale_after: float = 60.0):
        self.lock_path: Path = paths.locks / "write.lock"
        self.timeout = timeout
        self.stale_after = stale_after
        self._fd: int | None = None

    def __enter__(self) -> "WriteLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if self._is_stale():
                    self._remove()
                    continue
                if time.monotonic() >= deadline:
                    raise Conflict(f"project write lock is held by another process: {self.lock_path}")
                time.sleep(0.05)
                continue
            os.write(fd, f"pid={os.getpid()} time={time.time():.3f}\n".encode("utf-8"))
            self._fd = fd
            return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._remove()

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self.lock_path.stat().st_mtime
        except FileNotFoundError:
            return False
        return age > self.stale_after

    def _remove(self) -> None:
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass
