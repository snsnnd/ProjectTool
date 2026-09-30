"""V1-B.2：把已有 service method 补上 CLI 入口。

这一批**不新增任何领域概念**——每个 method 早就存在于 service + registry，
只是 CLI 触达不到。补完后 registry 的 108 个 method 全部有 CLI 入口
（`system.*` / `project.init` / `project.open` 走顶层命令与启动路径）。

同时覆盖 V1-B.2 的两个渲染修复：
  - 表格长标题按显示宽度截断（中文算 2 列），不再折行
  - `pjt status` 的 computed blocked 带上 area 名 / milestone 标题
"""

from __future__ import annotations

import json
import subprocess
import tomllib
import unicodedata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from project_tool.cli.main import app
from project_tool.cli.render import display_width, ellipsis
from project_tool.storage import init_project

runner = CliRunner()


def invoke(args):
    return runner.invoke(app, args)


def jinvoke(args):
    """--json 模式：stdout 直接可 json.loads。"""
    return runner.invoke(app, ["--json", *args])


@pytest.fixture()
def root(tmp_path):
    init_project(tmp_path, name="Completeness")
    return tmp_path


def _git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    return path


# ---------------------------------------------------------------- goal 生命周期


def test_goal_archive_then_restore(root):
    created = jinvoke(["-C", str(root), "goal", "add", "临时目标"])
    assert created.exit_code == 0, created.output
    goal_id = json.loads(created.output)["result"]["id"]

    assert jinvoke(["-C", str(root), "goal", "archive", goal_id]).exit_code == 0
    assert json.loads(jinvoke(["-C", str(root), "goal", "list"]).output)["result"] == []

    assert jinvoke(["-C", str(root), "goal", "restore", goal_id]).exit_code == 0
    listed = json.loads(jinvoke(["-C", str(root), "goal", "list"]).output)["result"]
    assert [g["id"] for g in listed] == [goal_id]


def test_goal_archive_respects_expected_rev(root):
    created = jinvoke(["-C", str(root), "goal", "add", "g"])
    goal_id = json.loads(created.output)["result"]["id"]
    bad = invoke(
        ["-C", str(root), "goal", "archive", goal_id, "--expected-rev", "sha256:" + "0" * 64]
    )
    assert bad.exit_code != 0
    assert "REVISION_CONFLICT" in bad.output


# ---------------------------------------------------------------- area 补全


def test_area_set_parent_and_detach(root):
    core = json.loads(jinvoke(["-C", str(root), "area", "add", "core"]).output)["result"]["id"]
    ui = json.loads(jinvoke(["-C", str(root), "area", "add", "ui"]).output)["result"]["id"]

    linked = jinvoke(["-C", str(root), "area", "set-parent", ui, "--parent", core])
    assert linked.exit_code == 0, linked.output
    assert json.loads(linked.output)["result"]["parent_area_id"] == core

    detached = jinvoke(["-C", str(root), "area", "set-parent", ui])
    assert detached.exit_code == 0
    assert json.loads(detached.output)["result"]["parent_area_id"] is None


def test_area_set_parent_rejects_a_cycle(root):
    a = json.loads(jinvoke(["-C", str(root), "area", "add", "a"]).output)["result"]["id"]
    b = json.loads(jinvoke(["-C", str(root), "area", "add", "b"]).output)["result"]["id"]
    assert jinvoke(["-C", str(root), "area", "set-parent", b, "--parent", a]).exit_code == 0
    # a 的父要是 b，就成了 a -> b -> a
    cyclic = jinvoke(["-C", str(root), "area", "set-parent", a, "--parent", b])
    assert cyclic.exit_code != 0
    assert "HIERARCHY_CYCLE" in cyclic.output


