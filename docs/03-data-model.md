# Project Tool — 领域数据模型

## 1. ID 规范

主键 = **类型前缀 + ULID**（Crockford Base32，26 字符）。

```text
PRJ-01K8H1ERK8   项目
GOL-01K8HA2K1M   Goal
MLS-01K8H44X30   Milestone
TSK-01K8H2MBQX   Task
MBR-01K8H61N2B   Member
UPD-01K8H82F4T   Update
DEC-01K8H51CJ7   Decision
ARA-01K8H6ZA0T   Area（V1-A）
ART-01K8H71R9M   Artifact（V1-A）
LNK-01K8H91ZXA   Project Link
EVT-01K8HB39NE   Event
TXN-01K8HB38ZF   Transaction
DEV-F12A81       Device
```

规则：

- ULID = 48bit 毫秒时间戳 + 80bit 随机数，**同毫秒内单调递增**；字典序即创建顺序。
- 不使用 `TASK-001` 之类自增编号作为主键（离线多人会冲突）。
- 短 ID：CLI 接受前缀片段，如 `TSK-01K8H2`，项目内无歧义即可；歧义时报 `INVALID_ARGUMENT`。
- UI 可展示人类编号 `#24`（由创建顺序推导），但**它不是主键，不落盘**。

## 2. 统一 Header

`.pjt/objects/**` 与 `.pjt/project.json` 的所有对象共享：

```json
{
  "schema_version": "1.0",
  "id": "TSK-01K8H2MBQX",
  "type": "task",
  "project_id": "PRJ-01K8H1ERK8",

  "version": 4,
  "rev": "sha256:2df70...",

  "lifecycle": "active",

  "created_at": "2026-09-30T10:30:00+08:00",
  "updated_at": "2026-09-30T14:20:00+08:00",

  "created_by": "MBR-01K8H61N2B",
  "updated_by": "MBR-01K8H61N2B"
}
```

| 字段 | 语义 |
|---|---|
| `version` | 逻辑版本，每次修改 +1 |
| `rev` | 内容哈希（见下），并发控制/同步/缓存共用 |
| `lifecycle` | `active` / `archived` / `deleted`，删除默认软删除 |
| `created_by` / `updated_by` | Member ID，可为 `null`（Member 建立前） |

> V0.1 起 `project.json` 同样包含 `version / rev / created_by / updated_by` 并参与
> optimistic concurrency；不重复引入 `lifecycle`（`ProjectStatus.archived` 已覆盖该语义）。

### rev 算法

```text
rev = "sha256:" + sha256( canonical_json(object without "rev") )
canonical_json = json.dumps(..., sort_keys=True, separators=(",",":"), ensure_ascii=False)
```

- 时间统一为带时区 ISO-8601（本地时区偏移），保证序列化稳定。
- 读取时校验 rev；不一致 → `PROJECT_CORRUPTED`（doctor 报告）。
- Pydantic 模型统一 `extra="forbid"`，未知字段直接报错而不是静默丢弃。

## 3. 对象清单与状态枚举

| 对象 | 文件目录 | 状态字段取值 | V0 |
|---|---|---|---|
| Project | `project.json` | `planned active paused completed archived` | ✓ |
| Goal | `objects/goals/` | `proposed active achieved dropped` | ✓ |
| Milestone | `objects/milestones/` | `planned active closed cancelled` | ✓ |
| Area | `objects/areas/` | 无 status（`lifecycle` only） | ✓ |
| Task | `objects/tasks/` | `inbox ready doing blocked review done cancelled` | ✓ |
| Member | `objects/members/` | 布尔 `active` | ✓ |
| Update | `objects/updates/` | 无状态（可 archive） | ✓ |
| Decision | `objects/decisions/` | `draft accepted rejected superseded` | ✓ |
| Link | `objects/links/` | 布尔 `enabled` | ✓ |
| Artifact | `objects/artifacts/` | 无状态 | ✓ |

