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
（Area / Artifact 本体在 V1-A 落地；Snapshot 与 Git 扫描仍在 V1-B）
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

**验证结果（dogfooding，2026-09-30）**：在真实 EFW Studio（`framework@tmp/new`，Git root ≠ project root）
完成一轮完整使用：15 个真实 Task / 5 依赖 / 3 Update / 3 Decision，零源码污染；
破坏性场景（rev 篡改、断链、层级环、陈旧锁、崩溃事务、恢复幂等、event 不可变）
全部只在 `.pjt` 副本执行并通过。结论：**无 P0/P1，适合持续使用**。
报告：`dogfooding/report.md`；两个 P2 CLI 小项（`task ready`、`task.update expected_rev`）建议进 V1 前顺手补。

### V1-A — UX / Contract Cleanup + Domain Completion（已完成，`0.2.0` / `SCHEMA_VERSION 1.1`）

V0.1 dogfooding 暴露的 P2/P3 中「已被真实使用证明有价值」的四项，先补齐再进 Git 感知层：

```text
✓ pjt task ready（V0.1 只有 start/block/review/done/cancel）
✓ 统一 expected_rev contract（ServiceContext.require_expected_rev 一处实现，
  覆盖全部修改型 operation；CLI 编辑命令 --expected-rev）
✓ Area（ARA-）：稳定工作领域维度，与 Milestone（阶段/交付）分开
✓ Artifact（ART-）：工程产物的**引用**（file/url/git_commit/git_branch + 10 种形态），
  关联 Task / Decision / Milestone / Goal；verify 只读；绝不修改被引用文件
✓ pjt task related-updates（API 早有，CLI 缺）+ pjt task artifacts
✓ pjt --version 修复（V0.1 实际 exit 2，属文档承诺的接口）
```

设计记录：`docs/09-v1a-design.md`；EFW 验证：`dogfooding/v1a-area-analysis.md`。

### V1-B — Git 感知层

dogfooding 后调整顺序：真实摩擦最大的是“任务 ↔ 产物”关联，
因此 **Artifact 提前到 Git Adapter 之前**（V1-A 已完成 Artifact）：

```text
Git Adapter（只读：pjt git status / scan，trailer: PJT-Task: TSK-…；支持 project root != git root）
           Artifact 的 git_commit / git_branch locator 由此获得真实语义
Search（本地结构化 + 全文）+ SQLite 索引（.pjt/local/index.sqlite，可重建）
Local Web Server（FastAPI）+ React/TypeScript UI（Vite）
Overview / Tasks(List+Board) / Graph / Timeline / Milestones / Areas / Goals /
Decisions / Artifacts / Members / Linked Projects / Settings
```

V1-A **刻意未做**（留到有真实需求时）：Artifact 内容快照（blob/CAS）、
Area 唯一名约束、Task 多 Area、Search / 索引。

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
| docs（本目录 + 07 审计 + 08 事件契约 + 09 交接） | ✓ |
| domain（ids/hashing/models/validation/errors/events） | ✓ |
| storage（project/object/event/transaction/recovery/lock/migrations） | ✓ |
| application（service/registry/context/services/queries/doctor） | ✓ |
| graph（dependency/project_graph） | ✓ |
| cli（main/common/render + 各域模块 + --json/--porcelain/--as） | ✓ |
| tests（pytest，120 cases，含故障注入/恢复幂等/锁） | ✓ |
| ruff + mypy + CI（Ubuntu/Windows + Python 3.12） | ✓ |
| web/（React） | V1 |
| api/（FastAPI） | V1 |
| sync/ | V2 |

## 4. 第一验证项目（已完成第一轮）

真实 EFW Studio（`framework@tmp/new` 的 `new/efw`，Git root 与 project root 不同）
已完成第一轮 dogfooding：

```text
1 Project / 1 Member / 1 Goal / 4 Milestones / 15 Tasks / 5 Dependencies
3 Updates / 3 Decisions；真实缺口全部来自只读审计（desktop 缺失、scripts 为空、
test:bridge 目标不存在、msgq 未聚合、ProcTransport 资源泄漏、模型页只读等）
```

数据保留在 `new/efw/.pjt`，继续使用即可累积真实历史。
复现与破坏性验证脚本：`dogfooding/scripts/`；报告：`dogfooding/report.md`。
