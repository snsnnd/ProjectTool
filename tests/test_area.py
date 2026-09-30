"""Area（V1-A 任务 3）：稳定分区维度。

覆盖：create / update / archive / restore、Task 归属与过滤、层级环、
doctor、事件、迁移兼容、以及「Area 不是 Milestone / 不是 Label」的边界。
"""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from project_tool.application.service import ProjectService
from project_tool.cli.main import app
from project_tool.domain.enums import Lifecycle
from project_tool.domain.errors import (
    HierarchyCycle,
    InvalidArgument,
    NotFound,
    RevisionConflict,
)
from project_tool.domain.ids import COLLECTION_BY_TYPE, PREFIX_BY_TYPE
from project_tool.storage import init_project, open_project
from project_tool.version import SCHEMA_VERSION

runner = CliRunner()
STALE_REV = "sha256:" + "0" * 64


def invoke(args):
    return runner.invoke(app, args)


@pytest.fixture()
def svc(tmp_path):
    init_project(tmp_path, name="Areas")
    return ProjectService(open_project(tmp_path))


@pytest.fixture()
def areas(svc):
    return {
        name: svc.call("area.create", {"name": name})
        for name in ("Core", "UI", "Debug", "Distribution")
    }


# --------------------------------------------------------------------- 身份与形状


def test_area_id_and_collection_are_registered():
    assert PREFIX_BY_TYPE["area"] == "ARA"
    assert COLLECTION_BY_TYPE["area"] == "areas"


def test_area_object_has_no_status_progress_due_or_owner(svc):
    area = svc.call("area.create", {"name": "Core"})
    for forbidden in ("status", "progress", "due_at", "owner", "owner_ids", "weight"):
        assert forbidden not in area
    assert area["lifecycle"] == Lifecycle.ACTIVE.value
    assert area["parent_area_id"] is None
    assert area["rev"].startswith("sha256:")


def test_area_reference_resolution(svc, areas):
    assert svc.call("area.get", {"area_id": "Debug"})["name"] == "Debug"
    assert svc.call("area.get", {"area_id": "debug"})["name"] == "Debug"
    full = areas["UI"]["id"]
    assert svc.call("area.get", {"area_id": full})["id"] == full
    all_ids = [row["id"] for row in svc.call("area.list")]
    unique = next(
        n
        for n in range(5, len(full) + 1)
        if sum(1 for other in all_ids if other.startswith(full[:n])) == 1
    )
    assert svc.call("area.get", {"area_id": full[:unique]})["id"] == full
    with pytest.raises(InvalidArgument):
        svc.call("area.get", {"area_id": ""})
    with pytest.raises(NotFound):
        svc.call("area.get", {"area_id": "NoSuchArea"})


def test_area_short_id_ambiguity_rejected(svc, areas):
    """同毫秒创建的 Area 共享时间戳前缀：共享前缀必须报歧义，不能猜。"""
    shared = os.path.commonprefix([row["id"] for row in svc.call("area.list")])
    assert len(shared) >= 5
    with pytest.raises(InvalidArgument) as exc:
        svc.call("area.get", {"area_id": shared})
    assert "ambiguous" in str(exc.value)


def test_area_duplicate_names_are_not_merged(svc, areas):
    second = svc.call("area.create", {"name": "Debug"})
    assert second["id"] != areas["Debug"]["id"]
    # 名称不唯一 -> INVALID_ARGUMENT（不是 NOT_FOUND）：文档与行为必须一致，
    # 并且必须列出候选 ID 让用户能消歧。
    with pytest.raises(InvalidArgument) as exc:
        svc.call("area.get", {"area_id": "Debug"})
    message = str(exc.value)
    assert "ambiguous area name" in message
    assert areas["Debug"]["id"] in message
    assert second["id"] in message
    # 用 ID / 短 ID 仍然精确可读
    assert svc.call("area.get", {"area_id": second["id"]})["id"] == second["id"]


