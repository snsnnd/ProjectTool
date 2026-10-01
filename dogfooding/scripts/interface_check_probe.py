"""拿一份「真人会怎么写」的接口文档试 `pjt interface check`。

问题不是「模板生成的文件能不能过自己的检查」（那必然过），而是
**一份手写的、真实的接口文档**过不过得了——这才说明模板和检查有没有意义。

不是测试，是手工验证脚本。跑法：
    python3 dogfooding/scripts/interface_check_probe.py
"""

from __future__ import annotations

import os
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

# 一份**手写**的接口文档，按 EFW 的真实形状写：有代码块、有"不保证"条款、
# 有破坏性变更规则、有变更历史表格。
HANDWRITTEN = """---
name: store.updateModel
kind: store_api
status: agreed
area: core
owners: [jichao]
consumers: [ui, dataflow, statemachine]
version: 3
---

# store.updateModel

## 用途

store 批量更新模型。通信页 / 数据流页 / 状态机页改完东西都走这里，
由 store 统一派发变更通知。

## 契约

```ts
updateModel(patch: ModelPatch): void
```

- `patch` 只允许改 `revision` 和 `observables`，其它字段忽略
- 每次调用 revision 必须 +1，否则 store 抛 `RevisionMismatch`
- 同一帧内多次调用按顺序派发，下游收到的事件顺序 == 调用顺序
- **不保证**：不在调用线程同步派发，UI 更新要等下一次 render

## 变更规则

core owner 可以直接改，但必须：

1. 在本文件的「变更历史」加一行
2. 在对应 Area 里建 task 说明改了什么
3. 通知 consumers 里的每个 Area owner

## 兼容策略

加字段、删字段、改默认值都算**破坏性变更**。
破坏性变更必须把 `version` +1 并写明迁移方式。
下游未同步就不能删老字段 —— 老字段至少保留两个 version。

## 变更历史

| 日期 | 改动 | 人 |
|---|---|---|
| 2026-09-20 | 初稿 | 计超 |
| 2026-10-01 | 明确「不保证同步派发」 | 计超 |
"""

# 故意有问题的两份：新人最可能犯的错
DRAFT_WITHOUT_CONSUMERS = """---
name: debug.serial.frame
kind: serial_frame
status: review
area: core
owners: [jichao]
version: 1
---

# debug.serial.frame

## 用途

真机串口回环测试用的帧格式。

## 契约

还没写清楚。

## 变更规则

"""

V1 = """---
name: debug.serial.frame
kind: serial_frame
status: draft
area: core
version: 1
---

# debug.serial.frame

## 用途

真机串口回环测试用的帧格式。

## 契约

## 变更规则

谁有权改、怎么通知下游。

## 兼容策略

什么算破坏性变更。

## 变更历史

| 日期 | 改动 | 人 |
|---|---|---|
"""


def pjt(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run([*PJT, "-C", str(root), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        print(proc.stdout or proc.stderr)
        raise SystemExit(f"pjt {' '.join(args)} failed")
    return proc


def register(root: Path, name: str) -> None:
    """用正规的 register 入口登记，而不是手改 JSON。

    手改 artifact 会被 rev 校验判成 PROJECT_CORRUPTED（§13 读即校验）——
    这正是当初必须提供 `interface register` 的原因。
    """
    pjt(root, "interface", "register", f"docs/interfaces/{name}.md")


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="pjt-iface-probe-"))
    pjt(root, "init", "--name", "IfaceProbe")
    pjt(root, "member", "add", "jichao")
    pjt(root, "area", "add", "core", "--path-pattern", "studio_core/**")

    (root / "docs" / "interfaces").mkdir(parents=True, exist_ok=True)
    cases = {
        "store.updateModel": HANDWRITTEN,
        "debug.serial.frame": V1,
        "half.written": DRAFT_WITHOUT_CONSUMERS,
    }
    for name, body in cases.items():
        (root / "docs" / "interfaces" / f"{name}.md").write_text(body, encoding="utf-8")
        register(root, name)

    print("=" * 78)
    print("一份手写的真实接口文档，能过自己的检查吗？")
    print("=" * 78)
    proc = pjt(root, "interface", "check", check=False)
    print(proc.stdout or proc.stderr)
    print(f"exit={proc.returncode}")
    print(f"\nworkdir: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())