# V1-A 设计记录：UX / Contract Cleanup + Domain Completion

> 本文件是 V1-A 轮（`task ready`、统一 `expected_rev`、Area、Artifact）的设计记录。
> 实现以本文件为准；公共行为变化同步 `docs/03`（模型）、`docs/05`（接口）、`docs/08`（事件）。
> 基线：`a7ac64e` dogfooding → `95e4a75` 交接文档。版本 `0.1.0` → `0.2.0`，`SCHEMA_VERSION` `1.0` → `1.1`。

---

## 1. 真实 dogfooding 暴露的问题

来源：`dogfooding/report.md`（EFW Studio，`framework@tmp/new`，`new/efw`，27 对象 / 36 事件）。

| 编号 | 问题 | 证据 | 本轮处理 |
|---|---|---|---|
| P2-1 | CLI 缺 inbox→ready 状态命令 | §F P2-1、§E「最不自然」 | 任务 1 |
| P2-2 | `expected_rev` 只覆盖 `task.set_status` / `project.update` | §F P2-2 | 任务 2 |
| P2-3 | computed blocked 列表不带 milestone（纯显示） | §F P2-3 | 不在本轮（纯渲染，可随时改） |
| P3-4 | **无 Artifact**：只能在 Task 文本里手写源码路径 | §E「最大的价值缺口」、§F P3-4 | 任务 4 |
| P3-6 | API 有 `task.related_updates`，CLI 没有 | §F P3-6 | 任务 4（顺手） |
| — | **Milestone 被当成 Area 用**：4 个 milestone（页面内模型编辑 / 真机调试链路 / 桌面壳与打包 / 工程卫生）实际是工作领域而非交付阶段 | §C 里程碑（4） | 任务 3 |
| — | 模块维度只能靠 label | §E | 任务 3 |

真实数据里 15 个任务的归属全部是「领域」（UI / Debug / Distribution / Runtime），
milestone 的 `progress` 因此恒为 0%（final-snapshot 里 active milestone `0%`）——
因为没有一个阶段是真正按时间交付的。这是 Area 要解决的第一性问题，不是理论设计。

### 1.1 任务 1：`task ready` 的状态规则决定

**先查当前 `task.set_status` 的规则，结论是：没有任何状态转换矩阵。**
`application/services/task.py:task_set_status` 只做 `enum_value(TaskStatus, status)`
然后赋值，任意状态可到任意状态。CLI 上 `task start` / `block` / `review` / `done` /
`cancel` 五个快捷命令共享同一个 `_set_status` 薄适配。

所以本轮的决定是：

```text
pjt task ready <task>  ==  pjt task start 等价物：只调 task.set_status{status: "ready"}
```

| 转换 | 是否允许 | 理由 |
|---|---|---|
| `inbox → ready` | ✓ | 目标场景 |
| `blocked → ready` | ✓ | 阻塞解除后重新可开始 |
| `review → ready` | ✓ | 被打回，回到可开始 |
| `done → ready` | ✓ | 同上：无转换矩阵 |
| `cancelled → ready` | ✓ | 同上 |

**不为 `ready` 单独引入转换矩阵**，理由：

1. 「done → ready」「cancelled → ready」是否允许，在没有转换矩阵的服务里本来就是
   允许的。只给 `ready` 加白名单，等于凭空发明一条与其它 6 个状态不同的规则——
   这正是本轮要消灭的「某些领域语义不同」。
2. 真正的转换矩阵是**跨状态的策略决定**（是否允许 review → doing、done → doing），
   应该一次性对全部状态统一决定，而不是为补一个缺失命令顺带发明。
3. CLI 保持薄适配层：业务规则只在 `task.set_status` 一处。

`blocked` 状态与 computed blocked 的区分不受影响（见下）。

### 1.2 computed blocked 仍然只推导

```text
Task.status = ready，dependencies 未完成
  → computed_blocked = true（读视图字段）
  → Task.status 仍然是 ready，不被改写
```

`task ready` 不引入任何自动状态转换；`is_computed_blocked` 是纯函数，
`graph/dependency.py` 不写库，status 也不回写。这条约束本轮不变。

---

## 2. Area 的设计理由

### 2.1 Milestone 与 Area 的区别

```text
Area:     这个工作属于哪里？          （稳定结构维度 / 模块 / 子系统）
Milestone: 这个工作服务于哪个阶段？   （时间 / 交付节点 / 阶段目标）
```

