"""Artifact（V1-A 任务 4）：工程产物的引用。

覆盖：add / update / remove / attach / detach / task.related_artifacts /
decision & milestone 关系 / verify（存在、缺失、路径穿越、绝对路径、URL 格式）/
revision 冲突 / 事件 / doctor，以及「绝不修改被引用文件」这条硬约束。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from project_tool.application.service import ProjectService
from project_tool.cli.main import app
from project_tool.domain.enums import Lifecycle
from project_tool.domain.errors import InvalidArgument, NotFound, RevisionConflict
from project_tool.domain.hashing import compute_rev
from project_tool.storage import init_project, open_project

runner = CliRunner()
STALE_REV = "sha256:" + "0" * 64


def invoke(args):
    return runner.invoke(app, args)


@pytest.fixture()
def root(tmp_path):
    init_project(tmp_path, name="Artifacts")
    (tmp_path / "studio_core").mkdir()
    (tmp_path / "studio_core" / "debug.py").write_text("def probe():\n    pass\n", "utf-8")
    (tmp_path / "package.json").write_text('{"name": "efw"}\n', "utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "04-debug-and-api.md").write_text("# debug\n", "utf-8")
    return tmp_path


@pytest.fixture()
def svc(root):
    return ProjectService(open_project(root))


def raw_events(svc, entity_id) -> list[dict]:
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((svc.opened.paths.events).rglob("EVT-*.json"))
    ]
    return [record for record in records if record.get("entity_id") == entity_id]


def tree_hash(root: Path) -> dict[str, str]:
    """整个工程树的 sha256（跳过 .pjt / .venv / node_modules），用于证明零写入。"""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] in {".pjt", ".venv", "node_modules", ".git"}:
            continue
        result[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


# --------------------------------------------------------------------- 身份


def test_artifact_prefix_and_collection():
    from project_tool.domain.ids import COLLECTION_BY_TYPE, PREFIX_BY_TYPE

    assert PREFIX_BY_TYPE["artifact"] == "ART"
    assert COLLECTION_BY_TYPE["artifact"] == "artifacts"


def test_artifact_object_shape(svc):
    artifact = svc.call(
        "artifact.create",
        {"kind": "file", "locator": "studio_core/debug.py", "name": "debug transport"},
    )
    assert artifact["id"].startswith("ART-")
    assert artifact["type"] == "artifact"
    assert artifact["kind"] == "file"
    assert artifact["locator"] == "studio_core/debug.py"
    assert artifact["lifecycle"] == Lifecycle.ACTIVE.value
    assert artifact["rev"].startswith("sha256:")
    assert artifact["related_task_ids"] == []
    assert artifact["metadata"] == {}


def test_artifact_name_defaults_to_locator(svc):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    assert artifact["name"] == "package.json"


# --------------------------------------------------------------------- locator 规则


@pytest.mark.parametrize(
    "locator",
    [
        "/etc/passwd",
        "/mnt/d/framework/new/efw/studio_core/debug.py",
        "C:\\Users\\me\\secret.txt",
        "c:/Users/me/secret.txt",
        "\\\\server\\share\\file.txt",
        "~/notes.md",
        "../../secret.txt",
        "studio_core/../../secret.txt",
        "./studio_core/debug.py",
        "studio_core//debug.py",
        ".pjt/project.json",
        ".PJT/objects/tasks/x.json",
        ".pjt",
        "",
        "   ",
        "docs/a\nb.md",
        "docs/a\tb.md",
    ],
)
def test_file_locator_rejections(svc, locator):
    with pytest.raises(InvalidArgument):
        svc.call("artifact.create", {"kind": "file", "locator": locator})


def test_file_locator_allows_ordinary_spaces(svc):
    """真实工程里含空格的文件名非常常见，工具不该规定禁止。"""
    for locator in (
        "docs/Design Notes.md",
        "assets/Test Result 01.csv",
        "hardware/Board Rev A.pdf",
        "with space.txt",
    ):
        record = svc.call("artifact.create", {"kind": "file", "locator": locator})
        assert record["locator"] == locator
        # 前后空白仍然被 strip
    assert svc.call(
        "artifact.create", {"kind": "file", "locator": "  docs/Padded.md  "}
    )["locator"] == "docs/Padded.md"


def test_file_locator_normalizes_backslashes(svc):
    artifact = svc.call(
        "artifact.create", {"kind": "file", "locator": r"studio_core\debug.py"}
    )
    assert artifact["locator"] == "studio_core/debug.py"


def test_file_locator_allows_dotted_filenames(svc):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "docs/04-debug.md"})
    assert artifact["locator"] == "docs/04-debug.md"


def test_absolute_path_rejected_for_non_file_kinds(svc):
    for kind in ("document", "report", "other", "hardware"):
        with pytest.raises(InvalidArgument):
            svc.call("artifact.create", {"kind": kind, "locator": "/etc/hosts"})
        with pytest.raises(InvalidArgument):
            svc.call("artifact.create", {"kind": kind, "locator": "C:\\data\\board.json"})


@pytest.mark.parametrize(
    "locator",
    [
        "https://example.com/docs",
        "http://127.0.0.1:8080/x",
    ],
)
def test_url_locator_accepted(svc, locator):
    artifact = svc.call("artifact.create", {"kind": "url", "locator": locator})
    assert artifact["locator"] == locator


@pytest.mark.parametrize("locator", ["not-a-url", "ftp://example.com", "https://", "://x"])
def test_url_locator_rejections(svc, locator):
    with pytest.raises(InvalidArgument):
        svc.call("artifact.create", {"kind": "url", "locator": locator})


def test_git_locator_forms(svc):
    assert svc.call(
        "artifact.create", {"kind": "git_commit", "locator": "abc123"}
    )["locator"] == "abc123"
    assert svc.call(
        "artifact.create", {"kind": "git_branch", "locator": "feature/foo"}
    )["locator"] == "feature/foo"
    for bad in ("zzzz", "not-hex-at-all", "123"):
        with pytest.raises(InvalidArgument):
            svc.call("artifact.create", {"kind": "git_commit", "locator": bad})
    for bad in ("feature/../main", "/leading", "trailing/", "has space"):
        with pytest.raises(InvalidArgument):
            svc.call("artifact.create", {"kind": "git_branch", "locator": bad})


def test_unknown_kind_rejected(svc):
    with pytest.raises(InvalidArgument):
        svc.call("artifact.create", {"kind": "screenshot_of_my_prompt", "locator": "x"})


# --------------------------------------------------------------------- 关系


def test_artifact_attach_to_task(svc):
    task = svc.call("task.create", {"title": "loopback"})
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "studio_core/debug.py"})
    attached = svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task["id"]})
    assert attached["related_task_ids"] == [task["id"]]
    # 幂等
    again = svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task["id"]})
    assert again["rev"] == attached["rev"]
    detached = svc.call("artifact.detach", {"artifact_id": artifact["id"], "task": task["id"]})
    assert detached["related_task_ids"] == []


def test_task_related_artifacts(svc):
    task = svc.call("task.create", {"title": "loopback"})
    other = svc.call("task.create", {"title": "packaging"})
    a = svc.call(
        "artifact.create",
        {"kind": "file", "locator": "studio_core/debug.py", "task": task["id"]},
    )
    svc.call(
        "artifact.create", {"kind": "file", "locator": "package.json", "task": other["id"]}
    )
    assert [r["id"] for r in svc.call("task.related_artifacts", {"task_id": task["id"]})] == [a["id"]]
    assert svc.call("task.related_artifacts", {"task_id": other["id"]})[0]["locator"] == "package.json"
    # 反向引用是派生读：Task 本身不存 artifact_ids
    assert "artifacts" not in svc.call("task.get", {"task_id": task["id"]})


def test_artifact_attach_to_decision_and_milestone(svc):
    goal = svc.call("goal.create", {"title": "G"})
    milestone = svc.call("milestone.create", {"title": "M", "goal_ids": [goal["id"]]})
    decision = svc.call("decision.create", {"title": "CLI and GUI share one service"})
    artifact = svc.call(
        "artifact.create",
        {
            "kind": "file",
            "locator": "studio_core/debug.py",
            "name": "Service and CLI share the same core",
        },
    )
    updated = svc.call(
        "artifact.attach",
        {
            "artifact_id": artifact["id"],
            "decision": decision["id"],
            "milestone": milestone["id"],
        },
    )
    assert updated["related_decision_ids"] == [decision["id"]]
    assert updated["related_milestone_ids"] == [milestone["id"]]
    assert svc.call("artifact.list", {"decision": decision["id"]})[0]["id"] == artifact["id"]
    assert svc.call("artifact.list", {"milestone": milestone["id"]})[0]["id"] == artifact["id"]


def test_artifact_attach_to_goal(svc):
    goal = svc.call("goal.create", {"title": "G"})
    artifact = svc.call("artifact.create", {"kind": "url", "locator": "https://example.com/x"})
    updated = svc.call("artifact.attach", {"artifact_id": artifact["id"], "goal": goal["id"]})
    assert updated["related_goal_ids"] == [goal["id"]]


def test_artifact_attach_requires_a_target(svc):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    with pytest.raises(InvalidArgument):
        svc.call("artifact.attach", {"artifact_id": artifact["id"]})


def test_artifact_attach_rejects_deleted_target(svc):
    task = svc.call("task.create", {"title": "gone"})
    svc.call("task.delete", {"task_id": task["id"]})
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    with pytest.raises(InvalidArgument):
        svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task["id"]})


# --------------------------------------------------------------------- update / remove


def test_artifact_update(svc):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    updated = svc.call(
        "artifact.update",
        {"artifact_id": artifact["id"], "name": "manifest", "description": "electron"},
    )
    assert updated["name"] == "manifest"
    assert updated["description"] == "electron"
    assert updated["version"] == 2
    with pytest.raises(InvalidArgument):
        svc.call("artifact.update", {"artifact_id": artifact["id"], "locator": "/etc/passwd"})


def test_artifact_update_revalidates_locator_on_kind_change(svc):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    with pytest.raises(InvalidArgument):
        svc.call("artifact.update", {"artifact_id": artifact["id"], "kind": "url"})
    assert svc.call("artifact.get", {"artifact_id": artifact["id"]})["kind"] == "file"
    ok = svc.call(
        "artifact.update",
        {"artifact_id": artifact["id"], "kind": "url", "locator": "https://example.com/pkg"},
    )
    assert (ok["kind"], ok["locator"]) == ("url", "https://example.com/pkg")


def test_artifact_metadata(svc):
    artifact = svc.call(
        "artifact.create",
        {"kind": "build", "locator": "dist/efw-0.1.zip", "metadata": {"size_mb": 12}},
    )
    assert artifact["metadata"] == {"size_mb": 12}
    with pytest.raises(InvalidArgument):
        svc.call("artifact.update", {"artifact_id": artifact["id"], "metadata": ["nope"]})


def test_artifact_remove_is_soft(svc):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    removed = svc.call("artifact.remove", {"artifact_id": artifact["id"]})
    assert removed["lifecycle"] == Lifecycle.DELETED.value
    assert svc.call("artifact.list") == []
    assert len(svc.call("artifact.list", {"include_deleted": True})) == 1
    # 与其它对象一致：get 仍可读到软删除对象，只是 lifecycle=deleted
    assert svc.call("artifact.get", {"artifact_id": artifact["id"]})["lifecycle"] == "deleted"
    # 相关查询也不再返回它
    task = svc.call("task.create", {"title": "T"})
    svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task["id"]})
    assert svc.call("task.related_artifacts", {"task_id": task["id"]}) == []
    assert len(
        svc.call(
            "task.related_artifacts", {"task_id": task["id"], "include_deleted": True}
        )
    ) == 1


# --------------------------------------------------------------------- 绝不改真实文件


def test_artifact_operations_never_touch_the_referenced_file(svc, root):
    before = tree_hash(root)
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "studio_core/debug.py"})
    task = svc.call("task.create", {"title": "T"})
    svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task["id"]})
    svc.call("artifact.verify", {})
    svc.call("artifact.update", {"artifact_id": artifact["id"], "name": "renamed reference"})
    svc.call("artifact.remove", {"artifact_id": artifact["id"]})
    assert tree_hash(root) == before
    assert (root / "studio_core" / "debug.py").is_file()


def test_artifact_remove_keeps_file_and_removes_object_file(svc, root):
    path = root / "studio_core" / "debug.py"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "studio_core/debug.py"})
    object_file = root / ".pjt" / "objects" / "artifacts" / f"{artifact['id']}.json"
    assert object_file.is_file()
    svc.call("artifact.remove", {"artifact_id": artifact["id"]})
    assert path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert json.loads(object_file.read_text(encoding="utf-8"))["lifecycle"] == "deleted"


# --------------------------------------------------------------------- verify


def test_verify_existing_file_passes(svc):
    svc.call("artifact.create", {"kind": "file", "locator": "studio_core/debug.py"})
    result = svc.call("artifact.verify", {})
    assert result[0]["status"] == "ok"
    assert result[0]["exists"] is True
    assert result[0]["path"] == "studio_core/debug.py"


def test_verify_missing_file_is_not_corruption(svc, root):
    svc.call("artifact.create", {"kind": "file", "locator": "studio_core/never.py"})
    result = svc.call("artifact.verify", {})
    assert result[0]["status"] == "missing"
    assert result[0]["exists"] is False
    report = svc.call("project.doctor")
    assert report["ok"] is True
    check = {c["name"]: c for c in report["checks"]}["artifacts.locators"]
    assert check["status"] == "warning"
    assert "not found" in check["message"]


def test_verify_url_only_checks_format(svc):
    svc.call("artifact.create", {"kind": "url", "locator": "https://example.invalid/nope"})
    result = svc.call("artifact.verify", {})
    assert result[0]["status"] == "ok"
    assert "no network request" in result[0]["detail"]


def test_verify_invalid_url_rejected_at_write_time(svc):
    with pytest.raises(InvalidArgument):
        svc.call("artifact.create", {"kind": "url", "locator": "example.com"})


def test_verify_git_kinds_report_adapter_off(svc):
    svc.call("artifact.create", {"kind": "git_commit", "locator": "abc1234"})
    svc.call("artifact.create", {"kind": "git_branch", "locator": "feature/x"})
    results = svc.call("artifact.verify", {})
    assert all(row["status"] == "ok" for row in results)
    assert all("git adapter not enabled" in row["detail"] for row in results)


def test_verify_opaque_kind_is_skipped(svc):
    svc.call("artifact.create", {"kind": "design", "locator": "brd rev C"})
    result = svc.call("artifact.verify", {})
    assert result[0]["status"] == "skipped"
    assert "opaque references" in result[0]["detail"]


def test_whitespace_rejected_for_url_and_git_kinds(svc):
    for kind, locator in (
        ("url", "https://example.com/a b"),
        ("git_branch", "feature/foo bar"),
        ("git_commit", "abc 123"),
    ):
        with pytest.raises(InvalidArgument):
            svc.call("artifact.create", {"kind": kind, "locator": locator})


def test_verify_single_artifact_and_short_id(svc):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    short = artifact["id"][:12]
    assert len(svc.call("artifact.verify", {"artifact_id": short})) == 1
    with pytest.raises(NotFound):
        svc.call("artifact.verify", {"artifact_id": "ART-01K8H2MBQXZ0ZZZZZZZZZZZZZ"})


def test_verify_produces_no_events(svc):
    svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    before = len(svc.call("log.list", {"limit": 500})["events"])
    svc.call("artifact.verify", {})
    svc.call("artifact.verify", {})
    assert len(svc.call("log.list", {"limit": 500})["events"]) == before


# --------------------------------------------------------------------- revision


def test_artifact_expected_rev_contract(svc):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    task = svc.call("task.create", {"title": "T"})
    for method, params in (
        ("artifact.update", {"name": "x"}),
        ("artifact.attach", {"task": task["id"]}),
        ("artifact.detach", {"task": task["id"]}),
        ("artifact.remove", {}),
    ):
        with pytest.raises(RevisionConflict):
            svc.call(
                method, {"artifact_id": artifact["id"], **params, "expected_rev": STALE_REV}
            )
    rev = svc.call("artifact.get", {"artifact_id": artifact["id"]})["rev"]
    assert svc.call(
        "artifact.update", {"artifact_id": artifact["id"], "name": "x", "expected_rev": rev}
    )["name"] == "x"
    assert svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task["id"]})[
        "related_task_ids"
    ] == [task["id"]]


# --------------------------------------------------------------------- 事件


def test_artifact_event_contract(svc):
    task = svc.call("task.create", {"title": "T"})
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task["id"]})
    svc.call("artifact.detach", {"artifact_id": artifact["id"], "task": task["id"]})
    svc.call("artifact.update", {"artifact_id": artifact["id"], "name": "manifest"})
    svc.call("artifact.remove", {"artifact_id": artifact["id"]})
    events = svc.call("artifact.history", {"artifact_id": artifact["id"]})["events"]
    assert [e["event_type"] for e in events] == [
        "artifact.created",
        "artifact.attached",
        "artifact.detached",
        "artifact.updated",
        "artifact.removed",
    ]
    assert events[0]["payload"] == {
        "name": "package.json",
        "kind": "file",
        "locator": "package.json",
    }
    assert events[1]["payload"] == {
        "relations": [{"relation": "task", "id": task["id"], "attached": True}]
    }
    assert events[4]["payload"] == {"lifecycle": "deleted"}
    # 事件链严格串起来（读原始事件文件，event_summary 不含 rev）
    raw = raw_events(svc, artifact["id"])
    assert raw[0]["base_rev"] is None
    for previous, current in zip(raw, raw[1:], strict=False):
        assert previous["new_rev"] == current["base_rev"]
    assert raw[-1]["new_rev"] == svc.call("artifact.get", {"artifact_id": artifact["id"]})["rev"]


def test_artifact_created_event_has_null_base_rev(svc, root):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    raw = raw_events(svc, artifact["id"])[0]
    assert raw["entity_type"] == "artifact"
    assert raw["entity_id"] == artifact["id"]
    assert raw["base_rev"] is None
    assert raw["new_rev"] == artifact["rev"]


# --------------------------------------------------------------------- Doctor


def test_doctor_covers_artifacts(svc):
    svc.call("artifact.create", {"kind": "file", "locator": "studio_core/debug.py"})
    report = svc.call("project.doctor")
    names = {c["name"]: c for c in report["checks"]}
    assert names["objects.artifact"]["status"] == "ok"
    assert "1 artifact object(s)" in names["objects.artifact"]["message"]
    assert names["artifacts.locators"]["status"] == "ok"
    assert report["summary"]["errors"] == 0


def test_doctor_flags_broken_artifact_relation_as_error(svc, root):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    path = root / ".pjt" / "objects" / "artifacts" / f"{artifact['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["related_task_ids"] = ["TSK-01K8H2MBQXZ0ZZZZZZZZZZZZZ"]
    record["rev"] = compute_rev({k: v for k, v in record.items() if k != "rev"})
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    report = ProjectService(open_project(root)).call("project.doctor")
    names = {c["name"]: c for c in report["checks"]}
    assert names["references"]["status"] == "error"
    assert any("missing task" in item for item in names["references"]["details"])


def test_doctor_flags_unsafe_artifact_locator_as_error(svc, root):
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "package.json"})
    path = root / ".pjt" / "objects" / "artifacts" / f"{artifact['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["locator"] = "../../etc/passwd"
    record["rev"] = compute_rev({k: v for k, v in record.items() if k != "rev"})
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    report = ProjectService(open_project(root)).call("project.doctor")
    names = {c["name"]: c for c in report["checks"]}
    assert names["artifacts.locators"]["status"] == "error"
    assert any(
        artifact["id"] in item and "must be a clean relative path" in item
        for item in names["artifacts.locators"]["details"]
    )


# --------------------------------------------------------------------- 兼容 / CLI


def test_v01_project_without_artifacts_dir_still_opens(root):
    import shutil

    service = ProjectService(open_project(root))
    service.call("task.create", {"title": "legacy"})
    shutil.rmtree(root / ".pjt" / "objects" / "artifacts")

    reopened = ProjectService(open_project(root))
    assert reopened.call("artifact.list") == []
    assert reopened.call("project.doctor")["ok"] is True
    result = reopened.call("project.migrate")
    assert "artifacts" in result["applied"]


def test_cli_artifact_flow(root):
    assert invoke(["--json", "-C", str(root), "artifact", "add", "file",
                   "studio_core/debug.py"]).exit_code == 0
    result = invoke(["--json", "-C", str(root), "artifact", "add", "file", "package.json",
                     "--name", "electron manifest", "--meta", "channel=stable"])
    assert result.exit_code == 0, result.output
    artifact = json.loads(result.output)["result"]
    assert artifact["metadata"] == {"channel": "stable"}

    result = invoke(["--json", "-C", str(root), "task", "add", "T1"])
    task = json.loads(result.output)["result"]
    result = invoke(["--json", "-C", str(root), "artifact", "attach", artifact["id"],
                     "--task", task["id"]])
    assert json.loads(result.output)["result"]["related_task_ids"] == [task["id"]]

    result = invoke(["--json", "-C", str(root), "task", "artifacts", task["id"]])
    assert [r["id"] for r in json.loads(result.output)["result"]] == [artifact["id"]]

    assert invoke(["-C", str(root), "artifact", "list"]).exit_code == 0
    assert invoke(["-C", str(root), "artifact", "show", artifact["id"]]).exit_code == 0
    assert invoke(["-C", str(root), "artifact", "verify"]).exit_code == 0
    assert invoke(["-C", str(root), "artifact", "verify", artifact["id"]]).exit_code == 0
    assert invoke(["-C", str(root), "artifact", "edit", artifact["id"], "--name", "m2"]).exit_code == 0
    assert invoke(["-C", str(root), "artifact", "detach", artifact["id"],
                   "--task", task["id"]]).exit_code == 0
    assert invoke(["-C", str(root), "artifact", "remove", artifact["id"]]).exit_code == 0
    assert invoke(["-C", str(root), "artifact", "history", artifact["id"]]).exit_code == 0
    assert invoke(["-C", str(root), "doctor"]).exit_code == 0


def test_cli_artifact_rejects_path_traversal(root):
    result = invoke(["--json", "-C", str(root), "artifact", "add", "file", "../../secret.txt"])
    assert result.exit_code == 3
    assert json.loads(result.output)["error"]["code"] == "INVALID_ARGUMENT"
    result = invoke(["--json", "-C", str(root), "artifact", "add", "file", "/etc/passwd"])
    assert result.exit_code == 3
    result = invoke(["--json", "-C", str(root), "artifact", "add", "file", ".pjt/project.json"])
    assert result.exit_code == 3


def test_cli_artifact_edit_expected_rev_conflict(root):
    result = invoke(["--json", "-C", str(root), "artifact", "add", "file", "package.json"])
    artifact = json.loads(result.output)["result"]
    result = invoke(["--json", "-C", str(root), "artifact", "edit", artifact["id"],
                     "--name", "x", "--expected-rev", STALE_REV])
    assert result.exit_code == 5, result.output
    assert json.loads(result.output)["error"]["code"] == "REVISION_CONFLICT"


def test_cli_artifact_help_page():
    assert invoke(["artifact", "--help"]).exit_code == 0
