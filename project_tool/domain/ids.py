"""ID 规范：类型前缀 + ULID；短 ID 解析辅助。"""

from __future__ import annotations

import os
import re
import threading
import time

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PREFIX_BY_TYPE: dict[str, str] = {
    "project": "PRJ",
    "goal": "GOL",
    "milestone": "MLS",
    "area": "ARA",
    "task": "TSK",
    "member": "MBR",
    "update": "UPD",
    "decision": "DEC",
    "artifact": "ART",
    "link": "LNK",
    "event": "EVT",
    "transaction": "TXN",
}

TYPE_BY_PREFIX = {prefix: obj_type for obj_type, prefix in PREFIX_BY_TYPE.items()}

COLLECTION_BY_TYPE: dict[str, str] = {
    "goal": "goals",
    "milestone": "milestones",
    "area": "areas",
    "task": "tasks",
    "member": "members",
    "update": "updates",
    "decision": "decisions",
    "artifact": "artifacts",
    "link": "links",
}

_ID_RE = re.compile(r"^([A-Z]{3})-([0-9A-HJKMNP-TV-Z]{2,26})$")

_lock = threading.Lock()
_last_ms = 0
_last_rand = 0


def _encode(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def ulid(now_ms: int | None = None) -> str:
    """Crockford Base32 ULID：10 字符时间戳 + 16 字符随机数，同毫秒单调递增。"""
    global _last_ms, _last_rand
    ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with _lock:
        if ms <= _last_ms:
            ms = _last_ms
            _last_rand += 1
            if _last_rand >= (1 << 80):
                ms += 1
                _last_rand = int.from_bytes(os.urandom(10), "big")
        else:
            _last_ms = ms
            _last_rand = int.from_bytes(os.urandom(10), "big")
        rand = _last_rand
    return _encode(ms, 10) + _encode(rand, 16)


def new_id(obj_type: str) -> str:
    return f"{PREFIX_BY_TYPE[obj_type]}-{ulid()}"


def new_device_id() -> str:
    return "DEV-" + os.urandom(4).hex().upper()


def split_id(value: str) -> tuple[str, str] | None:
    """返回 (prefix, ulid_part)；不是合法 ID 形式则 None。"""
    match = _ID_RE.match((value or "").strip().upper())
    if not match:
        return None
    return match.group(1), match.group(2)


def prefix_of(value: str) -> str | None:
    parsed = split_id(value)
    return parsed[0] if parsed else None


def is_full_id(value: str) -> bool:
    parsed = split_id(value)
    return parsed is not None and len(parsed[1]) == 26


def short_id(object_id: str, keep: int = 8) -> str:
    parsed = split_id(object_id)
    if not parsed:
        return object_id
    return f"{parsed[0]}-{parsed[1][:keep]}"