| | Milestone | Area |
|---|---|---|
| 变化频率 | 随交付节奏推进、结项、关闭 | 随项目结构演进，很少变 |
| 字段 | `status` `due_at` `goal_ids` | 只有 `name` `description` `parent_area_id` |
| 进度 | 派生 `progress`（加权 done/total） | **不派生**（见 2.2） |
| 回答 | “这批工作属于哪个交付？” | “这块代码/能力属于哪块？” |
| 例 | “真机 Debug MVP”“v1.0 发布” | `Core` `UI` `Debug` `Runtime` `Distribution` |

一个 Task 属于 **1 个 milestone + 1 个 area + N 个 label**（V1-A 保持单值 area）。
它可以同时是「Debug 领域」的工作、且服务于「真机 Debug MVP」阶段。

### 2.2 Area 明确**不**包含什么

Area 对象**没有** `status` / `progress` / `due_at` / `owner`，读视图也**不**返回 progress。
理由：一旦给 Area 加进度，它就退化成第二个 Milestone，V1-A 的整个分维度就没有意义。
Area 的读视图只有 `id / name / parent_area_id / task_count`；要看工作量请
`pjt task list --area Debug` 或 `pjt area show <area>`。

### 2.3 Area 与 Label 的区别

```text
Area  = 稳定结构维度，有类型（ARA-）、有层级、可被引用、被 task 反向归属
Label = 自由文本标签，无结构，可随意增删
```

EFW 里：Area = `Debug`；Label = `bug` `test` `high-risk` `hardware`。
Label 表达“这任务有什么属性”，Area 表达“这任务动的是哪块东西”。
**不允许用 Label 代替 Area**：`refs/labels.json` 仍然只聚合 Task.labels，不含 Area。

### 2.4 层级

只支持简单父子（`parent_area_id`），例如 `UI ├── Editor └── Debug UI`。
环检测复用 `ServiceContext._validate_chain`（与 goal/task parent 同一套），
doctor 的 `hierarchy` 检查也复用同一份字段表——**不新建第四套 cycle checker**。

### 2.5 已知取舍

- **不强制 Area 名唯一**（与 goal/milestone/task 的 title 一致）。代价是可能存在两个
  `UI`；收益是 `area.create` 保持 O(1) 且不引入新的唯一性错误路径。
  这是 V1-A 的明确决定，不是遗漏。`pjt area list` 输出 ID 供消歧。
- **Task 单 Area**。多 Area（一个任务跨模块）留到有真实需求时再评估。
- **Area 不参与 status 输出**（`pjt status` 不列 Area），避免信息过载；
  只在 `task show` / `task list --area` / `graph project` 出现。

---

## 3. Artifact 的设计边界

### 3.1 它解决什么

dogfooding 结论：真实摩擦是「任务 ↔ 产物」关联，Task 只能写纯文本路径：

```text
T6 serial/tcp 回环测试  →  描述里手写 "studio_core/debug.py"
DEC CLI 与 GUI 共用 Service  →  描述里手写三个路径
```

Artifact 把这个关联变成一等对象 + 一等关系，可以 `list` / `verify` / 追溯。

### 3.2 引用语义，不是内容存储

```text
V1-A:  只存 reference（kind + locator）
不做:  blob / CAS / snapshot / upload / 远端存储
```

**Artifact 绝不修改被引用的文件**：`artifact.remove` 只软删除 Artifact 对象
（`lifecycle=deleted`），不 copy / move / delete / rename / rewrite 任何工程文件。
代码里没有任何一条写路径指向 project root 下 Artifact 的 locator。
内容快照留待 V2（docs/06 记为 Artifact Snapshot）。

### 3.3 Locator 规则

`locator: str`（单值，不为每个 kind 建不同结构）：

| kind | locator 例子 | 校验 |
|---|---|---|
| `file` | `studio_core/debug.py` | **必须是 project-relative POSIX 路径** |
| `url` | `https://…` | http/https + netloc（**不做网络请求**） |
| `git_commit` | `abc1234` | 十六进制 4–40（**Git Adapter 未启用**，只做格式） |
| `git_branch` | `feature/foo` | git ref-name 字符集，无 `..` |
| 其他 11 种 | 自由串 | 非 URL 时按不透明串处理，只做通用安全校验 |

通用安全校验（对所有非 url kind）：

