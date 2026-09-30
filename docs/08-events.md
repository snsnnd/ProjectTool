# Project Tool — Event Contract（V0.1）

Event 是 Project Tool 的不可变历史。本文件定义 V0.1 的 event 契约；
未来 Sync / Webhook / KC 集成都依赖它。

## 1. 文件与格式

```text
.pjt/events/YYYY/MM/EVT-<ULID>.json
```

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

## 2. 不变量

1. **append-only**：EventStore 只提供 append / read；没有 update/delete API。
2. 纠正历史 = 产生新事件，绝不篡改旧事件。
3. 例外：`pjt migrate` 在明确版本迁移时可以改写历史格式（V0.1 无迁移步骤）。
4. `base_rev` = 变更前对象 rev；创建事件为 `null`。
5. `new_rev` = 变更后对象 rev。
6. 同一对象的 event 链满足：`event[i].base_rev == event[i-1].new_rev`（按 ULID 升序）。
7. 对象当前 `rev` == 该对象最后一个 event 的 `new_rev`。
   `pjt doctor` 的 `events.chain` 检查上述两条。
8. `transaction_id` 指向 `.pjt/transactions/` 中对应的 manifest；一次事务内的事件
   共享同一 `transaction_id` 与 `occurred_at`。
9. 事件排序：本地用 `occurred_at + ULID`；远程同步后由服务端附加 `server_seq`。

## 3. Payload 契约

`payload` 只包含与本次变更相关的字段。所有 `*` 表示数组。

| event_type | entity | payload | 说明 |
|---|---|---|---|
| `project.initialized` | project | `{name, slug}` | 初始化，`base_rev=null` |
| `project.updated` | project | `{fields*}` | 变更字段名列表 |
| `goal.created` | goal | `{title}` | |
| `goal.updated` | goal | `{fields*}` | |
| `goal.status_changed` | goal | `{from, to}` | 枚举值字符串 |
| `milestone.created` | milestone | `{title}` | |
| `milestone.updated` | milestone | `{fields*}` | |
| `milestone.activated` / `milestone.closed` / `milestone.cancelled` | milestone | `{from, to}` | |
| `area.created` | area | `{name}` | |
| `area.updated` | area | `{fields*}` | `parent_area_id` 变更时附 `{from, to}` |
| `task.created` | task | `{title}` | |
| `task.updated` | task | `{fields*}`；`milestone_id` 变更时附 `{from, to}` | |
| `task.status_changed` | task | `{from, to}` | inbox/ready/doing/blocked/review/done/cancelled |
| `task.assigned` / `task.unassigned` | task | `{member_id}` | |
| `task.dependency_added` | task | `{target_id, relation}` | depends_on/relates_to/duplicates |
| `task.dependency_removed` | task | `{target_id}` | |
| `task.label_added` / `task.label_removed` | task | `{label}` | |
| `project.migrated` | project | `{fields*, from, to}` | schema_version 抬升（1.0→1.1） |
| `member.added` | member | `{handle}` | |
| `member.updated` | member | `{fields*}` | |
| `member.deactivated` / `member.activated` | member | `{}` | |
| `update.created` | update | `{summary}` | |
| `update.updated` | update | `{fields*}` | |
| `decision.created` | decision | `{title}` | |
| `decision.updated` | decision | `{fields*}` | `supersedes_id` 变更时 fields 含它 |
| `decision.status_changed` | decision | `{from, to}` | draft/accepted/rejected/superseded |
| `link.added` | link | `{name, kind}` | |
| `link.updated` | link | `{fields*}` | |
| `link.removed` | link | `{}` | 软删除（lifecycle=deleted） |
| `object.archived` / `object.restored` / `object.deleted` | 任意 | `{lifecycle}` | 生命周期变更 |

约定：

- `fields` 是发生变化的字段名数组（如 `["title", "labels"]`），不保证顺序有意义。
- `from` / `to` 是枚举的字符串值（`area.updated` 里是 ID 或 `null`）。
- 新增事件类型必须在本文件登记；payload 只增不改，保持向后兼容。
- **纯查询不产生事件**：`artifact.verify` / `area.list` / `task.get` / `*.progress` 一律无事件。
  只有 mutation 才有事件。

## 4. 与事务的关系

- 一次命令（一个 transaction）可以产生多个事件（如 `decision.supersede` 同时产生
  `decision.status_changed` 与 `decision.updated`）。
- 事务 manifest 列出该事务的全部写入；recovery 保证「对象 + 事件」一起 roll-forward。
- 事件本身不是事务对象：事件文件一旦 apply 即不可再修改。
