"""搭一个真实的多人 Area 活跃度场景，用于手工验证 `pjt area activity`。

纯演示脚本，不是测试。跑法：
    python3 dogfooding/scripts/area_activity_demo.py
"""

from __future__ import annotations

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

PJT = [str(REPO / ".venv" / "bin" / "pjt")]


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def commit_as(root: Path, name: str, email: str, message: str, paths: dict[str, str]) -> None:
    for rel, content in paths.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-qm", message)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="pjt-act-demo-"))
    try:
        git(root, "init", "-q", "-b", "main")
        # 先有代码和历史，再 init .pjt（.pjt 不进 git）
        commit_as(root, "Alice Wang", "alice@x.com", "core: 初始骨架", {"src/core/store.ts": "1\n"})
        commit_as(root, "Bob Li", "bob@x.com", "ui: 通信页", {"src/ui/comm.ts": "1\n"})
        commit_as(root, "Alice Wang", "alice@x.com", "core: 批量更新入口", {"src/core/store.ts": "2\n"})

        pjt(root, "init", "--name", "ActivityDemo")
        pjt(root, "member", "add", "alice", "--name", "Alice")
        pjt(root, "member", "add", "bob", "--name", "Bob")
        pjt(root, "member", "map-git", "alice", "--git-name", "Alice Wang", "--git-email", "alice@x.com")
        pjt(root, "member", "map-git", "bob", "--git-name", "Bob Li", "--git-email", "bob@x.com")
        pjt(root, "area", "add", "core", "--path-pattern", "src/core/**")
        pjt(root, "area", "add", "ui", "--path-pattern", "src/ui/**")
        pjt(root, "area", "add", "tools")  # 故意不绑目录：演示 unbound
        pjt(root, "area", "set-owner", "core", "--add", "alice")
        pjt(root, "area", "set-owner", "ui", "--add", "bob")
        pjt(root, "area", "set-owner", "core", "--add", "bob")  # core 变公共接口区

        # 本机未提交改动：Bob 在 core 里加了东西，但没提交
        (root / "src" / "core" / "wip.ts").write_text("in progress\n", encoding="utf-8")

        pjt(root, "area", "activity", "--days", "7")
        print()
        pjt(root, "area", "activity", "--days", "7", "--area", "core")
    finally:
        print(f"\nworkdir: {root}  （保留供检查）")
        _ = shutil  # keep import used for readers who extend this script
    return 0


def pjt(root: Path, *args: str) -> None:
    proc = subprocess.run([*PJT, "-C", str(root), *args], capture_output=True, text=True)
    print(proc.stdout or proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"pjt {' '.join(args)} failed")


if __name__ == "__main__":
    raise SystemExit(main())