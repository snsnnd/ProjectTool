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
    "git": true,
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

### artifact

```text
artifact.create  artifact.get  artifact.list  artifact.update  artifact.remove
artifact.attach  artifact.detach  artifact.verify  artifact.history
```

全部 V1-A ✓。`artifact.verify` 是**只读查询，不产生事件**；`artifact.remove` 只删引用对象。

```bash
pjt artifact add file studio_core/debug.py --name "Debug transport" --task TSK-…
pjt artifact add --kind url --locator https://…     # 形态 kind 时用选项
pjt artifact attach ART-… --task TSK-… --milestone MLS-…
pjt artifact verify [ART-…]                          # 省略 = 全部
pjt task artifacts TSK-…
```

### git（V1-B，只读感知）

| Method | 作用 | 备注 |
|---|---|---|
| `git.available` | `{available, work_tree, project_subdir, project_root_is_git_root}` | 不可用是**状态**不是异常 |
| `git.status` | `{available, files[{path, status, candidate_areas[], referenced_by_artifacts[]}], pjt_changed, unbound_areas[]}` | 只推导 Area，不回写；`.pjt/**` 默认折叠成一行摘要 |
| `git.log` | `{available, commits[{sha, short_sha, author, subject, linked_task_ids[]}]}` | trailer = `PJT-Task: TSK-…` |
| `git.link_commit` | `{artifact, created, commit}` | **唯一 mutation，且只写 `.pjt`**，不碰仓库；同 commit 幂等 |

**只读不变量写在代码里**：`integrations/git.py` 的 `GitRepo.run()` 强制
`args[0] in READ_ONLY_SUBCOMMANDS`（`rev-parse` / `status` / `log` / `show`），
其余子命令直接 `ValueError`。并且一律加 `--no-optional-locks`，
不让 `git status` 去抢别人的 `.git/index` 锁。

**不提供**：clone / add / commit / checkout / merge / reset / clean / push / fetch ——
那些是 Git 的事，不是记录项目状态的工具的事。

```bash
pjt git status [--area ARA-x] [--no-untracked] [--include-pjt]
pjt git log [--task TSK-x] [--path ui/store.tsx] [--limit N]
pjt git link-commit <sha|HEAD> [--task TSK-x]
```

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
| `artifact.*` | 产物引用 | ✓（V1-A，见下） |
| `git.available` | Git 是否可用 + project root 与 git root 的关系 | ✓（V1-B） |
| `git.status` | 改动的工程文件 + 候选 Area + 引用它的 Artifact | ✓（V1-B） |
| `git.log` | 提交历史（按 `PJT-Task:` trailer / 路径过滤） | ✓（V1-B） |
| `git.link_commit` | 把 commit 登记成 `git_commit` Artifact（**只写 `.pjt`**） | ✓（V1-B） |
| `sync.*` | 远程同步 | ❌ **不做**（docs/06 §V2；`.pjt` 走 Git） |

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
- **Schema 写入门**：项目头 `project.json.schema_version` 必须已经等于工具的
  `SCHEMA_VERSION`，否则**所有 mutating method** 返回 `SCHEMA_MIGRATION_REQUIRED`。
  读路径不受影响（这正是让人能跑 `pjt migrate` 的前提）。
  实现在 `ProjectService.call()` 一处，按 `MethodSpec.mutating` 判定；
  豁免 `project.init` / `project.migrate` / `project.recover`
  （recover 必须永远能跑，否则崩溃残留无法恢复）。
- **rev 校验（完整性门）**：`ObjectStore.load_model` / `list_models` 在把对象变成领域模型时
  强制 `verify_rev(record)`。对象文件被手改、Git merge 或冲突解决动过之后，
  **读取时**就报 `PROJECT_CORRUPTED`，而不是等到下一次写入把它「洗白」重新签名。
  例外：`get_raw` / `list_raw` / `load_raw` 是读字节，不校验；
  `doctor` 用 `check_rev=False`，保证数据已损坏时仍能出报告。
- 列表方法统一支持 `limit`；日志/列表按时间倒序。
- 时间参数（`since` / `until`）接受 ISO-8601 或相对时间 `7d` / `24h` / `30m`。
- 引用校验：新引用不得指向 `lifecycle=deleted` 的对象；
  不得把任务分配到 inactive member 或 `closed/cancelled` milestone。
- Area 位置参数（`--area`、`pjt area …`）同时接受 ID、短 ID、Area 名（大小写不敏感）；
  名称不唯一时报 `INVALID_ARGUMENT`，不猜测。
- `link.resolve` 的 `resolved` 语义是**真的能拿到对方项目的数据**，不是「我填了地址」。
  没有服务器也不发网络请求，所以只有 `kind=local_project` 能真正解析；
  `remote_project` / `git_repository` / `external` 一律 `resolved=false` +
  `verifiable=false` + 说明原因。link 记录本身仍然有效可用。

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
| `SCHEMA_MIGRATION_REQUIRED` | 项目 schema 落后于工具；读允许，**写被拦**，先 `pjt migrate` | 9 |
| `SCHEMA_UNSUPPORTED` / `PROJECT_CORRUPTED` | 结构损坏 / major 版本不兼容 / 对象被外部篡改 | 9 |

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
pjt project show|edit            项目记录（edit 支持 --expected-rev）
pjt status                      项目状态摘要
pjt doctor [--repair]           完整性检查；--repair 先执行事务恢复/陈旧锁清理
pjt migrate                     结构升级

