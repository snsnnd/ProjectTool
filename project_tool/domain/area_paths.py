"""Area ↔ 目录的路径模式（V1-B，可选）。

Area 的 `path_patterns` 把「工作领域」和「工程目录」关联起来，
让 Git Adapter 能把改动的文件映射到候选 Area。

设计约束（docs/09-v1a-design.md §7、docs/09-handover.md §9）：

- **可选**：默认空列表 = 纯语义 Area，行为与 V1-A 完全一致。
  不填的人不需要关心目录绑定。
- **用 glob 列表而不是单个 `path`**：一个 Area 经常对应不连续的多个路径
  （`Distribution → desktop/** + scripts/** + package.json`）。
- **Git Adapter 只推导、不回写**：`changed file → 候选 Area` 只作为信息呈现，
  绝不自动改写 `Task.area_id`。Area 是人工判断的结构信息，
  从文件路径机械推导并回写会把跨 Area 的 commit 错误归类。
- 模式必须是 project-relative；绝对路径 / `..` / `.pjt/**` 一律拒绝
  （和 Artifact locator 同一套安全规则）。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from project_tool.domain.errors import InvalidArgument

RESERVED_DIR = ".pjt"
MAX_PATTERNS = 64
MAX_PATTERN_LENGTH = 512
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_GLOB_CHARS = re.compile(r"[*?\[\]]")


def normalize_path_pattern(pattern: str) -> str:
    """校验并规范化单个 glob 模式。"""
    text = str(pattern or "").strip()
    if not text:
        raise InvalidArgument("area path pattern must not be empty")
    if len(text) > MAX_PATTERN_LENGTH:
        raise InvalidArgument(
            f"area path pattern must be at most {MAX_PATTERN_LENGTH} characters (got {len(text)})"
        )
    if _WINDOWS_DRIVE_RE.match(text) or text.startswith(("\\\\", "//", "/", "~")):
        raise InvalidArgument(
            f"area path pattern must be project-relative, got an absolute path: {pattern!r}"
        )
    normalized = text.replace("\\", "/")
    segments = normalized.split("/")
    # 与 Artifact 的 file locator 同一套规则：拒绝空段 / `.` / `..`。
    # 不拒绝的话 `./.pjt/xxx` 和 `./../xxx` 会绕过下面的检查。
    if any(segment in ("", ".", "..") for segment in segments):
        raise InvalidArgument(
            "area path pattern must not contain empty, '.' or '..' segments: "
            f"{pattern!r}"
        )
    if segments[0].casefold() == RESERVED_DIR:
        raise InvalidArgument(
            f"area path pattern must not point inside {RESERVED_DIR}/: {pattern!r}"
        )
    return normalized


def normalize_path_patterns(values) -> list[str]:
    """规范化整个列表；去重但**保持顺序**（用户写的顺序是有意义的可读性）。"""
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    result: list[str] = []
    for value in values:
        text = normalize_path_pattern(value)
        if text not in result:
            result.append(text)
    if len(result) > MAX_PATTERNS:
        raise InvalidArgument(
            f"an area may have at most {MAX_PATTERNS} path patterns (got {len(result)})"
        )
    return result


def _segments(pattern: str) -> list[str]:
    return [part for part in pattern.split("/") if part]


def match_path(pattern: str, path: str) -> bool:
    """单个 glob 模式是否命中一个 project-relative 文件路径。

    只支持 Git 风格通配：`*`（不跨 `/`）、`**`（跨 `/`）、`?`、`[a-z]`。
    没有实现 `{}` 展开——那不是文件名的一部分，是 shell 的语法。
    """
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    pattern_parts = _segments(pattern)
    path_parts = _segments(normalized)
    if not pattern_parts or not path_parts:
        return False
    return _match_parts(pattern_parts, path_parts)


def _match_parts(pattern: list[str], path: list[str]) -> bool:
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        # `**` 匹配零个或多个 path segment
        if _match_parts(rest, path):
            return True
        return bool(path) and _match_parts(pattern, path[1:])
    if not path:
        return False
    if not _match_segment(head, path[0]):
        return False
    return _match_parts(rest, path[1:])


def _match_segment(pattern: str, text: str) -> bool:
    if pattern == text:
        return True
    if not _GLOB_CHARS.search(pattern):
        return False
    return re.fullmatch(_segment_regex(pattern), text) is not None


def _segment_regex(pattern: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            close = pattern.find("]", index + 1)
            if close == -1:
                out.append(re.escape(char))
            else:
                body = pattern[index + 1 : close]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                index = close
        else:
            out.append(re.escape(char))
        index += 1
    return "".join(out)


def match_any(patterns: list[str], path: str) -> bool:
    return any(match_path(pattern, path) for pattern in patterns or [])


def is_glob(pattern: str) -> bool:
    return bool(_GLOB_CHARS.search(str(pattern or "")))


SCAN_SKIP_DIRS = frozenset({".pjt", ".git", ".venv", "node_modules", "__pycache__"})
MAX_SCAN_FILES = 20000


def scan_files(root, skip: frozenset[str] = SCAN_SKIP_DIRS) -> list[str]:
    """列出 project root 下的相对文件路径（有上限，避免病态目录拖垮 doctor）。"""
    files: list[str] = []
    root_path = root if hasattr(root, "iterdir") else __import__("pathlib").Path(root)
    for path in root_path.rglob("*"):
        if len(files) >= MAX_SCAN_FILES:
            break
        relative = path.relative_to(root_path)
        if relative.parts[0] in skip:
            continue
        if path.is_file():
            files.append(relative.as_posix())
    return files


def find_matching_paths(root, patterns: list[str]) -> dict[str, list[str]]:
    """每个 pattern 命中了哪些文件（用于 doctor 检测「目录改名后 pattern 悬挂」）。"""
    if not patterns:
        return {}
    files = scan_files(root)
    result: dict[str, list[str]] = {}
    for pattern in patterns:
        result[pattern] = [path for path in files if match_path(pattern, path)]
    return result


def describe_match(pattern: str, path: str) -> dict[str, Any]:
    """给 `git status` 用：说明某个 Area 为什么被命中。"""
    normalized = PurePosixPath(str(path or "").replace("\\", "/")).as_posix()
    return {
        "pattern": pattern,
        "glob": is_glob(pattern),
        "exact": normalize_path_pattern(pattern) == normalized,
    }
