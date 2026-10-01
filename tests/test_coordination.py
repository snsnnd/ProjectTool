"""V1-C：分区协作 + 接口契约。

三块：

1. **`Area.owner_ids`** —— 显式 owner（不推导）。复数是刻意的：
   1 个 = 私有块，多个 = 公共接口区。这推翻了 V1-A「Area 不要 owner」的一半，
   但保留了「Area 不要时间维度」那一半（见 test_area.py）。
2. **role 词汇表** —— 只做**数据**，**不做本地门禁**。工具将来上服务器，
   权限以服务器为准；现在加本地门禁只会制造「已经管住了」的错觉。
3. **接口契约** —— 工作树里一份固定模板的 markdown + 注册成 Artifact。
   固定模板换来的可检查性由 `interface.check` 兑现。
"""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

from project_tool.application.service import ProjectService
from project_tool.cli.main import app
from project_tool.domain import interfaces as iface
from project_tool.domain.errors import InvalidArgument, RevisionConflict
from project_tool.storage import init_project, open_project

runner = CliRunner()


def invoke(args):
    return runner.invoke(app, args)


@pytest.fixture()
def root(tmp_path):
    init_project(tmp_path, name="Coord")
    return tmp_path


@pytest.fixture()
def svc(root):
    return ProjectService(open_project(root))


def _member(svc, handle: str) -> str:
    return svc.call("member.add", {"handle": handle})["id"]


# ================================================================== Area owner


def test_new_area_has_no_owners(svc):
    assert svc.call("area.create", {"name": "Core"})["owner_ids"] == []


def test_set_owner_accepts_handle_and_id(svc):
    alice = _member(svc, "alice")
    area = svc.call("area.create", {"name": "Core"})["id"]
    out = svc.call("area.set_owner", {"area_id": area, "add": ["alice"]})
    assert out["owner_ids"] == [alice]
    out = svc.call("area.set_owner", {"area_id": area, "add": [alice]})
    assert out["owner_ids"] == [alice]


def test_one_owner_is_a_private_block_and_two_make_a_shared_area(svc):
    """复数就是「公共」的表达——不需要额外的 shared 字段。"""
    _member(svc, "alice")
    _member(svc, "bob")
    area = svc.call("area.create", {"name": "Core"})["id"]
    svc.call("area.set_owner", {"area_id": area, "add": ["alice"]})
    assert len(svc.call("area.get", {"area_id": area})["owner_ids"]) == 1
    svc.call("area.set_owner", {"area_id": area, "add": ["bob"]})
    assert len(svc.call("area.get", {"area_id": area})["owner_ids"]) == 2


def test_set_owner_remove(svc):
    _member(svc, "alice")
    bob = _member(svc, "bob")
    area = svc.call("area.create", {"name": "Core"})["id"]
    svc.call("area.set_owner", {"area_id": area, "add": ["alice", "bob"]})
    out = svc.call("area.set_owner", {"area_id": area, "remove": ["alice"]})
    assert out["owner_ids"] == [bob]


def test_set_owner_is_idempotent_and_emits_no_event(svc):
    _member(svc, "alice")
    area = svc.call("area.create", {"name": "Core"})["id"]
    svc.call("area.set_owner", {"area_id": area, "add": ["alice"]})
    before = svc.call("area.history", {"area_id": area})["count"]
    out = svc.call("area.set_owner", {"area_id": area, "add": ["alice"]})
    assert svc.call("area.history", {"area_id": area})["count"] == before
    assert out["owner_ids"]


def test_set_owner_rejects_an_unknown_member(svc):
    area = svc.call("area.create", {"name": "Core"})["id"]
    with pytest.raises(Exception) as excinfo:
        svc.call("area.set_owner", {"area_id": area, "add": ["nobody"]})
    assert "not found" in str(excinfo.value)


def test_set_owner_respects_expected_rev(svc):
    _member(svc, "alice")
    area = svc.call("area.create", {"name": "Core"})["id"]
    with pytest.raises(RevisionConflict):
        svc.call(
            "area.set_owner",
            {"area_id": area, "add": ["alice"], "expected_rev": "sha256:" + "0" * 64},
        )


