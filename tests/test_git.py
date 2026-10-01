"""V1-B Git 感知层测试。

覆盖：
- `integrations/git.py`：porcelain 解析、trailer 解析、只读保证
- `Area.path_patterns`：glob 匹配、校验、反向匹配
- `git.available` / `git.status` / `git.log` / `git.link_commit`
- **project root != git root**（EFW 场景）与**同根目录**两个分支
- git 缺失 / 不在仓库内 -> 状态而非异常
- 绝不写 Git 仓库
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from project_tool.application.service import ProjectService
from project_tool.application.services.git import TASK_TRAILER, GitService
from project_tool.cli.main import app
from project_tool.domain.area_paths import (
    match_any,
    match_path,
    normalize_path_pattern,
    normalize_path_patterns,
)
from project_tool.domain.errors import InvalidArgument
from project_tool.integrations import git as git_integration
from project_tool.integrations.git import parse_trailers, trailer_values
from project_tool.storage import init_project, open_project

runner = CliRunner()


def git(*args: str, cwd: Path) -> str:
    # 只 rstrip：.strip() 会吃掉多行 porcelain 输出的首行前导空格（那是 XY 状态列）
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.rstrip()


def porcelain_paths(output: str) -> list[str]:
    """从 porcelain 输出取路径（跳过 XY 两列状态）。"""
    result = []
    for line in output.splitlines():
        if len(line) > 3:
            result.append(line[3:])
    return result


@pytest.fixture()
def repo(tmp_path):
    """一个真实的小 git 仓库（git root == project root）。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "studio_core").mkdir()
    (root / "studio_core" / "debug.py").write_text("x = 1\n")
    (root / "ui").mkdir()
    (root / "ui" / "store.tsx").write_text("export const s = 1\n")
    (root / "package.json").write_text("{}\n")
    (root / ".gitignore").write_text(".pjt/local/\n.pjt/transactions/\n")
    init_project(root, name="GitFixture")
    git("init", "-q", ".", cwd=root)
    git("config", "user.email", "t@example.com", cwd=root)
    git("config", "user.name", "Tester", cwd=root)
    git("add", "-A", cwd=root)
    git("commit", "-qm", "init", cwd=root)
    return root


@pytest.fixture()
def svc(repo):
    return ProjectService(open_project(repo))


# ============================================================ glob 匹配（纯函数）


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("ui/**", "ui/store.tsx", True),
        ("ui/**", "ui/pages/Debug.tsx", True),
        ("ui/**", "studio_core/debug.py", False),
        ("ui/*", "ui/store.tsx", True),
        ("ui/*", "ui/pages/Debug.tsx", False),   # * 不跨 /
        ("package.json", "package.json", True),
        ("package.json", "ui/package.json", False),
        ("*.py", "debug.py", True),
        ("*.py", "a/debug.py", False),
        ("**/*.py", "a/b/debug.py", True),
        ("**/*.py", "debug.py", True),
        ("scripts/**", "scripts/build.sh", True),
        ("desk?op/main.js", "desktop/main.js", True),
        ("desk?op/main.js", "deskop/main.js", False),
        ("a[0-9].txt", "a3.txt", True),
        ("a[0-9].txt", "ab.txt", False),
    ],
)
def test_match_path(pattern, path, expected):
    assert match_path(pattern, path) is expected


def test_match_any_empty_patterns_never_matches():
    assert match_any([], "ui/store.tsx") is False
    assert match_any(None, "ui/store.tsx") is False


@pytest.mark.parametrize(
    "pattern",
    [
        "/etc/passwd",
        "C:\\Users\\me\\x",
        "c:/Users/me/x",
        "\\\\server\\share",
        "~/notes.md",
        "../outside/**",
        "ui/../../etc/**",
        ".pjt/**",
        ".PJT/objects/**",
        "",
        "   ",
    ],
)
def test_path_pattern_rejections(pattern):
    with pytest.raises(InvalidArgument):
        normalize_path_pattern(pattern)


def test_path_pattern_normalization():
    assert normalize_path_pattern(r"ui\pages\**") == "ui/pages/**"
    assert normalize_path_patterns(["ui/**", "ui/**", "a.py"]) == ["ui/**", "a.py"]
    assert normalize_path_patterns(None) == []
    assert normalize_path_patterns("ui/**") == ["ui/**"]


# ============================================================ trailer 解析


