"""事务恢复：manifest 状态机 + roll-forward。

事务目录结构：

```text
.pjt/transactions/TXN-.../
├── manifest.json   # state: prepared | applied，writes 列表
├── COMMIT          # 提交标记（在 manifest 之后写入）
└── staged/         # 与 .pjt 相对路径镜像的暂存文件
```

恢复规则：

| manifest | COMMIT | 处理 |
|---|---|---|
| 无 / 无效 | 无 | 安全丢弃（未提交） |
| 无 / 无效 | 有 | 报错保留（无法 roll-forward，人工检查） |
| 有效 | 无 | 安全丢弃（未提交） |
| 有效 | 有 | roll-forward（幂等），成功后写 state 并删除事务目录 |

不做 rollback journal：apply 只会把 staged 文件替换到 canonical 路径，
每个写入以 `new_rev` 判定是否已生效，因此重复 apply 是幂等的。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_tool.domain.timeutil import now_local
from project_tool.integrations import filesystem
from project_tool.integrations.filesystem import fsync_dir
from project_tool.storage.project_store import write_state

MANIFEST_NAME = "manifest.json"
COMMIT_NAME = "COMMIT"
STAGED_DIR = "staged"

STATE_PREPARED = "prepared"
STATE_APPLIED = "applied"

# scan 状态
STATUS_UNCOMMITTED = "uncommitted"
STATUS_PREPARED = "prepared"
STATUS_APPLIED = "applied"
STATUS_INVALID = "invalid"


@dataclass
class TransactionScan:
    transaction_id: str
    path: Path
    status: str
    committed: bool
    repairable: bool
    manifest: dict[str, Any] | None = None
    detail: str = ""


@dataclass
class RecoveryResult:
    transaction_id: str
    action: str  # discarded | rolled_forward | error | noop
    detail: str = ""


# --------------------------------------------------------------------- helpers


def write_manifest(txn_dir: Path, manifest: dict[str, Any]) -> None:
    filesystem.write_json(Path(txn_dir) / MANIFEST_NAME, manifest)
    fsync_dir(Path(txn_dir))


def read_manifest(txn_dir: Path) -> dict[str, Any] | None:
    path = Path(txn_dir) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_commit_marker(txn_dir: Path, transaction_id: str) -> None:
    filesystem.atomic_write_text(Path(txn_dir) / COMMIT_NAME, transaction_id + "\n")
    fsync_dir(Path(txn_dir))


def has_commit_marker(txn_dir: Path) -> bool:
    return (Path(txn_dir) / COMMIT_NAME).is_file()


def staged_path(txn_dir: Path, target: str) -> Path:
    return Path(txn_dir) / STAGED_DIR / Path(target)


# ----------------------------------------------------------------------- scan


def scan_transactions(paths) -> list[TransactionScan]:
    base = paths.transactions
    if not base.is_dir():
        return []
    scans: list[TransactionScan] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        committed = has_commit_marker(entry)
        manifest_path = entry / MANIFEST_NAME
        manifest = read_manifest(entry)
        if manifest is None:
            if manifest_path.is_file():
                scans.append(
                    TransactionScan(
                        entry.name,
                        entry,
                        STATUS_INVALID,
                        committed=committed,
                        repairable=not committed,
                        detail=(
                            "invalid manifest with COMMIT marker; manual inspection required"
                            if committed
                            else "invalid manifest without commit; safe to discard"
                        ),
                    )
                )
            elif committed:
                scans.append(
                    TransactionScan(
                        entry.name,
                        entry,
                        STATUS_INVALID,
                        committed=True,
                        repairable=False,
                        detail="COMMIT marker without manifest; manual inspection required",
                    )
                )
            else:
                scans.append(
                    TransactionScan(
                        entry.name,
                        entry,
                        STATUS_UNCOMMITTED,
                        committed=False,
                        repairable=True,
                        detail="incomplete staging without manifest; safe to discard",
                    )
                )
            continue
        state = str(manifest.get("state") or "")
        if state == STATE_APPLIED:
            scans.append(
                TransactionScan(
                    entry.name,
                    entry,
                    STATUS_APPLIED,
                    committed=committed,
                    repairable=True,
                    manifest=manifest,
                    detail="applied but transaction directory not cleaned",
                )
            )
        elif committed:
            scans.append(
                TransactionScan(
                    entry.name,
                    entry,
                    STATUS_PREPARED,
                    committed=True,
                    repairable=True,
                    manifest=manifest,
                    detail="committed but not fully applied; roll-forward available",
                )
            )
        else:
            scans.append(
                TransactionScan(
                    entry.name,
                    entry,
                    STATUS_UNCOMMITTED,
                    committed=False,
                    repairable=True,
                    manifest=manifest,
                    detail="prepared but not committed; safe to discard",
                )
            )
    return scans


# ---------------------------------------------------------------------- apply


def _read_rev(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rev = data.get("rev") if isinstance(data, dict) else None
    return rev if isinstance(rev, str) and rev else None


def apply_committed_writes(paths, txn_dir: Path, manifest: dict[str, Any]) -> str | None:
    """把已提交事务的 staged 文件 roll-forward 到 canonical 路径。

    返回 None 表示全部应用（或此前已应用）；返回字符串表示冲突原因。
    """
    for write in manifest.get("writes") or []:
        target = write.get("target")
        if not isinstance(target, str) or not target:
            return "manifest write entry missing target"
        final = paths.pjt / Path(target)
        staged = staged_path(Path(txn_dir), target)
        new_rev = write.get("new_rev")
        base_rev = write.get("base_rev")
        current_rev = _read_rev(final)

        if current_rev is not None and new_rev is not None and current_rev == new_rev:
            continue  # 已应用
        if new_rev is None and current_rev is None and final.is_file():
            continue  # 无 rev 的写入（事件）：目标存在即已应用
        if current_rev != (base_rev or None):
            return (
                f"{target}: rev mismatch during recovery "
                f"(expected base {base_rev!r}, found {current_rev!r})"
            )
        if not staged.is_file():
            return f"{target}: staged file missing and target not at new_rev"
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, final)
        fsync_dir(final.parent)
    return None


def recover_transaction(paths, scan: TransactionScan) -> RecoveryResult:
    txn_id = scan.transaction_id
    if scan.status == STATUS_INVALID:
        if scan.committed:
            return RecoveryResult(txn_id, "error", scan.detail)
        shutil.rmtree(scan.path, ignore_errors=True)
        return RecoveryResult(txn_id, "discarded", scan.detail or "invalid staging discarded")
    if scan.status == STATUS_UNCOMMITTED:
        shutil.rmtree(scan.path, ignore_errors=True)
        return RecoveryResult(txn_id, "discarded", scan.detail or "uncommitted staging discarded")

    manifest = scan.manifest or {}
    try:
        conflict = apply_committed_writes(paths, scan.path, manifest)
    except OSError as exc:
        return RecoveryResult(txn_id, "error", f"apply failed: {exc}")
    if conflict:
        return RecoveryResult(txn_id, "error", conflict)

    manifest["state"] = STATE_APPLIED
    manifest["applied_at"] = now_local().isoformat()
    try:
        write_manifest(scan.path, manifest)
    except Exception:
        pass  # best effort；下一次恢复会重试
    try:
        write_state(paths, last_transaction_id=txn_id)
    except Exception as exc:
        return RecoveryResult(
            txn_id,
            "rolled_forward",
            f"objects applied but state update failed ({exc}); re-run recovery",
        )
    shutil.rmtree(scan.path, ignore_errors=True)
    return RecoveryResult(txn_id, "rolled_forward", "committed transaction rolled forward")


def recover_all(paths) -> list[RecoveryResult]:
    return [recover_transaction(paths, scan) for scan in scan_transactions(paths)]
