"""领域校验：字符串长度与基本形态约束。

这些约束是领域规则的一部分（docs/03-data-model.md §7），所有写入路径
（CLI / RPC / 未来 Web）共用。
"""

from __future__ import annotations

from project_tool.domain.errors import InvalidArgument

MAX_TITLE = 500
MAX_LABEL = 64
MAX_HANDLE = 64
MAX_TEXT = 200_000


def require_title(value, field: str = "title") -> str:
    text = str(value or "").strip()
    if not text:
        raise InvalidArgument(f"{field} is required")
    if len(text) > MAX_TITLE:
        raise InvalidArgument(f"{field} must be at most {MAX_TITLE} characters (got {len(text)})")
    return text


def optional_title(value, field: str = "title") -> str:
    text = str(value or "").strip()
    if not text:
        raise InvalidArgument(f"{field} must not be empty")
    if len(text) > MAX_TITLE:
        raise InvalidArgument(f"{field} must be at most {MAX_TITLE} characters (got {len(text)})")
    return text


def optional_text(value, field: str, limit: int = MAX_TEXT) -> str:
    text = "" if value is None else str(value)
    if len(text) > limit:
        raise InvalidArgument(f"{field} must be at most {limit} characters (got {len(text)})")
    return text


def require_label(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise InvalidArgument("label must not be empty")
    if len(text) > MAX_LABEL:
        raise InvalidArgument(f"label must be at most {MAX_LABEL} characters (got {len(text)})")
    return text


def check_handle(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise InvalidArgument("handle is required")
    if len(text) > MAX_HANDLE:
        raise InvalidArgument(f"handle must be at most {MAX_HANDLE} characters (got {len(text)})")
    return text
