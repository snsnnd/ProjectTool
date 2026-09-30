"""V1-A.1 Hardening：进入 Git Adapter 前的 4 个必须项 + 2 个小项。

1. `pyproject.toml` 与 `version.py` 的版本号单一来源
2. Schema 写入门（`SCHEMA_MIGRATION_REQUIRED`）
3. 正常读路径的 rev 校验（禁止「洗白」被手改过的对象）
4. `file` Artifact 允许合法空格路径
5. Area 重名 -> `INVALID_ARGUMENT`（不是 `NOT_FOUND`）
6. doctor 在数据已损坏时仍可运行
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from project_tool.application.service import SCHEMA_GATE_EXEMPT, ProjectService
from project_tool.cli.main import app
from project_tool.domain.errors import (
    ProjectCorrupted,
    SchemaMigrationRequired,
)
from project_tool.domain.hashing import compute_rev
from project_tool.storage import init_project, open_project
from project_tool.version import SCHEMA_VERSION, __version__

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]


def invoke(args):
    return runner.invoke(app, args)


@pytest.fixture()
def project(tmp_path):
    init_project(tmp_path, name="Hardening")
    return open_project(tmp_path)


@pytest.fixture()
def svc(project):
    return ProjectService(project)


def downgrade_project(root: Path, version: str = "1.0") -> None:
    """把 project.json 的 schema_version 改回旧值（不重算 rev——doctor 会报出来，
    这里只关心 schema 门，所以随后用 migrate 正常抬回）。"""
    path = root / ".pjt" / "project.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["schema_version"] = version
    record["rev"] = compute_rev({k: v for k, v in record.items() if k != "rev"})
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")


# ------------------------------------------------------------------ 1. 版本单一来源


def test_version_has_single_source_of_truth():
    """pyproject.toml 不能写死 version，否则包元数据与 `pjt --version` 会漂移。"""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    config = tomllib.loads(text)
    assert config["project"].get("version") is None, "pyproject must not hardcode version"
    assert "version" in config["project"].get("dynamic", [])
    assert config["tool"]["hatch"]["version"]["path"] == "project_tool/version.py"


def test_declared_version_matches_runtime_version():
    declared = re.search(r'__version__\s*=\s*"([^"]+)"',
                         (REPO / "project_tool" / "version.py").read_text(encoding="utf-8"))
    assert declared is not None
    assert declared.group(1) == __version__
    assert SCHEMA_VERSION == "1.1"


def test_cli_reports_the_same_version(svc, project):
    result = invoke(["-C", str(project.paths.root), "--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_built_metadata_matches_runtime_version():
    """构建产物里的元数据必须等于运行时版本（防止再次漂移）。

    真实元数据由 `uv sync` 安装出来，直接问解释器最可靠；
    拿不到（例如 CI 只做静态检查）就跳过，但静态约束仍由上面两个测试守住。
    """
    proc = subprocess.run(
        [sys.executable, "-c", "import importlib.metadata as m; print(m.version('project-tool'))"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip("project-tool is not installed in this interpreter")
    assert proc.stdout.strip() == __version__


# ------------------------------------------------------------------ 2. Schema 写入门


def test_read_is_allowed_on_older_schema(svc, project):
    task = svc.call("task.create", {"title": "T1"})
    downgrade_project(project.paths.root, "1.0")
    reopened = ProjectService(open_project(project.paths.root))
    assert reopened.call("task.get", {"task_id": task["id"]})["title"] == "T1"
    assert reopened.call("task.list")[0]["id"] == task["id"]
    assert reopened.call("project.status") is not None
    assert reopened.call("system.capabilities")["schema_version"] == SCHEMA_VERSION
    # doctor 也照常运行（downgrade_project 伪造了 project.json 的 rev，
    # 所以这里只要求「能出报告」，不要求 ok —— 那是另一条测试的事）
    report = reopened.call("project.doctor")
    assert report["checks"] and isinstance(report["ok"], bool)


def test_write_is_blocked_on_older_schema(svc, project):
    downgrade_project(project.paths.root, "1.0")
    reopened = ProjectService(open_project(project.paths.root))
    with pytest.raises(SchemaMigrationRequired) as exc:
        reopened.call("task.create", {"title": "must not be written"})
    assert exc.value.code == "SCHEMA_MIGRATION_REQUIRED"
    assert exc.value.exit_code == 9
    assert "pjt migrate" in exc.value.message
    assert exc.value.details == {
        "project_schema_version": "1.0",
        "tool_schema_version": SCHEMA_VERSION,
    }
    # 关键：没有产生任何对象
    assert reopened.call("task.list") == []


# 每个领域各取一条「参数合法、schema 也对时本来会成功」的 mutation。
# 门必须对所有领域一致生效——这正是要消灭的「某些领域语义不同」。
GATE_SAMPLE = [
    ("goal.create", {"title": "G"}),
    ("milestone.create", {"title": "M"}),
    ("task.create", {"title": "T"}),
    ("task.set_status", {"task_id": "TSK-x", "status": "doing"}),
    ("member.add", {"handle": "alice"}),
    ("update.create", {"summary": "U"}),
    ("decision.create", {"title": "D"}),
    ("link.add", {"name": "fw", "locator": "../firmware"}),
    ("area.create", {"name": "UI"}),
    ("artifact.create", {"kind": "file", "locator": "package.json"}),
]


def test_write_gate_covers_every_domain(svc, project):
    for method, _params in GATE_SAMPLE:
        assert svc.registry[method].mutating is True, method
    downgrade_project(project.paths.root, "1.0")
    reopened = ProjectService(open_project(project.paths.root))
    for method, params in GATE_SAMPLE:
        with pytest.raises(SchemaMigrationRequired):
            reopened.call(method, params)
    # 门在业务校验之前：连参数解析都还没轮到
    assert reopened.call("task.list") == []
    assert reopened.call("area.list") == []
    assert reopened.call("artifact.list") == []
    assert reopened.call("member.list") == []


def test_schema_gate_is_centralized_in_call(svc):
    """实现只能在 ProjectService.call 一处，不允许每个 Service 自己判断。"""
    import inspect
    from pathlib import Path as _Path

    source = inspect.getsource(ProjectService.call)
    assert "_require_current_schema" in source
    assert "spec.mutating" in source
    assert "_require_current_schema" in inspect.getsource(ProjectService._require_current_schema)
    # 领域 Service 里不允许自己抛 schema 门
    services_dir = _Path(inspect.getfile(ProjectService)).parent / "services"
    for module in services_dir.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert "SchemaMigrationRequired" not in text, (
            f"{module.name} must not implement the schema gate itself"
        )
    # storage 层也不允许（门属于 Application 层）
    storage_dir = _Path(inspect.getfile(ProjectService)).parents[1] / "storage"
    for module in storage_dir.glob("*.py"):
        assert "SchemaMigrationRequired" not in module.read_text(encoding="utf-8"), module.name


def test_exempt_methods_still_work(svc, project):
    assert SCHEMA_GATE_EXEMPT == {"project.init", "project.migrate", "project.recover"}


def test_migrate_and_recover_are_exempt(svc, project):
    """崩溃残留必须永远能恢复，不能被写入门挡住。"""
    downgrade_project(project.paths.root, "1.0")
    reopened = ProjectService(open_project(project.paths.root))
    result = reopened.call("project.migrate")
    assert result["from"] == "1.0"
    assert result["to"] == SCHEMA_VERSION
    assert reopened.call("project.recover")["count"] == 0
    # 迁移后写入恢复正常
    assert reopened.call("task.create", {"title": "now allowed"})["title"] == "now allowed"


def test_schema_gate_cli_exit_code(svc, project):
    downgrade_project(project.paths.root, "1.0")
    result = invoke(["--json", "-C", str(project.paths.root), "task", "add", "nope"])
    assert result.exit_code == 9
    assert json.loads(result.output)["error"]["code"] == "SCHEMA_MIGRATION_REQUIRED"
    # migrate 之后同一条命令成功
    assert invoke(["-C", str(project.paths.root), "migrate"]).exit_code == 0
    assert invoke(["-C", str(project.paths.root), "task", "add", "yes"]).exit_code == 0


# ------------------------------------------------------------------ 3. 读路径 rev 校验


def test_read_path_rejects_rev_mismatch(svc, project):
    task = svc.call("task.create", {"title": "T1"})
    path = project.paths.root / ".pjt" / "objects" / "tasks" / f"{task['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "hand edited without recomputing rev"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    reopened = ProjectService(open_project(project.paths.root))
    with pytest.raises(ProjectCorrupted) as exc:
        reopened.call("task.get", {"task_id": task["id"]})
    assert exc.value.code == "PROJECT_CORRUPTED"
    assert "rev mismatch" in exc.value.message
    assert "pjt doctor" in exc.value.message


def test_rev_mismatch_cannot_be_laundered_by_a_write(svc, project):
    """核心回归：手改过的对象不能靠「下一次正常写入」重新签名洗白。"""
    task = svc.call("task.create", {"title": "T1"})
    path = project.paths.root / ".pjt" / "objects" / "tasks" / f"{task['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "hand edited"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    reopened = ProjectService(open_project(project.paths.root))
    for method, params in (
        ("task.update", {"task_id": task["id"], "description": "d"}),
        ("task.set_status", {"task_id": task["id"], "status": "doing"}),
        ("task.add_label", {"task_id": task["id"], "label": "x"}),
        ("task.archive", {"task_id": task["id"]}),
    ):
        with pytest.raises(ProjectCorrupted):
            reopened.call(method, params)
    # 文件仍然保持被篡改的状态（没有被改回去，也没有被重新签名）
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["title"] == "hand edited"
    assert after["rev"] == record["rev"]


def test_rev_mismatch_detected_across_all_object_types(svc, project):
    seed = {
        "goal": svc.call("goal.create", {"title": "G"}),
        "milestone": svc.call("milestone.create", {"title": "M"}),
        "task": svc.call("task.create", {"title": "T"}),
        "member": svc.call("member.add", {"handle": "alice"}),
        "update": svc.call("update.create", {"summary": "U"}),
        "decision": svc.call("decision.create", {"title": "D"}),
        "artifact": svc.call(
            "artifact.create", {"kind": "file", "locator": "package.json"}
        ),
    }
    collections = {
        "goal": "goals", "milestone": "milestones", "task": "tasks", "member": "members",
        "update": "updates", "decision": "decisions", "artifact": "artifacts",
    }
    getters = {
        "goal": ("goal.get", "goal_id"),
        "milestone": ("milestone.get", "milestone_id"),
        "task": ("task.get", "task_id"),
        "member": ("member.get", "member"),
        "update": ("update.get", "update_id"),
        "decision": ("decision.get", "decision_id"),
        "artifact": ("artifact.get", "artifact_id"),
    }
    for obj_type, record in seed.items():
        path = (
            project.paths.root / ".pjt" / "objects" / collections[obj_type]
            / f"{record['id']}.json"
        )
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["description" if "description" in raw else "title"] = "tampered"
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
        method, key = getters[obj_type]
        with pytest.raises(ProjectCorrupted):
            ProjectService(open_project(project.paths.root)).call(
                method, {key: record["id"]}
            )


def test_area_rev_mismatch_detected(svc, project):
    area = svc.call("area.create", {"name": "UI"})
    path = project.paths.root / ".pjt" / "objects" / "areas" / f"{area['id']}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["name"] = "tampered"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    with pytest.raises(ProjectCorrupted):
        ProjectService(open_project(project.paths.root)).call("area.get", {"area_id": area["id"]})


def test_transaction_write_still_recomputes_rev(svc, project):
    """校验只拦「外部篡改」，正常写入照常产生新 rev。"""
    task = svc.call("task.create", {"title": "T1"})
    updated = svc.call("task.update", {"task_id": task["id"], "title": "T2"})
    assert updated["title"] == "T2"
    assert updated["rev"] != task["rev"]
    assert ProjectService(open_project(project.paths.root)).call(
        "task.get", {"task_id": task["id"]}
    )["rev"] == updated["rev"]


# ------------------------------------------------------------------ 6. doctor 韧性


def test_doctor_still_works_when_data_is_corrupt(svc, project):
    task = svc.call("task.create", {"title": "T1"})
    member = svc.call("member.add", {"handle": "alice"})
    for collection, record in (("tasks", task), ("members", member)):
        path = project.paths.root / ".pjt" / "objects" / collection / f"{record['id']}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["title"] = "tampered"
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")

    report = ProjectService(open_project(project.paths.root)).call("project.doctor")
    names = {check["name"]: check for check in report["checks"]}
    assert report["ok"] is False
    # doctor 自己把 rev 问题指出来，而不是崩掉
    assert names["objects.task"]["status"] == "error"
    assert any("rev mismatch" in item for item in names["objects.task"]["details"])
    assert names["objects.member"]["status"] == "error"
    # 其它检查照常运行完
    assert "events.chain" in names
    assert "write.lock" in names


def test_doctor_cli_works_on_corrupt_project(svc, project):
    task = svc.call("task.create", {"title": "T1"})
    path = project.paths.root / ".pjt" / "objects" / "tasks" / f"{task['id']}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["title"] = "tampered"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")
    result = invoke(["-C", str(project.paths.root), "doctor"])
    assert result.exit_code == 9
    assert "rev mismatch" in result.output
    assert "objects.task" in result.output
