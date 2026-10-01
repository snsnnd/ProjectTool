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

### V1-A.1 — Hardening（已完成，`0.2.1`）

V1-A 审查后、进入 Git Adapter 前的 4 个必须项 + 2 个小项：

```text
✓ 版本号单一来源（pyproject dynamic = ["version"] -> version.py，消除元数据/runtime 漂移）
✓ Schema 写入门：project schema != tool schema 时拦下所有 mutating method
  （SCHEMA_MIGRATION_REQUIRED；豁免 init / migrate / recover；实现在 ProjectService.call）
✓ 读路径 rev 校验：被外部篡改的对象读取即 PROJECT_CORRUPTED，无法靠下一次写入洗白
  （doctor 与 resolve_actor 例外，保证数据已损坏时仍能出报告）
✓ file Artifact 允许合法空格路径（控制字符仍禁止；url/git_* 仍禁空白）
✓ Area 重名 -> INVALID_ARGUMENT 并列出候选（原来落到 NOT_FOUND，与文档不一致）
✓ doctor 在 member/task rev 被篡改时仍可完整运行
```

### V1-B — Git 感知层（已完成，`0.3.0`）

dogfooding 后调整顺序：真实摩擦最大的是“任务 ↔ 产物”关联，
因此 **Artifact 提前到 Git Adapter 之前**（V1-A 已完成 Artifact）：

```text
✓ Area.path_patterns（可选 glob 列表，把模块和目录关联起来；只推导不回写）
✓ integrations/git.py 只读适配器（rev-parse / status / log / show 运行时白名单 +
  --no-optional-locks，不抢别人的 index 锁；支持 project root != git root）
✓ git.available / git.status / git.log / git.link_commit
✓ trailer 约定 `PJT-Task: TSK-…`；git_commit Artifact 的 locator 现在能真正解析
✓ `system.capabilities`: git = true
```

**未做**：Search / SQLite 索引 / Local Web / FastAPI / React。
2 个并发写者的 Git merge 辅助仍未做——这是 `docs/09-handover.md` §8 的下一项。

V1-A **刻意未做**（留到有真实需求时）：Artifact 内容快照（blob/CAS）、
Area 唯一名约束、Task 多 Area、Search / 索引。

### V1-B.2 — 触达补完 + 终端渲染（已完成，`0.4.0`）

不新增任何领域概念。两条线：

**CLI 触达率补到 100%**。registry 里有 22 个 method 此前没有任何 CLI 入口——
它们早就存在于 service + registry，只是摸不到。补上：

```text
goal archive/restore · area tasks/set-parent/match-path/history
update edit/archive/history · decision history · link status
task set-parent · 裸 pjt git（打印 Git 感知可用性）
```

**link 的机器本地路径写入口**（§7 的一半实现，之前只做了读侧）。
`LocalState.links` 被 `link.resolve` 读取，却**没有任何东西能写它**——
于是「绝对路径只进 local.toml」这条规则无法落地，`link add` 遇到绝对路径
只能报错并指向一个不存在的出路。补上 `link.map_local_path` /
`link.unmap_local_path` + CLI `link map-local` / `unmap-local`：

- 绝对路径只落 `local.toml`；objects / events / project.json 一律不出现（有测试逐个目录扫）
- **不发事件**：`local.toml` 不进 Git 而 `events/` 进 Git，写事件等于把绝对路径抄进共享历史
- 也不因为「路径存在」就宣称成功，`has_project` 只表示探测到 `.pjt/project.json`

**渲染修复**（V0.1 dogfooding 报告 P2-3 / P3-7）：

- 表格长标题按显示宽度截断加 `…`，不折行（全角算 2 列）；只有 Title 列伸缩，
  其余列 `min_width` 钉死，避免 rich 把 `status` 压成 `inb…`
- `pjt status` 的 computed blocked 内联显示 Area 名与 Milestone 标题；
  **仍不列举全部 Area**（V1-A 的决定），归属只出现在 blocked 条目上

### V1-C — 多人并发（进行中，`0.4.1`）

协作形态按**最多 20 人**设计。20 人与 handover 里写的「2 个并发写者」不是一个量级，
所以这一阶段的第一件事不是写合并辅助，而是**先量出真实的冲突面**
（`dogfooding/scripts/multiwriter_probe.py`：真 origin.git + 两个克隆，跑 9 个合并场景）。

结论比预期好：**存储架构本身可扩展，问题只在两个派生缓存文件上。**

