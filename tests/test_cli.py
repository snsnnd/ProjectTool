from __future__ import annotations

import json

from typer.testing import CliRunner

from project_tool.cli.main import app

runner = CliRunner()


def invoke(args):
    return runner.invoke(app, args)


def test_cli_full_flow(tmp_path):
    assert invoke(["-C", str(tmp_path), "init", "--name", "Demo"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "member", "add", "alice", "--name", "Alice"]).exit_code == 0

    result = invoke(["--json", "-C", str(tmp_path), "task", "add", "T1", "--owner", "alice"])
    assert result.exit_code == 0, result.output
    task_id = json.loads(result.output)["result"]["id"]

    result = invoke(["--json", "-C", str(tmp_path), "task", "list"])
    rows = json.loads(result.output)["result"]
    assert rows[0]["id"] == task_id
    assert rows[0]["owner_ids"]

    assert invoke(["-C", str(tmp_path), "task", "done", task_id]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "status"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "doctor"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "log", "--since", "1d"]).exit_code == 0
    assert invoke(["-C", str(tmp_path), "graph", "tasks"]).exit_code == 0


def test_cli_json_error_shape(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])
    result = invoke(["--json", "-C", str(tmp_path), "task", "show", "TSK-01K8H2MBQX"])
    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "NOT_FOUND"


def test_cli_dependency_cycle_exit_code(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])

    def add(title):
        result = invoke(["--json", "-C", str(tmp_path), "task", "add", title])
        return json.loads(result.output)["result"]["id"]

    a = add("A")
    b = add("B")
    assert invoke(["-C", str(tmp_path), "task", "depend", a, b]).exit_code == 0
    result = invoke(["--json", "-C", str(tmp_path), "task", "depend", b, a])
    assert result.exit_code == 3
    assert json.loads(result.output)["error"]["code"] == "DEPENDENCY_CYCLE"


def test_cli_porcelain_list(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])
    invoke(["-C", str(tmp_path), "task", "add", "T1"])
    result = invoke(["--porcelain", "-C", str(tmp_path), "task", "list"])
    assert result.exit_code == 0
    line = result.output.strip().splitlines()[0]
    fields = line.split("\t")
    assert len(fields) == 6
    assert fields[1] == "inbox"


def test_cli_doctor_fails_on_tamper(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])
    result = invoke(["--json", "-C", str(tmp_path), "task", "add", "T1"])
    task_id = json.loads(result.output)["result"]["id"]
    path = tmp_path / ".pjt" / "objects" / "tasks" / f"{task_id}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "tampered"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    assert invoke(["-C", str(tmp_path), "doctor"]).exit_code == 9


def test_cli_doctor_repair_cleans_staging(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])
    staging = tmp_path / ".pjt" / "transactions" / "TXN-CLI-TEST" / "staged" / "objects" / "tasks"
    staging.mkdir(parents=True)
    (staging / "TSK-FAKE.json").write_text('{"id": "TSK-FAKE"}', encoding="utf-8")

    result = invoke(["-C", str(tmp_path), "doctor", "--repair"])
    assert result.exit_code == 0, result.output
    assert list((tmp_path / ".pjt" / "transactions").iterdir()) == []


def test_cli_all_help_pages_build(tmp_path):
    groups = [
        None, "task", "area", "artifact", "goal", "milestone",
        "member", "update", "decision", "link", "log", "graph",
    ]
    for group in groups:
        args = [group, "--help"] if group else ["--help"]
        result = invoke(args)
        assert result.exit_code == 0, f"{args}: {result.output}"


def test_cli_decision_add_with_title_option(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])
    result = invoke(
        [
            "--json",
            "-C",
            str(tmp_path),
            "decision",
            "add",
            "--title",
            "Use local-first",
            "--decision",
            "keep .pjt",
        ]
    )
    assert result.exit_code == 0, result.output
    decision = json.loads(result.output)["result"]
    assert decision["title"] == "Use local-first"
    result = invoke(["-C", str(tmp_path), "decision", "add", "Positional title"])
    assert result.exit_code == 0, result.output