def test_area_unknown_name_is_not_found(svc, areas):
    with pytest.raises(NotFound) as exc:
        svc.call("area.get", {"area_id": "NoSuchArea"})
    assert "no area with that name" in str(exc.value)


# --------------------------------------------------------------------- 生命周期


def test_area_create_update_archive_restore(svc, areas):
    updated = svc.call("area.update", {"area_id": "UI", "description": "editor surfaces"})
    assert updated["description"] == "editor surfaces"
    assert updated["version"] == 2

    assert svc.call("area.archive", {"area_id": "UI"})["lifecycle"] == Lifecycle.ARCHIVED.value
    assert [row["name"] for row in svc.call("area.list")] == ["Core", "Debug", "Distribution"]
    assert "UI" in [row["name"] for row in svc.call("area.list", {"include_archived": True})]
    assert svc.call("area.restore", {"area_id": "UI"})["lifecycle"] == Lifecycle.ACTIVE.value


def test_area_update_without_fields_is_a_noop(svc, areas):
    before = svc.call("area.get", {"area_id": "UI"})
    assert svc.call("area.update", {"area_id": "UI"}) == before


def test_area_create_rejects_expected_rev(svc):
    with pytest.raises(InvalidArgument):
        svc.call("area.create", {"name": "Nope", "expected_rev": STALE_REV})


def test_area_expected_rev_contract(svc, areas):
    with pytest.raises(RevisionConflict):
        svc.call("area.update", {"area_id": "UI", "description": "x", "expected_rev": STALE_REV})
    rev = svc.call("area.get", {"area_id": "UI"})["rev"]
    assert (
        svc.call(
            "area.update", {"area_id": "UI", "description": "y", "expected_rev": rev}
        )["description"]
        == "y"
    )
    assert svc.call("area.update", {"area_id": "UI", "description": "z"})["description"] == "z"


# --------------------------------------------------------------------- Task 归属


def test_task_create_with_area_by_name(svc, areas):
    task = svc.call("task.create", {"title": "store.updateModel", "area_id": "UI"})
    assert task["area_id"] == areas["UI"]["id"]


def test_task_list_filter_by_area(svc, areas):
    a = svc.call("task.create", {"title": "editor", "area_id": "UI"})
    b = svc.call("task.create", {"title": "loopback", "area_id": "Debug"})
    c = svc.call("task.create", {"title": "unassigned"})
    assert [t["id"] for t in svc.call("task.list", {"area": "UI"})] == [a["id"]]
    assert [t["id"] for t in svc.call("task.list", {"area": "debug"})] == [b["id"]]
    assert c["area_id"] is None
    assert len(svc.call("task.list", {"area": "Core"})) == 0


def test_task_move_area_attach_and_detach(svc, areas):
    task = svc.call("task.create", {"title": "T"})
    moved = svc.call("task.move_area", {"task_id": task["id"], "area_id": "Debug"})
    assert moved["area_id"] == areas["Debug"]["id"]
    detached = svc.call("task.move_area", {"task_id": task["id"]})
    assert detached["area_id"] is None
    # no-op：同区域不产生事件
    before = len(svc.call("area.history", {"area_id": "Debug"})["events"])
    svc.call("task.move_area", {"task_id": task["id"], "area_id": "Debug"})
    assert len(svc.call("area.history", {"area_id": "Debug"})["events"]) == before


def test_task_update_area_field(svc, areas):
    task = svc.call("task.create", {"title": "T"})
    updated = svc.call("task.update", {"task_id": task["id"], "area_id": "Distribution"})
    assert updated["area_id"] == areas["Distribution"]["id"]


def test_task_area_unknown_reference(svc):
    with pytest.raises(NotFound):
        svc.call("task.create", {"title": "T", "area_id": "Nowhere"})


# --------------------------------------------------------------------- 层级


