"""Area 活跃度（V1-C 第三步）：谁最近在哪个 Area 里动代码。

## 最重要的一条：两半的信息量完全不同

- **已提交历史**跟着 Git 走，**所有人都能看到**——这是本功能的主体
- **未提交改动**只有本机可见。**别人的在途工作本工具看不到**，
  所以输出必须分开标注，不能让人以为「没出现在这里就是没人动」

归因链：commit 的文件 -> `Area.path_patterns` -> Area；
commit 的 author name/email -> `Member.git`（V1-B 的 `member map-git`）-> Member。
任何一环匹配不上就如实说匹配不上，不猜。

## 本文件钉住过的三个真 bug

1. `"active": bool(bucket)` 引用了遍历 commit 时的**循环变量**，导致所有 Area
   在第一次匹配之后都变成 active
2. renderer 里 `[yellow]` 用 `[/dim]` 闭合，只有存在未绑目录的 Area 时才触发
3. `repo.log()` 的 subject 取错了字段位（多了 author_email 之后位移了）
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC

import pytest
from typer.testing import CliRunner

from project_tool.application.service import ProjectService
from project_tool.cli.main import app
from project_tool.storage import init_project, open_project

runner = CliRunner()


def invoke(args):
    return runner.invoke(app, args)


def git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check, capture_output=True, text=True
    )


@pytest.fixture()
def repo(tmp_path):
    """一个 git 仓库 + .pjt 项目，带真实的提交历史。"""
    root = tmp_path / "repo"
    root.mkdir()
    git(root.parent, "init", "-q", "-b", "main", str(root))
    git(root, "config", "user.email", "alice@x.com")
    git(root, "config", "user.name", "Alice Wang")
    (root / "src" / "core").mkdir(parents=True)
    (root / "src" / "core" / "store.ts").write_text("1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "core: init")
    init_project(root, name="Activity")
    return root


def commit_as(root, name, email, message, relpath):
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(message + "\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-qm", message)


def setup_areas(svc, root):
    svc.call("area.create", {"name": "core", "path_patterns": ["src/core/**"]})
    svc.call("area.create", {"name": "ui", "path_patterns": ["src/ui/**"]})
    svc.call("area.create", {"name": "tools"})  # 故意不绑目录
    svc.call("member.add", {"handle": "alice"})
    svc.call("member.add", {"handle": "bob"})
    svc.call(
        "member.update",
        {"member": "alice", "git_names": ["Alice Wang"], "git_emails": ["alice@x.com"]},
    )
    return root


@pytest.fixture()
def svc_repo(repo):
    svc = ProjectService(open_project(repo))
    setup_areas(svc, repo)
    # pjt 自己产生的数据不该进 git 历史，否则归因会混进 pjt 提交
    git(repo, "add", "-f", ".pjt")
    git(repo, "commit", "-qm", "pjt init")
    return ProjectService(open_project(repo))


# ================================================================== 归因


def test_commit_maps_to_the_area_whose_pattern_matches(svc_repo, repo):
    result = svc_repo.call("area.activity", {"days": 7})
    by_name = {row["name"]: row for row in result["areas"]}
    assert by_name["core"]["active"] is True
    assert by_name["core"]["files"] == ["src/core/store.ts"]
    assert by_name["ui"]["active"] is False


def test_author_maps_to_a_member_through_member_git(svc_repo, repo):
    commit_as(repo, "Alice Wang", "alice@x.com", "core: more", "src/core/x.ts")
    result = svc_repo.call("area.activity", {"days": 7})
    core = next(row for row in result["areas"] if row["name"] == "core")
    assert [person["handle"] for person in core["people"]] == ["alice"]


def test_unmapped_author_is_reported_not_guessed(svc_repo, repo):
    commit_as(repo, "Stranger", "nobody@x.com", "core: mystery", "src/core/y.ts")
    result = svc_repo.call("area.activity", {"days": 7})
    assert {item["author"] for item in result["unmapped_authors"]} == {"Stranger"}
    core = next(row for row in result["areas"] if row["name"] == "core")
    # alice 来自首次提交（合法），stranger 绝不能被猜成任何人
    assert [person["handle"] for person in core["people"]] == ["alice"]


def test_an_area_without_path_patterns_is_never_active(svc_repo, repo):
    """回归：循环变量泄漏曾让所有 Area 都变成 active。"""
    result = svc_repo.call("area.activity", {"days": 7})
    tools = next(row for row in result["areas"] if row["name"] == "tools")
    assert tools["bound"] is False
    assert tools["active"] is False
    assert tools["commits"] == 0


def test_area_without_patterns_is_flagged_as_unbound(svc_repo):
    result = svc_repo.call("area.activity", {"days": 7})
    tools = next(row for row in result["areas"] if row["name"] == "tools")
    assert tools["bound"] is False


def test_days_window_excludes_older_commits(svc_repo, repo):
    """`git log --since` 按 **committer date** 过滤，且从 HEAD 往回走。

    所以：旧 commit 必须在**祖先**位置、HEAD 得是新的，否则 HEAD 本身就是
    旧日期，walk 立刻停下、整条历史都进不了窗口。顺便钉住「必须同时设
    GIT_COMMITTER_DATE」——只设 `--date=`（作者日期）是不生效的。
    """
    import os

    def dated_commit(relpath: str, when: str) -> None:
        target = repo / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(when + "\n", encoding="utf-8")
        git(repo, "add", "-A")
        subprocess.run(
            [
                "git", "-C", str(repo),
                "-c", "user.name=Alice Wang",
                "-c", "user.email=alice@x.com",
                "commit", "-qm", f"add {relpath}",
            ],
            check=True,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_DATE": when,
                "GIT_COMMITTER_DATE": when,
            },
        )

    from datetime import datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    dated_commit("src/core/old.ts", "2001-01-01T00:00:00")
    dated_commit("src/core/new.ts", recent)

    result = svc_repo.call("area.activity", {"days": 7})
    core = next(row for row in result["areas"] if row["name"] == "core")
    assert "src/core/new.ts" in core["files"]
    assert "src/core/old.ts" not in core["files"]


def test_filter_to_one_area(svc_repo, repo):
    commit_as(repo, "Alice Wang", "alice@x.com", "ui: page", "src/ui/a.ts")
    result = svc_repo.call("area.activity", {"days": 7, "area": "core"})
    assert [row["name"] for row in result["areas"]] == ["core"]


# ================================================================== 两半信息


def test_local_uncommitted_is_separate_from_committed_history(svc_repo, repo):
    (repo / "src" / "core" / "wip.ts").write_text("wip\n", encoding="utf-8")
    result = svc_repo.call("area.activity", {"days": 7})
    core = next(row for row in result["areas"] if row["name"] == "core")
    # 未提交的文件绝不能混进 committed 的 files
    assert "src/core/wip.ts" not in core["files"]
    assert [row["name"] for row in result["local_uncommitted"]] == ["core"]
    assert result["local_uncommitted"][0]["files"] == ["src/core/wip.ts"]


def test_no_local_changes_reports_empty_not_missing(svc_repo):
    result = svc_repo.call("area.activity", {"days": 7})
    assert result["local_uncommitted"] == []


def test_activity_degrades_gracefully_outside_a_git_repo(tmp_path):
    root = tmp_path / "plain"
    init_project(root, name="NoGit")
    svc = ProjectService(open_project(root))
    svc.call("area.create", {"name": "core", "path_patterns": ["src/**"]})
    result = svc.call("area.activity", {"days": 7})
    assert result["available"] is False
    assert result["reason"]
    assert result["areas"] == []


def test_cli_reports_unavailable_git_without_crashing(repo, tmp_path):
    plain = tmp_path / "nogit"
    init_project(plain, name="NoGit")
    result = invoke(["-C", str(plain), "area", "activity"])
    assert result.exit_code == 0, result.output
    assert "unavailable" in result.output


# ================================================================== 渲染


def test_cli_renders_unbound_areas_without_a_markup_crash(svc_repo):
    """回归：renderer 曾在 `[yellow]` 之后用 `[/dim]` 闭合，只有存在
    未绑目录的 Area 时才触发——也就是只有真数据才会暴露。"""
    result = invoke(["-C", str(svc_repo.paths.root), "area", "activity", "--days", "7"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "no path_patterns" in result.output


def test_cli_marks_local_changes_as_this_machine_only(svc_repo, repo):
    (repo / "src" / "core" / "wip.ts").write_text("wip\n", encoding="utf-8")
    result = invoke(["-C", str(repo), "area", "activity"])
    assert result.exit_code == 0
    assert "THIS machine only" in result.output
    assert "invisible" in result.output


def test_cli_json_shape(svc_repo, repo):
    commit_as(repo, "Alice Wang", "alice@x.com", "core: x", "src/core/x.ts")
    result = invoke(["--json", "-C", str(repo), "area", "activity", "--days", "7"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["available"] is True
    assert payload["days"] == 7
    assert {row["name"] for row in payload["areas"]} == {"core", "ui", "tools"}

def test_activity_on_a_repo_with_no_commits_does_not_crash(tmp_path):
    """回归：`pjt init` 后还没提交过是正常状态。

    `git log` 在空仓库上直接 exit != 0，而 `area.activity` 原来只对
    `detect()` 做了保护，于是抛 traceback。**空历史不等于 git 不可用**——
    应该照常返回「所有 Area 都没活动」。
    """
    root = tmp_path / "fresh"
    root.mkdir()
    git(root.parent, "init", "-q", "-b", "main", str(root))
    init_project(root, name="Fresh")
    svc = ProjectService(open_project(root))
    svc.call("area.create", {"name": "core", "path_patterns": ["src/**"]})

    result = svc.call("area.activity", {"days": 7})
    assert result["available"] is True, "空历史不该被当成 git 不可用"
    assert result["scanned_commits"] == 0
    core = next(row for row in result["areas"] if row["name"] == "core")
    assert core["active"] is False


def test_cli_activity_on_a_fresh_repo_exits_cleanly(tmp_path):
    root = tmp_path / "fresh2"
    root.mkdir()
    git(root.parent, "init", "-q", "-b", "main", str(root))
    init_project(root, name="Fresh2")
    result = invoke(["-C", str(root), "area", "activity"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output


def test_has_commits_is_false_on_an_empty_repo(tmp_path):
    from project_tool.integrations.git import detect

    root = tmp_path / "empty"
    root.mkdir()
    git(root.parent, "init", "-q", "-b", "main", str(root))
    assert detect(root).has_commits() is False
    (root / "f.txt").write_text("x\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "first")
    assert detect(root).has_commits() is True