def test_owner_change_is_recorded_in_the_event_payload(svc):
    """没有本地门禁，所以「谁改了归属」必须留在事件里可审。"""
    _member(svc, "alice")
    area = svc.call("area.create", {"name": "Core"})["id"]
    svc.call("area.set_owner", {"area_id": area, "add": ["alice"]})
    events = svc.call("area.history", {"area_id": area})["events"]
    payload = events[-1]["payload"]
    assert payload["fields"] == ["owner_ids"]
    assert payload["from"] == []
    assert len(payload["to"]) == 1


def test_cli_set_owner_and_show(svc, root):
    invoke(["-C", str(root), "member", "add", "alice"])
    invoke(["-C", str(root), "member", "add", "bob"])
    area = invoke(["--json", "-C", str(root), "area", "add", "core"])
    area_id = json.loads(area.output)["result"]["id"]

    assert invoke(["-C", str(root), "area", "set-owner", area_id, "--add", "alice"]).exit_code == 0
    result = invoke(["--json", "-C", str(root), "area", "show", area_id])
    assert len(json.loads(result.output)["result"]["owner_ids"]) == 1

    assert invoke(["-C", str(root), "area", "set-owner", area_id, "--add", "bob"]).exit_code == 0
    shown = json.loads(invoke(["--json", "-C", str(root), "area", "show", area_id]).output)
    assert len(shown["result"]["owner_ids"]) == 2


def test_doctor_errors_on_a_dangling_area_owner(svc, root):
    from project_tool.application.doctor import run_doctor

    _member(svc, "alice")
    area_id = svc.call("area.create", {"name": "Core"})["id"]
    svc.call("area.set_owner", {"area_id": area_id, "add": ["alice"]})
    assert run_doctor(ProjectService(open_project(root)).ctx)["ok"] is True

    # 外部篡改：owner 指向不存在的 member = 数据损坏，不是「还没分配」
    path = root / ".pjt" / "objects" / "areas" / f"{area_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["owner_ids"] = ["MBR-NOPE"]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_doctor(ProjectService(open_project(root)).ctx)
    assert report["ok"] is False
    check = next(item for item in report["checks"] if item["name"] == "area.owners")
    assert check["status"] == "error"


def test_doctor_warns_but_does_not_fail_on_a_non_standard_role(svc, root):
    from project_tool.application.doctor import run_doctor

    svc.call("member.add", {"handle": "alice", "roles": ["wizard"]})
    report = run_doctor(ProjectService(open_project(root)).ctx)
    assert report["ok"] is True, "老项目可能有自由 role，不能因此判 corrupted"
    check = next(item for item in report["checks"] if item["name"] == "member.roles")
    assert check["status"] == "warning"
    assert "wizard" in check["message"]


def test_known_roles_are_advisory_not_a_whitelist(svc):
    """自由字符串仍然接受——门禁留给服务器。"""
    member = svc.call("member.add", {"handle": "alice", "roles": ["whatever"]})
    assert member["roles"] == ["whatever"]


# ================================================================== 模板 / 校验


def test_template_round_trips_through_front_matter():
    text = iface.render_template(
        "store.updateModel", kind="store_api", area="core", owners=["jichao"], consumers=["ui"]
    )
    data, body, error = iface.parse_front_matter(text)
    assert error is None
    assert data["name"] == "store.updateModel"
    assert data["area"] == "core"
    assert data["owners"] == ["jichao"]
    assert data["consumers"] == ["ui"]
    assert "## 用途" in body


def test_a_freshly_rendered_template_passes_its_own_check():
    text = iface.render_template("x.y", area="core")
    assert [f for f in iface.check_document(text) if f.level == "error"] == []


def test_consumers_are_not_required_while_drafting():
    """第一版把 consumers 设成必填，结果不带 --consumer 根本建不出来——
    而「还没想清楚谁在用」正是 draft 阶段的常态。"""
    draft = iface.render_template("x.y", area="core")
    data, _, _ = iface.parse_front_matter(draft)
    assert "consumers" not in data
    assert [f for f in iface.check_document(draft) if f.level == "error"] == []


