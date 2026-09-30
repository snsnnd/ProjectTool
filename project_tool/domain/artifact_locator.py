"""Artifact locator 校验与验证（V1-A）。

核心安全规则（docs/09-v1a-design.md §3.3）：

1. `file` kind 必须是 **project-relative POSIX 路径**；禁止绝对路径、Windows 盘符、
   UNC、任何 `..` segment、`.pjt/**`。
2. 其它 kind 也**禁止机器本地绝对路径**（AGENTS.md 铁律：绝对路径只进 `.pjt/local/`）。
3. `url` 只校验格式，**绝不发起网络请求**。
4. `git_commit` / `git_branch` 只校验格式；Git Adapter 未启用（V1-B）。

canonical 形态统一为 `relative POSIX-style`（分隔符 `/`）。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from project_tool.domain.enums import ArtifactKind
from project_tool.domain.errors import InvalidArgument

WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
HEX_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")
GIT_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")
RESERVED_DIR = ".pjt"
URL_SCHEMES = ("http", "https")

# 控制字符（换行/制表/ESC…）在任何 kind 的 locator 里都是非法的：
# 它们会破坏 CLI 表格输出、事件 JSON 和事件 payload 的可读性。
# 普通空格则不是问题——真实工程里 `docs/Design Notes.md`、
# `assets/Test Result 01.csv` 是完全正常的文件名。
CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

# 领域层只能做格式校验（没有 I/O）。真正的解析由 GitAdapter 在 service 层完成。
GIT_ADAPTER_NOTE = "locator format ok; resolved against the git repository by the git adapter"

# locator 完全不透明、不做形态校验的 kind（只守住路径安全底线）。
OPAQUE_KINDS = frozenset(
    {
        ArtifactKind.RELEASE,
        ArtifactKind.BUILD,
        ArtifactKind.REPORT,
        ArtifactKind.DATASET,
        ArtifactKind.MODEL,
        ArtifactKind.DOCUMENT,
        ArtifactKind.DESIGN,
        ArtifactKind.HARDWARE,
        ArtifactKind.IMAGE,
        ArtifactKind.OTHER,
    }
)


def normalize_file_locator(locator: str) -> str:
    """把 `file` locator 规范化成 project-relative POSIX 路径，非法则抛错。"""
    text = str(locator or "").strip()
    if not text:
        raise InvalidArgument("file artifact requires a project-relative path")
    if WINDOWS_DRIVE_RE.match(text) or text.startswith(("\\\\", "//")):
        raise InvalidArgument(
            f"file artifact locator must be project-relative, got a machine-local path: {locator!r}; "
            "map absolute paths in .pjt/local/local.toml instead"
        )
    if text.startswith(("/", "~")):
        raise InvalidArgument(
            f"file artifact locator must be project-relative, got an absolute path: {locator!r}"
        )
    normalized = text.replace("\\", "/")
    segments = normalized.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise InvalidArgument(
            "file artifact locator must be a clean relative path "
            f"(no empty, '.' or '..' segments): {locator!r}"
        )
    if segments[0].casefold() == RESERVED_DIR:
        raise InvalidArgument(
            f"file artifact locator must not point inside {RESERVED_DIR}/: {locator!r}; "
            "Project Tool internal state is not an engineering artifact"
        )
    return "/".join(segments)


def check_locator(kind: ArtifactKind, locator: str) -> str:
    """校验并返回规范化后的 locator；不合法抛 `INVALID_ARGUMENT`。"""
    text = str(locator or "").strip()
    if not text:
        raise InvalidArgument("artifact locator must not be empty")
    if CONTROL_CHARS_RE.search(text):
        raise InvalidArgument(
            f"artifact locator must not contain control characters (newline, tab, …): {locator!r}"
        )

    if kind in OPAQUE_KINDS:
        # 设计稿 / 硬件 / 影像等 kind 的 locator 是不透明引用（"PCB rev C" 也合法），
        # 只守住「不能是机器本地绝对路径 / 不能逃出 project root」这两条底线。
        return _check_opaque(text)

    if kind == ArtifactKind.URL:
        # RFC 3986 不允许 URL 里出现裸空格（必须百分号编码）。urlsplit 很宽松，
        # 不会替我们抓这个错；存一条坏 URL 只会等到下游消费者才炸。
        if any(char.isspace() for char in text):
            raise InvalidArgument(
                f"url artifact locator must not contain whitespace (encode as %20): {locator!r}"
            )
        _check_url(text)
        return text

    if kind == ArtifactKind.FILE:
        # file 允许普通空格：真实工程文件名含空格非常常见，不该由工具规定禁止。
        return normalize_file_locator(text)

    # git_commit / git_branch：git 标识符不允许任何空白。
    if any(char.isspace() for char in text):
        raise InvalidArgument(f"{kind.value} artifact locator must not contain whitespace: {locator!r}")

    if kind == ArtifactKind.GIT_COMMIT:
        if not HEX_RE.match(text):
            raise InvalidArgument(
                f"git_commit artifact locator must be 4-40 hex characters, got {locator!r}"
            )
    else:  # git_branch
        valid = bool(GIT_BRANCH_RE.match(text)) and ".." not in text
        valid = valid and not text.startswith("/") and not text.endswith("/")
        if not valid:
            raise InvalidArgument(
                f"git_branch artifact locator is not a valid ref name: {locator!r}"
            )
    return text


def _check_opaque(text: str) -> str:
    if WINDOWS_DRIVE_RE.match(text) or text.startswith(("\\\\", "//", "/", "~")):
        raise InvalidArgument(
            f"artifact locator must not be a machine-local absolute path: {text!r}; "
            "map absolute paths in .pjt/local/local.toml instead"
        )
    if any(segment == ".." for segment in text.replace("\\", "/").split("/")):
        raise InvalidArgument(f"artifact locator must not escape the project root: {text!r}")
    return text


def _check_url(locator: str) -> None:
    parts = urlsplit(locator)
    if parts.scheme.lower() not in URL_SCHEMES or not parts.netloc:
        raise InvalidArgument(
            f"url artifact locator must be an http(s) URL with a host, got {locator!r}"
        )


def verify_locator(kind: ArtifactKind, locator: str, root) -> dict[str, Any]:
    """只读验证：文件存在性 / URL 格式 / Git 形态。**不产生事件，不修改任何文件。**"""
    if kind == ArtifactKind.FILE:
        relative = normalize_file_locator(locator)
        target = root / relative
        exists = target.is_file()
        return {
            "status": "ok" if exists else "missing",
            "exists": exists,
            "path": relative,
            "detail": "" if exists else f"no such file in project root: {relative}",
        }

    if kind == ArtifactKind.URL:
        _check_url(locator)
        return {
            "status": "ok",
            "exists": None,
            "path": None,
            "detail": "url format ok; no network request is made (V1-A)",
        }

    if kind in (ArtifactKind.GIT_COMMIT, ArtifactKind.GIT_BRANCH):
        check_locator(kind, locator)
        return {
            "status": "ok",
            "exists": None,
            "path": None,
            "detail": GIT_ADAPTER_NOTE,
        }

    return {
        "status": "skipped",
        "exists": None,
        "path": None,
        "detail": f"{kind.value} locators are opaque references in V1-A; nothing to verify",
    }