def test_area_hierarchy(svc, areas):
    editor = svc.call("area.create", {"name": "Editor", "parent_area_id": "UI"})
    nested = svc.call("area.create", {"name": "Debug UI", "parent_area_id": editor["id"]})
    assert svc.call("area.get", {"area_id": "UI"})["task_count"] == 0
    assert svc.call("area.list", {"parent": "UI"})[0]["id"] == editor["id"]
    assert nested["parent_area_id"] == editor["id"]
    assert svc.call("area.set_parent", {"area_id": "Debug UI", "parent_area_id": None})[
        "parent_area_id"
    ] is None


def test_area_self_parent_rejected(svc, areas):
    with pytest.raises(InvalidArgument):
        svc.call("area.update", {"area_id": "UI", "parent_area_id": "UI"})
    with pytest.raises(InvalidArgument):
        svc.call("area.set_parent", {"area_id": "UI", "parent_area_id": areas["UI"]["id"]})


def test_area_parent_cycle_rejected(svc, areas):
    editor = svc.call("area.create", {"name": "Editor", "parent_area_id": "UI"})
    nested = svc.call("area.create", {"name": "Debug UI", "parent_area_id": editor["id"]})
    with pytest.raises(HierarchyCycle):
        svc.call("area.set_parent", {"area_id": "UI", "parent_area_id": nested["id"]})
    assert svc.call("area.get", {"area_id": "UI"})["parent_area_id"] is None
    assert svc.call("area.get", {"area_id": editor["id"]})["parent_area_id"] == areas["UI"]["id"]


# --------------------------------------------------------------------- 事件


def test_area_events(svc, areas):
    svc.call("area.update", {"area_id": "UI", "description": "d"})
    svc.call("area.archive", {"area_id": "UI"})
    types = [event["event_type"] for event in svc.call("area.history", {"area_id": "UI"})["events"]]
    assert types == ["area.created", "area.updated", "object.archived"]
    assert svc.call("area.history", {"area_id": "UI"})["count"] == 3


def test_area_created_event_payload(svc):
    svc.call("area.create", {"name": "Core"})
    events = svc.call("log.list", {"entity_type": "area"})["events"]
    assert events[0]["event_type"] == "area.created"
    assert events[0]["payload"] == {"name": "Core"}
    raw = json.loads(
        next(
            (tmp_path_event for tmp_path_event in
             sorted((svc.opened.paths.events).rglob("EVT-*.json"))),
            None,
        ).read_text(encoding="utf-8")
    )
    assert raw["base_rev"] is None
    assert raw["new_rev"].startswith("sha256:")


def test_task_area_change_event(svc, areas):
    task = svc.call("task.create", {"title": "T"})
    svc.call("task.move_area", {"task_id": task["id"], "area_id": "Debug"})
    events = svc.call("task.history", {"task_id": task["id"]})["events"]
    assert events[-1]["event_type"] == "task.updated"
    assert events[-1]["payload"] == {
        "fields": ["area_id"],
        "from": None,
        "to": areas["Debug"]["id"],
    }


# --------------------------------------------------------------------- 图 / status


def test_graph_project_has_separate_areas_section(svc, areas):
    goal = svc.call("goal.create", {"title": "G"})
    svc.call("milestone.create", {"title": "M", "goal_ids": [goal["id"]]})
    svc.call("task.create", {"title": "T", "area_id": "UI"})
    tree = svc.call("graph.project")
    assert {row["name"] for row in tree["areas"]} == set(areas)
    by_name = {row["name"]: row for row in tree["areas"]}
    assert by_name["UI"]["task_count"] == 1
    assert by_name["Core"]["task_count"] == 0
    assert "progress" not in by_name["UI"]
    # Area 不被塞进 Goal -> Milestone 层级
    for goal_row in tree["goals"]:
        assert "area_ids" not in goal_row
    for milestone in tree["milestones"]:
        assert "area_ids" not in milestone


def test_status_does_not_list_areas(svc, areas):
    svc.call("task.create", {"title": "T", "area_id": "UI"})
    status = svc.call("project.status")
    assert "areas" not in status
    # 也不会因为引入 Area 而改变 computed blocked 语义
    assert status["blocked"] == []