def test_area_tasks_lists_only_that_area(root):
    core = json.loads(jinvoke(["-C", str(root), "area", "add", "core"]).output)["result"]["id"]
    ui = json.loads(jinvoke(["-C", str(root), "area", "add", "ui"]).output)["result"]["id"]
    in_core = json.loads(
        jinvoke(["-C", str(root), "task", "add", "核心任务", "--area", core]).output
    )["result"]["id"]
    jinvoke(["-C", str(root), "task", "add", "界面任务", "--area", ui])

    result = jinvoke(["-C", str(root), "area", "tasks", core])
    assert result.exit_code == 0, result.output
    assert [t["id"] for t in json.loads(result.output)["result"]] == [in_core]


def test_area_tasks_excludes_archived_by_default(root):
    area = json.loads(jinvoke(["-C", str(root), "area", "add", "core"]).output)["result"]["id"]
    task = json.loads(
        jinvoke(["-C", str(root), "task", "add", "任务", "--area", area]).output
    )["result"]["id"]
    jinvoke(["-C", str(root), "task", "archive", task])

    assert json.loads(jinvoke(["-C", str(root), "area", "tasks", area]).output)["result"] == []
    with_archived = jinvoke(["-C", str(root), "area", "tasks", area, "--include-archived"])
    assert [t["id"] for t in json.loads(with_archived.output)["result"]] == [task]


def test_area_match_path_uses_path_patterns(root):
    jinvoke(["-C", str(root), "area", "add", "core", "--path-pattern", "src/core/**"])
    jinvoke(["-C", str(root), "area", "add", "ui", "--path-pattern", "src/ui/**"])

    hit = jinvoke(["-C", str(root), "area", "match-path", "src/core/thing.ts"])
    assert hit.exit_code == 0, hit.output
    assert [m["name"] for m in json.loads(hit.output)["result"]] == ["core"]

    miss = jinvoke(["-C", str(root), "area", "match-path", "docs/readme.md"])
    assert json.loads(miss.output)["result"] == []


def test_area_match_path_rejects_empty(root):
    bad = invoke(["-C", str(root), "area", "match-path", ""])
    assert bad.exit_code != 0
    assert "INVALID_ARGUMENT" in bad.output


def test_area_history(root):
    area = json.loads(jinvoke(["-C", str(root), "area", "add", "core"]).output)["result"]["id"]
    result = jinvoke(["-C", str(root), "area", "history", area])
    assert result.exit_code == 0, result.output
    events = json.loads(result.output)["result"]["events"]
    assert [e["event_type"] for e in events] == ["area.created"]


# ---------------------------------------------------------------- update 补全


def test_update_edit_changes_summary(root):
    created = jinvoke(["-C", str(root), "update", "add", "原始正文", "-s", "周报 1"])
    assert created.exit_code == 0, created.output
    update_id = json.loads(created.output)["result"]["id"]

    edited = jinvoke(["-C", str(root), "update", "edit", update_id, "--summary", "周报 2"])
    assert edited.exit_code == 0, edited.output
    shown = json.loads(jinvoke(["-C", str(root), "update", "show", update_id]).output)["result"]
    assert shown["summary"] == "周报 2"
    assert shown["body"] == "原始正文"  # 没传的字段不动


def test_update_edit_without_changes_is_a_noop(root):
    created = jinvoke(["-C", str(root), "update", "add", "正文", "-s", "标题"])
    update_id = json.loads(created.output)["result"]["id"]
    before = json.loads(jinvoke(["-C", str(root), "update", "show", update_id]).output)["result"]

    assert jinvoke(["-C", str(root), "update", "edit", update_id]).exit_code == 0
    after = json.loads(jinvoke(["-C", str(root), "update", "show", update_id]).output)["result"]
    assert after["rev"] == before["rev"]


def test_update_archive_and_history(root):
    created = jinvoke(["-C", str(root), "update", "add", "正文", "-s", "标题"])
    update_id = json.loads(created.output)["result"]["id"]

    assert jinvoke(["-C", str(root), "update", "archive", update_id]).exit_code == 0
    assert json.loads(jinvoke(["-C", str(root), "update", "list"]).output)["result"] == []

    history = jinvoke(["-C", str(root), "update", "history", update_id])
    assert history.exit_code == 0, history.output
    types = [e["event_type"] for e in json.loads(history.output)["result"]["events"]]
    assert types == ["update.created", "object.archived"]


