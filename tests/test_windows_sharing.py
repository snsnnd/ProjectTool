"""Windows 共享冲突的容忍：这条路径只有 Windows 才走得到，所以在这里测。

## 为什么要处理

Python 打开文件时**没有** `FILE_SHARE_DELETE`。所以只要有任何人打开着目标
文件，`os.replace` / `unlink` 就会拿到 WinError 32。这在并发写 `.pjt` 时
不是理论问题：`task next` / `list` / `doctor` 的读都在写锁**之外**，读的那
一瞬间落进 `os.replace` 的窗口里，写的一方就会崩 —— 而锁只串行化**写**，
它挡不住这种情况。

这不是「放弃写入」的理由：临时文件已经写完并 fsync 过，重试只是把同一份
内容再放一次。所以这里保证两件事：**该重试的真的重试并最终写成功**，以及
**非 Windows 上真正的权限错误不会被吞掉**。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from project_tool.domain.errors import ProjectIOError
from project_tool.integrations import filesystem
from project_tool.integrations.filesystem import atomic_write_text, write_json
from project_tool.storage import init_project


@pytest.fixture()
def windows(monkeypatch):
    """让这个进程走 Windows 分支（我们在 Linux 上跑测试）。"""
    monkeypatch.setattr(filesystem, "IS_WINDOWS", True)
    monkeypatch.setattr(filesystem, "RETRY_DELAY", 0.001)
    return monkeypatch


def fails_then_succeeds(real, fail_times: int, calls: dict, error=PermissionError, code=32):
    def call(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise error(code, "used by another process")
        return real(*args, **kwargs)

    return call


# ================================================================== 原子写


def test_atomic_write_retries_a_sharing_violation_then_succeeds(windows, tmp_path):
    """共享冲突是瞬时的：等一下就好，最终内容必须真的落盘。"""
    calls = {"n": 0}
    windows.setattr(filesystem.os, "replace", fails_then_succeeds(os.replace, 3, calls))
    target = tmp_path / "objects" / "task.json"

    write_json(target, {"title": "认领之后"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"title": "认领之后"}
    assert calls["n"] == 4, "应该重试到成功，而不是一撞就放弃"


def test_atomic_write_gives_up_eventually(windows, tmp_path):
    """一直撞就放弃 —— 不能无限重试变成挂死，也不能留下临时文件残渣。"""
    calls = {"n": 0}
    windows.setattr(filesystem.os, "replace", fails_then_succeeds(os.replace, 10**6, calls))

    with pytest.raises(ProjectIOError):
        atomic_write_text(tmp_path / "x.json", "{}")

    assert calls["n"] == filesystem.RETRY_ATTEMPTS
    assert list(tmp_path.glob("*.tmp")) == [], "失败时不能留下临时文件"


def test_permission_errors_are_not_retried_off_windows(tmp_path):
    """非 Windows 上 PermissionError 是真的权限问题，等它没有意义。"""
    calls = {"n": 0}

    def deny(src, dst):
        calls["n"] += 1
        raise PermissionError(13, "permission denied")

    original = os.replace
    try:
        os.replace = deny  # type: ignore[assignment]
        with pytest.raises(ProjectIOError):
            atomic_write_text(tmp_path / "x.json", "{}")
    finally:
        os.replace = original  # type: ignore[assignment]

    assert calls["n"] == 1, "Linux 上应该一次就失败，不做无谓的重试"


def test_read_json_survives_a_sharing_violation(windows, tmp_path):
    """读也会撞（别的进程正在替换），同样要能撑过去。"""
    target = tmp_path / "a.json"
    target.write_text('{"n": 1}', encoding="utf-8")
    calls = {"n": 0}
    real_read = Path.read_text
    windows.setattr(
        Path,
        "read_text",
        fails_then_succeeds(real_read, 2, calls),
    )

    assert filesystem.read_json(target) == {"n": 1}
    assert calls["n"] == 3


# ================================================================== 写锁释放


def test_write_lock_release_survives_a_sharing_violation(windows, tmp_path):
    """释放锁时也要删得掉，否则留下锁残渣会让 doctor 判 corrupted。

    锁文件是每个 agent 都会读的东西，所以它是最容易撞共享冲突的路径。
    """
    opened = init_project(tmp_path / "repo", name="LockRelease")
    calls = {"n": 0}
    real_unlink = Path.unlink
    windows.setattr(Path, "unlink", fails_then_succeeds(real_unlink, 2, calls))

    lock_file = opened.paths.locks / "write.lock"
    lock_file.write_text("{}", encoding="utf-8")
    filesystem.retry_on_sharing_violation(lock_file, lock_file.unlink)

    assert not opened.paths.locks.joinpath("write.lock").exists()
    assert calls["n"] == 3, "删除锁文件也该重试，而不是直接失败"