Priority（统一四级）：`critical > high > normal > low`，默认 `normal`。

Task 状态语义：

| 状态 | 含义 |
|---|---|
| inbox | 已记录但尚未规划 |
| ready | 已明确，可开始 |
| doing | 正在执行 |
| blocked | 当前无法继续（人为标记） |
| review | 工作完成，等待检查 |
| done | 已完成 |
| cancelled | 不再执行 |

**禁止**在 Task 上填 `progress = 72%` 之类的百分比字段。

## 4. 各对象 Schema

### 4.1 Project（`.pjt/project.json`）

```json
{
  "schema_version": "1.0",
  "id": "PRJ-01K8H1ERK8",
  "type": "project",
  "name": "EFW",
  "slug": "efw",
  "description": "Embedded Framework",
  "status": "active",
  "version": 1,
  "rev": "sha256:…",
  "created_at": "2026-09-30T10:00:00+08:00",
  "updated_at": "2026-09-30T10:00:00+08:00",
  "created_by": null,
  "updated_by": null,
  "metadata": {}
}
```

### 4.2 Goal

```json
{
  "id": "GOL-01K8HA2K1M", "type": "goal",
  "title": "完成 EFW Studio 1.0",
  "description": "形成完整的嵌入式应用开发工作流。",
  "status": "active",
  "parent_goal_id": null,
  "success_criteria": ["支持状态机", "支持代码生成"],
  "due_at": null
}
```

### 4.3 Milestone

```json
{
  "id": "MLS-01K8H44X30", "type": "milestone",
  "title": "Debug Runtime MVP",
  "description": "",
  "status": "active",
  "goal_ids": ["GOL-01K8HA2K1M"],
  "due_at": "2026-10-20T23:59:59+08:00"
}
```

**Milestone 不保存 task 数组**；Task 通过 `milestone_id` 反向引用，避免多人改同一文件。

### 4.4 Task

```json
{
  "id": "TSK-01K8H2MBQX", "type": "task",
  "title": "实现 TCP Debug Transport",
  "description": "实现 Debug Runtime TCP 通信。",
  "status": "doing",
  "priority": "high",
  "weight": 2,
  "milestone_id": "MLS-01K8H44X30",
  "area_id": "ARA-01K8H6ZA0T",
  "parent_task_id": null,
  "owner_ids": ["MBR-01K8H61N2B"],
  "labels": ["debug", "network"],
  "dependencies": [
    { "task_id": "TSK-01K8H3M101", "relation": "depends_on" }
  ],
  "acceptance_criteria": ["能够建立 TCP 调试连接"],
  "started_at": "2026-09-30T11:00:00+08:00",
  "completed_at": null,
  "due_at": null
}
```

- `weight` ≥ 1，默认 1，用于进度加权。
- 状态离开 `doing` 不清空 `started_at`；进入 `done` 时写 `completed_at`（再次离开 `done` 时清空）。
- `area_id` 单值（V1-A 不支持一个 Task 多个 Area）；旧数据没有该字段时读作 `null`。
  Task 不保存 `milestone_ids` / `area_ids` 数组，Milestone / Area 反向查询时遍历 Task。

### 4.5 Member（只是项目内身份，不是账号）

```json
{
  "id": "MBR-01K8H61N2B", "type": "member",
  "display_name": "计超",
  "handle": "jichao",
  "roles": ["maintainer", "firmware"],
  "git": { "names": ["jichao"], "emails": [] },
  "external_ids": { "github": "snsnnd" },
  "active": true
}
```

`handle` 项目内唯一、小写；CLI 中所有需要 Member 的地方同时接受 handle 与 ID。

### 4.6 Update（项目进展）

```json
{
  "id": "UPD-01K8H82F4T", "type": "update",
  "summary": "TCP Transport 基本完成",
  "body": "已经实现连接、发送和接收……",
  "task_ids": ["TSK-01K8H2MBQX"],
  "milestone_id": "MLS-01K8H44X30",
  "blockers": ["Windows 下 socket close 行为仍需测试"],
  "next_steps": ["增加异常断线测试", "接入 Debug UI"]
}
```

