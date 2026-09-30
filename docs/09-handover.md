# Project Tool — 交接文档（V0.2 / V1-A → V1-B）

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
| 版本 | `0.2.1`，`SCHEMA_VERSION = "1.1"`（`project_tool/version.py` 是**唯一**版本来源，`pyproject.toml` 用 `dynamic = ["version"]`） |
| 关键提交 | `6a19628` V0 核心+CLI → `0fcc628` V0.1 硬化 → `a7ac64e` EFW dogfooding → `779a886` 统一 expected_rev → `d73a492` Area → `52e1a9f` Artifact → `bdad62d` EFW 二次 dogfooding → V1-A.1 Hardening |
| 质量门槛 | `ruff check .` 0 error · `mypy project_tool` 0 error · `pytest` **271 passed** · CI（Ubuntu+Windows, Py3.12） |
| 真实验证 | V0.1：EFW Studio 一轮 dogfooding（`dogfooding/report.md`）；V1-A：`dogfooding/v1a-area-analysis.md` + `dogfooding/v1a-evidence/`（Area 映射、Artifact 关联、零污染树哈希） |
| Service API | 显式 registry，**103 个 method**，`system.capabilities` 可发现（`area=true, artifact=true`） |
| 未实现 | Git Adapter / Search / SQLite 索引 / Web / Remote / Sync / KC / Artifact 内容快照（V1-B+） |

## 2. 新接手者 15 分钟上手

```bash
cd /path/to/ProjectTool
uv sync
uv run pytest                          # 271 passed
uv run ruff check . && uv run mypy project_tool

# 在临时目录体验完整流程（不要污染别人的真实项目）
mkdir -p /tmp/pjt-demo && cd /tmp/pjt-demo
P="uv run --project /path/to/ProjectTool pjt"
$P init --name "Demo"
$P member add alice --name Alice
$P goal add "Ship v1"
$P milestone add "Core" --goal GOL-xxx --status active
$P area add Debug                       # Area = 稳定模块维度，与 Milestone 分开
$P task add "Task A" --owner alice --milestone MLS-xxx --area Debug
$P task ready TSK-xxx
$P artifact add file studio_core/debug.py --task TSK-xxx
$P artifact verify
$P status && $P doctor && $P graph project
```