# ---------------------------------------------------------------- decision


def test_decision_history(root):
    created = jinvoke(["-C", str(root), "decision", "add", "用 X", "--rationale", "理由"])
    assert created.exit_code == 0, created.output
    decision_id = json.loads(created.output)["result"]["id"]
    result = jinvoke(["-C", str(root), "decision", "history", decision_id])
    assert result.exit_code == 0, result.output
    assert [e["event_type"] for e in json.loads(result.output)["result"]["events"]] == [
        "decision.created"
    ]


# ---------------------------------------------------------------- task 父子


def test_task_set_parent_and_detach(root):
    parent = json.loads(jinvoke(["-C", str(root), "task", "add", "父"]).output)["result"]["id"]
    child = json.loads(jinvoke(["-C", str(root), "task", "add", "子"]).output)["result"]["id"]

    linked = jinvoke(["-C", str(root), "task", "set-parent", child, "--parent", parent])
    assert linked.exit_code == 0, linked.output
    assert json.loads(linked.output)["result"]["parent_task_id"] == parent

    detached = jinvoke(["-C", str(root), "task", "set-parent", child])
    assert detached.exit_code == 0
    assert json.loads(detached.output)["result"]["parent_task_id"] is None


def test_task_cannot_be_its_own_parent(root):
    task = json.loads(jinvoke(["-C", str(root), "task", "add", "t"]).output)["result"]["id"]
    bad = invoke(["-C", str(root), "task", "set-parent", task, "--parent", task])
    assert bad.exit_code != 0
    assert "INVALID_ARGUMENT" in bad.output


# ---------------------------------------------------------------- link status