def test_parse_trailers():
    body = (
        "Some subject line\n\n"
        "Body text with a colon: not a trailer\n"
        "\n"
        f"{TASK_TRAILER}: TSK-01A TSK-01B\n"
        "Reviewed-by: alice\n"
    )
    trailers = parse_trailers(body)
    assert trailer_values(trailers, TASK_TRAILER) == ["TSK-01A TSK-01B"]
    assert trailer_values(trailers, "reviewed-by") == ["alice"]


def test_parse_trailers_ignores_body_colons():
    body = "Subject\n\nConfig: value\nnot a trailer here\n"
    assert parse_trailers(body) == {}


def test_parse_trailers_empty():
    assert parse_trailers("just a message") == {}
    assert parse_trailers("") == {}


# ============================================================ git.available


def test_git_available_same_root(svc, repo):
    result = svc.call("git.available", {})
    assert result["available"] is True
    assert result["project_root_is_git_root"] is True
    assert result["project_subdir"] is None


def test_git_available_nested_project_root(svc, repo):
    """EFW 场景：project root 在 git root 的子目录里。"""
    nested = repo / "new" / "efw"
    nested.mkdir(parents=True)
    init_project(nested, name="Nested")
    service = ProjectService(open_project(nested))
    result = service.call("git.available", {})
    assert result["available"] is True
    assert result["project_root_is_git_root"] is False
    assert result["project_subdir"] == "new/efw"


def test_git_unavailable_is_state_not_error(tmp_path):
    """不在 git 仓库里 -> 明确状态，不是异常。"""
    root = tmp_path / "lonely"
    root.mkdir()
    init_project(root, name="NoGit")
    service = ProjectService(open_project(root))
    # tmp_path 通常不在任何仓库里；若在，用一个确定不在仓库里的子目录
    result = service.call("git.available", {})
    if result["available"]:  # pragma: no cover - 环境相关
        pytest.skip("tmp_path happens to be inside a git repository")
    assert result["reason"]
    status = service.call("git.status", {})
    assert status["available"] is False and status["files"] == []
    log = service.call("git.log", {})
    assert log["available"] is False and log["commits"] == []
    with pytest.raises(InvalidArgument):
        service.call("git.link_commit", {"commit": "HEAD"})


def test_git_binary_missing_is_graceful(svc, repo, monkeypatch):
    monkeypatch.setattr(git_integration.shutil, "which", lambda _name: None)
    result = svc.call("git.available", {})
    assert result["available"] is False
    assert "not found" in result["reason"]


# ============================================================ Area.path_patterns


def test_area_path_patterns_are_optional(svc):
    plain = svc.call("area.create", {"name": "Core"})
    assert plain["path_patterns"] == []
    assert svc.call("area.get", {"area_id": "Core"})["path_patterns"] == []
    # 没填的 Area 永远不参与匹配
    assert svc.call("area.match_path", {"path": "ui/store.tsx"}) == []


def test_area_create_with_patterns(svc):
    area = svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**", "index.html"]})
    assert area["path_patterns"] == ["ui/**", "index.html"]


def test_area_edit_patterns(svc):
    svc.call("area.create", {"name": "UI"})
    updated = svc.call("area.update", {"area_id": "UI", "path_patterns": ["ui/**"]})
    assert updated["path_patterns"] == ["ui/**"]
    cleared = svc.call("area.update", {"area_id": "UI", "path_patterns": []})
    assert cleared["path_patterns"] == []


def test_area_rejects_unsafe_pattern(svc):
    with pytest.raises(InvalidArgument):
        svc.call("area.create", {"name": "Bad", "path_patterns": ["../outside/**"]})
    with pytest.raises(InvalidArgument):
        svc.call("area.create", {"name": "Bad", "path_patterns": ["/etc/**"]})
    with pytest.raises(InvalidArgument):
        svc.call("area.create", {"name": "Bad", "path_patterns": [".pjt/**"]})
    assert svc.call("area.list") == []


def test_area_match_path(svc):
    svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**"]})
    svc.call("area.create", {"name": "Debug", "path_patterns": ["studio_core/debug.py"]})
    hits = svc.call("area.match_path", {"path": "ui/store.tsx"})
    assert [hit["name"] for hit in hits] == ["UI"]
    hits = svc.call("area.match_path", {"path": "studio_core/debug.py"})
    assert [hit["name"] for hit in hits] == ["Debug"]
    assert svc.call("area.match_path", {"path": "README.md"}) == []
    with pytest.raises(InvalidArgument):
        svc.call("area.match_path", {"path": ""})


