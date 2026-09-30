# Project Tool — 接口规范

本文件定义三类接口：

1. **Application Service RPC**：CLI / Web（V1）/ SDK 共用，V0 唯一实现。
2. **CLI**：`pjt` 命令面。
3. **HTTP REST / Sync**：V1/V2 的预定映射，V0 不实现，但命名与 Service 一一对应。

## 1. Service RPC 协议

请求 / 响应（与规范 §30 一致）：

```json
{ "id": "req-001", "method": "task.create", "params": {} }
```

```json
{ "id": "req-001", "result": {} }
```

```json
{ "id": "req-001", "error": { "code": "NOT_FOUND", "message": "…", "details": {} } }
```

## 2. 方法总表（V0 状态）

图例：✓ 已实现 · ○ 预留（V1+）

### system

| Method | 作用 | V0 |
|---|---|---|
| `system.info` | 工具版本、schema 版本 | ✓ |

### project

| Method | 作用 | V0 |
|---|---|---|
| `project.init` | 初始化项目（path 级别，不要求已打开） | ✓ |
| `project.open` | 打开项目返回摘要 | ✓ |
| `project.get` | 项目信息 | ✓ |
| `project.update` | 修改项目 | ✓ |
| `project.status` | 项目状态摘要 | ✓ |
| `project.doctor` | 完整性检查 | ✓ |
| `project.migrate` | schema 升级入口（1.0 暂为 no-op + 校验） | ✓ |

### goal / milestone / task

```text
goal.create  goal.get  goal.list  goal.update  goal.set_status  goal.archive  goal.restore
milestone.create  milestone.get  milestone.list  milestone.update
milestone.activate  milestone.close  milestone.cancel  milestone.progress
task.create  task.get  task.list  task.update  task.set_status
task.assign  task.unassign  task.add_dependency  task.remove_dependency
task.add_label  task.remove_label  task.move_milestone  task.set_parent
task.archive  task.restore  task.delete
task.related_updates  task.history
```

全部 V0 ✓。

### member / update / decision / link

```text
member.add  member.get  member.list  member.update  member.deactivate  member.activate
member.workload  member.activity  member.map_git_identity
update.create  update.get  update.list  update.update  update.archive  update.history
decision.create  decision.get  decision.list  decision.update
decision.accept  decision.reject  decision.supersede  decision.history
link.add  link.get  link.list  link.update  link.remove  link.resolve  link.status
```

全部 V0 ✓。

### log / graph / search / artifact / git / sync

| Method | 作用 | V0 |
|---|---|---|
| `log.list` `log.get` `log.entity` `log.member` `log.since` | 事件历史 | ✓ |
| `graph.project` `graph.tasks` `graph.dependencies` `graph.links` | 项目图 | ✓ |
| `search.query` | 全文/结构化搜索 | ○（V1） |
| `artifact.*` | 产物 | ○（V1） |
| `git.*` | Git 集成 | ○（V1） |
| `sync.*` | 远程同步 | ○（V2） |

## 3. 关键参数约定

- 所有 `*_id` 参数接受**完整 ID 或短 ID**（如 `TSK-01K8H2`）。
- Member 位置参数同时接受 `handle` 或 `MBR-…`。
- 修改类方法可选 `expected_rev`；不匹配 → `REVISION_CONFLICT`。
- 列表方法统一支持 `limit`；日志/列表按时间倒序。
- 时间参数（`since` / `until`）接受 ISO-8601 或相对时间 `7d` / `24h` / `30m`。

示例：

```json
{
  "method": "task.set_status",
  "params": { "task_id": "TSK-01K8H2", "status": "doing", "expected_rev": "sha256:…" }
}
```

## 4. 错误码与退出码

| code | 含义 | CLI exit |
|---|---|---:|
| — | 成功 | 0 |
| `INTERNAL` / `IO_ERROR` / `GIT_ERROR` | 通用失败 | 1 |
| `INVALID_ARGUMENT` | 参数非法、短 ID 歧义 | 2/3 |
| `NOT_FOUND` | 对象/项目不存在 | 4 |
| `ALREADY_EXISTS` | handle 等唯一约束冲突 | 3 |
| `CONFLICT` / `REVISION_CONFLICT` | 并发修改、expected_rev 不符 | 5 |
| `DEPENDENCY_CYCLE` / `BROKEN_LINK` | 依赖成环、引用悬空 | 3 |
| `PERMISSION_DENIED` / `AUTH_REQUIRED` | 权限（V2） | 6 |
| `REMOTE_UNAVAILABLE` | 远程不可达（V2） | 7 |
| `SYNC_CONFLICT` | 同步冲突（V2） | 8 |
| `SCHEMA_UNSUPPORTED` / `PROJECT_CORRUPTED` | 结构损坏/版本不支持 | 9 |

