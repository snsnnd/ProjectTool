# Project Tool — 交接文档（V0.1 → V1）

> 给下一位接手的开发者 / agent。先读本文件，再按需读 `docs/02`–`docs/08`。
> 仓库：`https://github.com/snsnnd/ProjectTool`（origin fetch 为 HTTPS，push 走 SSH）。

## 0. 一分钟了解

Project Tool 是 Local-first 的工程项目状态系统：`.pjt/` 与 `.git/` 并列，
`objects/`（现在是什么）+ `events/`（为什么变）是 canonical 数据，
CLI（`pjt`）与未来 Web/SDK 都只经过同一个 Application Service。

```text
Git tracks code. Project Tool tracks the project.
```

## 1. 当前位置

| 项 | 值 |
|---|---|
| 版本 | `0.1.0`，`SCHEMA_VERSION = "1.0"`（`project_tool/version.py`） |
| 关键提交 | `6a19628` V0 核心+CLI → `0fcc628` V0.1 硬化 → `a7ac64e` EFW dogfooding 报告 |
| 质量门槛 | `ruff check .` 0 error · `mypy project_tool` 0 error · `pytest` **120 passed** · CI（Ubuntu+Windows, Py3.12） |
| 真实验证 | 已在 EFW Studio（`framework@tmp/new`，`new/efw`）完成一轮 dogfooding：**零源码污染**，数据保留在 `new/efw/.pjt`，报告见 `dogfooding/report.md` |
| Service API | 显式 registry，**83 个 method**，`system.capabilities` 可发现 |
| 未实现 | Artifact / Git Adapter / Search / SQLite 索引 / Web / Remote / Sync / KC（按计划 V1+） |

## 2. 新接手者 15 分钟上手

```bash
cd /path/to/ProjectTool
uv sync
uv run pytest                          # 120 passed
uv run ruff check . && uv run mypy project_tool

# 在临时目录体验完整流程（不要污染别人的真实项目）
mkdir -p /tmp/pjt-demo && cd /tmp/pjt-demo
P="uv run --project /path/to/ProjectTool pjt"
$P init --name "Demo"
$P member add alice --name Alice
$P goal add "Ship v1"
$P milestone add "Core" --goal GOL-xxx --status active
$P task add "Task A" --owner alice --milestone MLS-xxx
$P status && $P doctor && $P graph tasks
```

## 3. 仓库结构

```text
ProjectTool/
├── project_tool/
│   ├── domain/          # 模型 + 校验 + 错误码（零 I/O）
│   ├── storage/         # 唯一接触 .pjt 的层（transaction/recovery/lock/…）
│   ├── application/     # service（组合）+ registry + context + services/* + doctor
│   ├── graph/           # 依赖/层级/进度推导
│   ├── integrations/    # filesystem（原子写、fsync）
│   └── cli/             # Typer：main/common/render + 各域模块
├── tests/               # 15 个测试文件，120 cases
├── docs/                # 01–09（09 即本文件）
├── dogfooding/          # EFW 真实项目验证报告 + 证据 + 可复现脚本
├── pyproject.toml       # uv；dev 依赖 pytest/ruff/mypy；ruff+mypy 配置
└── .github/workflows/   # CI
```

`project_tool/application/services/` 是业务逻辑所在：
`project/system/goal/milestone/task/member/update/decision/link/log/graph` 各一个模块，
共享 `ServiceContext`（`application/context.py`）。

## 4. 架构心智模型

请求路径（永远只有这一条）：

```text
CLI / Web / SDK
  → ProjectService（application/service.py，只做 dispatch）
  → MethodSpec registry（application/registry.py）
  → 领域服务 application/services/*.py
  → ServiceContext（解析引用、领域校验、事务）
  → storage（WriteLock → Transaction → staging/manifest/COMMIT → apply）
  → .pjt
```

**新增一个 method 的固定步骤**：

1. 模型字段 → `domain/`；校验规则 → `domain/validation.py` 或 ServiceContext；
2. 业务逻辑 → `application/services/<域>.py` 加方法；
3. 在 `application/registry.py` 的显式列表注册（`name/handler/mutating/category/description`）；
4. 需要 CLI → `cli/<域>.py` 加命令，只调 `execute(ctx, "<method>", params)`；
5. 测试 → `tests/`（正常路径 + 边界 + 冲突）；
6. 文档 → `docs/05-interfaces.md` 方法表 + 行为变化对应文档；
7. `uv run ruff check . && uv run mypy project_tool && uv run pytest`。

## 5. 不可破坏的约定（改代码前必读）