pjt goal add|list|show|edit|achieve|drop|archive|restore   （edit 支持 --expected-rev）
pjt milestone add|list|show|edit|activate|close|cancel|progress
pjt task add|list|show|edit|ready|start|block|review|done|cancel|assign|unassign
          |depend|undepend|label|unlabel|move|move-area|artifacts|related-updates
          |archive|restore|delete|history|set-parent
pjt area add|list|show|tree|edit|archive|restore   （add/edit 支持 --path-pattern）
          |tasks|set-parent|set-owner|match-path|history|activity
pjt artifact add|list|show|edit|attach|detach|remove|verify|history   （attach/detach 支持 --area）
pjt interface init|list|show|register|check|sync   （接口契约：固定模板的 markdown）
pjt member add|list|show|edit|map-git|deactivate|activate|workload|activity|use
pjt update add|list|show|edit|archive|history
pjt decision add|list|show|accept|reject|supersede|history
pjt link add|list|show|remove|resolve|status|map-local|unmap-local
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

#### 表格与终端宽度（V1-B.2）

终端表格里的长标题**按显示宽度截断并加 `…`，不折行**（全角字符按 2 列算）。
折行会让每个任务占两行，十几条就没法扫了。要完整标题用 `pjt task show`，
要程序处理用 `--json` / `--porcelain`。

`pjt status` 的 `computed blocked` 每一行内联显示归属（Area 名 · Milestone 标题），
但**不列举全部 Area** —— 归属信息只出现在 blocked 条目上。
裸 `pjt git`（不带子命令）打印 Git 感知可用性与 project root / git root 的关系。

#### Area 活跃度（V1-C）

```bash
pjt area activity [--area <name>] [--days N] [--limit N]
```

从 Git 推导，**零新增状态**。归因链：commit 的文件 → `Area.path_patterns`
→ Area；commit 的 author name/email → `Member.git`（V1-B 的 `member map-git`）→ Member。
任何一环匹配不上就**如实说匹配不上**（`unmapped_authors`），不猜。

输出刻意分成两半，因为**信息量完全不同**：

- **已提交历史**跟着 Git 走，**所有人都能看到**——这是主体
- **未提交改动**（`local_uncommitted`）**只有本机可见**。**别人的在途工作本工具
  看不到**，所以它被单独标注为 "THIS machine only"，避免让人以为
  「没出现在这里就是没人动」

没有 `path_patterns` 的 Area 列为 `bound=false`，代码无法映射到它，会被提示。

#### 接口的 `kind`：由项目定，工具不校验

第一版把 `kind` 在 CLI help 里写成了封闭集合（`module_api | store_api | event |
protocol | other`）并默认 `module_api` —— 那是把**工具的猜测**焊进了数据。
真实的 kind 取决于项目：EFW 需要 `serial_frame`，别的项目可能是 `graphql` / `rpc`。

现在 `--kind` 是自由字符串、无默认值、不参与校验，不填也合法。
将来做自动索引时，有值的自然被归类，没有的就当没分类。

唯一仍是封闭词汇的是 `status`（`draft` / `review` / `agreed` / `deprecated`），
因为「什么时候算谈完」这条规则依赖它（`review` 之后必须有 `consumers`）。
如果某个项目的流程不是这样，就得改 `project_tool/domain/interfaces.py` 里的
`STATUSES` —— 这是**已知待决项**，还没做成项目级配置。

#### link 的机器本地路径（§7）

link 对象提交进 Git、团队共享，因此 locator 只能是**相对项目根**的路径。
真实项目常在不可相对寻址的位置（不同盘、Windows 盘符、未纳入版本库的目录），
这时把本机绝对路径记进 `.pjt/local/local.toml`：

```bash
pjt link add sib sibling --kind local_project   # 对象里放可移植的 locator
pjt link map-local sib /abs/path/to/sibling    # 本机绝对路径 -> local.toml
pjt link status sib                            # 映射生效，报 resolved
pjt link unmap-local sib                       # 删除映射，回落到对象里的 locator
```

`link.resolve` / `link.status` 优先用 `local.toml` 的映射，并在输出里标明
`local_mapped` / `local_path` 究竟用的是哪一个。

**这两个 method 不发事件**：`local.toml` 不进 Git 而 `events/` 进 Git，
写事件等于把绝对路径抄进共享历史，等于绕过 §7。`member_use` 写 `local.actor`
同理。副作用是「谁在这台机器上配了什么」保持为本机知识。
`link.map_local_path` 也不会因为路径存在就宣称成功——`has_project` 只说明
探测到了 `.pjt/project.json`，真正是否解析成功由 `link.status` 判定（§12）。

## 7. 未来 HTTP 映射（V1/V2 预定）

| Service | REST |
|---|---|
| `task.create/list/get/update` | `POST/GET/PATCH /api/v1/tasks[/{id}]` |
| `task.set_status` | `POST /api/v1/tasks/{id}/status` |
| `task.assign/unassign` | `PUT/DELETE /api/v1/tasks/{id}/owners/{member_id}` |
| `task.add_dependency/remove` | `PUT/DELETE /api/v1/tasks/{id}/dependencies/{target_id}` |
| `milestone.activate/close/cancel` | `POST /api/v1/milestones/{id}/{action}` |
| `decision.accept/reject/supersede` | `POST /api/v1/decisions/{id}/{action}` |
| `area.create/list/get/update` | `POST/GET/PATCH /api/v1/areas[/{id}]` |
| `artifact.create/list/get/update/remove` | `POST/GET/PATCH/DELETE /api/v1/artifacts[/{id}]` |
| `artifact.attach/detach` | `POST/DELETE /api/v1/artifacts/{id}/relations` |
| `artifact.verify` | `POST /api/v1/artifacts/verify` |
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