def test_consumers_become_required_at_review_time():
    text = iface.render_template("x.y", area="core").replace("status: draft", "status: review")
    messages = [f.message for f in iface.check_document(text)]
    assert any("consumers is required" in item for item in messages)


def test_unknown_status_is_an_error():
    text = iface.render_template("x.y", area="core").replace("status: draft", "status: pending")
    messages = [f.message for f in iface.check_document(text)]
    assert any("unknown status 'pending'" in item for item in messages)


def test_missing_required_field_is_an_error():
    text = iface.render_template("x.y", area="core")
    stripped = "\n".join(
        line for line in text.splitlines() if not line.startswith("area:")
    )
    messages = [f.message for f in iface.check_document(stripped)]
    assert any("missing required field: area" in item for item in messages)


def test_missing_required_section_is_an_error():
    text = iface.render_template("x.y", area="core")
    truncated = text.split("## 兼容策略")[0]
    messages = [f.message for f in iface.check_document(truncated)]
    assert any("missing required section" in item for item in messages)


def test_empty_section_is_a_warning_not_an_error():
    text = iface.render_template("x.y", area="core").replace(
        "## 用途\n\n", "## 用途\n\n## 契约\n"
    )
    levels = {f.level for f in iface.check_document(text)}
    assert "warning" in levels


def test_document_without_front_matter_is_rejected():
    findings = iface.check_document("# just a heading\n")
    assert findings[0].level == "error"
    assert "front-matter" in findings[0].message


def test_parsing_does_not_need_a_yaml_dependency():
    """依赖越少，20 个人在各自机器上装出来的行为越一致。"""
    import sys

    assert "yaml" not in sys.modules


# ================================================================== interface 服务


def test_interface_init_creates_a_file_and_registers_an_artifact(svc, root):
    svc.call("area.create", {"name": "core"})
    record = svc.call(
        "interface.init",
        {"name": "store.updateModel", "area": "core", "summary": "入口"},
    )
    assert record["metadata"]["interface"] is True
    assert record["related_area_ids"]
    path = root / record["locator"]
    assert path.is_file()
    assert "store.updateModel" in path.read_text(encoding="utf-8")


def test_interface_front_matter_stores_the_area_name_not_the_id(svc, root):
    """这份文档是给人看的沟通材料，`ARA-01M3T…` 对读者没有信息量。"""
    svc.call("area.create", {"name": "core"})
    record = svc.call("interface.init", {"name": "a.b", "area": "core"})
    text = (root / record["locator"]).read_text(encoding="utf-8")
    data, _, _ = iface.parse_front_matter(text)
    assert data["area"] == "core"
    assert not data["area"].startswith("ARA-")


def test_interface_init_refuses_to_overwrite_without_force(svc, root):
    """接口文档是多方沟通的产物，被一次 init 静默清空是最坏的结果。"""
    svc.call("area.create", {"name": "core"})
    first = svc.call("interface.init", {"name": "a.b", "area": "core"})
    path = root / first["locator"]
    path.write_text(path.read_text(encoding="utf-8") + "\n# 我的笔记\n", encoding="utf-8")

    with pytest.raises(InvalidArgument) as excinfo:
        svc.call("interface.init", {"name": "a.b", "area": "core"})
    assert "already exists" in str(excinfo.value)
    assert "我的笔记" in path.read_text(encoding="utf-8")

    assert svc.call("interface.init", {"name": "a.b", "area": "core", "force": True})


def test_interface_init_cannot_escape_the_project_root(svc, root):
    svc.call("area.create", {"name": "core"})
    with pytest.raises(InvalidArgument):
        svc.call(
            "interface.init",
            {"name": "a.b", "area": "core", "path": "../outside.md"},
        )


def test_interface_list_reports_an_unreadable_document(svc, root):
    """文件被删/被改坏不是「不存在」，必须如实报出来。"""
    svc.call("area.create", {"name": "core"})
    record = svc.call("interface.init", {"name": "a.b", "area": "core"})
    (root / record["locator"]).unlink()
    rows = svc.call("interface.list", {})
    assert rows[0]["document"] is None
    assert "not found" in rows[0]["read_error"]