Usage error（Typer 解析失败）固定 exit 2。

## 5. CLI 规范

### 全局选项

```text
pjt [--json] [--porcelain] [--as MEMBER] [-C PATH] <command>

--json       输出 RPC 形式的 JSON（机器可读）
--porcelain  稳定纯文本，列分隔固定，供脚本解析
--as         指定本次操作的 Actor（覆盖 local.toml）
-C           指定项目路径（默认从 cwd 向上查找 .pjt）
--version    版本
```

### 命令面（V0）

```text
pjt init [PATH]                 初始化
pjt status                      项目状态摘要
pjt doctor                      完整性检查
pjt migrate                     结构升级

pjt goal add|list|show|edit|achieve|drop
pjt milestone add|list|show|edit|activate|close|cancel|progress
pjt task add|list|show|start|block|review|done|cancel|assign|unassign|depend|undepend
          |label|unlabel|move|archive|restore|delete|history
pjt member add|list|show|edit|deactivate|activate|workload|activity|use
pjt update add|list|show
pjt decision add|list|show|accept|reject|supersede
pjt link add|list|show|remove|resolve
pjt log [--task --member --since --type]
pjt graph [tasks|milestone <id>|projects]
```

说明：`member use` 只写本机 `.pjt/local/local.toml` 的默认 Actor，不产生项目事件；
`update add` 省略文本时读取 stdin 或 `$EDITOR`。

示例：

```bash
pjt init
pjt member add jichao --name "计超" --role maintainer
pjt goal add "完成 EFW Studio 1.0"
pjt milestone add "Debug Runtime" --goal GOL-xxx
pjt task add "实现 TCP Transport" --owner jichao --milestone MLS-xxx --priority high --weight 2
pjt task done TSK-xxx
pjt update add --task TSK-xxx "TCP 通信完成，开始处理断线重连"
pjt log --since 7d
pjt graph tasks
```

### 输出约定

- 默认：人类可读（表格/树）。
- `--json`：RPC 响应包（`{"id","result"}` 或 `{"id","error"}`），`ensure_ascii=False`。
- `--porcelain`：`field<TAB>field`，无颜色无表头，专供脚本。
- 错误输出到 stderr，带 `code`。

## 6. 未来 HTTP 映射（V1/V2 预定）

| Service | REST |
|---|---|
| `task.create/list/get/update` | `POST/GET/PATCH /api/v1/tasks[/{id}]` |
| `task.set_status` | `POST /api/v1/tasks/{id}/status` |
| `task.assign/unassign` | `PUT/DELETE /api/v1/tasks/{id}/owners/{member_id}` |
| `task.add_dependency/remove` | `PUT/DELETE /api/v1/tasks/{id}/dependencies/{target_id}` |
| `milestone.activate/close/cancel` | `POST /api/v1/milestones/{id}/{action}` |
| `decision.accept/reject/supersede` | `POST /api/v1/decisions/{id}/{action}` |
| `log.list` | `GET /api/v1/events?entity_type=&since=&limit=&cursor=` |
| `search.query` | `GET /api/v1/search?q=&types=&status=&owner=&label=` |
| `graph.*` | `GET /api/v1/graph?type=&milestone=&depth=` |
| `sync.pull/push` | `GET /api/v1/sync/pull?cursor=` / `POST /api/v1/sync/push` |

并发控制：`GET` 返回 `ETag`，`PATCH` 带 `If-Match`，冲突 → `409` + `{code, entity_id, expected_rev, actual_rev}`。

## 7. 同步协议摘要（V2 预定）

- 同步单元 = 对象快照 + 事件 + rev，不是上传整个 `.pjt`。
- `pjt sync` = pull → resolve/apply → push。
- 冲突判定：Local rev = B，Server rev = C，但二者 base 均为 A → 真冲突，写入 `.pjt/local/conflicts/`，不做 Last-Write-Wins。
- 事件排序：本地 `occurred_at + ULID`；服务端附加 `server_seq` 提供全局时间线。
