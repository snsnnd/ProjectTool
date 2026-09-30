# Project Tool — 接口规范（V0.1）

本文件定义三类接口：

1. **Application Service RPC**：CLI / Web（V1）/ SDK 共用，V0.1 唯一实现。
2. **CLI**：`pjt` 命令面。
3. **HTTP REST / Sync**：V1/V2 的预定映射，V0.1 不实现，但命名与 Service 一一对应。

## 1. Service RPC 协议

```json
{ "id": "req-001", "method": "task.create", "params": {} }
```

```json
{ "id": "req-001", "result": {} }
```

```json
{ "id": "req-001", "error": { "code": "NOT_FOUND", "message": "…", "details": {} } }
```

dispatch 由 `application/registry.py` 的显式 `MethodSpec` 表完成（不再是动态 getattr）。
每个 method 带 `mutating / category / description` 元数据；未知 method → `INVALID_ARGUMENT`。

## 2. 能力发现

```http
system.capabilities
```

```json
{
  "protocol_version": 1,
  "schema_version": "1.1",
  "methods": ["area.archive", "goal.archive", "..."],
  "features": {
    "area": true,
    "artifact": false,
    "git": false,
    "search": false,
    "web": false,
    "remote": false,
    "sync": false
  }
}
```

`features` 是**能力发现**的唯一来源：客户端据此决定是否展示 Area / Artifact 相关 UI，
而不是靠猜 method 是否存在。

## 3. 方法总表（V0.1 状态）

图例：✓ 已实现 · ○ 预留（V1+）

### system / project

| Method | 作用 | V0.1 |
|---|---|---|
| `system.info` | 工具版本、schema 版本 | ✓ |
| `system.capabilities` | 能力发现（methods + features） | ✓ |
| `project.init` | 初始化项目（path 级别，不要求已打开） | ✓ |
| `project.open` | 打开项目返回摘要 | ✓ |
| `project.get` | 项目信息（含 version/rev） | ✓ |
| `project.update` | 修改项目（支持 `expected_rev`） | ✓ |
| `project.status` | 项目状态摘要 | ✓ |
| `project.doctor` | 完整性检查（repairable 标记） | ✓ |
| `project.migrate` | schema 升级入口（1.0→1.1：补齐集合目录 + 抬升 project schema_version） | ✓ |
| `project.recover` | 事务 roll-forward + 清理陈旧锁 | ✓ |

### area

```text
area.create  area.get  area.list  area.update  area.set_parent
area.archive  area.restore  area.tasks  area.history
```

全部 V1-A ✓。Area 没有 status / progress；`area.*` 全部接受 `expected_rev`（create 除外）。

### goal / milestone / task

```text
goal.create  goal.get  goal.list  goal.update  goal.set_status  goal.archive  goal.restore
milestone.create  milestone.get  milestone.list  milestone.update
milestone.activate  milestone.close  milestone.cancel  milestone.progress
task.create  task.get  task.list  task.update  task.set_status
task.assign  task.unassign  task.add_dependency  task.remove_dependency
task.add_label  task.remove_label  task.move_milestone  task.move_area  task.set_parent
task.archive  task.restore  task.delete
task.related_updates  task.related_artifacts  task.history
```

全部 V0.1 ✓（`task.move_area` / `task.related_artifacts` 为 V1-A 新增）。

### member / update / decision / link

```text
member.add  member.get  member.list  member.update  member.deactivate  member.activate
member.workload  member.activity  member.map_git_identity
update.create  update.get  update.list  update.update  update.archive  update.history
decision.create  decision.get  decision.list  decision.update
decision.accept  decision.reject  decision.supersede  decision.history
link.add  link.get  link.list  link.update  link.remove  link.resolve  link.status
```

全部 V0.1 ✓。

### log / graph / search / artifact / git / sync