1. `.pjt` 是唯一数据源（`project.json + objects/ + events/`）；服务器永远不是前提。
2. 一对象一文件；ULID 主键 + 短 ID 解析；`rev = sha256(canonical json)`。
3. Event **append-only**；EventStore 不提供任何 update/delete API；纠正历史 = 新事件。
4. 事务必须经过 `staged/ + manifest + COMMIT` 协议；恢复只 roll-forward，幂等；
   **不要**把 `transactions/` 当垃圾直接删（先 `doctor`）。
5. WriteLock：活 PID 永不偷锁；释放只删自己的 `lock_id`。
6. `computed blocked` 只读推导，**绝不改写** `Task.status`；进度不落库。
7. CLI **不得** import `storage` / `filesystem`；Core 不得依赖 Web。
8. `.pjt/local/`、`.pjt/transactions/` 永远不进 Git；绝对路径只进 `local.toml`。
9. Project Tool 不接管 Git、不做组织账号（KC 的事）。
10. 所有修改带 revision/base_rev 校验，不允许静默覆盖。
11. 引用校验：新引用不得指向 deleted 对象、inactive member、closed/cancelled milestone。
12. 领域校验统一放 ServiceContext，CLI/未来 Web 行为必须一致。

## 6. 协议速查

### 6.1 事务与恢复

```text
staged → manifest(prepared)+COMMIT → apply → manifest(applied) → state → 清理

scan 状态:  uncommitted / prepared / applied / invalid
recover 动作: discarded / rolled_forward / error
repair 入口:  pjt doctor --repair  ==  project.recover（先拿锁，再恢复）
```

判定规则：无 COMMIT → 安全丢弃；有 COMMIT → roll-forward；manifest 损坏且有 COMMIT → 保留现场报 error。

### 6.2 错误码 / 退出码

```text
3 INVALID_ARGUMENT / ALREADY_EXISTS / DEPENDENCY_CYCLE / HIERARCHY_CYCLE / BROKEN_LINK
4 NOT_FOUND
5 CONFLICT / REVISION_CONFLICT
1 IO_ERROR / INTERNAL       9 PROJECT_CORRUPTED / SCHEMA_UNSUPPORTED
```

### 6.3 Actor / 短 ID

- Actor：`--as` > `PJT_ACTOR` > `.pjt/local/local.toml` > 第一个 active member > null。
- 短 ID：完整 ID 或前缀片段，项目内无歧义即可；歧义 → `INVALID_ARGUMENT`（给候选）。

### 6.4 派生数据

`refs/labels.json`、`state/state.json`、未来的 SQLite 全部可删可重建；任何逻辑不得以它们为准。
`doctor` 会校验 events 的 `base_rev → new_rev` 链与对象当前 rev 一致。

## 7. 测试地图

| 文件 | 覆盖 |
|---|---|
| `test_ids.py` / `test_hashing.py` | ULID、短 ID、canonical/rev |
| `test_storage.py` | init 布局、^C、短 ID 歧义 |
| `test_service_flow.py` | 全流程、状态机、软删除、并发 expected_rev |
| `test_dependency.py` | 依赖环、computed blocked、加权进度 |
| `test_project_revision.py` | Project version/rev/并发 |
| `test_locking.py` | 活 PID 保护、死 PID 回收、ownership、陈旧锁 |
| `test_transaction_recovery.py` | 故障注入（staged/manifest/COMMIT/部分 apply/state）、恢复幂等 |
| `test_validation.py` | 长度/重复/删除引用/inactive/closed milestone/层级环 |
| `test_events.py` | 不可变性、payload 契约 |
| `test_registry.py` | capabilities、dispatch、错误形状 |
| `test_doctor.py` / `test_cli.py` / `test_graph.py` | 诊断、CLI 全命令、图 |

写测试要求：只用 `tmp_path` + monkeypatch；禁止 sleep/网络/随机碰撞；失败注入用确定性的 monkeypatch（参考 `test_transaction_recovery.py` 的 `crash_on_apply`）。

## 8. 已知问题 / 技术债

**P2（建议 V1 前顺手补）**

- CLI 无 `pjt task ready`（服务端 `task.set_status` 支持 `ready`）；
- `expected_rev` 仅暴露在 `task.set_status` / `project.update`，`task.update` 等未暴露（有事务级 base_rev 兜底）；
- `pjt status` 的 computed blocked 列表未带 milestone。

**P3 / V1 能力缺口**

- 无 Artifact：无法关联文件/URL/commit/录制（真实使用最大摩擦）；
- 无 Git Adapter；无 `task related_updates` CLI（API 已有）；长中文标题终端折行。

**技术债**