def test_cli_task_edit_with_expected_rev(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])
    result = invoke(["--json", "-C", str(tmp_path), "task", "add", "T1"])
    task = json.loads(result.output)["result"]
    rev = task["rev"]

    stale = "sha256:" + "0" * 64
    result = invoke(
        ["--json", "-C", str(tmp_path), "task", "edit", task["id"], "--title", "T1b",
         "--expected-rev", stale]
    )
    assert result.exit_code == 5
    assert json.loads(result.output)["error"]["code"] == "REVISION_CONFLICT"

    result = invoke(
        ["--json", "-C", str(tmp_path), "task", "edit", task["id"], "--title", "T1b",
         "--weight", "3", "--label", "x", "--expected-rev", rev]
    )
    assert result.exit_code == 0, result.output
    updated = json.loads(result.output)["result"]
    assert updated["title"] == "T1b"
    assert updated["weight"] == 3
    assert updated["labels"] == ["x"]


def test_cli_edit_commands_expose_expected_rev(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])

    def add_id(args):
        result = invoke(["--json", "-C", str(tmp_path), *args])
        assert result.exit_code == 0, result.output
        return json.loads(result.output)["result"]["id"]

    goal_id = add_id(["goal", "add", "G1"])
    milestone_id = add_id(["milestone", "add", "M1"])
    decision_id = add_id(["decision", "add", "D1"])
    invoke(["-C", str(tmp_path), "member", "add", "alice", "--name", "Alice"])
    invoke(["-C", str(tmp_path), "link", "add", "fw", "../firmware"])

    stale = ["--expected-rev", "sha256:" + "0" * 64]
    for args in (
        ["goal", "edit", goal_id, "--title", "G2"],
        ["milestone", "edit", milestone_id, "--title", "M2"],
        ["member", "edit", "alice", "--name", "A2"],
        ["decision", "edit", decision_id, "--title", "D2"],
        ["link", "edit", "fw", "--mode", "aggregate"],
    ):
        result = invoke(["--json", "-C", str(tmp_path), *args, *stale])
        assert result.exit_code == 5, f"{args}: {result.output}"
        assert json.loads(result.output)["error"]["code"] == "REVISION_CONFLICT", args


def test_cli_decision_and_link_edit_happy_path(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])
    result = invoke(["--json", "-C", str(tmp_path), "decision", "add", "D1"])
    decision = json.loads(result.output)["result"]
    result = invoke(
        ["--json", "-C", str(tmp_path), "decision", "edit", decision["id"],
         "--rationale", "simpler", "--expected-rev", decision["rev"]]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result"]["rationale"] == "simpler"

    result = invoke(["--json", "-C", str(tmp_path), "link", "add", "fw", "../firmware"])
    link = json.loads(result.output)["result"]
    result = invoke(
        ["--json", "-C", str(tmp_path), "link", "edit", "fw", "--enable",
         "--expected-rev", link["rev"]]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result"]["enabled"] is True


def test_cli_milestone_show_exposes_rev(tmp_path):
    invoke(["-C", str(tmp_path), "init", "--name", "Demo"])
    result = invoke(["--json", "-C", str(tmp_path), "milestone", "add", "M1"])
    milestone = json.loads(result.output)["result"]
    result = invoke(["--json", "-C", str(tmp_path), "milestone", "show", milestone["id"]])
    assert result.exit_code == 0, result.output
    view = json.loads(result.output)["result"]
    assert view["rev"] == milestone["rev"]
    assert view["version"] == 1


def test_cli_version_and_bare_invocation():
    result = invoke(["--version"])
    assert result.exit_code == 0
    assert "project-tool" in result.output

    # 无子命令 -> 打印 help，exit 0（与 docs/05 的 --version 承诺一致）
    result = invoke([])
    assert result.exit_code == 0
    assert "Usage" in result.output

    # 未知选项仍然是 usage error (exit 2)
    assert invoke(["--definitely-not-an-option"]).exit_code == 2