# --------------------------------------------------------------------- Doctor


def test_doctor_covers_areas(tmp_path):
    init_project(tmp_path, name="Areas")
    svc = ProjectService(open_project(tmp_path))
    svc.call("area.create", {"name": "UI"})
    report = svc.call("project.doctor")
    names = {check["name"]: check for check in report["checks"]}
    assert names["objects.area"]["status"] == "ok"
    assert "1 area object(s)" in names["objects.area"]["message"]
    assert names["references"]["status"] == "ok"
    assert names["hierarchy"]["status"] == "ok"
    assert report["summary"]["errors"] == 0


def test_doctor_reports_broken_area_reference(tmp_path):
    init_project(tmp_path, name="Areas")
    svc = ProjectService(open_project(tmp_path))
    area = svc.call("area.create", {"name": "UI"})
    task = svc.call("task.create", {"title": "T", "area_id": area["id"]})
    task_path = tmp_path / ".pjt" / "objects" / "tasks" / f"{task['id']}.json"
    record = json.loads(task_path.read_text(encoding="utf-8"))
    record["area_id"] = "ARA-01K8H2MBQXZ0ZZZZZZZZZZZZZ"
    task_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    # 同时让 rev 自洽，doctor 报的是「引用缺失」而不是「rev 不匹配」
    from project_tool.domain.hashing import compute_rev

    record["rev"] = compute_rev({k: v for k, v in record.items() if k != "rev"})
    task_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    report = ProjectService(open_project(tmp_path)).call("project.doctor")
    names = {check["name"]: check for check in report["checks"]}
    assert names["references"]["status"] == "error"
    assert any("missing area" in item for item in names["references"]["details"])


def test_doctor_reports_area_hierarchy_cycle(tmp_path):
    init_project(tmp_path, name="Areas")
    svc = ProjectService(open_project(tmp_path))
    a = svc.call("area.create", {"name": "A"})
    b = svc.call("area.create", {"name": "B", "parent_area_id": a["id"]})
    # 手改形成 A -> B -> A（绕过 service 的环检测）
    from project_tool.domain.hashing import compute_rev

    path = tmp_path / ".pjt" / "objects" / "areas" / f"{a['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["parent_area_id"] = b["id"]
    record["rev"] = compute_rev({k: v for k, v in record.items() if k != "rev"})
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    report = ProjectService(open_project(tmp_path)).call("project.doctor")
    names = {check["name"]: check for check in report["checks"]}
    assert names["hierarchy"]["status"] == "error"
    assert any("area parent cycle" in item for item in names["hierarchy"]["details"])


# --------------------------------------------------------------------- 迁移兼容


def test_v01_project_without_areas_dir_still_opens(tmp_path):
    """模拟 V0.1 项目：删掉 areas/ 目录后必须照常打开，doctor 只 warning。"""
    init_project(tmp_path, name="Legacy")
    svc = ProjectService(open_project(tmp_path))
    svc.call("task.create", {"title": "legacy task"})
    import shutil

    shutil.rmtree(tmp_path / ".pjt" / "objects" / "areas")

    reopened = ProjectService(open_project(tmp_path))
    assert reopened.call("area.list") == []
    assert reopened.call("task.list")[0]["title"] == "legacy task"
    assert reopened.call("task.list")[0]["area_id"] is None

    report = reopened.call("project.doctor")
    assert report["ok"] is True
    names = {check["name"]: check for check in report["checks"]}
    assert names["objects.layout"]["status"] == "warning"
    assert "areas" in names["objects.layout"]["message"]

    result = reopened.call("project.migrate")
    assert "areas" in result["applied"]
    assert (tmp_path / ".pjt" / "objects" / "areas").is_dir()
    after = reopened.call("project.doctor")
    assert {c["name"]: c for c in after["checks"]}["objects.layout"]["status"] == "ok"
    # migrate 之后再写 Area 正常工作
    assert reopened.call("area.create", {"name": "UI"})["name"] == "UI"