def test_area_match_path_ignores_archived(svc):
    area = svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**"]})
    svc.call("area.archive", {"area_id": area["id"]})
    assert svc.call("area.match_path", {"path": "ui/store.tsx"}) == []


# ============================================================ git.status


def test_git_status_clean(svc, repo):
    result = svc.call("git.status", {})
    assert result["available"] is True
    assert result["count"] == 0
    assert result["files"] == []


def test_git_status_maps_changed_files_to_areas(svc, repo):
    svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**"]})
    svc.call("area.create", {"name": "Debug", "path_patterns": ["studio_core/debug.py"]})
    svc.call("area.create", {"name": "NoBinding"})
    (repo / "studio_core" / "debug.py").write_text("x = 2\n")
    (repo / "ui" / "store.tsx").write_text("export const s = 2\n")
    (repo / "README.md").write_text("hi\n")

    result = svc.call("git.status", {})
    by_path = {item["path"]: item for item in result["files"]}
    assert [hit["name"] for hit in by_path["studio_core/debug.py"]["candidate_areas"]] == ["Debug"]
    assert [hit["name"] for hit in by_path["ui/store.tsx"]["candidate_areas"]] == ["UI"]
    assert by_path["README.md"]["candidate_areas"] == []
    # 没绑定的 Area 在摘要里列出
    assert [a["name"] for a in result["unbound_areas"]] == ["NoBinding"]


def test_git_status_filter_by_area(svc, repo):
    svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**"]})
    svc.call("area.create", {"name": "Debug", "path_patterns": ["studio_core/**"]})
    (repo / "studio_core" / "debug.py").write_text("x = 3\n")
    (repo / "ui" / "store.tsx").write_text("export const s = 3\n")

    result = svc.call("git.status", {"area": "UI"})
    assert [item["path"] for item in result["files"]] == ["ui/store.tsx"]
    result = svc.call("git.status", {"area": "Debug"})
    assert [item["path"] for item in result["files"]] == ["studio_core/debug.py"]


def test_git_status_links_artifacts(svc, repo):
    task = svc.call("task.create", {"title": "loopback"})
    svc.call(
        "artifact.create",
        {"kind": "file", "locator": "studio_core/debug.py", "task": task["id"]},
    )
    (repo / "studio_core" / "debug.py").write_text("x = 4\n")
    item = next(
        row for row in svc.call("git.status", {})["files"]
        if row["path"] == "studio_core/debug.py"
    )
    assert [a["relation"] for a in item["referenced_by_artifacts"]] == ["task"]


def test_git_status_collapses_pjt(svc, repo):
    """`.pjt/**` 是我们自己的数据：默认折叠成一行，不淹没工程文件。"""
    svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**"]})
    (repo / "ui" / "store.tsx").write_text("export const s = 5\n")
    result = svc.call("git.status", {})
    assert all(not item["path"].startswith(".pjt/") for item in result["files"])
    assert result["pjt_changed"] > 0
    assert result["pjt_status_counts"]
    expanded = svc.call("git.status", {"include_pjt": True})
    assert any(item["path"].startswith(".pjt/") for item in expanded["files"])


def test_git_status_untracked_toggle(svc, repo):
    (repo / "NEW.md").write_text("new\n")
    assert len(svc.call("git.status", {})["files"]) == 1
    assert svc.call("git.status", {"include_untracked": False})["files"] == []