def test_interface_check_flags_a_missing_file(svc, root):
    svc.call("area.create", {"name": "core"})
    record = svc.call("interface.init", {"name": "a.b", "area": "core"})
    (root / record["locator"]).unlink()
    result = svc.call("interface.check", {})
    assert result["ok"] is False
    assert "cannot read document" in result["interfaces"][0]["findings"][0]["message"]


def test_interface_check_does_not_rewrite_the_document(svc, root):
    """工具替人改契约比不检查更糟。"""
    svc.call("area.create", {"name": "core"})
    record = svc.call("interface.init", {"name": "a.b", "area": "core"})
    path = root / record["locator"]
    path.write_text(
        path.read_text(encoding="utf-8").replace("status: draft", "status: nonsense"),
        encoding="utf-8",
    )
    before = path.read_text(encoding="utf-8")
    svc.call("interface.check", {})
    assert path.read_text(encoding="utf-8") == before


def test_interface_sync_aligns_the_area_binding(svc, root):
    svc.call("area.create", {"name": "core"})
    svc.call("area.create", {"name": "ui"})
    record = svc.call("interface.init", {"name": "a.b", "area": "core"})
    path = root / record["locator"]
    text = path.read_text(encoding="utf-8").replace("area: core", "area: ui")
    path.write_text(text, encoding="utf-8")

    synced = svc.call("interface.sync", {"artifact": record["id"]})
    ui_id = next(row["id"] for row in svc.call("area.list", {}) if row["name"] == "ui")
    assert synced["related_area_ids"] == [ui_id]


def test_interface_init_does_not_add_a_new_artifact_on_reinit(svc, root):
    svc.call("area.create", {"name": "core"})
    first = svc.call("interface.init", {"name": "a.b", "area": "core"})
    second = svc.call("interface.init", {"name": "a.b", "area": "core", "force": True})
    assert first["id"] == second["id"]


def test_artifact_can_be_attached_to_an_area(svc):
    svc.call("area.create", {"name": "core"})
    artifact = svc.call("artifact.create", {"kind": "file", "locator": "docs/x.md"})
    assert artifact["related_area_ids"] == []
    out = svc.call("artifact.attach", {"artifact_id": artifact["id"], "area": "core"})
    assert len(out["related_area_ids"]) == 1


# ================================================================== CLI


def test_cli_interface_flow(svc, root):
    invoke(["-C", str(root), "area", "add", "core"])
    invoke(["-C", str(root), "member", "add", "jichao"])

    created = invoke(
        [
            "--json", "-C", str(root), "interface", "init",
            "store.updateModel",
            "--area", "core",
            "--kind", "store_api",
            "--owner", "jichao",
            "--consumer", "ui",
            "--summary", "入口",
        ]
    )
    assert created.exit_code == 0, created.output

    listed = invoke(["--json", "-C", str(root), "interface", "list"])
    assert listed.exit_code == 0, listed.output
    rows = json.loads(listed.output)["result"]
    assert [row["name"] for row in rows] == ["store.updateModel"]
    assert rows[0]["area_names"] == ["core"]
    # related_area_ids 必须存 id，不能是名字——引用字段一律是 id
    assert rows[0]["area_ids"][0].startswith("ARA-")

    shown = invoke(["--json", "-C", str(root), "interface", "show", "store.updateModel"])
    assert "## 兼容策略" in json.loads(shown.output)["result"]["text"]

    checked = invoke(["--json", "-C", str(root), "interface", "check"])
    assert checked.exit_code == 0
    assert json.loads(checked.output)["result"]["ok"] is True


def test_cli_check_exits_nonzero_so_it_can_gate_ci(svc, root):
    invoke(["-C", str(root), "area", "add", "core"])
    invoke(["-C", str(root), "interface", "init", "a.b", "--area", "core"])
    assert invoke(["-C", str(root), "interface", "check"]).exit_code == 0

    path = root / "docs" / "interfaces" / "a.b.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("status: draft", "status: review"),
        encoding="utf-8",
    )
    result = invoke(["-C", str(root), "interface", "check"])
    assert result.exit_code == 1
    assert "consumers is required" in result.output