> 迁移：老项目（`.pjt` 为 schema 1.0、无 `objects/areas/`）先跑一次 `pjt migrate`。

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
├── tests/               # 20 个测试文件，271 cases
├── docs/                # 01–09（09-handover = 本文件，09-v1a-design = 本轮设计记录）
├── dogfooding/          # EFW 真实项目验证报告 + 证据 + 可复现脚本
├── pyproject.toml       # uv；dev 依赖 pytest/ruff/mypy；ruff+mypy 配置
└── .github/workflows/   # CI
```

`project_tool/application/services/` 是业务逻辑所在：
`project/system/area/artifact/goal/milestone/task/member/update/decision/link/log/graph`
各一个模块，共享 `ServiceContext`（`application/context.py`）。
`AreaService` 依赖 `TaskService`（`area.tasks` 转发到 `task.list --area`），
`GraphService` 依赖 `LinkService` —— 依赖方向都是「已存在的域」指向新域，不成环。

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
13. **`expected_rev` 只有一种语义**：`ServiceContext.require_expected_rev(obj_type, model, expected_rev)`
    是唯一实现点（load 后、任何业务逻辑前，包括 no-op 短路）。
    省略 = 用当前 rev 作 base_rev；提供 = 必须相等，否则 `REVISION_CONFLICT`。
    不允许任何领域自己写 `if expected_rev != model.rev`。
14. **Milestone ≠ Area**：Milestone 是阶段/交付（有 status、due_at、派生 progress）；
    Area 是稳定模块/工作领域（只有 name / description / parent_area_id，
    **读视图也没有 progress**）。不要给 Area 加进度或截止时间。
15. **Area ≠ Label**：Label 是自由标签（`bug` `test` `high-risk`），
    Area 是有类型、有层级、被 doctor 校验引用完整性的稳定分区。
    `refs/labels.json` 只聚合 Task.labels。
16. **Artifact 只是引用**：没有 blob / CAS / snapshot。
    `kind=file` 的 locator 必须是 project-relative POSIX 路径；
    **任何写路径都不得 copy/move/delete/rename/rewrite 被引用的工程文件**。
    `artifact.remove` 只软删引用对象。
17. **只有 mutation 产生事件**：`artifact.verify` / `area.list` / `task.get` / `*.progress`
    一律无事件。
18. **Schema 写入门**：项目头 schema 必须等于工具 schema，否则所有 mutating method
    报 `SCHEMA_MIGRATION_REQUIRED`。实现在 `ProjectService.call()` 一处（按
    `MethodSpec.mutating`），豁免 `project.init` / `migrate` / `recover`。
19. **读取即校验 rev**：`load_model` / `list_models` 强制 `verify_rev`。
    对象被手改 / Git merge / 冲突解决动过之后，**读取时**报 `PROJECT_CORRUPTED`，
    不允许靠下一次写入「洗白」。唯一例外是 `doctor`（`check_rev=False`）与
    `resolve_actor`——它们必须在数据已损坏时仍能工作。

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
`objects/areas/`、`objects/artifacts/` 是**空目录也没有关系**——`ObjectStore.list_raw`
对缺失目录返回 `[]`，doctor 的 `objects.layout` 只报 warning（`pjt migrate` 可补齐）。
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
| `test_transaction_recovery.py` | 故障注入（staged/manifest/COMMIT/部分 apply/state）、恢复幂等；Area create / Artifact attach 崩溃 roll-forward |
| `test_validation.py` | 长度/重复/删除引用/inactive/closed milestone/层级环 |
| `test_events.py` | 不可变性、payload 契约 |
| `test_registry.py` | capabilities、dispatch、错误形状 |
| `test_doctor.py` / `test_cli.py` / `test_graph.py` | 诊断、CLI 全命令、图 |
| `test_task_ready_cli.py` | `task ready`：状态来源、CLI 薄适配、事件、JSON、computed blocked 不被破坏 |
| `test_expected_rev.py` | 七领域 × 正确/过期/省略 三态 + no-op 也不吞过期 rev |
| `test_area.py` | Area CRUD、Task 归属与过滤、层级环、doctor、事件、迁移兼容 |
| `test_artifact.py` | locator 安全（含合法空格）、关系、verify（存在/缺失/穿越/绝对路径/URL）、rev、事件、doctor、零写入 |
| `test_hardening.py` | V1-A.1：版本单一来源、schema 写入门、读路径 rev 校验、篡改不可洗白、doctor 韧性 |

写测试要求：只用 `tmp_path` + monkeypatch；禁止 sleep/网络/随机碰撞；失败注入用确定性的 monkeypatch（参考 `test_transaction_recovery.py` 的 `crash_on_apply`）。

## 8. 已知问题 / 技术债

**V0.2 已补（V1-A）**

- ~~CLI 无 `pjt task ready`~~ → `pjt task ready` 已加（`test_task_ready_cli.py`，13 cases）。
- ~~`expected_rev` 只覆盖两处~~ → 统一 contract（`tests/test_expected_rev.py`，14 cases）。
- ~~无 `task related_updates` CLI~~ → `pjt task related-updates` / `pjt task artifacts` 已加。
- ~~无 Artifact / 无 Area 维度~~ → `artifact.*`（8 method）+ `area.*`（9 method）。
- ~~`pjt --version` 实际 exit 2~~ → 修好（V0.1 文档承诺了它但没生效）。

**仍未做（按优先级）**

- `pjt status` 的 computed blocked 列表未带 milestone / area（纯渲染，随时可改）。
- 长中文标题在终端表格/树中折行（纯显示）。
- Artifact `file` 缺失时 doctor 报 warning——**这是有意的**：分支切换/删除工程文件很常见，
  不能当数据损坏。但目前没有「这个 artifact 已经不需要了」的批量清理入口（只有单条 remove）。
- `artifact.list` / `task.related_artifacts` 每次都是全量 file scan；15 任务规模无压力，
  上千 artifact 时需要 Search/Index（V1-B）。

**模型层待决（进 Git Adapter 前要先定）**

- **Task 单 Area** 是硬限制。EFW 15 个任务里 2 个（T5 引用检查、T12 ProcTransport 泄漏）
  跨域，V1-A 强制取主 Area，跨域信息只能进 description/label。
  如果「主 Area 说不清」的比例上升，应升到多 Area，而不是硬塞。
- **Area 名不唯一**。同 goal/milestone/task 的 title 一致；按名引用不唯一时报
  `INVALID_ARGUMENT` 要求用 ID 消歧。真实使用时「UI 只有一个」是自然约束，
  但没有强制。
- **Area ↔ 目录没有绑定**。目前靠人维护 `Area=UI ↔ ui/`。
  Git Adapter 落地时最自然的做法是让 `area` 记住**目录前缀**（相对 project root），
  这样 `task list --area UI` 能直接推出候选 Artifact 路径。
  **但这会把目录结构写进 canonical 数据，重命名目录就会留下悬挂引用**——
  V1-B 必须先决定：硬编码前缀 / 可选前缀 / 保持纯语义不做绑定。

**技术债**

- 陈旧锁抢占是 compare-and-delete，仍有极小 TOCTOU 窗口（活 PID 保护为强保证）；
- legacy（无 rev）事件链只报 warning，不强制迁移；
- `doctor` 未做 state/labels 内容级对比（只查存在性）；
- `ProjectService._member_id` 是兼容旧调用的过渡 helper；
- `milestone.get` / `milestone.list` 走 `milestone_summary`，不带完整模型字段
  （没有 `parent_goal_id`、没有 `metadata`）——V1-A 只补了 `rev/version/lifecycle` 让
  `expected_rev` 可用，字段补齐留给 Web（V1-B）；
- mypy 为“合理范围”而非 `--strict`，新增代码不得扩大豁免。

## 9. 下一步：V1-B（Git Adapter）

V1-A 已完成 Artifact，因此下一个自然落点是 **Git Adapter（只读）**。

1. **先定 Area ↔ 目录的关系**（见 §8「模型层待决」）。这是 Git Adapter 的前置条件：
   Area 不和目录绑定，`task list --area UI` 就无法自动推出该看哪些文件。

   **不要用单个 `path = ui/`**——真实映射是多对多的：

   ```text
   Distribution
   ├── desktop/**
   ├── scripts/**
   ├── package.json
   └── electron-builder config
   ```

   更合理的形状是 **glob 列表**（`path_patterns: ["desktop/**", "scripts/**", "package.json"]`），
   这样「一个 Area 跨多个不连续路径」和「一个 glob 命中多个 Area」都能表达。
   代价是把目录结构写进 canonical 数据：重命名目录会留下悬挂引用。
   三个选项要一起决定：**硬绑定 / 可选绑定（无绑定时退回人工） / 保持纯语义不做绑定**。

   无论选哪个，Git Adapter 只允许 **推导**：

   ```text
   changed file  ->  候选 Area（报告 / 建议 / 生成命令）
   绝不  ->  自动改写 Task.area_id
   ```

   否则一个跨 Area 的 commit 会被错误归类，而 Area 是**人工维护的结构判断**，
   不是可以从文件路径机械推导出来的东西。
2. **Git Adapter（只读）**
   - `integrations/git.py`：`detect/status/scan_commits`（trailer `PJT-Task: TSK-…`）；
   - 产出 Artifact：`kind=git_commit` / `git_branch` 的 locator 从「格式校验」升级为
     「真实可解析」（`git rev-parse --verify`）；
   - `git.link_commit` 产生 `git.commit_linked` 事件（docs/08 预留）；
   - 注意：**Project root != Git root 必须支持**（EFW 场景已验证），只按 path 向上找 `.git`，
     不得假设相等。`artifact.kind=git_*` 的 verify 也要按 Git root 解析，不是 project root。
3. **Search + SQLite**：`.pjt/local/index.sqlite` 只读缓存 + `pjt index rebuild`；
   索引失败不得影响 canonical。顺带解决 §8 里「artifact 全量 file scan」的问题。
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
- 版本：`project_tool/version.py`（唯一来源，`pyproject.toml` 用 `dynamic = ["version"]` 指向它）；
  不兼容模型变化才升 `SCHEMA_VERSION` major。
  本仓库是 editable 安装，**改完版本号要 `uv pip install -e . --reinstall-package project-tool`**
  才能让包元数据跟上（`tests/test_hardening.py` 会抓到这种漂移）。
- CI 在 push/PR 上跑三件套；Windows job 覆盖 WriteLock 平台分支。

## 12. Dogfooding 数据与规则（重要）

- 真实使用点：`/mnt/d/framework/new/efw`（Git root 是 `/mnt/d/framework`，project root 是 `new/efw`）。
- 数据：`new/efw/.pjt`（27 对象/37 事件，含 15 个真实任务；已 migrate 到 schema 1.1）；
  **保留，不要删除**。
- V1-A 的 Area / Artifact 只写在**临时副本**上（`/tmp/pjt-v1a-efw-*`），
  真实 `.pjt` 只被 `pjt migrate` 改过（新增空 `objects/areas/` + `project.schema_version 1.0→1.1`），
  **没有自动改写任何 milestone 或 task**。是否迁移真实数据是维护者的决定。
- **framework 仓库禁止任何 git 写操作**（add/commit/push/reset/checkout/restore/clean）；
  EFW 源码禁止修改；唯一允许的写入是 `new/efw/.pjt/**`（以及 `.gitignore` 的那两行 ignore）。
- 可复现脚本（只在 `.pjt` 副本上跑破坏性测试）：
  `dogfooding/scripts/seed_efw.sh`、`destructive_checks.py`、`format_result.py`；
  证据在 `dogfooding/evidence/`，结论在 `dogfooding/report.md`。
- V1-A 回归：`python3 dogfooding/scripts/v1a_dogfood.py`（自带 re-exec 到仓库 venv）；
  输出 `dogfooding/v1a-evidence/v1a-dogfooding.txt`，结论 `dogfooding/v1a-area-analysis.md`。
  脚本会 `tar` 一份不含 `.pjt`/构建产物的临时副本 + `cp -a .pjt` 进去，
  用整棵源码树的 sha256 前后对比证明「Artifact 从未修改任何工程文件」。
  注意：单次运行约 3–4 分钟（`pjt` 每次启动要 import pydantic+rich+typer，WSL 下约 5s）。

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
| 09-v1a-design | V1-A 设计记录（Area / Artifact / revision contract / migration） |