- 陈旧锁抢占是 compare-and-delete，仍有极小 TOCTOU 窗口（活 PID 保护为强保证）；
- legacy（无 rev）事件链只报 warning，不强制迁移；
- `doctor` 未做 state/labels 内容级对比（只查存在性）；
- `ProjectService._member_id` 是兼容旧调用的过渡 helper；
- mypy 为“合理范围”而非 `--strict`，新增代码不得扩大豁免。

## 9. V1 建议与第一步

dogfooding 结论：**Artifact → Git Adapter → Search + SQLite → FastAPI/Web**（原顺序中 Artifact 提前）。

第一批具体工作建议：

1. **Artifact**
   - `domain/artifact.py`（kind/title/locator/task_ids/metadata）+ 迁移到 ObjectStore 集合；
   - `artifact.add/get/list/update/remove/attach_task/detach_task/verify`；
   - CLI：`pjt artifact add file:... --task TSK-…`、`--commit HEAD`（先只存 locator，不扫 Git）；
   - doctor：locator 基础校验（file 相对路径存在 = warning）；
   - `docs/03` §4.8 已冻结 schema，直接用。
2. **Git Adapter（只读）**
   - `integrations/git.py`：`detect/status/scan_commits`（trailer `PJT-Task: TSK-…`）；
   - `git.link_commit` 产生 `git.commit_linked` 事件（docs/08 预留）；
   - 注意：**Project root != Git root 必须支持**（EFW 场景已验证），只按 path 向上找 `.git`，不得假设相等。
3. **Search + SQLite**：`.pjt/local/index.sqlite` 只读缓存 + `pjt index rebuild`；索引失败不得影响 canonical。
4. **Web**：先 `system.capabilities` → FastAPI 薄封装（REST 映射见 docs/05 §7）→ React。

## 10. 排障手册

| 症状 | 处理 |
|---|---|
| `REVISION_CONFLICT` | 有人先改了：重新 `show` 拿新 rev 再提交；不要绕过 |
| `CONFLICT: write lock is held` | 另一进程在写；`pjt doctor` 看 owner pid；进程已死则 `pjt doctor --repair` |
| `NOT_FOUND .pjt not found` | 不在项目内（向上查找失败）；用 `-C PATH` |
| `doctor` 报 transactions warning | 崩溃残留：`pjt doctor --repair`（roll-forward / 丢弃） |
| `doctor` 报 invalid + COMMIT | 保留现场人工检查，不要手删；先备份 `.pjt` |
| 对象被手改（rev mismatch） | 从 `events/` 最后一条 `new_rev` 或 Git 历史恢复；勿信 `state/` |
| 派生数据可疑 | 直接删 `state/state.json`、`refs/labels.json`（会重建）；V1 后 `index rebuild` |
| schema 不支持 | 停止写入，只读；等待迁移或降级工具版本 |

## 11. 协作/发布流程

- 本仓库：改动 → `ruff/mypy/pytest` 全绿 → commit → push（`origin/main`；push 走 SSH）。
- 修改公共行为必须同步：`docs/05`（方法/CLI）、`docs/03`（模型/校验）、`docs/08`（event payload）。
- 版本：`project_tool/version.py`；不兼容模型变化才升 `SCHEMA_VERSION` major。
- CI 在 push/PR 上跑三件套；Windows job 覆盖 WriteLock 平台分支。

## 12. Dogfooding 数据与规则（重要）

- 真实使用点：`/mnt/d/framework/new/efw`（Git root 是 `/mnt/d/framework`，project root 是 `new/efw`）。
- 数据：`new/efw/.pjt`（27 对象/36 事件，含 15 个真实任务）；**保留，不要删除**。
- **framework 仓库禁止任何 git 写操作**（add/commit/push/reset/checkout/restore/clean）；
  EFW 源码禁止修改；唯一允许的写入是 `new/efw/.pjt/**`（以及 `.gitignore` 的那两行 ignore）。
- 可复现脚本（只在 `.pjt` 副本上跑破坏性测试）：
  `dogfooding/scripts/seed_efw.sh`、`destructive_checks.py`、`format_result.py`；
  证据在 `dogfooding/evidence/`，结论在 `dogfooding/report.md`。

## 13. 文档索引

| 文档 | 内容 |
|---|---|
| 01-overview | 产品定义与边界 |
| 02-architecture | 分层架构与模块结构 |
| 03-data-model | 对象 schema + 校验规则 |
| 04-storage | `.pjt` 布局、事务协议、锁、恢复 |
| 05-interfaces | Service API / CLI / 错误码 |
| 06-roadmap | 路线图与验收标准 |
| 07-v0.1-audit | V0.1 审计发现与处理结果 |
| 08-events | Event contract |
| 09-handover | 本文件 |