| Method | 作用 | V0.1 |
|---|---|---|
| `log.list` `log.get` `log.entity` `log.member` `log.since` | 事件历史 | ✓ |
| `graph.project` `graph.tasks` `graph.dependencies` `graph.links` | 项目图 | ✓ |
| `search.query` | 全文/结构化搜索 | ○（V1-B） |
| `artifact.*` | 产物引用 | ○（V1-A，见下） |
| `git.*` | Git 集成 | ○（V1） |
| `sync.*` | 远程同步 | ○（V2） |

## 4. 关键参数约定

- 所有 `*_id` 参数接受**完整 ID 或短 ID**（如 `TSK-01K8H2`）。
- Member 位置参数同时接受 `handle` 或 `MBR-…`。
- **统一并发契约**：所有修改已有 canonical object 的 operation 都接受可选
  `expected_rev`，语义完全一致，不按领域变化：

  ```text
  expected_rev 省略 -> 用 load 时的当前 rev 作为事务 base_rev
  expected_rev 提供 -> 必须等于当前 canonical rev，否则 REVISION_CONFLICT
  ```

  覆盖：`project.update` / `goal.update` / `goal.set_status` /
  `milestone.update|activate|close|cancel` / `task.update|set_status|assign|unassign|
  add_dependency|remove_dependency|add_label|remove_label|move_milestone|move_area|set_parent`
  / `member.update|activate|deactivate|map_git_identity` / `update.update` /
  `decision.update|accept|reject|supersede` / `link.update|link.remove` /
  `area.update|set_parent|archive|restore` / `artifact.update|attach|detach|remove`
  以及全部 `*.archive` / `*.restore`。

  实现在 `ServiceContext.require_expected_rev()` 一处，不允许各领域复制比较逻辑。
  此外每个事务在提交前重新校验全部 `base_rev`，并发修改不会被静默覆盖。
- 多对象操作（`decision.supersede`）只接受一个 `expected_rev`，作用于主目标 `old_id`；
  `new_id` 的 base_rev 在 load 时读取并由事务层强制校验。
- 列表方法统一支持 `limit`；日志/列表按时间倒序。
- 时间参数（`since` / `until`）接受 ISO-8601 或相对时间 `7d` / `24h` / `30m`。
- 引用校验：新引用不得指向 `lifecycle=deleted` 的对象；
  不得把任务分配到 inactive member 或 `closed/cancelled` milestone。
- Area 位置参数（`--area`、`pjt area …`）同时接受 ID、短 ID、Area 名（大小写不敏感）；
  名称不唯一时报 `INVALID_ARGUMENT`，不猜测。

示例：

```json
{
  "method": "task.set_status",
  "params": { "task_id": "TSK-01K8H2", "status": "doing", "expected_rev": "sha256:…" }
}
```

## 5. 错误码与退出码

| code | 含义 | CLI exit |
|---|---|---:|
| — | 成功 | 0 |
| `INTERNAL` / `IO_ERROR` / `GIT_ERROR` | 通用失败 | 1 |
| `INVALID_ARGUMENT` | 参数非法、短 ID 歧义 | 3 |
| `NOT_FOUND` | 对象/项目不存在 | 4 |
| `ALREADY_EXISTS` | handle 等唯一约束冲突 | 3 |
| `CONFLICT` / `REVISION_CONFLICT` | 并发修改、expected_rev 不符 | 5 |
| `DEPENDENCY_CYCLE` | task dependency 成环 | 3 |
| `HIERARCHY_CYCLE` | goal/task parent 或 decision supersede 成环 | 3 |
| `BROKEN_LINK` | 引用悬空 | 3 |
| `PERMISSION_DENIED` / `AUTH_REQUIRED` | 权限（V2） | 6 |
| `REMOTE_UNAVAILABLE` | 远程不可达（V2） | 7 |
| `SYNC_CONFLICT` | 同步冲突（V2） | 8 |
| `SCHEMA_UNSUPPORTED` / `PROJECT_CORRUPTED` | 结构损坏/版本不支持 | 9 |

Usage error（Typer 解析失败）固定 exit 2。

