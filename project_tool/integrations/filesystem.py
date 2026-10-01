"""原子文件写入与 JSON 读写。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from project_tool.domain.errors import ProjectIOError

# Windows 上共享冲突的重试预算：25ms x 40 = 1s
RETRY_ATTEMPTS = 40
RETRY_DELAY = 0.025
# 单独一个常量，这样测试可以在 Linux 上直接走 Windows 分支
IS_WINDOWS = os.name == "nt"


def retry_on_sharing_violation(path: Path, action):
    """执行 `action()`，Windows 上「有别的句柄开着这个文件」时重试。

    Python 打开文件时没有带 FILE_SHARE_DELETE，所以只要**任何人**打开着目标
    文件，替换/删除就会拿到 WinError 32。读（`task next` / `list` /
    `doctor`）都在写锁之外，于是读的那一瞬间落进替换窗口里，写的一方就崩
    —— 锁只串行化**写**，挡不住这种情况。

    这不是「放弃写入」的理由：临时文件此刻已经写完并 fsync 过，重试只是
    把同一份内容再放一次，不会丢数据。

    非 Windows 上不重试 —— 那里 PermissionError 是真的权限问题，等它没有
    意义，只会变成无谓的等待。

    用回调而不是 contextmanager：generator 被 `throw()` 重新进入后**不能
    再次 yield**，所以带重试的 contextmanager 是不成立的。
    """
    if not IS_WINDOWS:
        return action()
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return action()
        except PermissionError:
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_DELAY)


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        retry_on_sharing_violation(path, lambda: os.replace(tmp_name, path))
    except OSError as exc:
        _silent_unlink(tmp_name)
        raise ProjectIOError(f"cannot write {path}: {exc}") from exc


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=True) + "\n"
    atomic_write_text(path, text)


def read_json(path: Path) -> Any:
    try:
        return retry_on_sharing_violation(
            path, lambda: json.loads(Path(path).read_text(encoding="utf-8"))
        )
    except OSError as exc:
        raise ProjectIOError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectIOError(f"invalid JSON in {path}: {exc}") from exc


def fsync_dir(path: Path) -> None:
    """尽力 fsync 目录项（POSIX）；Windows 等不支持时静默跳过。"""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _silent_unlink(path: str | Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
