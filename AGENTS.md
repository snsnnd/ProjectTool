# AGENTS.md — Project Tool 交接

> 给下一位接手的 agent / 开发者。先读本文件，再按需读 `docs/09-handover.md`（完整交接）、
> `docs/02`（架构）、`docs/03`（数据模型）、`docs/04`（存储/恢复）。
> 仓库：`https://github.com/snsnnd/ProjectTool`

## 0. 一句话

Local-first 的工程项目状态系统：`.pjt/` 与 `.git/` 并列，
`objects/`（现在是什么）+ `events/`（为什么变）是 canonical 数据；
CLI / 未来 Web / SDK 都只经过同一个 Application Service。

## 1. 当前状态

- 版本 `0.1.0`，`SCHEMA_VERSION = "1.0"`。
- 提交线：`6a19628` V0 → `0fcc628` V0.1 硬化 → `a7ac64e` EFW dogfooding 报告。
- 质量门槛：`uv run ruff check .`、`uv run mypy project_tool`、`uv run pytest`（120 passed）；CI 覆盖 Ubuntu + Windows。
- 真实使用：EFW Studio（`framework@tmp/new` 的 `new/efw`）已完成一轮 dogfooding，零源码污染；
  数据保留在 `new/efw/.pjt`，结论见 `dogfooding/report.md`。
- 未实现（V1+）：Artifact / Git Adapter / Search / SQLite 索引 / Web / Remote / Sync / KC。

## 2. 最重要八条（违反即事故）

1. `.pjt` 是唯一数据源；`project.json + objects/ + events/` 不可被缓存替代。
2. Event append-only；禁止任何 update/delete 事件的 API 或脚本。
3. 事务必须走 `staged/ + manifest + COMMIT` 协议；`transactions/` 里的目录只许 `pjt doctor --repair` 处理。
4. WriteLock 活 PID 永不偷锁；释放只删自己的 `lock_id`。
5. `computed blocked` / milestone progress 只推导，绝不写回对象。
6. CLI 不 import `storage`/`filesystem`；Core 不依赖 Web。
7. `.pjt/local/`、`.pjt/transactions/` 不进 Git；绝对路径只进 `local.toml`。
8. 不接管 Git、不做组织账号（KC 职责）；改动必须带 revision 校验。

## 3. 常用命令

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy project_tool
uv run pjt --help

# 本地体验（用临时目录，不要动真实项目）
cd /tmp && mkdir -p demo && cd demo
uv run --project /path/to/ProjectTool pjt init --name Demo
```

## 4. 加一个 method（固定流程）

```text
domain 模型/校验 → application/services/<域>.py → registry.py 注册
→ cli/<域>.py（只 execute(method, params)）→ tests → 文档（05/03/08）
→ ruff + mypy + pytest
```

## 5. 禁区

- `new/efw`（真实 dogfooding 项目）与 framework 仓库：**禁止任何 EFW 源码修改，
  禁止任何 git 写操作**；只允许 `new/efw/.pjt/**` 的 ProjectTool 数据。
- 破坏性实验（rev 篡改 / 锁 / 事务恢复 / event 校验）只能对 `.pjt` 的临时副本执行
  （`dogfooding/scripts/destructive_checks.py` 是范例）。
- 不要删除或手工修改 `.pjt/transactions/`、`.pjt/events/`。

## 6. 验证习惯

- 任何改动：`ruff check .` + `mypy project_tool` + `pytest` 全绿再提交。
- 测试只用 `tmp_path` + monkeypatch，禁止 sleep/网络/随机依赖；失败注入参考
  `tests/test_transaction_recovery.py`。
- 公共行为变化必须同步 `docs/05`（接口）、`docs/03`（模型/校验）、`docs/08`（事件 payload）。
- 下一阶段目标与第一批工作见 `docs/09-handover.md` §9（V1：Artifact → Git Adapter → Search/Index → Web）。