def test_legacy_task_without_area_id_reads_as_null(tmp_path):
    """旧 Task JSON 没有 area_id 字段，必须读成 null 而不是校验失败。"""
    init_project(tmp_path, name="Legacy")
    svc = ProjectService(open_project(tmp_path))
    task = svc.call("task.create", {"title": "old"})
    path = tmp_path / ".pjt" / "objects" / "tasks" / f"{task['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("area_id")
    from project_tool.domain.hashing import compute_rev

    record["rev"] = compute_rev({k: v for k, v in record.items() if k != "rev"})
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    reopened = ProjectService(open_project(tmp_path))
    assert reopened.call("task.get", {"task_id": task["id"]})["area_id"] is None


def test_migrate_bumps_project_schema_version(tmp_path):
    init_project(tmp_path, name="Legacy")
    path = tmp_path / ".pjt" / "project.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["schema_version"] = "1.0"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    svc = ProjectService(open_project(tmp_path))
    assert svc.call("project.open")["schema_version"] == "1.0"
    result = svc.call("project.migrate")
    assert result["from"] == "1.0"
    assert result["to"] == SCHEMA_VERSION == "1.1"
    assert result["needs_project_bump"] is True
    assert result["project_schema_version"] == "1.1"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == "1.1"

    events = [e for e in svc.call("log.list", {"entity_type": "project"})["events"]]
    assert events[0]["event_type"] == "project.migrated"
    assert events[0]["payload"]["from"] == "1.0"

    # 幂等
    again = svc.call("project.migrate")
    assert again["needs_project_bump"] is False
    assert again["applied"] == []
    assert again["message"] == "already up to date"
    assert ProjectService(open_project(tmp_path)).call("project.doctor")["ok"] is True


# --------------------------------------------------------------------- CLI


def test_cli_area_flow(tmp_path):
    init_project(tmp_path, name="Areas")
    assert invoke(["-C", str(tmp_path), "area", "add", "UI", "-d", "editor"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "area", "add", "Editor", "--parent", "UI"]).exit_code == 0
    result = invoke(["--json", "-C", str(tmp_path), "area", "add", "Debug"])
    debug = json.loads(result.output)["result"]
    assert debug["name"] == "Debug"

    result = invoke(["--json", "-C", str(tmp_path), "task", "add", "T1", "--area", "Debug"])
    task = json.loads(result.output)["result"]
    assert task["area_id"] == debug["id"]

    result = invoke(["--json", "-C", str(tmp_path), "task", "list", "--area", "Debug"])
    assert [row["id"] for row in json.loads(result.output)["result"]] == [task["id"]]

    result = invoke(["--json", "-C", str(tmp_path), "task", "move-area", task["id"], "UI"])
    assert json.loads(result.output)["result"]["area_id"] != debug["id"]

    assert invoke(["-C", str(tmp_path), "area", "list"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "area", "show", "Debug"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "area", "tree"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "area", "edit", "UI", "--name", "UI2"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "area", "archive", "Debug"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "area", "restore", "Debug"]).exit_code == 0
    result = invoke(["--json", "-C", str(tmp_path), "graph", "project"])
    assert {row["name"] for row in json.loads(result.output)["result"]["areas"]} == {
        "UI2",
        "Editor",
        "Debug",
    }
    result = invoke(["-C", str(tmp_path), "doctor"])
    assert result.exit_code == 0, result.output


def test_cli_area_edit_expected_rev_conflict(tmp_path):
    init_project(tmp_path, name="Areas")
    invoke(["-C", str(tmp_path), "area", "add", "UI"])
    result = invoke(
        ["--json", "-C", str(tmp_path), "area", "edit", "UI", "--name", "X",
         "--expected-rev", STALE_REV]
    )
    assert result.exit_code == 5
    assert json.loads(result.output)["error"]["code"] == "REVISION_CONFLICT"


def test_cli_area_help_page():
    result = invoke(["area", "--help"])
    assert result.exit_code == 0
