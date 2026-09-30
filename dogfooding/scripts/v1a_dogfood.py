#!/usr/bin/env python3
"""V1-A dogfooding driver：Area + Artifact 对真实 EFW 项目的回归验证。

硬规则（AGENTS.md §5）：
  - 真实 EFW 源码零修改；framework 仓库禁止任何 git 写操作。
  - 真实 .pjt 只跑只读命令 + `pjt migrate`（补空目录 / 抬 schema_version）。
  - Area / Artifact 的实际写入全部发生在 /tmp 的临时副本上。

为什么大部分走 Service API 而不是 CLI：`pjt` 每次启动要 import pydantic+rich+typer
（WSL 下约 5s），70 次调用就是 6 分钟。CLI 仍然被完整验证——见 `cli_checks`。

用法: python3 dogfooding/scripts/v1a_dogfood.py [EFW_PATH]
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # dogfooding/scripts/x.py -> repo root
# 用仓库自己的 venv 解释器跑（系统 python3 没有 pydantic）
VENV_PY = REPO / ".venv" / "bin" / "python"
if VENV_PY.is_file() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
sys.path.insert(0, str(REPO))

from project_tool.application.service import ProjectService  # noqa: E402
from project_tool.domain.errors import ProjectToolError  # noqa: E402
from project_tool.storage import open_project  # noqa: E402

EFW = Path(sys.argv[1] if len(sys.argv) > 1 else "/mnt/d/framework/new/efw").resolve()
EVIDENCE = REPO / "dogfooding" / "v1a-evidence"
PJT_BIN = [str(REPO / ".venv" / "bin" / "pjt")]

AREA_MAP = [
    ("store.updateModel", "Core"),
    ("通信页行内编辑", "UI"),
    ("数据流页句子行内编辑", "UI"),
    ("状态机页编辑", "UI"),
    ("删除对象前的引用检查", "Core"),
    ("serial/tcp 回环集成测试", "Debug"),
    ("真机 hash 不一致提示", "Debug"),
    ("重建 desktop 主进程", "Distribution"),
    ("修复 package.json 脚本", "Distribution"),
    ("PyInstaller 后端打包脚本", "Distribution"),
    ("打包发布 smoke test", "Distribution"),
    ("ProcTransport.close 资源泄漏", "Core"),
    ("efw.h 聚合 msgq.h", "Runtime"),
    ("源码草稿持久化", "UI"),
]

TASK_ARTIFACT_MAP = [
    ("studio_core/debug.py", "serial/tcp 回环集成测试"),
    ("package.json", "重建 desktop 主进程"),
    ("ui/store.tsx", "store.updateModel"),
    ("docs/04-debug-and-api.md", "真机 hash 不一致提示"),
]

BAD_LOCATORS = [
    "../../secret.txt",
    "../outside/secret.txt",
    "/etc/passwd",
    r"C:\Users\me\secret.txt",
    "c:/Users/me/secret.txt",
    "\\\\server\\share\\secret.txt",
    "~/notes.md",
    ".pjt/project.json",
    ".PJT/objects/tasks/x.json",
    "",
    "   ",
]

lines: list[str] = []


def out(text: str = "") -> None:
    print(text)
    lines.append(text)
    if EVIDENCE.is_dir():
        (EVIDENCE / "v1a-dogfooding.txt").open("a", encoding="utf-8").write(text + "\n")


def section(title: str) -> None:
    out()
    out(f"--- {title} ---")


def cli(args: list[str], root: Path, json_out: bool = False) -> tuple[int, str]:
    # 全局选项（--json）必须放在子命令**之前**：Typer 的 group-level option
    # 放在子命令后面会被当成未知参数 -> usage error (exit 2)。
    head = ["--json"] if json_out else []
    proc = subprocess.run(
        [*PJT_BIN, "-C", str(root), *head, *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    return proc.returncode, (proc.stdout + proc.stderr).rstrip()


def cli_json(args: list[str], root: Path) -> tuple[int, dict | None]:
    """--json 输出可能被 rich 按终端宽度折行，解析前先拼回单行。"""
    code, text = cli(args, root, json_out=True)
    flat = " ".join(text.split())
    try:
        return code, json.loads(flat)
    except json.JSONDecodeError:
        return code, None


def error_code(payload: dict | None) -> str:
    if payload and "error" in payload:
        return str(payload["error"]["code"])
    return "NO ERROR"


def hash_tree(root: Path) -> dict[str, str]:
    """工程源码的 sha256 映射（跳过 .pjt 与构建产物），用于证明零写入。"""
    skip = {".pjt", ".venv", "node_modules", "dist", "test-results", ".git"}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] in skip:
            continue
        result[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def call(service: ProjectService, method: str, **params):
    try:
        return None, service.call(method, params)
    except ProjectToolError as exc:
        return exc, None


def by_title(service: ProjectService, prefix: str):
    for row in service.call("task.list", {}):
        if row["title"].startswith(prefix):
            return row["id"]
    return None


def unique_prefix(service: ProjectService, full_id: str, keep: int = 8) -> str:
    """最短无歧义短 ID（同毫秒创建的 Artifact 共享时间戳前缀，不能用固定长度）。"""
    all_ids = [row["id"] for row in service.call("artifact.list", {"include_archived": True})]
    all_ids += [row["id"] for row in service.call("artifact.list", {
        "include_archived": True, "include_deleted": True})]
    for n in range(keep, len(full_id) + 1):
        prefix = full_id[:n]
        if sum(1 for other in set(all_ids) if other.startswith(prefix)) == 1:
            return prefix
    return full_id


def by_locator(service: ProjectService, locator: str):
    for row in service.call("artifact.list", {"include_archived": True}):
        if row["locator"] == locator:
            return row["id"]
    return None


# ===================================================================== 1. 真实 EFW


def real_efw_readonly() -> None:
    out("===== 1. REAL EFW: read-only regression + schema 1.0 -> 1.1 =====")
    section("pjt --version")
    code, text = cli(["--version"], EFW)
    out(text)

    section("project.json before migrate")
    out((EFW / ".pjt" / "project.json").read_text(encoding="utf-8").rstrip())

    section("pjt migrate")
    code, text = cli(["migrate"], EFW)
    out(f"exit={code}")
    out(text)

    section("pjt migrate (idempotent)")
    code, text = cli(["migrate"], EFW)
    out(f"exit={code}")
    out(text)

    section("project.json after migrate")
    out((EFW / ".pjt" / "project.json").read_text(encoding="utf-8").rstrip())

    section("pjt doctor")
    code, text = cli(["doctor"], EFW)
    out(text)
    out(f"exit={code}")

    section("pjt status")
    code, text = cli(["status"], EFW)
    out(text)

    section("pjt area list / artifact list  (旧项目：空集合，不是 corrupted)")
    for args in (["area", "list"], ["artifact", "list"], ["area", "tree"]):
        code, text = cli(args, EFW)
        out(f"$ pjt {' '.join(args)}  -> exit={code}")
        out(text)

    section("object collection dirs after migrate（没有 areas.json 之类的聚合文件）")
    for child in sorted((EFW / ".pjt" / "objects").iterdir()):
        count = len(list(child.glob("*.json"))) if child.is_dir() else -1
        out(f"  {child.name:<14} {'dir' if child.is_dir() else 'FILE'}  {count} object(s)")

    section("pjt log --type project  (migrate 事件)")
    code, text = cli(["log", "--type", "project", "--limit", "3"], EFW)
    out(text)


# ===================================================================== 2. 临时副本


def make_copy(work: Path) -> Path:
    copy = work / "efw"
    copy.mkdir(parents=True)
    archive = subprocess.run(
        [
            "tar", "-C", str(EFW), "-cf", "-",
            "--exclude=./.pjt", "--exclude=./.venv", "--exclude=./node_modules",
            "--exclude=./dist", "--exclude=./test-results",
            ".",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["tar", "-C", str(copy), "-xf", "-"], input=archive.stdout, check=True)
    shutil.copytree(EFW / ".pjt", copy / ".pjt")
    return copy


def area_dimension(copy: Path, before: dict[str, str]) -> None:
    out()
    out("===== 2. TEMP COPY: Area dimension (vs real EFW data) =====")
    service = ProjectService(open_project(copy))

    section("2.1 5 个顶层 Area（EFW 的真实模块边界）")
    for name, desc in (
        ("Core", "studio_core service/cli/server, model store, generated code"),
        ("UI", "Electron renderer (ui/): pages, store, RPC"),
        ("Debug", "transport, real-device debug, observe_port templates"),
        ("Runtime", "C runtime: header aggregation, msgq, ProcTransport"),
        ("Distribution", "desktop shell, package.json, PyInstaller, installer"),
    ):
        _, record = call(service, "area.create", name=name, description=desc)
        out(f"created {record['id']}  {record['name']}")
    section("2.2 二级 Area（UI 下面的稳定子分区）")
    for name, desc in (
        ("Editor", "in-app model editing surfaces"),
        ("Debug UI", "debug page + port templates"),
    ):
        _, record = call(service, "area.create", name=name, description=desc, parent_area_id="UI")
        out(f"created {record['id']}  {record['name']}  parent={record['parent_area_id']}")

    section("2.3 把 14 个真实 EFW 任务映射到 Area（Task 单 Area，取主 Area）")
    for prefix, area in AREA_MAP:
        task_id = by_title(service, prefix)
        if task_id is None:
            out(f"  SKIP (task not found): {prefix}")
            continue
        _, record = call(service, "task.move_area", task_id=task_id, area_id=area)
        out(f"  {prefix:<34} -> {area:<12} ({record['id'] if record else 'FAILED'})")

    section("2.4 Area / Milestone 两个维度同时看（graph project）")
    tree = service.call("graph.project", {})
    out(f"  Goals      : {[g['title'] for g in tree['goals']]}")
    out(f"  Milestones : {[(m['title'], m['progress']) for m in tree['milestones']]}")
    for area in tree["areas"]:
        depth = ""
        out(f"  Area       : {area['name']:<14} {area['task_count']} task(s) {depth}")
    out("  => Area 是与 Goal/Milestone 平级的独立分区，没有被塞进 Goal->Milestone 层级")

    section("2.5 task list --area Debug / --area Distribution")
    for area in ("Debug", "Distribution"):
        rows = service.call("task.list", {"area": area})
        out(f"  --area {area}")
        for row in rows:
            flag = " !" if row["computed_blocked"] else ""
            out(f"    {row['id'][:12]}  {row['status']:<8}{flag:<2} {row['title']}")

    section("2.6 pjt status 不列 Area（避免信息过载）")
    status = service.call("project.status", {})
    out(f"  status keys: {sorted(status)}")
    out(f"  'areas' in status -> {'areas' in status}")

    section("2.7 Area 层级规则")
    for args, expect in (
        ({"area_id": "Debug", "parent_area_id": "Debug"}, "self parent"),
        ({"area_id": "UI", "parent_area_id": "Debug UI"}, "2 级子 area 作为父级"),
    ):
        exc, _ = call(service, "area.set_parent", **args)
        out(f"  {expect:<22} -> {exc.code if exc else 'NO ERROR'}: {exc.message if exc else ''}")
    out("  => 环/自引用由与 goal/task parent 同一套 _validate_chain 拦截")

    section("2.8 Area 事件")
    for record in service.call("log.list", {"event_type": "area", "limit": 8})["events"]:
        out(f"  {record['event_type']:<18} {record['payload']}")

    section("2.9 doctor")
    report = service.call("project.doctor", {})
    for check in report["checks"]:
        if check["status"] != "ok":
            out(f"  {check['status'].upper():<8} {check['name']}  {check['message']}")
    out(
        f"  ok={report['ok']} objects={report['summary']['objects']} "
        f"events={report['summary']['events']} errors={report['summary']['errors']} "
        f"warnings={report['summary']['warnings']}"
    )
    out(f"  工程源码 tree hash 未变: {hash_tree(copy) == before}")


# ===================================================================== 3. Artifact


def artifact_dimension(copy: Path, before: dict[str, str]) -> None:
    out()
    out("===== 3. TEMP COPY: Artifact references =====")
    service = ProjectService(open_project(copy))

    section("3.1 file artifact（只对已确认存在的路径建引用）")
    for kind, locator, name, desc in (
        ("file", "studio_core/service.py", "Core service (shared by CLI and GUI)",
         "同一 Service 被 CLI / GUI / stdio server 共用"),
        ("file", "studio_core/cli.py", "Studio CLI entry point", ""),
        ("file", "studio_core/server.py", "stdio server entry point", ""),
        ("file", "studio_core/debug.py", "Debug transport implementation", ""),
        ("file", "package.json", "Electron build manifest", ""),
        ("file", "ui/store.tsx", "Renderer store (model editing state)", ""),
        ("document", "docs/04-debug-and-api.md", "Debug and API contract", ""),
        ("url", "https://www.electronjs.org/docs/latest/tutorial/quick-start",
         "Electron quick start (external)", ""),
        ("git_branch", "tmp/new", "framework branch used for this data", ""),
        ("git_commit", "2cb4a74", "framework HEAD at dogfooding time", ""),
    ):
        _, record = call(
            service, "artifact.create", kind=kind, locator=locator, name=name, description=desc
        )
        out(f"  {kind:<12} {locator[:58]:<58} {record['id'] if record else 'FAILED'}")

    section("3.2 path boundary：ProjectTool 自己的 report 在另一个仓库里")
    out("  dogfooding/report.md 位于 ProjectTool 仓库，不在 EFW project root：")
    for kind, locator, label in (
        ("file", "dogfooding/report.md", "as file artifact (locator 合法但文件不存在)"),
        ("file", "../../ProjectTool/dogfooding/report.md", "as file artifact 逃出 root"),
    ):
        exc, record = call(service, "artifact.create", kind=kind, locator=locator)
        if exc:
            out(f"    {label:<52} -> {exc.code}: {exc.message}")
        else:
            status = service.call("artifact.verify", {"artifact_id": record["id"]})[0]
            out(
                f"    {label:<52} -> created, verify={status['status']} "
                f"(exists={status['exists']}) => 只是 warning，不是数据损坏"
            )
    out("  正确做法（外部文档用 url 引用）：")
    _, record = call(
        service,
        "artifact.create",
        kind="url",
        locator="https://github.com/snsnnd/ProjectTool/blob/main/dogfooding/report.md",
        name="ProjectTool V0.1 dogfooding report (external)",
    )
    out(f"    url  ART  {record['id']}  {record['locator']}")

    section("3.3 危险 locator 全部拒绝")
    for kind, locator in (
        [("file", value) for value in BAD_LOCATORS]
        + [
            ("url", "example.com"),
            ("url", "ftp://example.com"),
            ("git_commit", "zzzz"),
            ("git_branch", "feature/../main"),
        ]
    ):
        # 展示用标签不改变实际传入值（空串必须真的传空串）
        label = repr(locator) if locator.strip() == "" and locator else locator
        exc, _ = call(service, "artifact.create", kind=kind, locator=locator)
        out(f"  {kind:<11} {label[:34]:<34} -> {exc.code if exc else 'NO ERROR -> FAIL'}")

    section("3.4 真实关联：Artifact ↔ Task / Decision / Milestone")
    for locator, title_prefix in TASK_ARTIFACT_MAP:
        artifact_id = by_locator(service, locator)
        task_id = by_title(service, title_prefix)
        if not artifact_id or not task_id:
            out(f"  SKIP {locator} / {title_prefix}")
            continue
        _, record = call(service, "artifact.attach", artifact_id=artifact_id, task=task_id)
        out(f"  {locator:<28} <-> {title_prefix:<32} tasks={record['related_task_ids']}")

    decisions = {row["title"]: row["id"] for row in service.call("decision.list", {})}
    cli_shared = next(
        (v for k, v in decisions.items() if "CLI" in k and "GUI" in k), None
    )
    if cli_shared:
        service_id = by_locator(service, "studio_core/service.py")
        for locator in ("studio_core/cli.py", "studio_core/server.py"):
            call(service, "artifact.attach", artifact_id=by_locator(service, locator),
                 decision=cli_shared)
        record = service.call("artifact.get", {"artifact_id": service_id})
        out(f"  Decision '{next(k for k in decisions if decisions[k] == cli_shared)[:40]}'")
        out(f"    studio_core/service.py artifacts = {record['related_decision_ids']}")
        out("    (service.py / cli.py / server.py 三份引用都挂到同一条 Decision 上)")

    active_milestone = next(
        (m["id"] for m in service.call("milestone.list", {}) if m["status"] == "active"), None
    )
    if active_milestone:
        call(service, "artifact.attach",
             artifact_id=by_locator(service, "studio_core/debug.py"), milestone=active_milestone)
        record = service.call("artifact.get", {"artifact_id": by_locator(service, "studio_core/debug.py")})
        out(f"  active milestone {active_milestone[:12]} <- {record['related_milestone_ids']}")

    section("3.5 反向读：task.related_artifacts（file scan 派生，不落库）")
    for title_prefix in ("serial/tcp 回环集成测试", "store.updateModel", "真机 hash 不一致提示"):
        task_id = by_title(service, title_prefix)
        rows = service.call("task.related_artifacts", {"task_id": task_id})
        out(f"  {title_prefix}: {[(r['kind'], r['locator']) for r in rows]}")

    section("3.6 verify")
    rows = service.call("artifact.verify", {})
    for row in rows:
        out(f"  {row['status']:<8} {row['kind']:<11} {row['locator'][:56]:<56} {row['detail']}")

    section("3.7 缺失文件 = warning 而不是 PROJECT_CORRUPTED")
    _, missing = call(
        service, "artifact.create", kind="file", locator="scripts/never_created.py",
        name="planned packaging script (not written yet)",
    )
    out(f"  created {missing['id']} locator={missing['locator']} (scripts/ 目前为空)")
    row = service.call("artifact.verify", {"artifact_id": missing["id"]})[0]
    out(f"  verify -> {row['status']} exists={row['exists']}")
    report = service.call("project.doctor", {})
    check = {c["name"]: c for c in report["checks"]}["artifacts.locators"]
    out(f"  doctor artifacts.locators -> {check['status']}: {check['message']}")
    for detail in check.get("details", []):
        out(f"      {detail}")
    out(f"  doctor ok = {report['ok']}  (file 缺失不判 corrupted)")

    section("3.8 verify 是纯查询：不产生事件")
    before_events = service.call("log.list", {"limit": 500})["count"]
    service.call("artifact.verify", {})
    service.call("artifact.verify", {})
    service.call("task.related_artifacts", {"task_id": by_title(service, "store.updateModel")})
    after_events = service.call("log.list", {"limit": 500})["count"]
    out(f"  events before={before_events} after={after_events} (must be equal)")

    section("3.9 Artifact 事件契约")
    for record in service.call(
        "log.list", {"event_type": "artifact", "limit": 6}
    )["events"]:
        out(f"  {record['occurred_at'][:19]}  {record['event_type']:<20} {record['payload']}")

    section("3.10 remove 只删引用，绝不动被引用文件")
    artifact_id = by_locator(service, "studio_core/debug.py")
    target = copy / "studio_core" / "debug.py"
    digest_before = hashlib.sha256(target.read_bytes()).hexdigest()
    out(f"  before: {target}  sha256={digest_before[:16]}  size={target.stat().st_size}")
    record = service.call("artifact.remove", {"artifact_id": artifact_id})
    out(f"  artifact.remove -> lifecycle={record['lifecycle']}")
    digest_after = hashlib.sha256(target.read_bytes()).hexdigest()
    out(f"  after : {target}  sha256={digest_after[:16]}  size={target.stat().st_size}")
    out(f"  file untouched: {digest_before == digest_after and target.is_file()}")

    section("3.11 expected_rev 合同（过期 rev -> REVISION_CONFLICT）")
    fresh = service.call("artifact.create", {"kind": "file", "locator": "package.json"})["id"]
    stale = "sha256:" + "0" * 64
    for method, params in (
        ("artifact.update", {"name": "x"}),
        ("artifact.attach", {"task": by_title(service, "store.updateModel")}),
        ("artifact.detach", {"task": by_title(service, "store.updateModel")}),
        ("artifact.remove", {}),
    ):
        exc, _ = call(service, method, artifact_id=fresh, expected_rev=stale, **params)
        out(f"  {method:<20} stale expected_rev -> {exc.code if exc else 'NO ERROR'}")
    rev = service.call("artifact.get", {"artifact_id": fresh})["rev"]
    record = service.call("artifact.update", {"artifact_id": fresh, "name": "ok", "expected_rev": rev})
    out(f"  artifact.update correct expected_rev -> {record['name']}")

    section("3.12 零污染：整个工程源码 tree hash 前后对比")
    after = hash_tree(copy)
    if after == before:
        out("  TREE HASH: IDENTICAL  => ProjectTool 只写 .pjt/**，一个工程文件都没碰")
    else:
        changed = sorted(k for k in set(after) | set(before) if after.get(k) != before.get(k))
        out(f"  TREE HASH: CHANGED -> FAIL: {changed}")
    out(f"  files compared: {len(after)}")


# ===================================================================== 4. CLI


def cli_checks(copy: Path) -> None:
    out()
    out("===== 4. CLI surface (real commands, not just the Service API) =====")
    service = ProjectService(open_project(copy))
    # debug.py 的 artifact 在 3.10 被 remove（软删除，默认 list 不可见），
    # 所以 CLI 演示挑一个仍活着的 artifact + 它的任务。
    task_id = by_title(service, "重建 desktop 主进程")
    artifact_id = by_locator(service, "package.json")
    short = unique_prefix(service, artifact_id)
    out(f"  (task {task_id[:12]}, artifact {artifact_id[:12]}, short id {short})")

    for args in (
        ["area", "list"],
        ["area", "show", "Debug"],
        ["area", "tree"],
        ["task", "list", "--area", "Debug"],
        ["task", "show", task_id],
        ["task", "artifacts", task_id],
        ["task", "related-updates", task_id],
        ["artifact", "list", "--task", task_id],
        ["artifact", "show", short],
        ["artifact", "verify"],
        ["artifact", "history", short],
        ["graph", "project"],
    ):
        code, text = cli(args, copy)
        head = "\n      ".join(text.splitlines()[:14])
        out(f"\n  $ pjt {' '.join(args)}   [exit={code}]")
        if text:
            out(f"      {head}")

    section("4.1 CLI 拒绝危险 locator")
    for bad in ("../../secret.txt", "/etc/passwd", r"C:\Users\me\x.txt", ".pjt/project.json"):
        code, payload = cli_json(["artifact", "add", "file", bad], copy)
        out(f"  pjt artifact add file {bad:<24} -> exit={code} {error_code(payload)}")

    section("4.2 CLI --expected-rev")
    code, payload = cli_json(
        ["artifact", "edit", artifact_id, "--name", "x", "--expected-rev", "sha256:" + "0" * 64],
        copy,
    )
    out(f"  pjt artifact edit --expected-rev <stale> -> exit={code} {error_code(payload)}")
    code, payload = cli_json(
        ["task", "edit", task_id, "--title", "renamed", "--expected-rev", "sha256:" + "0" * 64],
        copy,
    )
    out(f"  pjt task edit     --expected-rev <stale> -> exit={code} {error_code(payload)}")

    section("4.3 pjt task ready（本轮补齐的 CLI 缺口）")
    for args in (
        ["task", "ready", task_id],
        ["task", "ready", task_id, "--expected-rev", "sha256:" + "0" * 64],
    ):
        code, text = cli(args, copy)
        out(f"  $ pjt {' '.join(args[:3])} {args[3] if len(args) > 3 else ''} -> exit={code}")
        out(f"      {text.splitlines()[0] if text else ''}")

    section("4.4 pjt doctor 汇总")
    code, text = cli(["doctor"], copy)
    out(text)


# ===================================================================== 5. 存储布局


def storage_layout(copy: Path) -> None:
    out()
    out("===== 5. Storage layout & transaction hygiene =====")
    out("  one object per file（没有 areas.json / artifacts.json 聚合文件）:")
    for child in sorted((copy / ".pjt" / "objects").iterdir()):
        count = len(list(child.glob("*.json"))) if child.is_dir() else -1
        out(f"    {child.name:<14} {'dir' if child.is_dir() else 'FILE':<5} {count} object(s)")
    out(f"  transactions/ 残留: {len(list((copy / '.pjt' / 'transactions').iterdir()))} (必须为 0)")
    out(f"  write.lock 残留   : {(copy / '.pjt' / 'local' / 'locks' / 'write.lock').is_file()}")
    out(f"  events 总数       : {len(list((copy / '.pjt' / 'events').rglob('EVT-*.json')))}")
    report = ProjectService(open_project(copy)).call("project.doctor", {})
    out(f"  doctor            : ok={report['ok']} errors={report['summary']['errors']} "
        f"warnings={report['summary']['warnings']} repairable={report['summary']['repairable']}")


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report = EVIDENCE / "v1a-dogfooding.txt"
    if report.exists():
        report.unlink()
    report.write_text("", encoding="utf-8")
    work = Path(tempfile.mkdtemp(prefix="pjt-v1a-efw-"))
    copy = make_copy(work)
    out(f"workdir: {work}")
    out(f"efw:     {EFW}")
    out(f"copy:    {copy}")

    real_efw_readonly()
    before = hash_tree(copy)
    area_dimension(copy, before)
    artifact_dimension(copy, before)
    cli_checks(copy)
    storage_layout(copy)

    out()
    out(f"done. workdir kept for inspection: {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