1. 禁止绝对路径（`/…`、Windows 盘符 `C:\…`、UNC `\\host`）——AGENTS.md 铁律：
   机器本地绝对路径只进 `.pjt/local/`。
2. 禁止任何 `..` path segment——禁止逃出 project root（§41）。
3. 禁止以 `~` 开头。
4. `file` kind 额外：分隔符统一 `/`、禁止 `.`/空 segment、禁止首段为 `.pjt`
   （ProjectTool 内部状态不是工程 Artifact，§42）。

canonical 形态：`relative POSIX-style`，统一 `/`。

### 3.4 关联模型（为什么不是独立 relation 对象）

```text
Artifact.related_task_ids / related_decision_ids / related_milestone_ids / related_goal_ids
```

不新建 `ArtifactLink` 对象，理由：

- **低冲突**：`artifact.attach --task T` 只写 Artifact 一个文件；反例（Task 存
  `artifact_ids`）会同时改 Task 文件，与并发编辑 Task 的操作直接冲突。
- **merge-friendly**：ID 数组是可并集合并的最小单元，Git 层面几乎不冲突。
- **简单**：与既有 `Update.task_ids` / `Decision.related_task_ids` 形态完全一致，
  doctor 引用检查、UI 遍历都复用同一套 `check_ref`。

反向查询（`task.related_artifacts`）是**派生读**，用 file scan 遍历 `objects/artifacts/`
——本轮不引入 SQLite / 索引（§43）。

### 3.5 verify 的边界

```text
file        → 检查 project-relative 路径是否存在（exists true/false）
url         → 只校验格式，绝不发起网络请求
git_commit  → 只校验格式 + 附带「git adapter 未启用」提示
git_branch  → 同上
其他 kind   → skipped（不透明引用，V1-A 无可校验语义）
```

`artifact.verify` 是**纯查询**：不产生事件（§38）。只有 mutation 产生 event。

### 3.6 Doctor 语义

| 情况 | 级别 | 理由 |
|---|---|---|
| file locator 不存在 | `warning` | 工程文件可能被 Git 分支切换 / 删除 / 暂时缺失，不是数据损坏 |
| locator 越界（绝对路径 / `..` / `.pjt`） | `error` | 手改对象后的安全不变量破坏 |
| `related_*_ids` 指向不存在的 Task/Decision/Milestone/Goal | `error` | 引用结构损坏（§40） |
| Area/Artifact 对象 rev / schema / project_id | `error`（沿用通用 objects 检查） | |

---

## 4. Revision contract（统一 `expected_rev`）

### 4.1 规则

所有**修改已有 canonical object** 的 operation 都接受 `expected_rev: optional`：

```text
expected_rev 省略   → 用 load 时的当前 rev 作为 transaction base_rev
expected_rev 提供   → 必须等于当前 canonical rev，否则 REVISION_CONFLICT
```

- 校验发生在 **load 之后、任何业务逻辑之前**（含 no-op 短路），
  所以「过期的 expected_rev」永远失败，行为可预测。
- 不按领域改变语义：所有领域完全一致。
- 事务层 `Transaction.commit` 仍然对**全部** touched 对象重校验 `base_rev`；
  `expected_rev` 是入口处的乐观并发门，事务校验是提交前的最终门，两层都要在。

### 4.2 覆盖范围

```text
project.update

goal.update  goal.set_status
milestone.update  milestone.activate  milestone.close  milestone.cancel
task.update  task.set_status  task.assign  task.unassign
task.add_dependency  task.remove_dependency
task.add_label  task.remove_label
task.move_milestone  task.set_parent  task.move_area
member.update  member.activate  member.deactivate
update.update
decision.update  decision.accept  decision.reject  decision.supersede
link.update

area.update  area.set_parent  area.archive  area.restore
artifact.update  artifact.attach  artifact.detach  artifact.remove
```

所有 `*.archive` / `*.restore`（`set_lifecycle`）也接受，因为它们同样修改 canonical object。

### 4.3 集中实现

不复制 `if expected_rev != ...`，统一 helper：

```python
ServiceContext.require_expected_rev(obj_type, model, expected_rev) -> str
```

`task_set_status` 与 `project_update` 里原来各自手写的比较被删除，改为调用该 helper。
`project` 特例：`save_project` 走 `ctx.opened.project`，helper 同样适用。

### 4.4 多对象操作（`decision.supersede`）

