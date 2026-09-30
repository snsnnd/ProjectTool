"""多人写者冲突探针（V1-C 的前置调查）。

目的：在设计任何合并辅助之前，**先量出真实的冲突面**。
纯 Git 操作，全部发生在临时目录；绝不碰 new/efw 或 framework。

做法：造一个 origin，两个克隆各自在 work 分支上写入，然后往 origin 合，
用 `git diff --name-only --diff-filter=U` 列出真正冲突的文件。

关键问题（20 人并发时哪些结构会天天冲突）：
  - events/ 是不是每写一次都追加到同一个文件？（若是，20 人必炸）
  - objects/ 一对象一文件是否天然可合并？
  - refs/labels.json 这种共享集合怎么办？
  - state/state.json 每次写都变，是否只是无意义的冲突源？
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# 用仓库自己的 venv 解释器跑（系统 python3 没有 pydantic）
VENV_PY = REPO / ".venv" / "bin" / "python"
if VENV_PY.is_file() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
sys.path.insert(0, str(REPO))

PJT_BIN = [str(REPO / ".venv" / "bin" / "pjt")]


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def pjt(root: Path, *args: str) -> str:
    """调 pjt CLI（用 -C 指向项目）。"""
    proc = run([*PJT_BIN, "-C", str(root), *args], cwd=root.parent, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"pjt {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def new_id(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise RuntimeError(f"no id in output: {text[:400]}")
    return match.group(0)


class Bench:
    """一个隔离的多写者实验台：origin.git(裸) + origin(工作树) + a/ b/ 两个克隆。

    整体放在一个 mktemp 目录下，结束即删——绝不碰 new/efw 或 framework。
    """

    def __init__(self, name: str = "MultiWriter", ignore_derived: bool = False):
        self.base = Path(tempfile.mkdtemp(prefix="pjt-mw-"))
        self.bare = self.base / "origin.git"
        self.origin = self.base / "origin"
        # 必须 -b main：裸库默认 HEAD 指向 master，clone 会 checkout 一个空树，
        # 症状是克隆里没有 .pjt，pjt 报 NOT_FOUND。
        run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], cwd=self.base)
        self.origin.mkdir()
        pjt(self.origin, "init", "--name", name)
        if ignore_derived:
            # 验证用：state/ 和 refs/ 都是可重建的派生缓存，不该进版本控制
            gitignore = self.origin / ".gitignore"
            with gitignore.open("a", encoding="utf-8") as handle:
                handle.write(".pjt/state/\n.pjt/refs/\n")
        run(["git", "init", "-q", "-b", "main", "."], cwd=self.origin)
        run(["git", "config", "user.email", "origin@example.com"], cwd=self.origin)
        run(["git", "config", "user.name", "Origin"], cwd=self.origin)
        run(["git", "remote", "add", "origin", str(self.bare)], cwd=self.origin)
        run(["git", "add", "-A"], cwd=self.origin)
        run(["git", "commit", "-qm", "init"], cwd=self.origin)
        run(["git", "push", "-q", "-u", "origin", "main"], cwd=self.origin)

    def clone(self, name: str) -> Path:
        target = self.base / name
        run(["git", "clone", "-q", str(self.bare), str(target)], cwd=self.base)
        run(["git", "config", "user.email", f"{name}@example.com"], cwd=target)
        run(["git", "config", "user.name", name.upper()], cwd=target)
        run(["git", "checkout", "-q", "-b", "work"], cwd=target)
        return target

    def merge_into_main(self, branches: list[str]) -> tuple[bool, list[str]]:
        run(["git", "checkout", "-q", "main"], cwd=self.origin)
        # 分支是推到裸库的，origin 必须先 fetch 才知道它们存在
        run(["git", "fetch", "-q", "origin"], cwd=self.origin)
        clean = True
        conflicts: list[str] = []
        for branch in branches:
            proc = run(
                ["git", "merge", "--no-edit", "-q", f"origin/{branch}"],
                cwd=self.origin,
                check=False,
            )
            if proc.returncode != 0:
                clean = False
                listed = run(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    cwd=self.origin,
                    check=False,
                ).stdout.split()
                if listed:
                    conflicts.extend(listed)
                else:
                    # 没冲突文件却 merge 失败 = 失败原因不是内容冲突（例如分支不存在），
                    # 必须把原始错误带出来，否则证据里只能写个「(unlisted)」没法查。
                    conflicts.append(f"<merge error: {(proc.stderr or proc.stdout).strip()[:200]}>")
                run(["git", "merge", "--abort"], cwd=self.origin, check=False)
        return clean, conflicts

    def close(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)


def commit(work: Path, label: str) -> bool:
    """没有改动时 git commit 返回 1；对照组场景需要容忍。"""
    run(["git", "add", "-A"], cwd=work)
    proc = run(["git", "commit", "-qm", label], cwd=work, check=False)
    if proc.returncode != 0 and "nothing to commit" not in (proc.stdout + proc.stderr):
        raise RuntimeError(f"commit failed in {work}: {proc.stdout}{proc.stderr}")
    return proc.returncode == 0


def scenario(
    name: str,
    act_a,
    act_b,
    ignore_derived: bool = False,
    seed=None,
) -> dict:
    bench = Bench(ignore_derived=ignore_derived)
    try:
        seeded = seed(bench.origin) if seed else None
        a = bench.clone("a")
        b = bench.clone("b")
        run(["git", "branch", "-M", "work", "work-a"], cwd=a)
        run(["git", "branch", "-M", "work", "work-b"], cwd=b)
        act_a(a, seeded)
        commit(a, "A writes")
        run(["git", "push", "-q", "origin", "work-a"], cwd=a)
        act_b(b, seeded)
        commit(b, "B writes")
        run(["git", "push", "-q", "origin", "work-b"], cwd=b)
        clean, conflicts = bench.merge_into_main(["work-a", "work-b"])
        return {
            "scenario": name,
            "clean": clean,
            "conflicts": conflicts,
            "ignore_derived": ignore_derived,
        }
    finally:
        bench.close()


# ------------------------------------------------------------------ 场景



def add_task(root: Path, title: str, seeded=None) -> str:
    return new_id(pjt(root, "task", "add", title), r"TSK-[A-Z0-9]+")


def _scenarios() -> list[tuple[str, object, object]]:
    """(名字, A 的动作, B 的动作)。共享对象需要先造出来，所以用闭包。"""

    def add_task(root: Path, title: str, seeded=None) -> str:
        pjt(root, "task", "add", title)
        return new_id(pjt(root, "task", "list"), r"TSK-[A-Z0-9]+")

    def post_update(root: Path, text: str, seeded=None) -> None:
        pjt(root, "update", "add", text, "-s", "week")

    def add_labelled_task(root: Path, title: str, label: str, seeded=None) -> None:
        pjt(root, "task", "label", add_task(root, title), label)

    def start_own_task(root: Path, title: str, seeded=None) -> None:
        pjt(root, "task", "start", add_task(root, title))

    def add_task_in_same_area(root: Path, seeded=None) -> None:
        area = new_id(pjt(root, "area", "add", "shared-area"), r"ARA-[A-Z0-9]+")
        pjt(root, "task", "add", f"task in area from {root.name}", "--area", area)

    def add_member(root: Path, handle: str, seeded=None) -> None:
        pjt(root, "member", "add", handle)

    # 真·共享对象：对象在 main 里造好，两边克隆后改**同一个文件**。
    # 之前的版本两边各自建同名任务，ID 不同，根本没碰到同一个文件——那是假测试。
    def seed_shared_task(root: Path):
        pjt(root, "task", "add", "one shared task")
        run(["git", "add", "-A"], cwd=root)
        run(["git", "commit", "-qm", "seed shared task"], cwd=root)
        run(["git", "push", "-q", "origin", "main"], cwd=root)
        return new_id(pjt(root, "task", "list"), r"TSK-[A-Z0-9]+")

    def edit_shared_a(root: Path, seeded: str) -> None:
        pjt(root, "task", "start", seeded)

    def edit_shared_b(root: Path, seeded: str) -> None:
        pjt(root, "task", "start", seeded)

    return [
        ("S0 both idle (control)", lambda r, _s: None, lambda r, _s: None),
        (
            "S1 both create a different task",
            lambda r, _s: add_task(r, "A task"),
            lambda r, _s: add_task(r, "B task"),
        ),
        (
            "S2 both post an update",
            lambda r, _s: post_update(r, "A progress"),
            lambda r, _s: post_update(r, "B progress"),
        ),
        (
            "S3 both add a label",
            lambda r, _s: add_labelled_task(r, "labelled-a", "alpha"),
            lambda r, _s: add_labelled_task(r, "labelled-b", "beta"),
        ),
        (
            "S4 both edit a different task",
            lambda r, _s: start_own_task(r, "own-a"),
            lambda r, _s: start_own_task(r, "own-b"),
        ),
        ("S5 both edit the SAME task object", edit_shared_a, edit_shared_b, seed_shared_task),
        (
            "S6 A creates task / B posts update",
            lambda r, _s: add_task(r, "A only"),
            lambda r, _s: post_update(r, "B only"),
        ),
        (
            "S7 both create a task in the same area",
            add_task_in_same_area,
            add_task_in_same_area,
        ),
        (
            "S8 both add a member",
            lambda r, _s: add_member(r, "alice"),
            lambda r, _s: add_member(r, "bob"),
        ),
    ]


def _run_all(ignore_derived: bool) -> list[dict]:
    results = []
    for entry in _scenarios():
        name, act_a, act_b = entry[0], entry[1], entry[2]
        seed = entry[3] if len(entry) > 3 else None
        results.append(scenario(name, act_a, act_b, ignore_derived=ignore_derived, seed=seed))
    return results


def _print(results: list[dict], title: str) -> None:
    print()
    print(title)
    print("-" * 78)
    for r in results:
        mark = "clean" if r["clean"] else "CONFLICT: " + ", ".join(r["conflicts"])
        print(f"{r['scenario']:<44} {mark}")
    clean = sum(1 for r in results if r["clean"])
    print("-" * 78)
    print(f"{clean}/{len(results)} 可以无冲突合并")


def main() -> int:
    print("=" * 78)
    print("多人写者冲突探针 —— 纯 Git，全部在临时目录，绝不碰 new/efw")
    print("=" * 78)

    before = _run_all(ignore_derived=False)
    after = _run_all(ignore_derived=True)

    _print(before, "A) 现状（state/ 和 refs/ 都提交进 Git）")
    _print(after, "B) 把 state/ 和 refs/ 排除出版本控制后")

    out = REPO / "dogfooding" / "multiwriter-evidence"
    out.mkdir(exist_ok=True)
    (out / "conflict-probe.json").write_text(
        json.dumps({"as_is": before, "derived_ignored": after}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fixed = [b["scenario"] for b, a in zip(before, after, strict=True) if not b["clean"] and a["clean"]]
    still = [a["scenario"] for a in after if not a["clean"]]
    print()
    print(f"被修复的场景 ({len(fixed)}):")
    for name in fixed:
        print(f"  + {name}")
    print(f"仍然冲突的场景 ({len(still)}):")
    for name in still:
        print(f"  ! {name}")
    print()
    print(f"证据: {out / 'conflict-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
