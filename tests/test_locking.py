from __future__ import annotations

import json
import os
import time

import pytest

from project_tool.domain.errors import Conflict
from project_tool.storage import WriteLock
from project_tool.storage.local_state import lock_is_stale, lock_path, read_lock, remove_stale_lock

DEAD_PID = 999_999_999


def write_lock_file(paths, *, pid: int, created_at: float, lock_id: str = "LCK-TEST") -> None:
    path = lock_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": pid, "lock_id": lock_id, "created_at": created_at, "host": "test"}),
        encoding="utf-8",
    )


def test_lock_excludes_second_lock(project):
    with WriteLock(project.paths):
        with pytest.raises(Conflict):
            with WriteLock(project.paths, timeout=0.2):
                pass


def test_lock_released_on_exit(project):
    with WriteLock(project.paths):
        assert lock_path(project.paths).is_file()
    assert not lock_path(project.paths).is_file()


def test_active_pid_never_stolen(project):
    write_lock_file(project.paths, pid=os.getpid(), created_at=time.time() - 3600)
    assert not lock_is_stale(project.paths)
    with pytest.raises(Conflict):
        with WriteLock(project.paths, timeout=0.2):
            pass
    assert read_lock(project.paths) is not None


def test_dead_pid_stale_lock_stolen(project):
    write_lock_file(project.paths, pid=DEAD_PID, created_at=time.time() - 3600)
    assert lock_is_stale(project.paths)
    with WriteLock(project.paths, timeout=0.5):
        info = read_lock(project.paths)
        assert info is not None and info["pid"] == os.getpid()
        assert info["lock_id"] != "LCK-TEST"
    assert not lock_path(project.paths).is_file()


def test_dead_pid_fresh_lock_not_stolen(project):
    write_lock_file(project.paths, pid=DEAD_PID, created_at=time.time())
    assert not lock_is_stale(project.paths)
    with pytest.raises(Conflict):
        with WriteLock(project.paths, timeout=0.2):
            pass
    # 清理，避免影响其他测试
    lock_path(project.paths).unlink()


def test_exit_does_not_remove_replaced_lock(project):
    lock_a = WriteLock(project.paths)
    lock_a.__enter__()
    # 模拟 B 进程替换锁
    write_lock_file(project.paths, pid=os.getpid(), created_at=time.time(), lock_id="LCK-OTHER")
    lock_a.__exit__(None, None, None)
    info = read_lock(project.paths)
    assert info is not None and info["lock_id"] == "LCK-OTHER"
    lock_path(project.paths).unlink()


def test_legacy_plaintext_lock_uses_mtime(project):
    path = lock_path(project.paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("pid=12345 time=0\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(path, (old, old))
    assert lock_is_stale(project.paths)
    assert remove_stale_lock(project.paths)
    assert not path.is_file()


def test_recover_cleans_stale_lock(service):
    from project_tool.storage.local_state import lock_path as _lock_path

    write_lock_file(service.paths, pid=DEAD_PID, created_at=time.time() - 3600)
    result = service.call("project.recover", {})
    assert result["count"] == 0
    assert not _lock_path(service.paths).is_file()
