"""Git 只读适配器（V1-B）。

**硬约束：只读。** 本模块只调用不改变仓库状态的 git 子命令，且一律加
`--no-optional-locks`，避免 `git status` 去抢 `.git/index` 的锁——
一个「记录项目状态」的工具不该在别人的仓库里留下 index.lock。

命令清单（全部只读）：

```text
rev-parse    定位 git root / 判断是否在仓库内
status       工作区改动（--porcelain，机器可读）
log          提交历史（trailer / 路径过滤）
ls-files     index 里被跟踪的文件（判断派生缓存有没有被提交；只读 index）
```

**不做**：clone / fetch / add / commit / checkout / merge / reset / clean。
将来要写能力必须是另一个模块（`integrations/git_write.py`），不要往这里加。

两个必须处理的真实情况（EFW 已验证）：

1. **project root != git root**：`.pjt` 可以放在仓库的子目录里
   （`framework/` 仓库里的 `new/efw/`）。所以路径一律相对 **git root** 解析，
   绝不能假设两者相等。
2. **git 不存在 / 不在仓库内**：不抛异常，返回明确的 unavailable 状态，
   让上层把它呈现成「不可用」而不是「出错」。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 仓库状态码（porcelain v1 XY）
STATUS_LABELS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "U": "unmerged",
    "?": "untracked",
    "!": "ignored",
}

_TRAILER_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9_-]*:\s*(\S.*?)\s*$")
READ_ONLY_FLAGS = ("--no-optional-locks", "-c", "core.quotepath=false")
DEFAULT_TIMEOUT = 20.0

# 唯一允许的 git 子命令。`GitRepo.run` 在运行时强制检查这个白名单——
# 只靠 code review 盯着是不够的，将来有人顺手加一行 `repo.run("add", ...)` 必须失败。
READ_ONLY_SUBCOMMANDS = frozenset({"rev-parse", "status", "log", "show", "ls-files"})

# 会改变仓库状态的动词（写进文档 + 测试断言用；运行时不检查，靠白名单保证）
WRITE_SUBCOMMANDS = frozenset(
    {
        "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "clone",
        "commit", "fetch", "gc", "init", "merge", "mv", "pull", "push", "rebase",
        "reset", "restore", "revert", "stash", "submodule", "tag", "worktree",
    }
)


class GitUnavailable(Exception):
    """git 不可用 / 不在仓库内。调用方应把它当状态而不是错误。"""


@dataclass
class GitStatusEntry:
    path: str
    index_status: str
    worktree_status: str
    old_path: str | None = None

    @property
    def status(self) -> str:
        code = (self.index_status + self.worktree_status).strip() or "?"
        if code == "??":
            return "untracked"
        if code == "!!":
            return "ignored"
        if self.index_status in STATUS_LABELS and self.index_status == "U":
            return "unmerged"
        if self.worktree_status and self.worktree_status not in (" ", ""):
            return STATUS_LABELS.get(self.worktree_status, self.worktree_status)
        return STATUS_LABELS.get(self.index_status, self.index_status or "?")

    @property
    def is_change(self) -> bool:
        return self.status in {"modified", "added", "deleted", "renamed", "copied", "unmerged"}


@dataclass
class GitRepo:
    work_tree: Path
    git_dir: Path
    binary: str
    _runner: Any = field(default=None, repr=False)

    # ------------------------------------------------------------------ 底层

    def run(self, *args: str, timeout: float = DEFAULT_TIMEOUT) -> str:
        """跑一个只读 git 命令。失败抛 GitUnavailable（含 stderr 摘要）。"""
        if not args:
            raise ValueError("git subcommand is required")
        subcommand = args[0]
        if subcommand not in READ_ONLY_SUBCOMMANDS:
            # 运行时不变量：这个适配器只允许只读子命令
            raise ValueError(
                f"git.{subcommand!r} is not allowed: integrations/git.py is read-only "
                f"(allowed: {', '.join(sorted(READ_ONLY_SUBCOMMANDS))})"
            )
        proc = self._runner or subprocess.run
        try:
            completed = proc(
                [
                    self.binary,
                    *READ_ONLY_FLAGS,
                    "-C",
                    str(self.work_tree),
                    *args,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitUnavailable(f"git {args[0] if args else ''} failed: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise GitUnavailable(detail[0] if detail else f"git exited {completed.returncode}")
        return completed.stdout

    # ------------------------------------------------------------------ 查询

    def status(self, subdir: str | None = None) -> list[GitStatusEntry]:
        """工作区改动。`subdir` 限定在某个相对 git root 的子目录内。"""
        args = ["status", "--porcelain=v1", "--untracked-files=all", "-z"]
        if subdir:
            args += ["--", subdir]
        entries: list[GitStatusEntry] = []
        # -z 输出以 NUL 分隔，重命名/复制会额外多一个 path 字段（old -> new）
        records = self.run(*args).split("\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if len(record) < 3:
                continue
            code, path = record[:2], record[3:]
            old_path = None
            if code[0] in ("R", "C") and index < len(records):
                old_path, path = path, records[index]
                index += 1
            entries.append(
                GitStatusEntry(
                    path=path,
                    index_status=code[0],
                    worktree_status=code[1],
                    old_path=old_path,
                )
            )
        return entries

    def log(
        self,
        limit: int = 50,
        path_filter: str | None = None,
        trailer: str | None = None,
    ) -> list[dict[str, Any]]:
        """提交历史（只读）。`trailer` 用 `--grep` 过滤 message。"""
        fmt = "--format=%H%x1f%an%x1f%aI%x1f%s"
        args = ["log", f"--max-count={max(1, int(limit))}", "--no-decorate", fmt]
        if trailer:
            args += [f"--grep={trailer}"]
        if path_filter:
            args += ["--", path_filter]
        commits: list[dict[str, Any]] = []
        for line in self.run(*args).splitlines():
            if not line.strip():
                continue
            parts = line.split("\x1f")
            if len(parts) < 4:
                continue
            commits.append(
                {
                    "sha": parts[0],
                    "short_sha": parts[0][:8],
                    "author": parts[1],
                    "authored_at": parts[2],
                    "subject": parts[3],
                }
            )
        return commits

    def commit_body(self, sha: str) -> dict[str, Any]:
        """取单个 commit 的完整 message 并解析 trailer。"""
        text = self.run("show", "-s", "--format=%H%x1f%an%x1f%aI%x1f%B", sha)
        head, _, body = text.partition("\n")
        parts = head.split("\x1f")
        if len(parts) < 4:
            raise GitUnavailable(f"cannot parse commit {sha!r}")
        return {
            "sha": parts[0],
            "short_sha": parts[0][:8],
            "author": parts[1],
            "authored_at": parts[2],
            "subject": parts[3].strip(),
            "body": body,
            "trailers": parse_trailers(body),
        }

    def resolve_commit(self, ref: str) -> str:
        return self.run("rev-parse", "--verify", f"{ref}^{{commit}}").strip()

    def relpath(self, path: Path) -> str:
        """绝对路径 -> 相对 git root 的 POSIX 路径。"""
        try:
            return path.resolve().relative_to(self.work_tree).as_posix()
        except ValueError:
            return path.resolve().as_posix()


def parse_trailers(body: str) -> dict[str, list[str]]:
    """从 commit message 尾部解析 `Key: value` trailer（Git 的标准 trailer 语法）。"""
    trailers: dict[str, list[str]] = {}
    lines = (body or "").splitlines()
    # 只看最后一段「连续的 Key: value 块」，避免把正文里的冒号行误判为 trailer
    index = len(lines) - 1
    while index >= 0 and not lines[index].strip():
        index -= 1
    while index >= 0:
        match = _TRAILER_RE.match(lines[index])
        if not match:
            break
        key, _, value = lines[index].partition(":")
        trailers.setdefault(key.strip(), []).append(match.group(1))
        index -= 1
        while index >= 0 and not lines[index].strip():
            index -= 1
    return trailers


def trailer_values(trailers: dict[str, list[str]], key: str) -> list[str]:
    wanted = key.strip().casefold()
    values: list[str] = []
    for name, items in trailers.items():
        if name.casefold() == wanted:
            values.extend(items)
    return values


def detect(root: str | Path) -> GitRepo:
    """从 `root` 向上找 `.git`，返回只读 repo 句柄。找不到 / git 不存在则抛 GitUnavailable。"""
    binary = shutil.which("git")
    if not binary:
        raise GitUnavailable("git executable not found on PATH")
    start = Path(root).resolve()
    if start.is_file():
        start = start.parent

    def run(cwd: Path, *args: str) -> str:
        try:
            completed = subprocess.run(
                [binary, *READ_ONLY_FLAGS, "-C", str(cwd), *args],
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitUnavailable(f"git {args[0]} failed: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip().splitlines()
            raise GitUnavailable(detail[0] if detail else f"git exited {completed.returncode}")
        return completed.stdout

    # 向上逐级试 rev-parse（不假设 project root == git root）
    for candidate in (start, *start.parents):
        try:
            work_tree = run(candidate, "rev-parse", "--show-toplevel").strip()
        except GitUnavailable:
            continue
        if not work_tree:
            continue
        git_dir = run(candidate, "rev-parse", "--absolute-git-dir").strip()
        return GitRepo(work_tree=Path(work_tree), git_dir=Path(git_dir), binary=binary)
    raise GitUnavailable(f"no git repository found at or above {start}")


def tracked_files(root: str | Path, *paths: str) -> set[str]:
    """index 里被跟踪的文件（相对 git root 的 posix 路径）。

    用途：判断 `.pjt` 的**派生缓存**是不是被提交进了 Git。被提交的派生文件
    在多人合并时每次都冲突——V1-C 探针实测 9 个真实场景里 8 个因此冲突，
    排除后 8/9 干净，剩下的那个本来就该冲突。

    只读 `.git/index`，不写任何东西；不在仓库内 / git 不可用时返回空集
    （不可用是状态，不是错误——非 Git 项目同样要能跑 doctor）。
    """
    if not paths:
        return set()
    try:
        repo = detect(root)
    except GitUnavailable:
        return set()
    try:
        raw = repo.run("ls-files", "-z", "--", *paths)
    except GitUnavailable:
        return set()
    return {entry for entry in raw.split("\0") if entry}


def availability(root: str | Path) -> dict[str, Any]:
    """给上层用的探测结果——不可用是状态，不是异常。"""
    try:
        repo = detect(root)
    except GitUnavailable as exc:
        return {"available": False, "reason": str(exc), "work_tree": None, "git_dir": None}
    return {
        "available": True,
        "reason": None,
        "work_tree": str(repo.work_tree),
        "git_dir": str(repo.git_dir),
    }