def test_interface_show_accepts_the_name_that_list_displays(svc, root):
    """界面展示的是名字，命令就必须认名字——否则是在教用户用一个不接受的东西。"""
    svc.call("area.create", {"name": "core"})
    record = svc.call("interface.init", {"name": "store.updateModel", "area": "core"})
    by_name = svc.call("interface.show", {"name": "store.updateModel"})
    by_id = svc.call("interface.show", {"artifact": record["id"]})
    assert by_name["id"] == by_id["id"] == record["id"]


def test_interface_stores_the_area_id_not_the_name(svc, root):
    svc.call("area.create", {"name": "core"})
    record = svc.call("interface.init", {"name": "a.b", "area": "core"})
    assert record["related_area_ids"][0].startswith("ARA-")


def test_cli_interface_show_prints_the_document_verbatim(svc, root):
    invoke(["-C", str(root), "area", "add", "core"])
    invoke(["-C", str(root), "interface", "init", "a.b", "--area", "core"])
    result = invoke(["-C", str(root), "interface", "show", "a.b"])
    assert result.exit_code == 0, result.output
    # 文档里没有方括号，但这条钉住「原文照打」的意图：不能被 rich 吃掉
    assert "## 变更规则" in result.output


def test_git_status_still_ignores_pjt(svc, root):
    """接口文件在工作树里，pjt 不能因此开始跟踪 .pjt 的东西。"""
    invoke(["-C", str(root), "area", "add", "core"])
    invoke(["-C", str(root), "interface", "init", "a.b", "--area", "core"])
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", ".pjt"], capture_output=True, text=True
    )
    assert ".pjt/state/state.json" not in tracked.stdout


# ================================================================== register / 词汇表


def test_interface_register_accepts_a_handwritten_doc(svc, root):
    """手写文档必须能登记——`init` 只能新建，现实中很多是手写或迁过来的。

    之前没有这条路，只能手改 artifact 的 JSON，而那会被 rev 校验判成
    `PROJECT_CORRUPTED`（§13 读即校验正好挡住了这个后门）。
    """
    svc.call("area.create", {"name": "core"})
    path = root / "docs" / "legacy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        iface.render_template("legacy.api", area="core", consumers=["ui"]), encoding="utf-8"
    )
    record = svc.call("interface.register", {"path": "docs/legacy.md"})
    assert record["metadata"]["interface"] is True
    assert record["related_area_ids"][0].startswith("ARA-")
    rows = svc.call("interface.list", {})
    assert [row["name"] for row in rows] == ["legacy.api"]


def test_interface_register_rejects_a_file_without_front_matter(svc, root):
    """没有 front-matter 的只是普通笔记，不是接口。"""
    path = root / "docs" / "notes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 就一些笔记\n", encoding="utf-8")
    with pytest.raises(InvalidArgument) as excinfo:
        svc.call("interface.register", {"path": "docs/notes.md"})
    assert "not an interface document" in str(excinfo.value)


def test_interface_register_rejects_a_missing_file(svc, root):
    from project_tool.domain.errors import NotFound

    with pytest.raises(NotFound):
        svc.call("interface.register", {"path": "docs/nope.md"})


def test_interface_register_does_not_block_on_incomplete_docs(svc, root):
    """登记的用途就是把「还不完整」的已有文档纳入管理，硬拦会让迁移做不成。"""
    svc.call("area.create", {"name": "core"})
    path = root / "docs" / "wip.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nname: wip.api\nstatus: draft\narea: core\n---\n\n# wip\n",
        encoding="utf-8",
    )
    record = svc.call("interface.register", {"path": "docs/wip.md"})
    assert record["check"]["ok"] is False  # 登记成功，但体检结果如实带回来
    assert record["check"]["errors"] >= 1


def test_kind_is_free_form_not_a_closed_vocabulary(svc, root):
    """kind 由**项目**定义，工具不校验。

    第一版的 CLI help 把它写成了 `module_api | store_api | ...`，看起来像
    封闭集合，还把 `module_api` 设成默认——那是把工具的猜测焊进了数据。
    """
    svc.call("area.create", {"name": "core"})
    record = svc.call(
        "interface.init",
        {"name": "debug.serial.frame", "area": "core", "kind": "serial_frame"},
    )
    assert record["metadata"]["interface_kind"] == "serial_frame"
    # 再来一个工具"没见过"的 kind，照样接受
    record = svc.call(
        "interface.init",
        {"name": "odd.thing", "area": "core", "kind": "totally_made_up"},
    )
    assert record["metadata"]["interface_kind"] == "totally_made_up"