```text
✓ events/ 一事件一文件（按月分片）→ 永不冲突。append-only 最常见的死法
  （都往同一文件尾部追加）在这里不存在
✓ objects/ 一对象一文件 → 改不同任务天然不冲突
✓ project.json 不随每次写入变化（sha256 实测）→ 不是全局冲突点
✓ 派生缓存不进版本控制 → 1/9 干净合并变 8/9
  .gitignore 规则 + doctor 把「被 git 跟踪」判为 error（防静默回归）
```

剩下的 1/9（两人改同一个 task）是**本来就该冲突**的真语义冲突，由 `expected_rev`
在写入时拦截。所以下一步不该做「更聪明的自动合并」——无服务器架构下那很容易变成
看不出对错的静默合并，比冲突危险得多——而该做**降低同对象并发**。

**第二步：分区归属 + 接口契约**（`0.5.0`）

协作形态定为「每人负责一块，但有公共接口，而且能看见别人在做什么」。

```text
✓ Area.owner_ids（显式，不推导）+ pjt area set-owner
  1 个 owner = 私有块，多个 = 公共接口区（复数就是「公共」，不需要 shared 字段）
✓ Member.roles 建议词汇表；**不做本地权限门禁**——权限留给服务器
✓ 接口契约 = 固定模板的 markdown + Artifact 注册（不是一等对象，见理由）
  pjt interface init | list | show | check | sync
  front-matter 机器可读（为将来自动索引），必需章节是强制沟通清单
  check 只报告不改写，有 error 退出码 1 -> 可当 CI 门禁
```

两个刻意的「不做」：

- **不做本地权限门禁**。`.pjt/objects/**` 是可读 JSON 跟着 Git 走，本地门禁
  只会制造「已经管住了」的错觉。上服务器后权限以服务器为准。
- **不把接口做成一等对象**。正文是人写的散文，塞进 JSON 只会让人绕过工具；
  diff/blame/历史 Git 已经做得比自建机制好。工具只提供模板与检查。

未做：Area 活跃度视图（「谁现在正在哪个 Area 里动代码」，从 Git 推导）、
真正的 merge 辅助、服务器权限模型。

### ~~V2 — 远程协作~~（❌ 已决定不做）

**决定（2026-09-30）**：Project Tool **不提供远程服务器**。

理由不是做不动，而是**协作已经有更好的载体**：

- `.pjt/` 是可读 JSON、跟着 Git 走 → 历史 / 分支 / diff / blame / CI / review 全都白送；
  自建服务器要重新实现其中一半，还要自己运维、自己备份、自己保证不丢数据。
- 我们的并发模型（`rev` = 内容哈希 + `base_rev → new_rev` 事件链）比多数同步协议更严：
  冲突会**显式报出来**（`REVISION_CONCEPT` 级别的 rev mismatch），不会静默 Last-Write-Wins。
- 离线可用、零运维、零账号体系。个人 / 小团队自用场景下这是纯收益。

放弃的便利（明确知道会缺，认了）：

| 缺的 | 替代方案 |
|---|---|
| 跨机实时同步 | Git pull（可能需要人肉解 JSON merge） |
| 细粒度 ACL | `.pjt` 进 Git，权限交给 Git 托管 / 仓库权限 |
| Webhook（CI 响应任务完成） | CI 直接读 `.pjt/`，或将来写 `.github/workflows` 脚本 |
| 跨项目检索 | 本地 grep / 未来的 `pjt search`（V1-B，纯本地） |

**已知代价**：2 个并发写者 + Git merge 冲突时，目前没有 merge 辅助工具，
`doctor` 会报 `PROJECT_CORRUPTED`（正确但需要人工解）。这是真实缺口，
要用多人协作时才会遇到，届时应做 merge 辅助而不是做同步服务器。

`errors.py` 里的 `SyncConflict` / `PermissionDenied` / `AuthRequired` /
`RemoteUnavailable` / `BrokenLink` 保留为**占位错误码**，不实现对应功能。

### ~~V3 — KC 集成~~（⏸ 视需要，不排期）

KC 原本依赖 Project Server 提供 organization / project 映射、visibility、权限。
既然**不做 remote**，KC 集成也随之搁置：没有账号与 ACL 体系可供对接。

真要做，最小形态是 KC 直接读某个仓库的 `.pjt`（KC 侧拉取或用 Git 同步），
而不是 KC → SDK → 我们的 Server。多一层我们自己维护的服务端没有收益。

```text
（搁置）
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
