# Project Tool — 路线图与 V0 验收

## 1. 版本规划

### V0 — Core + CLI（本次搭建）

```text
Project / Goal / Member / Milestone / Task / Update / Decision / Link
Event History
.pjt storage（canonical / 一对象一文件 / ULID / rev / lifecycle）
Transaction + 写锁
Dependency Graph（环检测、computed blocked、进度推导）
CLI：init status doctor migrate
     goal milestone task member update decision link log graph
```

不做（刻意）：

```text
账号系统 / Remote Server / 多人同步 / Webhook / KC 集成
复杂权限 / Artifact / Artifact Snapshot / Git 自动扫描 / IDE 插件
SQLite 索引 / Local Web UI / React 前端
```

> 先验证：`.pjt + Core + CLI` 这个模型是否真的好用。

### V0.1 — 架构审计与硬化（当前）

```text
Project 纳入 revision concurrency control（expected_rev）
Crash-Recoverable Transaction（manifest + COMMIT + roll-forward，幂等恢复）
storage/recovery.py + project.recover + pjt doctor --repair
WriteLock：PID 判活 + ownership token（不误删活锁）
Service 拆分（application/services/*）+ 显式 registry + system.capabilities
CLI 拆分（common/render/各域模块），命令保持兼容
HIERARCHY_CYCLE（goal/task parent、decision supersede）
引用校验（deleted / inactive / closed milestone）
Doctor：事务 / 锁 / 事件链 / project rev + repairable 标记
Event contract（docs/08-events.md）+ 不可变性测试
ruff + mypy + GitHub Actions CI（Ubuntu + Windows, Python 3.12）
```

不增加任何用户可见新功能；外部 CLI 行为与 V0 兼容。

### V1 — 增强与本地 Web

```text
Git Adapter（pjt git status / scan / link，trailer: PJT-Task: TSK-…）
Artifact（引用 + --snapshot）
Search（本地结构化 + 全文）
SQLite 索引（.pjt/local/index.sqlite，可重建）
Local Web Server（FastAPI）+ React/TypeScript UI（Vite）
Overview / Tasks(List+Board) / Graph / Timeline / Milestones / Goals /
Decisions / Artifacts / Members / Linked Projects / Settings
```

### V2 — 远程协作

```text
Project Server（FastAPI + PostgreSQL：projects / project_objects / project_events /
project_members / project_acl / sync_cursors / blobs / webhooks）
Remote accounts 与 Member mapping
owner / maintainer / contributor / viewer
push / pull / conflicts（不做 Last-Write-Wins）
Webhook（task.created / task.status_changed / milestone.closed /
        decision.accepted / project.updated）
@project-tool/sdk（TypeScript）
```

### V3 — KC 集成

```text
KC → Project SDK → Project Server
KC 只保存 organization_project_id / project_tool_project_id / member mapping /
visibility / 权限 / 展示元数据
不复制 Task / Decision / Event；最多 read cache + Webhook 刷新
KC Admin 使用 @project-tool/embed 组件（ProjectOverview / TaskBoard / Timeline / Graph）
```

## 2. V0 验收标准（可执行）

1. `uv run pjt init` 生成完整 `.pjt` 结构与 `.gitignore`。
2. `pjt member/goal/milestone/task/update/decision/link` 全流程可跑通。
3. 每个对象：ULID 主键、`version`、`rev` 可校验、`lifecycle` 支持 archive/restore/delete。
4. 每次修改产生不可变 Event，且 `base_rev/new_rev` 正确；`pjt log` 可查询。
5. `task done` 等操作在一个事务内原子完成（staging + rename + 锁）。
6. `expected_rev` 不符 → `REVISION_CONFLICT`（exit 5）。
7. 依赖环 → `DEPENDENCY_CYCLE`（exit 3）。
8. `milestone.progress` 由 weight 推导；computed blocked 不修改任务状态。
9. `pjt doctor` 对新鲜项目全 OK；篡改对象后能报 ERROR。
10. 删除 SQLite/state/labels 不影响任何功能（V0 无 SQLite，state/labels 派生）。
11. `pytest` 全绿；`--json` 输出稳定可解析。

## 3. 实现进度

| 模块 | 状态 |
|---|---|
| docs（本目录 + 07 审计 + 08 事件契约） | ✓ |
| domain（ids/hashing/models/validation/errors/events） | ✓ |
| storage（project/object/event/transaction/recovery/lock/migrations） | ✓ |
| application（service/registry/context/services/queries/doctor） | ✓ |
| graph（dependency/project_graph） | ✓ |
| cli（main/common/render + 各域模块 + --json/--porcelain/--as） | ✓ |
| tests（pytest，118 cases，含故障注入/恢复幂等/锁） | ✓ |
| ruff + mypy + CI（Ubuntu/Windows + Python 3.12） | ✓ |
| web/（React） | V1 |
| api/（FastAPI） | V1 |
| sync/ | V2 |

## 4. 第一验证项目

```bash
cd <efw 项目目录>
uv run --project /path/to/project-tool pjt init
uv run pjt member add jichao --name "计超" --role maintainer
uv run pjt goal add "完成 EFW Studio"
uv run pjt milestone add "Debug Runtime"
uv run pjt task add "实现 TCP Transport" --milestone MLS-xxx --owner jichao
# 之后每天真实使用：status / task start / update / decision add / log
```

不使用编造数据，直接在日常开发中验证。