def test_kind_is_not_required_to_come_from_the_tool(svc, root):
    svc.call("area.create", {"name": "core"})
    record = svc.call("interface.init", {"name": "a.b", "area": "core"})
    assert "interface_kind" not in (record["metadata"] or {})


def test_a_realistic_handwritten_document_passes_without_false_positives(svc, root):
    """真人的接口文档有代码块、表格、**不保证**条款——check 不该误报。"""
    svc.call("area.create", {"name": "core"})
    path = root / "docs" / "store.updateModel.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "name: store.updateModel\n"
        "kind: store_api\n"
        "status: agreed\n"
        "area: core\n"
        "owners: [jichao]\n"
        "consumers: [ui, dataflow]\n"
        "version: 3\n"
        "---\n\n"
        "# store.updateModel\n\n"
        "## 用途\n\nstore 批量更新模型。\n\n"
        "## 契约\n\n"
        "```ts\nupdateModel(patch: ModelPatch): void\n```\n\n"
        "- **不保证**：不在调用线程同步派发\n\n"
        "## 变更规则\n\n1. 变更历史加一行\n2. 建 task\n\n"
        "## 兼容策略\n\n删字段算破坏性变更。\n\n"
        "## 变更历史\n\n"
        "| 日期 | 改动 | 人 |\n|---|---|---|\n| 2026-09-20 | 初稿 | 计超 |\n",
        encoding="utf-8",
    )
    svc.call("interface.register", {"path": "docs/store.updateModel.md"})
    result = svc.call("interface.check", {})
    assert result["errors"] == 0, result
    assert result["warnings"] == 0, result


def test_cli_external_id_round_trip(root):
    """KC 映射 KC user id 的 CLI 入口（之前只有 Python API 能写）。"""
    invoke(
        [
            "-C", str(root), "member", "add", "jichao", "--name", "计超",
            "--external-id", "kc_user=u_12345",
            "--external-id", "email=jichao@corp.com",
        ]
    )
    listed = json.loads(invoke(["--json", "-C", str(root), "member", "list"]).output)["result"]
    ids = listed[0]["external_ids"]
    assert ids == {"kc_user": "u_12345", "email": "jichao@corp.com"}


def test_cli_external_id_replaces_on_edit(root):
    invoke(["-C", str(root), "member", "add", "jichao", "--external-id", "kc_user=old"])
    assert invoke(
        ["-C", str(root), "member", "edit", "jichao", "--external-id", "kc_user=new"]
    ).exit_code == 0
    listed = json.loads(invoke(["--json", "-C", str(root), "member", "list"]).output)["result"]
    assert listed[0]["external_ids"] == {"kc_user": "new"}


def test_cli_external_id_rejects_a_value_without_an_equals(root):
    invoke(["-C", str(root), "member", "add", "jichao"])
    bad = invoke(["--json", "-C", str(root), "member", "edit", "jichao", "--external-id", "nope"])
    assert bad.exit_code != 0
    # 必须走正常错误通道：`--json` 模式下是合法错误包，而不是裸 traceback
    envelope = json.loads(bad.output)
    assert envelope["error"]["code"] == "INVALID_ARGUMENT"
    assert "key=value" in envelope["error"]["message"]


def test_key_values_keeps_equals_signs_inside_the_value():
    from project_tool.cli.common import key_values

    assert key_values(["url=https://x/y?a=b"]) == {"url": "https://x/y?a=b"}
    assert key_values([]) == {}
    assert key_values(["a=1", "a=2"]) == {"a": "2"}
    with pytest.raises(InvalidArgument):
        key_values(["nokey"])
    with pytest.raises(InvalidArgument):
        key_values(["=value"])


# ================================================================== task.related_interfaces


