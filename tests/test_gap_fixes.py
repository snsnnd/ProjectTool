"""V1-B.1：补齐 A/B 两组欠账。

A 组（真 bug / 文档已承诺但没兑现）
  1. `link` 的非 local kind 报告 `resolved=true` —— 其实什么都没验证
  2. `doctor` 不检查 `Area.path_patterns` —— 目录改名后 pattern 悬挂而无人报警

B 组（CLI 覆盖不全：108 个 method 里这些之前触达不到）
  3. `project.update` 没有任何 CLI —— 改项目名只能手改 project.json
  4. `member.map_git_identity` 没有任何 CLI —— Git 适配器的自然延伸
"""

from __future__ import annotations

import json
import shutil

import pytest
from typer.testing import CliRunner

from project_tool.application.service import ProjectService
from project_tool.cli.main import app
from project_tool.domain.errors import InvalidArgument, RevisionConflict
from project_tool.storage import init_project, open_project

runner = CliRunner()
STALE_REV = "sha256:" + "0" * 64


def invoke(args):
    return runner.invoke(app, args)


@pytest.fixture()
def root(tmp_path):
    init_project(tmp_path, name="Fixture")
    return tmp_path


@pytest.fixture()
def svc(root):
    return ProjectService(open_project(root))


# ================================================================ A1: link 不再说谎


def test_link_remote_kind_does_not_claim_resolved(svc):
    for kind, locator in (
        ("remote_project", "https://github.com/foo/bar"),
        ("git_repository", "https://github.com/foo/bar.git"),
        ("external", "https://example.com/spec"),
    ):
        name = f"link-{kind}"
        svc.call("link.add", {"name": name, "locator": locator, "kind": kind})
        result = svc.call("link.resolve", {"name": name})
        assert result["resolved"] is False, kind
        assert result.get("verifiable") is False
        assert "no server" in result["error"]
        assert "local_project" in result["error"]


def test_link_record_still_usable_even_if_not_resolvable(svc):
    """不解析 != 不允许记录。remote link 依然是有效的项目关联信息。"""
    svc.call("link.add", {"name": "upstream", "locator": "https://github.com/foo/bar",
                          "kind": "remote_project"})
    record = svc.call("link.get", {"name": "upstream"})
    assert record["target"]["locator"] == "https://github.com/foo/bar"
    assert record["enabled"] is True
    assert len(svc.call("link.list")) == 1


def test_link_local_project_still_resolves(root, svc):
    target = root / "other-project"   # local_project 的 locator 相对 project root
    target.mkdir()
    init_project(target, name="Other")
    svc.call("link.add", {"name": "other", "locator": target.name, "kind": "local_project"})
    result = svc.call("link.resolve", {"name": "other"})
    assert result["resolved"] is True
    assert result["project"]["name"] == "Other"


def test_link_local_project_missing_reports_why(svc):
    svc.call("link.add", {"name": "gone", "locator": "../nowhere", "kind": "local_project"})
    result = svc.call("link.resolve", {"name": "gone"})
    assert result["resolved"] is False
    assert "project.json" in result["error"]


def test_link_without_locator_reports_why(svc):
    svc.call("link.add", {"name": "empty", "locator": "", "kind": "external"})
    result = svc.call("link.resolve", {"name": "empty"})
    assert result["resolved"] is False
    assert "neither locator nor project_id" in result["error"]


def test_link_resolve_is_read_only(svc):
    svc.call("link.add", {"name": "upstream", "locator": "https://x/y",
                          "kind": "remote_project"})
    before = svc.call("link.get", {"name": "upstream"})
    svc.call("link.resolve", {"name": "upstream"})
    svc.call("link.status", {"name": "upstream"})
    assert svc.call("link.get", {"name": "upstream"}) == before


# ================================================================ A2: doctor 检查 path_patterns


def test_doctor_checks_path_patterns(svc, root):
    (root / "ui").mkdir()
    (root / "ui" / "store.tsx").write_text("x\n")
    svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**"]})
    report = svc.call("project.doctor")
    check = {c["name"]: c for c in report["checks"]}["areas.path_patterns"]
    assert check["status"] == "ok"
    assert "1 area path pattern(s)" in check["message"]