### 4.7 Decision（一等对象）

```json
{
  "id": "DEC-01K8H51CJ7", "type": "decision",
  "title": "Debug Runtime 使用 TCP 而不是 WebSocket",
  "status": "accepted",
  "context": "需要支持 PC、Jetson 和嵌入式 Linux。",
  "decision": "底层 Transport 使用 TCP。",
  "rationale": "实现简单，语言无关，适合低依赖环境。",
  "alternatives": [
    { "name": "WebSocket", "reason_not_selected": "协议栈更复杂" }
  ],
  "consequences": ["需要自行设计 framing"],
  "related_task_ids": ["TSK-01K8H2MBQX"],
  "supersedes_id": null
}
```

supersede 语义：`DEC-A` 取代 `DEC-B` 时，B.status → `superseded`，A.supersedes_id → B。

### 4.7b Area（稳定的项目分区 / 工作领域）

```json
{
  "id": "ARA-01K8H6ZA0T", "type": "area",
  "name": "Debug",
  "description": "真机调试与传输层",
  "parent_area_id": null
}
```

- Area 回答「这个工作属于哪里？」（模块 / 子系统），Milestone 回答「这个工作服务于哪个阶段？」。
- **没有** `status` / `progress` / `due_at` / `owner`：给它加进度就退化成第二个 Milestone。
  读视图 `area.get` / `area.list` / `graph.project` 也**不返回 progress**。
- `parent_area_id` 支持简单父子层级（`UI ├── Editor └── Debug UI`）；
  环检测与 goal/task parent 复用同一套 `_validate_chain`。
- 名称**不强制唯一**（与 goal/milestone/task 的 title 一致）；按名称引用时不唯一则报
  `INVALID_ARGUMENT: ambiguous area name ...` 并**列出候选 ID**（要求用 ID/短 ID 消歧），
  不是 `NOT_FOUND`，更不猜。
- Area ≠ Label：Label 是自由标签（`bug` / `test` / `high-risk`），没有结构；
  Area 是有类型（`ARA-`）、有层级、可被引用的稳定分区。
  `refs/labels.json` 仍然只聚合 Task.labels，不含 Area。
- Area **不进入** `pjt status`（避免信息过载），只在 `task show` / `task list --area` /
  `graph project` 中出现。

### 4.8 Artifact（V1-A：reference 语义，无内容存储）

```json
{
  "id": "ART-01K8H71R9M", "type": "artifact",
  "name": "TCP Transport implementation",
  "description": "",
  "kind": "file",
  "locator": "studio_core/debug.py",
  "related_task_ids": ["TSK-01K8H2MBQX"],
  "related_decision_ids": ["DEC-01K8H51CJ7"],
  "related_milestone_ids": [],
  "related_goal_ids": [],
  "metadata": {}
}
```

`kind` ∈ `file url git_commit git_branch release build report dataset model document
design hardware image other`。

**Reference，不是存储**：

- 只保存 `kind` + `locator`；没有 blob / CAS / snapshot / upload / 远端存储。
- **绝不修改被引用的文件**：`artifact.remove` 只软删除 Artifact 对象
  （`lifecycle=deleted`），不 copy / move / delete / rename / rewrite 工程文件。
- 关系数组放在 Artifact 上（不建独立 relation 对象）：`artifact.attach --task T`
  只写一个文件，与并发编辑 Task 的操作不冲突；反向查询（`task.related_artifacts`）
  是 file scan 派生读。

**Locator 规则**（canonical 形态：相对 POSIX 路径，统一 `/`）：

