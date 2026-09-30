"""时间工具：本地时区感知时间、ISO 解析、相对时间（7d/24h/30m）。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")


def now_local() -> datetime:
    return datetime.now().astimezone()


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.astimezone()
    return value


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return ensure_aware(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError(f"invalid datetime: {value!r}") from exc


def parse_time_spec(value: str | datetime | None) -> datetime | None:
    """接受 ISO-8601 或相对时间，如 30m / 24h / 7d / 2w。"""
    if value is None or isinstance(value, datetime):
        return value
    text = value.strip().lower()
    match = _DURATION_RE.match(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 604800,
        }[unit]
        return now_local() - timedelta(seconds=amount * seconds)
    return parse_datetime(text)


def format_time(value: datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%Y-%m-%d %H:%M")
