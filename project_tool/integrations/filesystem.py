"""原子文件写入与 JSON 读写。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from project_tool.domain.errors import ProjectIOError


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        _silent_unlink(tmp_name)
        raise ProjectIOError(f"cannot write {path}: {exc}") from exc


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=True) + "\n"
    atomic_write_text(path, text)


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectIOError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectIOError(f"invalid JSON in {path}: {exc}") from exc


def _silent_unlink(path: str | Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