| kind | 例子 | 校验 |
|---|---|---|
| `file` | `studio_core/debug.py` | 必须是 project-relative 路径；禁绝对路径 / 盘符 / UNC / `..` / `.pjt/**` / 控制字符。**允许普通空格**（`docs/Design Notes.md` 是真实工程常态） |
| `url` | `https://…` | http(s) + netloc（**不做网络请求**） |
| `git_commit` | `abc123` | 4–40 位十六进制（Git Adapter 未启用，只存引用） |
| `git_branch` | `feature/foo` | git ref-name 字符集，无 `..` |
| 其余 10 种 | `brd rev C` | 不透明引用；只守住「非机器本地绝对路径」「不逃出 project root」 |

**控制字符**（换行 / 制表 / ESC …）在**所有** kind 的 locator 里都非法——它们会破坏 CLI 表格
输出、事件 JSON 与 payload 的可读性。普通空格只在 `file` / 10 种不透明 kind 里合法；
`url`（RFC 3986 要求百分号编码）、`git_commit`、`git_branch` 禁止任何空白。

`artifact.verify` 是**纯查询**：不产生事件、不修改文件。`file` 检查存在性，
`url` 只校验格式，`git_*` 报告「adapter 未启用」，其余标记 `skipped`。
doctor 对「file 不存在」报 **warning**（分支切换/删除是正常现象），
对「locator 越界」和「related ID 指向不存在的对象」报 **error**。

### 4.9 Project Link

```json
{
  "id": "LNK-01K8H91ZXA", "type": "link",
  "name": "firmware",
  "target": {
    "kind": "local_project",
    "project_id": "PRJ-01K9XXXXXX",
    "locator": "../firmware"
  },
  "mode": "aggregate",
  "enabled": true
}
```

- `target.kind` ∈ `local_project remote_project git_repository external`。
- `mode` ∈ `reference`（只显示关联）/ `aggregate`（父项目聚合子项目状态）。
- **只允许相对路径 / URL / project ID**；机器特定绝对路径写 `.pjt/local/local.toml`。

### 4.10 Event（不可变）

```json
{
  "schema_version": "1.0",
  "id": "EVT-01K8HB39NE",
  "transaction_id": "TXN-01K8HB38ZF",
  "event_type": "task.status_changed",
  "project_id": "PRJ-01K8H1ERK8",
  "entity_type": "task",
  "entity_id": "TSK-01K8H2MBQX",
  "actor_id": "MBR-01K8H61N2B",
  "device_id": "DEV-F12A81",
  "occurred_at": "2026-09-30T14:20:01+08:00",
  "base_rev": "sha256:aaa...",
  "new_rev": "sha256:bbb...",
  "payload": { "from": "doing", "to": "review" }
}
```

事件类型命名（标准集合）：

```text
project.initialized / project.updated
goal.created / goal.updated / goal.status_changed
milestone.created / milestone.updated / milestone.activated / milestone.closed / milestone.cancelled
area.created / area.updated
task.created / task.updated / task.status_changed / task.assigned / task.unassigned
task.dependency_added / task.dependency_removed / task.label_added / task.label_removed
member.added / member.updated / member.deactivated / member.activated
update.created / update.updated
decision.created / decision.updated / decision.status_changed
link.added / link.updated / link.removed
object.archived / object.deleted / object.restored
```

纠正历史 = 产生新事件，**永不修改旧事件**。

## 5. 派生计算

### 5.1 Milestone 进度

```text
progress = Σ(done task weight) / Σ(non-cancelled task weight)
```

`cancelled` 不进分母；分母为 0 时进度为 0，并标记 `empty = true`。

### 5.2 computed blocked

```text
A depends_on B 且 B 未 done  →  A.computed_blocked = true, blocked_by = [B...]
```

- 只读推导，**不改 A.status**。
- `A.status == blocked` 是人为阻塞，与 computed blocked 分开呈现。
- 只统计 `relation == "depends_on"`；`relates_to`、`duplicates` 不参与阻塞与环检测。

### 5.3 Project 状态

