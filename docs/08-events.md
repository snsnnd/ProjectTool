# Project Tool — Event Contract（对齐 v0.6.9）

Event 是 Project Tool 的不可变历史。本文件定义 event 契约；未来 Sync /
Webhook / KC 集成都依赖它。

> **本文是事件的唯一登记处。** `tests/test_events.py::test_every_event_type_is_documented`
> 会扫源码里所有真正 append 的 `event_type`，逐个要求出现在本文 §3 的表里。
> 代码里没有集中的 `EventType` 集合，所以那条测试是唯一的闸门——新增事件
> 类型而不来本文登记，CI 会红。
>
> 顺带说明这份文档为什么会漏登记过：V1-C 加的 `task.claimed` /
> `task.released` / `artifact.added` 三个事件就漏了，而 §3 末尾原本写着
> 「新增事件类型必须在本文件登记」。规则写了没人查，所以现在是可执行的。

## 1. 文件与格式

```text
.pjt/events/YYYY/MM/EVT-<ULID>.json
```

```json
{
  "schema_version": "1.1",
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

`actor_id` 可以为 `null`（`project.initialized` 就是——初始化时还没有成员）。

## 2. 不变量

1. **append-only**：`EventStore`（`storage/event_store.py`）是个纯只读类，
   只有 `iter_records` / `get`，**没有任何写方法**。写入只发生在两处：
   `storage/transaction.py`（经 staged / manifest / COMMIT）与
   `storage/project_store.py`（`init` 的特例）。三重防护：EventStore 无写 API、
   事务 manifest 对 event 写项固定 `base_rev=null` / `new_rev=null`、
   roll-forward 跳过已存在的事件文件（`recovery.py` 里
   `if new_rev is None and current_rev is None and final.is_file(): continue`）。
2. 纠正历史 = 产生新事件，绝不篡改旧事件。
3. **没有例外。** 旧版本文档曾写「`pjt migrate` 可以改写历史格式」——
   实现里不存在这条路径：`storage/migrations.py` 只做
   `ensure_object_dirs` + `ensure_gitignore` + 读 Git 判断派生缓存是否被跟踪，
   完全不碰 `events/`；抬 `schema_version` 走标准事务并发 `project.migrated`。
4. `base_rev` = 变更前对象 rev；创建事件为 `null`。
5. `new_rev` = 变更后对象 rev。
6. 同一对象的 event 链满足：`event[i].base_rev == event[i-1].new_rev`（按 ULID 升序）。
7. 对象当前 `rev` == 该对象最后一个 event 的 `new_rev`。
   `pjt doctor` 的 `events.chain` 检查上述两条。
   **legacy 豁免**：若该实体的任一事件 `new_rev is None`（V0 早期遗留），整条链
   跳过、计入 `legacy_chains` 并报 warning，而不是判 error。
8. `transaction_id` 标识一次写入，**不指向任何持久文件**：事务 apply 完成后
   `.pjt/transactions/<TXN-…>/` 立刻被 `shutil.rmtree` 删掉，所以事后查不到
   manifest。它只用来把一次命令产生的多个事件归成一组。
   一次事务内的事件共享同一 `transaction_id` 与 `occurred_at`
   （`occurred_at` 在事务开始时取一次，见 `transaction.py`）。
9. 事件排序：`occurred_at + ULID`（ULID 字典序即创建顺序，够用）。
   **没有 `server_seq`**——不做远程同步（docs/06 §V2），跨设备的顺序由 Git 拓扑决定。

`events` 这个 check 名下还包含另一层校验：`project_id` 一致性、`entity_type`
合法性、以及孤儿事件（引用了已删对象的事件）。rev 链那两条则归在
`events.chain`。

## 3. Payload 契约

`payload` 只包含与本次变更相关的字段。所有 `*` 表示数组。

| event_type | entity | payload | 说明 |
|---|---|---|---|
| `project.initialized` | project | `{name, slug}` | 初始化，`base_rev=null`，`actor_id=null` |
| `project.updated` | project | `{fields*}` | 变更字段名列表 |
| `project.migrated` | project | `{fields*, from, to}` | schema_version 抬升（1.0→1.1） |
| `goal.created` | goal | `{title}` | |
| `goal.updated` | goal | `{fields*}` | |
| `goal.status_changed` | goal | `{from, to}` | 枚举值字符串 |
| `milestone.created` | milestone | `{title}` | |
| `milestone.updated` | milestone | `{fields*}` | |
| `milestone.activated` / `milestone.closed` / `milestone.cancelled` | milestone | `{from, to}` | |
| `area.created` | area | `{name}` | |
| `area.updated` | area | `{fields*}` | `parent_area_id` 变更时附 `{from, to}`；`owner_ids` 变更时附 `{from*, to*, added*, removed*}`（成员 ID 数组） |
| `task.created` | task | `{title}` | |
| `task.updated` | task | `{fields*}`；`milestone_id` 或 `area_id` 变更时附 `{from, to}` | `task.move_area` 也走这里 |
| `task.status_changed` | task | `{from, to}` | inbox/ready/doing/blocked/review/done/cancelled |
| `task.assigned` / `task.unassigned` | task | `{member_id}` | |
| `task.dependency_added` | task | `{target_id, relation}` | depends_on/relates_to/duplicates |
| `task.dependency_removed` | task | `{target_id}` | |
| `task.label_added` / `task.label_removed` | task | `{label}` | |
| `task.claimed` | task | `{member_id, expires_at, ttl_minutes, renewed}` | `renewed=false` 是首次认领，`true` 是续期（续期保留原 `claimed_at`） |
| `task.released` | task | `{member_id}` | |
| `member.added` | member | `{handle}` | |
| `member.updated` | member | `{fields*}` | `git.names` / `git.emails` 是点路径字段 |
| `member.deactivated` / `member.activated` | member | `{}` | |
| `update.created` | update | `{summary}` | |
| `update.updated` | update | `{fields*}` | |
| `decision.created` | decision | `{title}` | |
| `decision.updated` | decision | `{fields*}` | `supersedes_id` 变更时 fields 含它 |
| `decision.status_changed` | decision | `{from, to}` | draft/accepted/rejected/superseded |
| `artifact.created` | artifact | `{name, kind, locator}` | `base_rev=null`；来自 `pjt artifact add` |
| `artifact.added` | artifact | `{name}` | 来自 `interface init` / `interface register`——**接口契约文档的登记**，与 `artifact.created` 是同域两个不同事件 |
| `artifact.updated` | artifact | `{fields*}` | `interface.sync` 发的是点路径：`related_area_ids` / `metadata.interface_kind` |
| `artifact.attached` / `artifact.detached` | artifact | `{relations*: [{relation, id, attached}]}` | `relation` ∈ task/decision/milestone/goal/**area** |
| `artifact.removed` | artifact | `{lifecycle}` | 只删引用对象，不动被引用文件 |
| `link.added` | link | `{name, kind}` | |
| `link.updated` | link | `{fields*}` | |
| `link.removed` | link | `{}` | 软删除（lifecycle=deleted） |
| `git.commit_linked` | artifact | `{sha, short_sha, author, task_id, created}` | 只写 `.pjt`，不写 Git 仓库；同 commit 幂等（`created: false`）。**幂等补关联那条路径只发 `{sha, task_id, created}`**——不会重复登记 short_sha / author |
| `object.archived` / `object.restored` / `object.deleted` | 任意 | `{lifecycle}` | 生命周期变更 |

共 **46** 个事件类型。

约定：

- `fields` 是发生变化的字段名数组（如 `["title", "labels"]`），不保证顺序有意义。
  允许点路径表示嵌套字段（`metadata.interface_kind`、`git.names`）。
- `from` / `to` 通常是枚举字符串值；`area.updated` 改 `parent_area_id` 时是 ID 或
  `null`，改 `owner_ids` 时是**成员 ID 数组**（并额外带 `added` / `removed`）。
- 新增事件类型必须在本文件登记；payload 只增不改，保持向后兼容。
- **纯查询不产生事件**：`artifact.verify` / `area.list` / `task.get` /
  `*.progress` / `task.next` / `task.related_interfaces` 一律无事件。
- **少数 mutation 刻意零事件**：`link.map_local_path` /
  `link.unmap_local_path` 写的是 `.pjt/local/local.toml`（机器本地路径映射，
  不该进共享状态、绝对路径不该跟着 Git 走），`member.use` 只读默认 actor。
  所以「mutation 必有事件」不成立。

## 4. 与事务的关系

- 一次命令（一个 transaction）可以产生多个事件（如 `decision.supersede` 同时产生
  `decision.status_changed` 与 `decision.updated`；`task.claim` 一次也只产生一个）。
- 事务 manifest 列出该事务的全部写入；recovery 保证「对象 + 事件」一起 roll-forward。
- 事件本身不是事务对象：事件文件一旦 apply 即不可再修改。