## 6. CLI 规范

### 全局选项

```text
pjt [--json] [--porcelain] [--as MEMBER] [-C PATH] <command>

--json       输出 RPC 形式的 JSON（机器可读）
--porcelain  稳定纯文本，列分隔固定，供脚本解析
--as         指定本次操作的 Actor（覆盖 local.toml）
-C           指定项目路径（默认从 cwd 向上查找 .pjt）
--version    版本
```

### 命令面（V0.1）

```text
pjt init [PATH]                 初始化
pjt status                      项目状态摘要
pjt doctor [--repair]           完整性检查；--repair 先执行事务恢复/陈旧锁清理
pjt migrate                     结构升级

pjt goal add|list|show|edit|achieve|drop   （edit 支持 --expected-rev）
pjt milestone add|list|show|edit|activate|close|cancel|progress
pjt task add|list|show|edit|ready|start|block|review|done|cancel|assign|unassign
          |depend|undepend|label|unlabel|move|move-area|artifacts|related-updates
          |archive|restore|delete|history
pjt area add|list|show|tree|edit|archive|restore
pjt member add|list|show|edit|deactivate|activate|workload|activity|use
pjt update add|list|show
pjt decision add|list|show|accept|reject|supersede
pjt link add|list|show|remove|resolve
pjt log [--task --member --since --type]
pjt graph [tasks|milestone <id>|projects]
```

编辑类命令统一支持 `--expected-rev REV`（`goal/milestone/task/member/decision/link/area/artifact edit`），
不匹配时 exit 5 / `REVISION_CONFLICT`。

说明：`member use` 只写本机 `.pjt/local/local.toml` 的默认 Actor，不产生项目事件；
`update add` 省略文本时读取 stdin 或 `$EDITOR`。

### 输出约定

- 默认：人类可读（表格/树）。
- `--json`：RPC 响应包（`{"id","result"}` 或 `{"id","error"}`），`ensure_ascii=False`。
- `--porcelain`：`field<TAB>field`，无颜色无表头，专供脚本。
- 错误输出到 stderr，带 `code`。

## 7. 未来 HTTP 映射（V1/V2 预定）

| Service | REST |
|---|---|
| `task.create/list/get/update` | `POST/GET/PATCH /api/v1/tasks[/{id}]` |
| `task.set_status` | `POST /api/v1/tasks/{id}/status` |
| `task.assign/unassign` | `PUT/DELETE /api/v1/tasks/{id}/owners/{member_id}` |
| `task.add_dependency/remove` | `PUT/DELETE /api/v1/tasks/{id}/dependencies/{target_id}` |
| `milestone.activate/close/cancel` | `POST /api/v1/milestones/{id}/{action}` |
| `decision.accept/reject/supersede` | `POST /api/v1/decisions/{id}/{action}` |
| `project.recover` | `POST /api/v1/project/recover` |
| `log.list` | `GET /api/v1/events?entity_type=&since=&limit=&cursor=` |
| `search.query` | `GET /api/v1/search?q=&types=&status=&owner=&label=` |
| `graph.*` | `GET /api/v1/graph?type=&milestone=&depth=` |
| `sync.pull/push` | `GET /api/v1/sync/pull?cursor=` / `POST /api/v1/sync/push` |

并发控制：`GET` 返回 `ETag`，`PATCH` 带 `If-Match`，冲突 → `409`
+ `{code, entity_id, expected_rev, actual_rev}`。

## 8. 同步协议摘要（V2 预定）

- 同步单元 = 对象快照 + 事件 + rev，不是上传整个 `.pjt`。
- `pjt sync` = pull → resolve/apply → push。
- 冲突判定：Local rev = B，Server rev = C，但二者 base 均为 A → 真冲突，
  写入 `.pjt/local/conflicts/`，不做 Last-Write-Wins。
- 事件排序：本地 `occurred_at + ULID`；服务端附加 `server_seq` 提供全局时间线。