不以单一全局百分比呈现，而是：

```text
active milestone + 其 progress
task 状态分布（inbox/ready/doing/blocked/review/done/cancelled）
computed blocked 列表
最近事件（由 events 推导）
成员活跃任务数
```

## 6. 关系一览

```text
Goal        parent_goal_id → Goal
Milestone   goal_ids → Goal[]
Area        parent_area_id → Area
Task        milestone_id → Milestone         area_id → Area
            parent_task_id → Task
            owner_ids → Member[]             dependencies → Task[]
Update      task_ids → Task[]                milestone_id → Milestone
Decision    related_task_ids → Task[]        supersedes_id → Decision
Artifact    related_task_ids → Task[]        related_decision_ids → Decision[]
            related_milestone_ids → Milestone[]   related_goal_ids → Goal[]
Link        target.project_id → Project（另一项目）
Event       entity_id → 任意对象
```

引用完整性由 doctor 校验；悬空引用报告为 `BROKEN_LINK`。

## 7. 领域校验规则（V0.1）

领域校验统一在 ServiceContext 层执行，所有客户端（CLI / 未来 Web / SDK）行为一致。

| 规则 | 行为 | 错误码 |
|---|---|---|
| 空 / 纯空白 title | 拒绝（project/goal/milestone/task/decision/link） | `INVALID_ARGUMENT` |
| title > 500 字符 | 拒绝 | `INVALID_ARGUMENT` |
| label 为空 / > 64 字符 | 拒绝 | `INVALID_ARGUMENT` |
| handle 非法（`^[a-z0-9][a-z0-9._-]*$`）/ > 64 字符 | 拒绝 | `INVALID_ARGUMENT` |
| 文本（description/body/…）> 200000 字符 | 拒绝 | `INVALID_ARGUMENT` |
| 重复 label / owner | 去重，不报错 | — |
| 重复 dependency / 重复 assign | 幂等 no-op，不产生事件 | — |
| self dependency / self parent | 拒绝 | `INVALID_ARGUMENT` |
| task dependency 环（depends_on） | 拒绝 | `DEPENDENCY_CYCLE` |
| goal parent 环 / area parent 环 / task parent 环 | 拒绝 | `HIERARCHY_CYCLE` |
| area self parent | 拒绝 | `INVALID_ARGUMENT` |
| Task 引用 deleted area | 拒绝 | `INVALID_ARGUMENT` |
| artifact.file locator 绝对路径 / `..` / `.pjt/**` | 拒绝 | `INVALID_ARGUMENT` |
| 非 file kind 的 locator 是机器本地绝对路径 / 含 `..` | 拒绝 | `INVALID_ARGUMENT` |
| artifact.url 非 http(s) / 缺 netloc | 拒绝 | `INVALID_ARGUMENT` |
| `expected_rev` 与当前 rev 不符 | 拒绝（省略则用当前 rev 作 base_rev） | `REVISION_CONFLICT` |
| decision supersede 环 / 自我取代 | 拒绝 | `HIERARCHY_CYCLE` / `INVALID_ARGUMENT` |
| 新引用 deleted 对象 | 拒绝 | `INVALID_ARGUMENT` |
| assign inactive / deleted member | 拒绝 | `INVALID_ARGUMENT` |
| 新增任务到 closed/cancelled milestone | 拒绝 | `INVALID_ARGUMENT` |
| 已属于 closed milestone 的任务同值保持 | 允许（no-op） | — |
| 编辑 done task（标签/描述/优先级等） | 允许（保留 completed_at） | — |
| done task 回到其它状态 | 允许（清空 completed_at） | — |
| 软删除对象 | 允许，可 restore | — |

说明：

- 历史数据中已有的悬空引用 / 删除引用不做强制清除；doctor 以 warning 呈现。
- `progress`、`computed_blocked` 不是可写字段，永远由真实 Task 状态推导。
- Event 不可修改；纠正历史必须产生新事件。
