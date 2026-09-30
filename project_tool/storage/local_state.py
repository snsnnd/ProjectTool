"""本地状态：.pjt/local/local.toml 与写锁（PID + ownership token）。"""

from __future__ import annotations

import json
import os
import socket
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from project_tool.domain.errors import Conflict
from project_tool.domain.ids import new_device_id, ulid
from project_tool.integrations import filesystem

LOCK_FILENAME = "write.lock"


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


# ---------------------------------------------------------------------- 锁工具


def lock_path(paths) -> Path:
    return paths.locks / LOCK_FILENAME


def read_lock(paths) -> dict | None:
    path = lock_path(paths)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def process_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - windows only
        try:
            import ctypes

            process_query_limited_information = 0x1000
            windll = getattr(ctypes, "windll", None)
            if windll is None:
                return False
            kernel32 = windll.kernel32
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def lock_is_stale(paths, stale_after: float = 60.0) -> bool:
    """PID 存活 -> 永不视为陈旧；PID 死亡/不可解析 -> 超过 stale_after 视为陈旧。"""
    path = lock_path(paths)
    if not path.is_file():
        return False
    info = read_lock(paths)
    if info is not None:
        pid = info.get("pid")
        if isinstance(pid, int) and process_alive(pid):
            return False
        created = info.get("created_at")
        if isinstance(created, (int, float)) and created > 0:
            age = time.time() - float(created)
        else:
            age = _mtime_age(path)
    else:
        age = _mtime_age(path)
    return age > stale_after


def remove_stale_lock(paths, stale_after: float = 60.0) -> bool:
    if lock_is_stale(paths, stale_after):
        try:
            lock_path(paths).unlink()
            return True
        except FileNotFoundError:
            pass
    return False


def _mtime_age(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


class WriteLock:
    """项目级写锁。

    - 锁文件为 JSON：`pid / lock_id / created_at / host`
    - PID 存活时永不偷锁；PID 死亡或不可解析且超过 `stale_after` 才回收
    - 释放时仅在 `lock_id` 匹配时删除，避免删除他人替换后的锁
    """

    def __init__(self, paths, timeout: float = 10.0, stale_after: float = 60.0):
        self.paths = paths
        self.lock_path: Path = lock_path(paths)
        self.timeout = timeout
        self.stale_after = stale_after
        self.lock_id = f"LCK-{ulid()}"
        self._held = False

    def __enter__(self) -> WriteLock:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "lock_id": self.lock_id,
            "created_at": time.time(),
            "host": socket.gethostname(),
        }
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if lock_is_stale(self.paths, self.stale_after):
                    self._steal_if_unchanged()
                    continue
                if time.monotonic() >= deadline:
                    raise Conflict(
                        f"project write lock is held by another process: {self.lock_path}"
                    ) from None
                time.sleep(0.05)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            self._held = True
            return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._held:
            return
        info = read_lock(self.paths)
        if info is not None and info.get("lock_id") == self.lock_id:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
        # 锁已被替换或不可解析：保持不动，绝不删除他人的锁
        self._held = False

    def _steal_if_unchanged(self) -> None:
        """compare-and-delete：删除前确认锁未被其他进程替换。"""
        observed = read_lock(self.paths)
        observed_id = observed.get("lock_id") if isinstance(observed, dict) else None
        current = read_lock(self.paths)
        current_id = current.get("lock_id") if isinstance(current, dict) else None
        if current_id == observed_id and lock_is_stale(self.paths, self.stale_after):
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