def test_link_status_reports_a_resolvable_local_project(root, tmp_path):
    sibling = _git_repo(tmp_path / "sibling")
    init_project(sibling, name="Sibling")
    added = jinvoke(
        ["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"]
    )
    assert added.exit_code == 0, added.output

    result = jinvoke(["-C", str(root), "link", "status", "sib"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["resolved"] is True
    assert payload["project"]["name"] == "Sibling"


def test_link_status_does_not_claim_remote_links_are_resolved(root):
    jinvoke(
        ["-C", str(root), "link", "add", "up", "https://example.com/x",
         "--kind", "remote_project"]
    )
    result = jinvoke(["-C", str(root), "link", "status", "up"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["resolved"] is False
    assert payload["verifiable"] is False
    assert "no server" in payload["error"]


def test_link_status_rejects_an_empty_reference(root):
    bad = invoke(["-C", str(root), "link", "status", ""])
    assert bad.exit_code != 0
    assert "INVALID_ARGUMENT" in bad.output


# ---------------------------------------------------------------- 裸 pjt git


def test_bare_git_reports_availability_inside_a_repo(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    init_project(repo, name="Gitty")
    result = invoke(["-C", str(repo), "git"])
    assert result.exit_code == 0, result.output
    assert "available" in result.output
    assert "project root == git root" in result.output


def test_bare_git_reports_unavailable_outside_a_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    init_project(plain, name="Plain")
    result = invoke(["-C", str(plain), "git"])
    assert result.exit_code == 0, result.output
    assert "unavailable" in result.output


def test_bare_git_still_shows_subcommands(root):
    assert invoke(["-C", str(root), "git", "--help"]).exit_code == 0
    assert "link-commit" in invoke(["-C", str(root), "git", "--help"]).output


# ---------------------------------------------------------------- 渲染修复


def test_display_width_counts_cjk_as_two_columns():
    assert display_width("abc") == 3
    assert display_width("中文") == 4
    assert display_width("a中") == 3


TRUNCATION_SAMPLES = ("中文标题很长很长", "ascii title that is long", "", "中", "a中b中c")


def test_ellipsis_never_exceeds_the_requested_width():
    """契约：结果的显示宽度 <= 请求宽度（省略号本身算在预算内）。"""
    for text in TRUNCATION_SAMPLES:
        for width in range(2, 12):
            assert display_width(ellipsis(text, width)) <= width, (text, width)


def test_ellipsis_returns_empty_for_a_degenerate_width():
    for width in (0, 1, -3):
        assert ellipsis("中文标题", width) == ""


def test_ellipsis_leaves_text_that_already_fits_untouched():
    assert ellipsis("中文", 4) == "中文"  # 正好 4 列
    assert ellipsis("abc", 3) == "abc"
    assert ellipsis("", 10) == ""


def test_ellipsis_marks_actual_truncation_with_an_ellipsis():
    for text in TRUNCATION_SAMPLES:
        for width in range(2, 12):
            out = ellipsis(text, width)
            if display_width(text) <= width:
                assert out == text
            else:
                assert out.endswith("…"), (text, width)


def test_ellipsis_leaves_short_text_alone():
    assert ellipsis("短", 10) == "短"
    assert ellipsis("abc", 10) == "abc"


def test_ellipsis_keeps_whole_characters():
    # 不能把一个全角字符劈成半个
    assert ellipsis("中文", 3) == "中…"


def test_task_list_renders_one_line_per_task(root):
    invoke(["-C", str(root), "task", "add", "通信页行内编辑（信号、事件、队列的增删改）" * 3])
    result = invoke(["-C", str(root), "task", "list"])
    assert result.exit_code == 0, result.output
    body = [line for line in result.output.splitlines() if "TSK-" in line]
    assert len(body) == 1


def test_status_blocked_shows_milestone_title(root):
    milestone = json.loads(
        jinvoke(["-C", str(root), "milestone", "add", "阶段一"]).output
    )["result"]["id"]
    blocker = json.loads(
        jinvoke(["-C", str(root), "task", "add", "前置任务", "--milestone", milestone]).output
    )["result"]["id"]
    blocked = json.loads(
        jinvoke(["-C", str(root), "task", "add", "被挡任务", "--milestone", milestone]).output
    )["result"]["id"]
    depend = jinvoke(
        ["-C", str(root), "task", "depend", blocked, blocker, "--relation", "depends_on"]
    )
    assert depend.exit_code == 0, depend.output

    result = jinvoke(["-C", str(root), "status"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    blocked = payload["blocked"]
    assert len(blocked) == 1
    assert blocked[0]["milestone_title"] == "阶段一"


def test_status_blocked_shows_area_name(root):
    area = json.loads(jinvoke(["-C", str(root), "area", "add", "核心引擎"]).output)["result"]["id"]
    blocker = json.loads(
        jinvoke(["-C", str(root), "task", "add", "前置", "--area", area]).output
    )["result"]["id"]
    blocked = json.loads(
        jinvoke(["-C", str(root), "task", "add", "被挡", "--area", area]).output
    )["result"]["id"]
    depend = jinvoke(
        ["-C", str(root), "task", "depend", blocked, blocker, "--relation", "depends_on"]
    )
    assert depend.exit_code == 0, depend.output

    payload = json.loads(jinvoke(["-C", str(root), "status"]).output)["result"]
    assert payload["blocked"][0]["area_name"] == "核心引擎"


def test_status_does_not_dump_every_area(root):
    """V1-A 的决定：status 不列举所有 Area。归属信息只内联在 blocked 条目上。"""
    jinvoke(["-C", str(root), "area", "add", "alpha"])
    jinvoke(["-C", str(root), "area", "add", "beta"])
    result = jinvoke(["-C", str(root), "status"])
    assert "Areas" not in result.output
    assert "areas" not in json.loads(result.output)["result"]


def test_ellipsis_helper_is_importable_from_render():
    assert callable(ellipsis)
    assert unicodedata.east_asian_width("中") == "W"


# ------------------------------------------- link 的机器本地路径（V1-B.2 补完的半截功能）


def _absolute_locator_link_error(root, absolute: str) -> str:
    """absolute 必须由 tmp_path 派生：POSIX 的 /abs/x 在 Windows 上并不算绝对路径
    （PureWindowsPath('/abs/x').is_absolute() 是 False），写死会只在 Windows 上炸。"""
    bad = invoke(["-C", str(root), "link", "add", "sib", absolute, "--kind", "local_project"])
    assert bad.exit_code != 0
    assert "INVALID_ARGUMENT" in bad.output
    return bad.output


def test_link_add_absolute_locator_error_names_both_ways_out(root, tmp_path):
    """原来只说「去 local.toml 映射」，但当时根本没有 CLI 能映射——误导。"""
    output = _absolute_locator_link_error(root, str(tmp_path / "elsewhere"))
    assert "relative" in output
    assert "map-local" in output


def test_link_add_rejects_absolute_locator(root, tmp_path):
    sibling = tmp_path / "sib"
    init_project(sibling, name="Sib")
    bad = invoke(
        ["-C", str(root), "link", "add", "sib", str(sibling), "--kind", "local_project"]
    )
    assert bad.exit_code != 0
    # 拒绝之后不能留下半个 link
    assert json.loads(jinvoke(["-C", str(root), "link", "list"]).output)["result"] == []


def test_link_map_local_path_resolves_the_link(root, tmp_path):
    sibling = tmp_path / "sib"
    init_project(sibling, name="Mapped")
    jinvoke(["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"])

    mapped = jinvoke(["-C", str(root), "link", "map-local", "sib", str(sibling)])
    assert mapped.exit_code == 0, mapped.output
    assert json.loads(mapped.output)["result"]["has_project"] is True

    status = jinvoke(["-C", str(root), "link", "status", "sib"])
    payload = json.loads(status.output)["result"]
    assert payload["resolved"] is True
    assert payload["project"]["name"] == "Mapped"
    assert payload["local_mapped"] is True


def _local_link_paths(root) -> dict:
    """解析 local.toml 的 [links.*] path。

    不要用 `str(path) in text` 判断：save_local 写的是 json.dumps(path)，
    Windows 上反斜杠会被翻倍（"C:\\x" -> "C:\\\\x"），字面匹配在
    Windows 上永远不成立。必须解析后比较。
    """
    pjt = root / ".pjt" / "local" / "local.toml"
    data = tomllib.loads(pjt.read_text(encoding="utf-8"))
    return {name: cfg.get("path") for name, cfg in (data.get("links") or {}).items()}


def _path_needles(path) -> list:
    """路径的原始形态 + JSON 转义后的形态（Windows 专用）。"""
    return [str(path), json.dumps(str(path))[1:-1]]


def test_link_map_local_path_never_leaks_into_shared_state(root, tmp_path):
    """§7：绝对路径只进 local.toml。objects / events / project.json 一律不许出现。"""
    sibling = tmp_path / "sib"
    init_project(sibling, name="Secret")
    jinvoke(["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"])
    jinvoke(["-C", str(root), "link", "map-local", "sib", str(sibling)])

    assert _local_link_paths(root)["sib"] == str(sibling)

    needles = _path_needles(sibling)
    pjt = root / ".pjt"
    for shared in (pjt / "objects", pjt / "events"):
        for path in shared.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                for needle in needles:
                    assert needle not in text, path
    project_json = (pjt / "project.json").read_text(encoding="utf-8")
    for needle in needles:
        assert needle not in project_json


def test_link_map_local_path_emits_no_event(root, tmp_path):
    """写事件等于把绝对路径抄进共享历史，等于绕过 §7。"""
    sibling = tmp_path / "sib"
    init_project(sibling, name="Sib")
    jinvoke(["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"])
    before = json.loads(jinvoke(["-C", str(root), "log"]).output)["result"]["count"]
    jinvoke(["-C", str(root), "link", "map-local", "sib", str(sibling)])
    after = json.loads(jinvoke(["-C", str(root), "log"]).output)["result"]["count"]
    assert after == before


def test_link_map_local_path_requires_an_absolute_path(root):
    jinvoke(["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"])
    bad = jinvoke(["-C", str(root), "link", "map-local", "sib", "relative/path"])
    assert bad.exit_code != 0
    assert "INVALID_ARGUMENT" in bad.output


def test_link_map_local_path_rejects_empty(root):
    jinvoke(["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"])
    bad = jinvoke(["-C", str(root), "link", "map-local", "sib", " "])
    assert bad.exit_code != 0
    assert "INVALID_ARGUMENT" in bad.output


def test_link_map_local_path_needs_an_existing_link(root, tmp_path):
    bad = jinvoke(
        ["-C", str(root), "link", "map-local", "nope", str(tmp_path / "wherever")]
    )
    assert bad.exit_code != 0
    assert "INVALID_ARGUMENT" in bad.output


def test_link_map_local_path_does_not_claim_success_without_a_project(root, tmp_path):
    """路径存在但不是 .pjt 项目：如实说 note，交给 link.status 判定（§12）。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    jinvoke(["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"])
    mapped = jinvoke(["-C", str(root), "link", "map-local", "sib", str(empty)])
    assert json.loads(mapped.output)["result"]["has_project"] is False

    status = jinvoke(["-C", str(root), "link", "status", "sib"])
    assert json.loads(status.output)["result"]["resolved"] is False


def test_link_unmap_local_path_falls_back_to_the_object_locator(root, tmp_path):
    sibling = tmp_path / "sib"
    init_project(sibling, name="Sib")
    jinvoke(["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"])
    jinvoke(["-C", str(root), "link", "map-local", "sib", str(sibling)])

    unmapped = jinvoke(["-C", str(root), "link", "unmap-local", "sib"])
    assert unmapped.exit_code == 0, unmapped.output
    assert json.loads(unmapped.output)["result"]["unmapped"] is True

    # 映射没了，回到对象里的相对 locator；那个路径不存在，所以如实 unresolved
    status = json.loads(jinvoke(["-C", str(root), "link", "status", "sib"]).output)["result"]
    assert status["local_mapped"] if "local_mapped" in status else True
    assert "local_mapped" not in status


def test_link_unmap_local_path_is_a_noop_without_a_mapping(root):
    jinvoke(["-C", str(root), "link", "add", "sib", "sibling", "--kind", "local_project"])
    result = jinvoke(["-C", str(root), "link", "unmap-local", "sib"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result"]["unmapped"] is False


def test_local_toml_is_git_ignored(tmp_path):
    """§7 / §3：.pjt/local/ 不进 Git。必须真建一个 git 仓库，否则这条断言形同虚设。"""
    repo = _git_repo(tmp_path / "repo")
    init_project(repo, name="Ignored")
    probe = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", ".pjt/local/local.toml"],
        capture_output=True,
    )
    assert probe.returncode == 0, ".pjt/local/local.toml must be git-ignored (§7)"

    # 确认 .gitignore 是项目自带的那条，而不是环境里的 global 配置在兜底
    matched = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-v", ".pjt/local/local.toml"],
        capture_output=True,
        text=True,
    )
    assert ".pjt/local/" in matched.stdout


def test_map_local_writes_a_git_ignorable_file(tmp_path):
    """映射写完之后，git 依然看不到这个绝对路径。"""
    repo = _git_repo(tmp_path / "repo")
    init_project(repo, name="Ignored")
    sibling = tmp_path / "sib"
    init_project(sibling, name="Sib")
    jinvoke(["-C", str(repo), "link", "add", "sib", "sibling", "--kind", "local_project"])
    jinvoke(["-C", str(repo), "link", "map-local", "sib", str(sibling)])

    assert _local_link_paths(repo)["sib"] == str(sibling)
    tracked = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
    ).stdout
    for needle in _path_needles(sibling):
        assert needle not in tracked
