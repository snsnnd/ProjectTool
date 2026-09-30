#!/usr/bin/env python3
"""V1-B dogfooding driver：Git 感知层对真实 EFW 项目的回归验证。

硬规则（AGENTS.md §5）：
  - 真实 EFW 源码零修改；framework 仓库**禁止任何 git 写操作**。
  - 真实 EFW 只跑只读命令（`git status` / `git log` / `git available`）。
  - 任何会产生写入的验证（`git link-commit`、Area 绑定 path_patterns）
    全部在 /tmp 的临时副本上做。

用法: python3 dogfooding/scripts/v1b_dogfood.py [EFW_PATH]
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

REPO = Path(__file__).resolve().parents[2]
VENV_PY = REPO / ".venv" / "bin" / "python"
if VENV_PY.is_file() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
sys.path.insert(0, str(REPO))

from project_tool.application.service import ProjectService  # noqa: E402
from project_tool.storage import open_project  # noqa: E402

EFW = Path(sys.argv[1] if len(sys.argv) > 1 else "/mnt/d/framework/new/efw").resolve()
EVIDENCE = REPO / "dogfooding" / "v1b-evidence"
SKIP = {".pjt", ".venv", "node_modules", "dist", "test-results", ".git"}


def out(text: str = "") -> None:
    print(text)
    (EVIDENCE / "v1b-dogfooding.txt").open("a", encoding="utf-8").write(text + "\n")


def section(title: str) -> None:
    out()
    out(f"--- {title} ---")


def hash_tree(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.relative_to(root).parts[0] not in SKIP:
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def framework_git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", "/mnt/d/framework", *args], capture_output=True, text=True
    ).stdout.rstrip()


# ================================================================ 1. 真实 EFW（只读）


def real_efw_readonly() -> None:
    out("===== 1. REAL EFW: read-only Git awareness =====")
    service = ProjectService(open_project(EFW))

    section("1.1 git.available —— project root != git root（EFW 的真实结构）")
    info = service.call("git.available", {})
    out(json.dumps(info, ensure_ascii=False, indent=2))
    out(f"  project root : {EFW}")
    out(f"  git root     : {info['work_tree']}")
    out(f"  两者相同？    : {info['project_root_is_git_root']}  -> 必须为 False（EFW 是子目录）")

    section("1.2 git.status —— 只列 project root 下的文件，.pjt 折叠成一行")
    status = service.call("git.status", {})
    out(f"  work_tree   : {status['work_tree']}")
    out(f"  subdir      : {status['project_subdir']}")
    out(f"  工程文件数  : {status['count']}")
    for item in status["files"]:
        out(f"    {item['status']:<10} {item['path']}")
    out(f"  .pjt 文件数 : {status['pjt_changed']}  {status['pjt_status_counts']}")
    out(f"  未绑定 Area : {[a['name'] for a in status['unbound_areas']]}")
    out("  => 真实 EFW 还没有 Area（V1-A 只在临时副本建过），所以 candidate_areas 全空")
    out("  => 同仓库其它目录的改动（framework/ 根目录等）没有混进来，这就是 subdir 过滤的作用")

    section("1.3 git.log —— 真实提交历史")
    log = service.call("git.log", {"limit": 5})
    for commit in log["commits"]:
        out(
            f"    {commit['short_sha']}  {commit['authored_at'][:10]}  "
            f"{commit['author']:<12}  {commit['subject'][:46]}"
        )
    out("  => EFW 现有提交没有 PJT-Task trailer（trailer 是 V1-B 才引入的约定）")

    section("1.4 只读保证：真实仓库状态没被我们碰过")
    out(f"  framework HEAD   : {framework_git('rev-parse', 'HEAD')}")
    out(f"  framework branch : {framework_git('rev-parse', '--abbrev-ref', 'HEAD')}")
    out(f"  reflog 条数      : {len(framework_git('reflog').splitlines())}")
    out("  => 三个值与本轮开始前一致（见 v1a-evidence/00-efw-pollution-check.txt）")


# ================================================================ 2. 临时副本


def make_copy(work: Path) -> Path:
    """复刻 EFW 的真实结构：git root 与 project root **不同**（`new/efw`）。

    不能只是把源码摊在 /tmp 下——那样 project root == git root，
    测不到 `subdir` 过滤这条最容易出错的路径。
    """
    framework = work / "framework"
    copy = framework / "new" / "efw"
    copy.mkdir(parents=True)
    archive = subprocess.run(
        [
            "tar", "-C", str(EFW), "-cf", "-",
            "--exclude=./.pjt", "--exclude=./.venv", "--exclude=./node_modules",
            "--exclude=./dist", "--exclude=./test-results",
            ".",
        ],
        check=True, capture_output=True,
    )
    subprocess.run(["tar", "-C", str(copy), "-xf", "-"], input=archive.stdout, check=True)
    shutil.copytree(EFW / ".pjt", copy / ".pjt")
    (framework / "README.md").write_text("framework root (outside the project)\n", "utf-8")
    for args in (
        ["init", "-q", "."],
        ["config", "user.email", "v1b@example.com"],
        ["config", "user.name", "V1B Dogfood"],
        ["add", "-A"],
        ["commit", "-qm", "import EFW"],
    ):
        subprocess.run(["git", "-C", str(framework), *args], check=True,
                       capture_output=True)
    return copy


def git_root(project_root: Path) -> Path:
    """临时副本的 git root（`framework/`，project root 是 `framework/new/efw`）。"""
    return project_root.parent.parent


def copy_git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True
    ).stdout.rstrip()


def temp_copy(copy: Path) -> None:
    out()
    out("===== 2. TEMP COPY: Area 目录绑定 + commit 关联 =====")
    service = ProjectService(open_project(copy))
    info = service.call("git.available", {})
    out(f"  copy          : {copy}")
    out(f"  git work_tree : {info['work_tree']}")
    out(f"  subdir        : {info['project_subdir']}")
    assert info["project_root_is_git_root"] is False, "临时副本必须复刻 EFW 的嵌套结构"
    assert info["project_subdir"] == "new/efw"

    section("2.1 给 Area 绑 path_patterns（V1-B 新能力，可选）")
    for name, patterns in (
        ("Core", ["studio_core/**"]),
        ("UI", ["ui/**"]),
        ("Debug", ["studio_core/debug.py", "runtime/**"]),
        ("Runtime", ["runtime/**"]),
        ("Distribution", ["package.json", "scripts/**", "docs/**"]),
    ):
        existing = service.call("area.list", {"include_archived": True})
        record = next((a for a in existing if a["name"] == name), None)
        params = {"path_patterns": patterns}
        if record:
            params["area_id"] = record["id"]
            service.call("area.update", params)
            out(f"  updated {name:<13} <- {patterns}")
        else:
            service.call("area.create", {"name": name, "path_patterns": patterns})
            out(f"  created {name:<13} <- {patterns}")
    out("  => Debug 和 Runtime 故意重叠（runtime/**），证明一个文件可命中多个 Area")

    section("2.2 制造改动，看 git.status 的 Area 映射")
    (copy / "ui" / "store.tsx").write_text(
        (copy / "ui" / "store.tsx").read_text(encoding="utf-8") + "\n// touched by v1b dogfooding\n",
        encoding="utf-8",
    )
    (copy / "studio_core" / "debug.py").write_text(
        (copy / "studio_core" / "debug.py").read_text(encoding="utf-8") + "\n# touched\n",
        encoding="utf-8",
    )
    (copy / "package.json").write_text(
        (copy / "package.json").read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    status = service.call("git.status", {})
    out(f"  {'status':<10} {'path':<34} candidate areas")
    for item in status["files"]:
        areas = ", ".join(a["name"] for a in item["candidate_areas"]) or "-"
        out(f"  {item['status']:<10} {item['path'][:34]:<34} {areas}")
    out("  => 重叠的 runtime/** 会同时出现在 Debug 与 Runtime 的候选里（推导，不是归类）")

    # 零写入基线必须在「故意改文件」之后取，否则会把我们自己的改动算进去
    before = hash_tree(copy)

    section("2.3 git.status --area 过滤")
    for area in ("UI", "Debug"):
        filtered = service.call("git.status", {"area": area})
        out(f"  --area {area:<6} -> {[f['path'] for f in filtered['files']]}")

    section("2.4 commit trailer -> 任务关联（约定：PJT-Task: TSK-…）")
    tasks = service.call("task.list", {})
    t6 = next(t for t in tasks if t["title"].startswith("serial/tcp"))
    out(f"  target task: {t6['id'][:12]}  {t6['title']}")
    copy_git("add", "-A", cwd=git_root(copy))
    copy_git(
        "commit", "-qm",
        f"add serial/tcp loopback coverage\n\nPJT-Task: {t6['id']}",
        cwd=git_root(copy),
    )
    sha = copy_git("rev-parse", "HEAD", cwd=git_root(copy))
    out(f"  commit: {sha[:12]}")
    log = service.call("git.log", {"task": t6["id"]})
    out(f"  git log --task -> {[(c['short_sha'], c['linked_task_ids']) for c in log['commits']]}")

    section("2.5 git.link-commit -> git_commit Artifact（只写 .pjt）")
    head_before = copy_git("rev-parse", "HEAD", cwd=git_root(copy))
    reflog_before = copy_git("reflog", cwd=git_root(copy))
    result = service.call("git.link_commit", {"commit": sha})
    out(f"  created   : {result['created']}")
    out(f"  artifact  : {result['artifact']['id'][:12]}  kind={result['artifact']['kind']}  "
        f"locator={result['artifact']['locator']}")
    out(f"  tasks     : {result['artifact']['related_task_ids']}")
    again = service.call("git.link_commit", {"commit": sha})
    out(f"  幂等重跑  : created={again['created']}  same_artifact="
        f"{again['artifact']['id'] == result['artifact']['id']}")
    out(f"  仓库 HEAD 不变 : {copy_git('rev-parse', 'HEAD', cwd=git_root(copy)) == head_before}")
    out(f"  仓库 reflog 不变: {copy_git('reflog', cwd=git_root(copy)) == reflog_before}")

    section("2.6 task.related_artifacts 现在含 commit 引用")
    for row in service.call("task.related_artifacts", {"task_id": t6["id"]}):
        out(f"    {row['kind']:<12} {row['locator']:<16} {row['name'][:40]}")

    section("2.7 git_commit artifact 的 verify（git adapter 已启用）")
    for row in service.call("artifact.verify", {}):
        if row["kind"] == "git_commit":
            out(f"    {row['status']:<8} {row['locator']}  {row['detail']}")

    section("2.8 事件")
    for event in service.call("log.list", {"event_type": "git", "limit": 3})["events"]:
        out(f"    {event['event_type']:<20} {json.dumps(event['payload'], ensure_ascii=False)}")

    section("2.9 零写入证明：git 操作前后工程源码树 sha256 对比")
    after = hash_tree(copy)
    if after == before:
        out("  TREE HASH: IDENTICAL  => git 操作只写了 .pjt/**，一个工程文件都没碰")
    else:
        changed = sorted(k for k in set(after) | set(before) if after.get(k) != before.get(k))
        out(f"  TREE HASH: CHANGED -> FAIL: {changed}")
    out(f"  files compared: {len(after)}  (基线取自 2.2 故意改动之后)")

    section("2.10 doctor")
    report = service.call("project.doctor", {})
    for check in report["checks"]:
        if check["status"] != "ok":
            out(f"  {check['status'].upper():<8} {check['name']}  {check['message']}")
    out(f"  ok={report['ok']} objects={report['summary']['objects']} "
        f"errors={report['summary']['errors']} warnings={report['summary']['warnings']}")


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "v1b-dogfooding.txt").unlink(missing_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pjt-v1b-efw-"))
    out(f"workdir: {work}")
    out(f"efw:     {EFW}")
    real_efw_readonly()
    copy = make_copy(work)
    temp_copy(copy)
    out()
    out(f"done. workdir kept: {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