`supersede` 同时改两个对象，只接受**一个** `expected_rev`，作用于主目标
（`old_id`，被取代的那个）。`new_id` 的 `base_rev` 在 load 时读取，
由事务层强制校验——两层门都覆盖到，不存在未受保护的写入。

### 4.5 CLI 暴露范围

`--expected-rev` 暴露给常用编辑命令：

```text
project update?   （V0.1 CLI 没有 project update 子命令，Service 层已支持）
goal edit  milestone edit  task edit  member edit  decision edit  link update
area edit  artifact update
```

**必须**包含 `task update`——真实 dogfooding 已证明 `task.update` 缺 `expected_rev`
是实际问题（report §F P2-2）。任务状态快捷命令（`task start/ready/block/…`）也一并带上
`--expected-rev`（同一个 `_set_status` helper，一行成本）。
未暴露 `--expected-rev` 的命令不影响 contract：Service 层始终支持。

---

## 5. CLI changes

```text
pjt task ready <task>                          新增（任务 1）
pjt task artifacts <task>                     新增（task.related_artifacts）
pjt task related-updates <task>                新增（补 P3-6）
pjt task move-area <task> [area]               新增（省略 area = 脱离）
pjt task list --area <area>                   新增过滤
pjt task add --area <area>                    新增
pjt task edit ... --expected-rev REV          新增

pjt area add|list|show|edit|archive|restore|tree
pjt artifact add|list|show|update|remove|attach|detach|verify
pjt graph project                              输出新增 Areas 分区
```

`--area` / `pjt area ...` 的位置参数同时接受 **ID / 短 ID / Area 名**（大小写不敏感），
与 `member` 的 handle 解析同一套思路（`ObjectStore.find_by_name`）。

`pjt artifact add <kind> <locator>` 的 kind 是**位置参数**：

```bash
pjt artifact add file studio_core/debug.py
pjt artifact add --kind url --locator https://… --name "设计文档"
```

---

## 6. Migration / compatibility

### 6.1 `SCHEMA_VERSION` 1.0 → 1.1

兼容变更（新增可选字段 + 新对象类型），不升 major。依据 AGENTS.md「不兼容模型变化才升 major」。

- 旧 Task JSON 没有 `area_id` → pydantic 默认 `null`，正常读取。
- `extra="forbid"` 对**旧数据**无影响（缺字段 OK），对**旧工具读新数据**才是硬失败
  （V1-A 数据需要 ≥ 0.2.0 工具）——这是有意的单向兼容。
- `open_project` 只比较 major，`1.0` / `1.1` 都可正常打开、可继续写入。

### 6.2 `project.migrate` 的两个幂等步骤

```text
1  补齐缺失的 .pjt/objects/<collection>/ 目录（V0.1 项目没有 areas/）
2  project.json 的 schema_version != 1.1 时，走事务 + project.migrated 事件更新
```

第 1 步是**布局**修复，不产生对象/事件；第 2 步是标准事务写路径（WriteLock →
Transaction → event），可回滚、可追溯。

### 6.3 旧项目行为

| 情况 | 行为 |
|---|---|
| 缺 `objects/areas/` | 正常打开；`area.list` 返回 `[]`；`task.area_id = null` |
| 缺 `objects/artifacts/` | 正常打开；`artifact.list` 返回 `[]` |
| `doctor` | `warning: missing object collection dir(s): areas; run 'pjt migrate'`——**不是** corrupted |
| 是否需要删掉重建 `.pjt` | **不需要** |

### 6.4 EFW 真实数据

- **不自动重新解释现有 milestone**。4 个 EFW milestone 保持 milestone。
- 真实 `new/efw/.pjt` 只跑 `open / migrate / doctor / status`（`.pjt/**` 是允许的写入面）。
- Area 迁移效果只在**临时副本**上验证，结论与建议映射见
  `dogfooding/v1a-area-analysis.md`。

---

## 7. 非目标（本轮明确不做）

```text
Git Adapter / GitHub / git scan / commit trailer / branch status   （只为 V1-B 留模型接口）
Search / SQLite / FTS / index
FastAPI / React / Local Web / HTTP API
Remote Server / Sync / Conflict UI
Accounts / ACL / Webhook / KC
Artifact blob / CAS / snapshot / upload
Project templates / workflow engine / Epic / Sprint / Kanban
Task 多 Area / Area 唯一名约束 / Area 进度
```

`system.capabilities` 相应变为：

```json
{ "area": true, "artifact": true, "git": false, "search": false,
  "web": false, "remote": false, "sync": false }
```