def test_git_status_nested_project_root_only_sees_own_files(svc, repo):
    """EFW 场景关键：只列 project root 下的文件，不列同仓库其它目录。"""
    nested = repo / "new" / "efw"
    nested.mkdir(parents=True)
    (nested / "own.py").write_text("a = 1\n")
    init_project(nested, name="Nested")
    # 同仓库里、但 project root 之外的改动
    (repo / "studio_core" / "debug.py").write_text("x = 6\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "nested", cwd=repo)
    (repo / "studio_core" / "debug.py").write_text("x = 7\n")
    (nested / "own.py").write_text("a = 2\n")

    service = ProjectService(open_project(nested))
    paths = [item["path"] for item in service.call("git.status", {})["files"]]
    assert paths == ["own.py"]


# ============================================================ git.log / link_commit


def test_git_log_filters_by_task_trailer(svc, repo):
    task = svc.call("task.create", {"title": "T"})
    (repo / "a.py").write_text("1\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", f"work\n\n{TASK_TRAILER}: {task['id']}", cwd=repo)
    (repo / "b.py").write_text("2\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "unrelated", cwd=repo)

    result = svc.call("git.log", {"task": task["id"]})
    assert result["available"] is True
    assert result["count"] == 1
    assert result["commits"][0]["linked_task_ids"] == [task["id"]]

    all_commits = svc.call("git.log", {})
    assert all_commits["count"] >= 2


def test_git_log_path_filter(svc, repo):
    (repo / "studio_core" / "debug.py").write_text("x = 8\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "touch debug", cwd=repo)
    (repo / "ui" / "store.tsx").write_text("export const s = 8\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "touch ui", cwd=repo)
    result = svc.call("git.log", {"path": "ui/store.tsx"})
    subjects = [c["subject"] for c in result["commits"]]
    # init commit 也创建了 ui/store.tsx，所以它会命中；关键是不含 touch debug
    assert subjects[0] == "touch ui"
    assert "touch debug" not in subjects


def test_git_link_commit_creates_artifact(svc, repo):
    task = svc.call("task.create", {"title": "T"})
    (repo / "a.py").write_text("1\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", f"real work\n\n{TASK_TRAILER}: {task['id']}", cwd=repo)
    sha = git("rev-parse", "HEAD", cwd=repo)

    result = svc.call("git.link_commit", {"commit": sha})
    assert result["created"] is True
    artifact = result["artifact"]
    assert artifact["kind"] == "git_commit"
    assert artifact["locator"] == sha[:12]
    assert artifact["related_task_ids"] == [task["id"]]
    assert svc.call("task.related_artifacts", {"task_id": task["id"]})[0]["id"] == artifact["id"]


def test_git_link_commit_is_idempotent(svc, repo):
    (repo / "a.py").write_text("1\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "work", cwd=repo)
    sha = git("rev-parse", "HEAD", cwd=repo)
    first = svc.call("git.link_commit", {"commit": sha})
    second = svc.call("git.link_commit", {"commit": sha})
    assert first["created"] is True
    assert second["created"] is False
    assert second["artifact"]["id"] == first["artifact"]["id"]
    assert len(svc.call("artifact.list", {})) == 1


def test_git_link_commit_explicit_task_overrides_trailer(svc, repo):
    tagged = svc.call("task.create", {"title": "tagged"})
    other = svc.call("task.create", {"title": "other"})
    (repo / "a.py").write_text("1\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", f"work\n\n{TASK_TRAILER}: {tagged['id']}", cwd=repo)
    sha = git("rev-parse", "HEAD", cwd=repo)
    result = svc.call("git.link_commit", {"commit": sha, "task": other["id"]})
    assert result["artifact"]["related_task_ids"] == [other["id"]]


def test_git_link_commit_emits_event(svc, repo):
    (repo / "a.py").write_text("1\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "work", cwd=repo)
    sha = git("rev-parse", "HEAD", cwd=repo)
    artifact = svc.call("git.link_commit", {"commit": sha})["artifact"]
    events = svc.call("artifact.history", {"artifact_id": artifact["id"]})["events"]
    assert [e["event_type"] for e in events] == ["git.commit_linked"]
    assert events[0]["payload"]["created"] is True
    assert events[0]["payload"]["sha"] == sha


def test_git_link_commit_accepts_any_ref(svc, repo):
    (repo / "a.py").write_text("1\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "work", cwd=repo)
    result = svc.call("git.link_commit", {"commit": "HEAD"})
    assert result["created"] is True


# ============================================================ 只读保证


def test_git_operations_never_write_the_repository(svc, repo):
    """核心约束：所有 git.* 调用都不许改动仓库。"""
    svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**"]})
    task = svc.call("task.create", {"title": "T"})
    (repo / "ui" / "store.tsx").write_text("export const s = 9\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", f"work\n\n{TASK_TRAILER}: {task['id']}", cwd=repo)
    sha = git("rev-parse", "HEAD", cwd=repo)

    before_head = git("rev-parse", "HEAD", cwd=repo)
    before_branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    before_reflog = git("reflog", cwd=repo)
    before_status = git("--no-optional-locks", "status", "--porcelain", "-uall", cwd=repo)

    svc.call("git.available", {})
    svc.call("git.status", {})
    svc.call("git.log", {"task": task["id"]})
    svc.call("git.link_commit", {"commit": sha})

    assert git("rev-parse", "HEAD", cwd=repo) == before_head
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == before_branch
    assert git("reflog", cwd=repo) == before_reflog
    after_status = git("--no-optional-locks", "status", "--porcelain", "-uall", cwd=repo)
    # 只允许 .pjt 变化：工程文件一个都不能被碰
    non_pjt_after = [p for p in porcelain_paths(after_status) if not p.startswith(".pjt/")]
    non_pjt_before = [p for p in porcelain_paths(before_status) if not p.startswith(".pjt/")]
    assert non_pjt_after == non_pjt_before
    assert non_pjt_after == []


def test_read_only_subcommand_whitelist():
    """只读不变量写在**代码**里，不是靠 review 盯着。"""
    from project_tool.integrations.git import (
        READ_ONLY_SUBCOMMANDS,
        WRITE_SUBCOMMANDS,
    )

    # 白名单是**精确集合**断言，不是包含断言——加任何子命令都必须在这里
    # 被显式看见。（V1-C 加了 ls-files：判断派生缓存有没有被提交，只读 index。）
    assert READ_ONLY_SUBCOMMANDS == {"rev-parse", "status", "log", "show", "ls-files"}
    # 两个集合不能有交集——否则「只读」承诺有洞
    assert not (READ_ONLY_SUBCOMMANDS & WRITE_SUBCOMMANDS)
    for verb in ("add", "commit", "checkout", "merge", "reset", "clean", "push", "fetch"):
        assert verb in WRITE_SUBCOMMANDS
    # ls-files 必须不在写集合里
    assert "ls-files" not in WRITE_SUBCOMMANDS


def test_git_repo_run_rejects_write_subcommands(svc, repo):
    """白名单是运行时强制的：写子命令直接抛错，不执行。"""
    from project_tool.integrations.git import detect

    handle = detect(repo)
    for verb in ("add", "commit", "push", "reset", "clean", "checkout"):
        with pytest.raises(ValueError, match="read-only"):
            handle.run(verb, "whatever")
    # 只读的能跑
    assert handle.run("rev-parse", "--show-toplevel").strip()


def test_git_service_does_not_shell_out_directly():
    """service 层不直接 subprocess，全部经由适配器。"""
    text = (Path(GitService.__module__.replace(".", "/") + ".py")).read_text(encoding="utf-8")
    assert "subprocess" not in text
    assert "--no-optional-locks" in Path("project_tool/integrations/git.py").read_text(
        encoding="utf-8"
    )


# ============================================================ CLI


def test_cli_git_flow(repo):
    def invoke(args):
        return runner.invoke(app, args)

    project = ["-C", str(repo)]
    assert invoke([*project, "area", "add", "UI", "--path-pattern", "ui/**"]).exit_code == 0
    assert invoke([*project, "git", "status"]).exit_code == 0
    assert invoke([*project, "git", "log"]).exit_code == 0
    assert "working tree clean" in invoke([*project, "git", "status"]).output

    (repo / "ui" / "store.tsx").write_text("export const s = 10\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "work", cwd=repo)
    result = invoke(["--json", *project, "git", "link-commit", "HEAD"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["created"] is True

    status_out = invoke([*project, "git", "status"]).output
    assert "UI" not in status_out  # 干净时不该列 area
    assert "working tree clean" in status_out


def test_cli_git_help_page():
    result = runner.invoke(app, ["git", "--help"])
    assert result.exit_code == 0



def test_git_commit_artifact_verify_resolves(svc, repo):
    """V1-B：登记的 commit 能被 artifact.verify 真正解析出来。"""
    (repo / "a.py").write_text("1\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "work", cwd=repo)
    sha = git("rev-parse", "HEAD", cwd=repo)
    artifact = svc.call("git.link_commit", {"commit": sha})["artifact"]

    row = svc.call("artifact.verify", {"artifact_id": artifact["id"]})[0]
    assert row["status"] == "ok"
    assert row["exists"] is True
    assert row["path"] == sha
    assert "resolved to" in row["detail"]


def test_git_commit_artifact_verify_missing_when_absent(svc, repo):
    """commit 不存在 -> missing（warning 级），不是 corrupted。"""
    svc.call("artifact.create", {"kind": "git_commit", "locator": "deadbeefff"})
    row = svc.call("artifact.verify", {})[0]
    assert row["status"] == "missing"
    assert row["exists"] is False
    assert svc.call("project.doctor")["ok"] is True
