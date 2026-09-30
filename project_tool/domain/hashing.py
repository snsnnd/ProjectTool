"""canonical JSON 与 rev（对象内容哈希）。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

REV_PREFIX = "sha256:"


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_rev(data: dict[str, Any]) -> str:
    payload = {key: value for key, value in data.items() if key != "rev"}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return REV_PREFIX + digest


def verify_rev(data: dict[str, Any]) -> bool:
    rev = data.get("rev")
    return isinstance(rev, str) and rev == compute_rev(data)