def test_doctor_warns_when_pattern_dangles_after_rename(svc, root):
    """目录改名后 pattern 悬挂 -> warning（不是 corrupted，但要有人告诉你）。"""
    (root / "ui").mkdir()
    (root / "ui" / "store.tsx").write_text("x\n")
    svc.call("area.create", {"name": "UI", "path_patterns": ["ui/**"]})
    assert {c["name"]: c for c in svc.call("project.doctor")["checks"]}[
        "areas.path_patterns"
    ]["status"] == "ok"

    shutil.move(str(root / "ui"), str(root / "frontend"))
    report = ProjectService(open_project(root)).call("project.doctor")
    check = {c["name"]: c for c in report["checks"]}["areas.path_patterns"]
    assert check["status"] == "warning"
    assert "match nothing" in check["message"]
    assert any("ui/**" in item for item in check["details"])
    assert report["ok"] is True, "悬挂是 warning，不是数据损坏"


def test_doctor_skips_areas_without_patterns(svc, root):
    """没填 path_patterns 的 Area 不该被报——它是纯语义 Area。"""
    svc.call("area.create", {"name": "Core"})
    check = {c["name"]: c for c in svc.call("project.doctor")["checks"]}
    assert "areas.path_patterns" not in check


def test_doctor_flags_hand_edited_unsafe_pattern(svc, root):
    """手改对象塞进越界 pattern -> error（安全不变量）。"""
    from project_tool.domain.hashing import compute_rev

    area = svc.call("area.create", {"name": "Evil", "path_patterns": ["ui/**"]})
    path = root / ".pjt" / "objects" / "areas" / f"{area['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["path_patterns"] = ["../../etc/**"]
    record["rev"] = compute_rev({k: v for k, v in record.items() if k != "rev"})
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    report = ProjectService(open_project(root)).call("project.doctor")
    check = {c["name"]: c for c in report["checks"]}["areas.path_patterns"]
    assert check["status"] == "error"
    assert any("'..' segments" in item for item in check["details"])
    # rev 是自洽的（所以对象本身能读），报的是 pattern 越界这一条
    assert ProjectService(open_project(root)).call(
        "area.get", {"area_id": area["id"]}
    )["path_patterns"] == ["../../etc/**"]


def test_doctor_pattern_does_not_count_pjt_files_as_hits(svc, root):
    """`.pjt/**` 里的文件不算「pattern 有命中」——那是我们的数据，不是工程文件。"""
    svc.call("task.create", {"title": "T"})   # 产生 .pjt/objects/tasks/*.json
    area = svc.call("area.create", {"name": "Suspicious", "path_patterns": ["objects/**"]})
    assert area["path_patterns"] == ["objects/**"]
    check = {c["name"]: c for c in svc.call("project.doctor")["checks"]}["areas.path_patterns"]
    assert check["status"] == "warning"
    assert "match nothing" in check["message"]


@pytest.mark.parametrize(
    "pattern",
    [".pjt/**", ".PJT/objects/**", "./.pjt/config.toml", "a/./b/**", "ui//x", "a/../b", ""],
)
def test_area_rejects_unsafe_pattern(svc, pattern):
    """`.` / 空 / `..` 段一律拒绝——否则 `./.pjt/…` 会绕过 `.pjt` 检查。"""
    with pytest.raises(InvalidArgument):
        svc.call("area.create", {"name": "Bad", "path_patterns": [pattern]})


# ================================================================ B3: project edit CLI


def test_cli_project_show_and_edit(root):
    result = invoke(["-C", str(root), "project", "show"])
    assert result.exit_code == 0, result.output
    assert "Fixture" in result.output

    result = invoke(["--json", "-C", str(root), "project", "edit",
                     "--name", "Renamed", "--description", "new description"])
    assert result.exit_code == 0, result.output
    record = json.loads(result.output)["result"]
    assert record["name"] == "Renamed"
    assert record["description"] == "new description"
    assert record["version"] == 2
    # show / edit 返回同一种形状（扁平 project 记录）
    shown = json.loads(invoke(["--json", "-C", str(root), "project", "show"]).output)["result"]
    assert shown["id"] == record["id"]
    assert set(shown) == set(record)
    assert "Renamed" in invoke(["-C", str(root), "project", "show"]).output


def test_cli_project_edit_status(root):
    result = invoke(["--json", "-C", str(root), "project", "edit", "--status", "paused"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result"]["status"] == "paused"


def test_cli_project_edit_expected_rev(root):
    result = invoke(["--json", "-C", str(root), "project", "edit",
                     "--name", "X", "--expected-rev", STALE_REV])
    assert result.exit_code == 5
    assert json.loads(result.output)["error"]["code"] == "REVISION_CONFLICT"
    # 没被改动
    assert "Fixture" in invoke(["-C", str(root), "project", "show"]).output


def test_cli_project_edit_valid_rev(root):
    current = json.loads(
        (root / ".pjt" / "project.json").read_text(encoding="utf-8")
    )["rev"]
    assert current.startswith("sha256:")
    result = invoke(["--json", "-C", str(root), "project", "edit",
                     "--name", "Y", "--expected-rev", current])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result"]["name"] == "Y"


def test_cli_project_edit_invalid_status(root):
    result = invoke(["--json", "-C", str(root), "project", "edit", "--status", "bogus"])
    assert result.exit_code == 3
    assert json.loads(result.output)["error"]["code"] == "INVALID_ARGUMENT"


# ================================================================ B4: member map-git CLI


def test_cli_member_map_git(root):
    invoke(["-C", str(root), "member", "add", "jichao", "--name", "计超"])
    result = invoke(["--json", "-C", str(root), "member", "map-git", "jichao",
                     "--git-name", "jichao", "--git-email", "jichao@example.com",
                     "--git-name", "Jichao"])
    assert result.exit_code == 0, result.output
    git = json.loads(result.output)["result"]["git"]
    assert git["names"] == ["jichao", "Jichao"]
    assert git["emails"] == ["jichao@example.com"]


def test_member_map_git_is_idempotent(root, svc):
    invoke(["-C", str(root), "member", "add", "alice"])
    invoke(["-C", str(root), "member", "map-git", "alice", "--git-name", "alice"])
    before = svc.call("member.get", {"member": "alice"})
    result = invoke(["--json", "-C", str(root), "member", "map-git", "alice",
                     "--git-name", "alice"])
    assert result.exit_code == 0
    after = json.loads(result.output)["result"]
    assert after["git"]["names"] == ["alice"]
    assert after["version"] == before["version"], "重复映射不应产生新版本"


def test_cli_member_map_git_requires_an_argument(root):
    invoke(["-C", str(root), "member", "add", "alice"])
    result = invoke(["-C", str(root), "member", "map-git", "alice"])
    # usage error（exit 2）。文案本身由 rich 渲染、会随终端宽度折行，
    # 所以这里只断言退出码；文案的关键片段用 service 层另行断言。
    assert result.exit_code == 2
    assert "map-git" in result.output


def test_member_map_git_expected_rev(svc, root):
    svc.call("member.add", {"handle": "bob"})
    with pytest.raises(RevisionConflict) as exc:
        svc.call("member.map_git_identity",
                 {"member": "bob", "git_names": ["bob"], "expected_rev": STALE_REV})
    assert exc.value.code == "REVISION_CONFLICT"
    assert svc.call("member.get", {"member": "bob"})["git"]["names"] == []


def test_member_map_git_without_any_identity_is_a_noop(svc):
    """不传任何身份 = 无事可做，不产生新版本、不产生事件。"""
    svc.call("member.add", {"handle": "dave"})
    before = svc.call("member.get", {"member": "dave"})
    after = svc.call("member.map_git_identity", {"member": "dave"})
    assert after["git"] == before["git"]
    assert after["version"] == before["version"]


def test_member_map_git_only_touches_git_fields(svc):
    svc.call("member.add", {"handle": "carol", "display_name": "Carol"})
    before = svc.call("member.get", {"member": "carol"})
    after = svc.call("member.map_git_identity",
                     {"member": "carol", "git_names": ["c"]})
    assert after["display_name"] == before["display_name"]
    assert after["handle"] == "carol"
    assert after["git"]["names"] == ["c"]


# ================================================================ 回归：既有行为不变


def test_link_status_still_works(svc):
    svc.call("link.add", {"name": "fw", "locator": "../firmware"})
    assert svc.call("link.status", {"name": "fw"})["kind"] == "local_project"


def test_project_group_help_page():
    assert invoke(["project", "--help"]).exit_code == 0
    assert invoke(["member", "map-git", "--help"]).exit_code == 0
