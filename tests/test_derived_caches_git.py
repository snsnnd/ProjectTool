"""V1-C 第一步：派生缓存不进版本控制（多人合并的前提）。

背景（`dogfooding/multiwriter-evidence/conflict-probe.json`）：
2 个写者的 9 个真实合并场景里，现状只有 1 个能干净合并。冲突几乎全部来自
两个**派生缓存**：

- `.pjt/state/state.json`   每次事务都重写（计数 + last_transaction_id）
- `.pjt/refs/labels.json`   `rebuild_labels()` 重扫所有 task 生成

两者都是可重建的派生数据（`docs/09-handover.md` §「派生数据可疑 直接删 …
会重建」），被提交进 Git 就意味着**每一次**并发合并都撞一次。排除出版本
控制后 8/9 干净，剩下的那个（两人改同一个 task）本来就该冲突。

这里钉住三件事：
1. `pjt init` 写好 ignore 规则；`pjt migrate` 给老项目幂等补齐
2. `doctor` 把「派生缓存被 git 跟踪」判为 **error**——静默约定必须有牙齿，
   否则半年后一次 `git add -f` 就悄悄回归
3. 工具**只报告不代劳**：修它要 `git rm --cached`，那是 Git 写操作，
   而 Git 适配器是只读的（AGENTS.md §11）
"""

from __future__ import annotations

import subprocess

import pytest
from typer.testing import CliRunner

from project_tool.cli.main import app
from project_tool.integrations import git as git_integration
from project_tool.storage import init_project
from project_tool.storage.project_store import DERIVED_CACHE_PATHS, ensure_gitignore

runner = CliRunner()


def invoke(args):
    return runner.invoke(app, args)


def _git(path, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=check, capture_output=True, text=True
    )


@pytest.fixture()
def git_root(tmp_path):
    """一个真实的 git 仓库，里面 init 了一个 .pjt 项目。"""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    init_project(root, name="Derived")
    return root


@pytest.fixture()
def plain_root(tmp_path):
    root = tmp_path / "plain"
    init_project(root, name="Plain")
    return root


def _commit_everything(root, force: bool = False):
    _git(root, "add", "-A")
    if force:
        # -f 越过 .gitignore：模拟「有人手滑提交了派生缓存」
        _git(root, "add", "-f", ".pjt/state/state.json", ".pjt/refs/labels.json")
    _git(root, "commit", "-qm", "snapshot")


# ----------------------------------------------------------------- .gitignore


def test_init_writes_both_ignore_groups(plain_root):
    text = (plain_root / ".gitignore").read_text(encoding="utf-8")
    assert ".pjt/local/" in text
    assert ".pjt/transactions/" in text
    assert ".pjt/state/" in text
    assert ".pjt/refs/labels.json" in text


def test_gitignore_ignores_derived_but_not_canonical_state(git_root):
    """canonical 数据绝不能被 ignore 掉——否则就是静默丢数据。

    用真的 git 仓库跑，否则 `check-ignore` 直接返回 128，这条断言等于没写。
    """
    invoke(["-C", str(git_root), "task", "add", "canonical"])
    _commit_everything(git_root)

    def ignored(path: str) -> bool:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", path], cwd=git_root, capture_output=True
            ).returncode
            == 0
        )

    assert ignored(".pjt/state/state.json")
    assert ignored(".pjt/refs/labels.json")
    # 本机状态
    assert ignored(".pjt/local/local.toml")
    assert ignored(".pjt/transactions/")
    # canonical 数据必须照常进版本控制
    assert not ignored(".pjt/project.json")
    assert not ignored(".pjt/config.toml")
    assert not ignored(".pjt/objects/tasks")
    assert not ignored(".pjt/events")


def test_ensure_gitignore_is_idempotent(plain_root):
    first = ensure_gitignore(plain_root)
    assert first == []
    text = (plain_root / ".gitignore").read_text(encoding="utf-8")
    # 再调一次不能追加重复块
    ensure_gitignore(plain_root)
    assert (plain_root / ".gitignore").read_text(encoding="utf-8") == text


def test_ensure_gitignore_adds_only_the_missing_group(plain_root):
    """老项目已经有 local/transactions 规则，只该补派生那两条，且不重复旧注释块。"""
    gitignore = plain_root / ".gitignore"
    gitignore.write_text(
        "# Project Tool local state\n.pjt/local/\n.pjt/transactions/\n", encoding="utf-8"
    )
    added = ensure_gitignore(plain_root)
    assert added == [".pjt/state/", ".pjt/refs/labels.json"]
    text = gitignore.read_text(encoding="utf-8")
    assert text.count("# Project Tool local state") == 1
    assert ".pjt/local/" in text


def test_migrate_upgrades_a_legacy_gitignore(plain_root):
    (plain_root / ".gitignore").write_text(".pjt/local/\n", encoding="utf-8")
    result = invoke(["--json", "-C", str(plain_root), "migrate"])
    assert result.exit_code == 0, result.output
    assert ".pjt/state/" in (plain_root / ".gitignore").read_text(encoding="utf-8")


# ----------------------------------------------------------------- doctor