def test_related_interfaces_finds_explicitly_linked(svc, root):
    svc.call("area.create", {"name": "core"})
    artifact = svc.call(
        "interface.init", {"name": "store.updateModel", "area": "core", "consumers": ["ui"]}
    )
    task_id = svc.call("task.create", {"title": "改点东西", "area_id": None})["id"]
    svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task_id})

    result = svc.call("task.related_interfaces", {"task_id": task_id})
    assert result["count"] == 1
    entry = result["interfaces"][0]
    assert entry["reason"] == "linked"
    assert entry["name"] == "store.updateModel"
    assert entry["consumers"] == ["ui"]


def test_related_interfaces_finds_the_same_area(svc, root):
    area = svc.call("area.create", {"name": "core"})
    svc.call(
        "interface.init",
        {"name": "store.updateModel", "area": "core", "consumers": ["ui"]},
    )
    task_id = svc.call("task.create", {"title": "无关标题", "area_id": area["id"]})["id"]
    result = svc.call("task.related_interfaces", {"task_id": task_id})
    assert [e["reason"] for e in result["interfaces"]] == ["same_area"]


def test_related_interfaces_area_scope_can_be_disabled(svc, root):
    area = svc.call("area.create", {"name": "core"})
    svc.call("interface.init", {"name": "store.updateModel", "area": "core"})
    task_id = svc.call("task.create", {"title": "无关", "area_id": area["id"]})["id"]
    assert svc.call("task.related_interfaces", {"task_id": task_id, "area_scope": False})["count"] == 0


def test_related_interfaces_finds_mentions_in_the_title(svc, root):
    svc.call("area.create", {"name": "core"})
    svc.call("interface.init", {"name": "store.updateModel", "area": "core"})
    task_id = svc.call("task.create", {"title": "调整 store.updateModel 的签名"})["id"]
    result = svc.call("task.related_interfaces", {"task_id": task_id})
    assert [e["reason"] for e in result["interfaces"]] == ["mentioned"]


def test_related_interfaces_orders_linked_before_same_area(svc, root):
    """可信度递减：显式关联 > 同 Area > 正文提及。"""
    area = svc.call("area.create", {"name": "core"})
    linked = svc.call("interface.init", {"name": "store.updateModel", "area": "core"})
    svc.call("interface.init", {"name": "core.internal", "area": "core"})
    task_id = svc.call("task.create", {"title": "同时提到 core.internal", "area_id": area["id"]})["id"]
    svc.call("artifact.attach", {"artifact_id": linked["id"], "task": task_id})
    result = svc.call("task.related_interfaces", {"task_id": task_id})
    reasons = [e["reason"] for e in result["interfaces"]]
    assert reasons[0] == "linked"
    assert reasons.index("linked") < reasons.index("same_area")


def test_related_interfaces_area_id_is_an_id_not_a_name(svc, root):
    """回归：front-matter 的 `area` 是**名字**，拿它和 task.area_id 比会永远不匹配。"""
    area = svc.call("area.create", {"name": "core"})
    svc.call("interface.init", {"name": "store.updateModel", "area": "core"})
    task_id = svc.call("task.create", {"title": "无关", "area_id": area["id"]})["id"]
    row = svc.call("task.related_interfaces", {"task_id": task_id})["interfaces"][0]
    assert row["area_id"] == area["id"]
    assert row["area"] == "core"


def test_related_interfaces_reports_an_unreadable_document(svc, root):
    area = svc.call("area.create", {"name": "core"})
    artifact = svc.call("interface.init", {"name": "gone.api", "area": "core"})
    (root / artifact["locator"]).unlink()
    task_id = svc.call("task.create", {"title": "无关", "area_id": area["id"]})["id"]
    row = svc.call("task.related_interfaces", {"task_id": task_id})["interfaces"][0]
    assert row["readable"] is False
    assert "not found" in row["read_error"]


def test_cli_related_interfaces(root, svc):
    invoke(["-C", str(root), "area", "add", "core"])
    invoke(
        ["-C", str(root), "interface", "init", "store.updateModel",
         "--area", "core", "--consumer", "ui"]
    )
    task = json.loads(
        invoke(["--json", "-C", str(root), "task", "add", "无关", "--area", "core"]).output
    )["result"]["id"]
    result = invoke(["--json", "-C", str(root), "task", "related-interfaces", task])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["count"] == 1
    assert payload["interfaces"][0]["name"] == "store.updateModel"