def _doctor(root, expect_exit: int | None = 0) -> dict:
    """跑 doctor 并解析报告。

    注意：`pjt doctor` 发现 error 时**故意**以非 0 退出（9），
    所以这里不能一律断言 exit_code == 0——那正是本次要测的行为之一。
    """
    result = invoke(["--json", "-C", str(root), "doctor"])
    if expect_exit is not None:
        assert result.exit_code == expect_exit, result.output
    import json

    return json.loads(result.output)["result"]


def _check(report: dict, name: str) -> dict:
    return next(item for item in report["checks"] if item["name"] == name)


def test_doctor_passes_on_a_fresh_project(plain_root):
    report = _doctor(plain_root)
    assert report["ok"] is True
    assert _check(report, "derived.git_tracked")["status"] == "ok"


def test_doctor_passes_when_derived_caches_are_untracked(git_root):
    invoke(["-C", str(git_root), "task", "add", "one"])
    _commit_everything(git_root)
    tracked = _git(git_root, "ls-files").stdout
    for path in DERIVED_CACHE_PATHS:
        assert path not in tracked, f"{path} should not be tracked after init's .gitignore"
    report = _doctor(git_root)
    assert report["ok"] is True, report
    assert _check(report, "derived.git_tracked")["status"] == "ok"


def test_doctor_errors_when_derived_caches_are_committed(git_root):
    invoke(["-C", str(git_root), "task", "add", "one"])
    _commit_everything(git_root, force=True)

    tracked = _git(git_root, "ls-files").stdout
    assert ".pjt/state/state.json" in tracked

    report = _doctor(git_root, expect_exit=None)
    assert report["ok"] is False
    assert report["summary"]["errors"] >= 1
    check = _check(report, "derived.git_tracked")
    assert check["status"] == "error"
    # 必须给出可直接执行的修复命令——工具自己不代劳（Git 适配器只读）
    assert "git rm --cached" in check["message"]


def test_doctor_does_not_run_git_writes(git_root):
    """doctor 报告之后，index 必须原封不动。"""
    invoke(["-C", str(git_root), "task", "add", "one"])
    _commit_everything(git_root, force=True)
    before = _git(git_root, "ls-files").stdout
    _doctor(git_root, expect_exit=None)
    after = _git(git_root, "ls-files").stdout
    assert before == after
    # 也不能留下 index.lock
    assert not (git_root / ".git" / "index.lock").exists()


def test_doctor_still_works_outside_a_git_repo(plain_root):
    """非 Git 项目必须照常跑 doctor——「查不到」不等于「有问题」。"""
    invoke(["-C", str(plain_root), "task", "add", "one"])
    report = _doctor(plain_root)
    assert report["ok"] is True
    assert _check(report, "derived.git_tracked")["status"] == "ok"


def test_untracking_clears_the_doctor_error(git_root):
    invoke(["-C", str(git_root), "task", "add", "one"])
    _commit_everything(git_root, force=True)
    assert _doctor(git_root, expect_exit=None)["ok"] is False

    _git(git_root, "rm", "-r", "-q", "--cached", ".pjt/state", ".pjt/refs")
    _git(git_root, "commit", "-qm", "untrack derived caches")

    report = _doctor(git_root)
    assert report["ok"] is True, report
    assert _check(report, "derived.git_tracked")["status"] == "ok"


def test_migrate_reports_the_untrack_command(git_root):
    invoke(["-C", str(git_root), "task", "add", "one"])
    _commit_everything(git_root, force=True)
    result = invoke(["--json", "-C", str(git_root), "migrate"])
    import json

    payload = json.loads(result.output)["result"]
    assert payload["derived_tracked"], "should list the tracked derived caches"
    assert "git rm --cached" in payload["message"]


def test_migrate_survives_when_git_is_absent(plain_root, monkeypatch):
    """git 不可用时 migrate 不能炸——它还得能补目录和 .gitignore。"""
    monkeypatch.setattr(
        "project_tool.storage.migrations.tracked_files",
        lambda *a, **k: set(),
    )
    result = invoke(["--json", "-C", str(plain_root), "migrate"])
    assert result.exit_code == 0, result.output


# ----------------------------------------------------------------- git 适配器


def test_ls_files_is_read_only_and_whitelisted():
    assert "ls-files" in git_integration.READ_ONLY_SUBCOMMANDS
    assert "ls-files" not in git_integration.WRITE_SUBCOMMANDS


def test_git_repo_run_rejects_non_whitelisted_subcommands(git_root):
    """运行时白名单仍然拦得住写命令（AGENTS.md §11）。"""
    from project_tool.integrations.git import detect

    repo = detect(git_root)
    with pytest.raises(Exception) as excinfo:
        repo.run("add", ".")
    assert "ls-files" in str(excinfo.value) or "not allowed" in str(excinfo.value)


def test_tracked_files_is_empty_outside_a_repo(plain_root):
    assert git_integration.tracked_files(plain_root, *DERIVED_CACHE_PATHS) == set()


def test_tracked_files_reports_relative_posix_paths(git_root):
    invoke(["-C", str(git_root), "task", "add", "one"])
    _commit_everything(git_root, force=True)
    found = git_integration.tracked_files(git_root, *DERIVED_CACHE_PATHS)
    assert ".pjt/state/state.json" in found
    assert ".pjt/refs/labels.json" in found