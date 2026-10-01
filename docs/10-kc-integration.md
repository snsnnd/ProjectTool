# Project Tool — KC 接入参考

> 面向 KC 侧：怎么读 Project Tool 的数据、身份怎么映射、哪些红线不能碰、
> 哪些能力 KC 自己拥有。**不含**实现细节，实现见 `docs/02`~`docs/05`。

## 0. 三十秒版本

```text
Git          →  代码发生了什么
Project Tool →  项目发生了什么，以及为什么
KC           →  项目属于谁、谁可以参与、组织如何运行
```

| | 归属 |
|---|---|
| 代码、diff、blame、代码评审 | Git |
| task / milestone / area / 决策 / 事件历史 | Project Tool（`.pjt/`） |
| **账号、组织、可见性、ACL** | **KC** |
| 界面 | 谁想看就用什么；KC 的 web UI 也算一种 |

**关键事实：Project Tool 没有账号体系，也没有权限模型。**
`Member` 只回答「这个人在这个项目里是谁」（handle / role / git 身份），
不是用户，不是权限实体。访问控制靠 **Git 托管**（私有仓库）或文件系统权限。

## 1. 数据契约：哪些能信，哪些是缓存

这是 KC 侧最容易踩的坑 —— **读错文件会拿到过期或互相矛盾的数据**。

### canonical（跟着 Git 走，是真相）

```text
.pjt/project.json              项目元信息（含 project.rev）
.pjt/objects/<collection>/*.json   一个对象一个文件
.pjt/events/YYYY/MM/EVT-*.json    一个事件一个文件（append-only）
.pjt/config.toml               只读配置
```

### 派生缓存（**不要读**，可随时删掉重建）

```text
.pjt/state/state.json          计数 + last_transaction_id
.pjt/refs/labels.json          label 目录（重扫 task 生成）
```

这两份已经被**排除出版本控制**（`pjt init` 写 `.gitignore`，`pjt doctor` 把
「它们被 git 跟踪」判为 **error**）。V1-C 的合并探针实测：如果它们被提交，
2 个写者的 9 个真实合并场景只有 1 个能干净合并；排除后 8/9。
剩下的那一个（两人改同一个 task）本来就该冲突。

> **所以 KC 侧不要把 `state/` `refs/` 纳入索引，也不要把它们写回去。**
> 需要 label 集合就自己扫 `objects/tasks/*.json` 的 `labels` 字段。

### 接口契约文档

接口定义**不是 `.pjt` 对象**，是工作树里的 markdown + 注册成 `kind=file` 的
Artifact（`.pjt/objects/artifacts/ART-*.json`，locator 指向文件路径）：

```text
docs/interfaces/<slug>.md     front-matter 机器可读，正文是散文
```

front-matter 字段：`name` / `status`（`draft|review|agreed|deprecated`）/
`area` / `kind`（**由项目自定义，工具不校验**）/ `owners` / `consumers` / `version`。
KC 若要索引「谁依赖了哪个接口」，读 `consumers` 与 `area` 即可。

## 2. 接入点：方法注册表（推荐）

**不要直接解析 JSON 文件做业务逻辑** —— 那是最后的 fallback，不是首选。

`registry` 是显式的 118 个方法（`system.capabilities` 会列全），每个带 `mutating` 标记与分类。这是为了
将来 REST / SDK / 权限 / OpenAPI 有稳定基础。读取入口：

```python
from project_tool.application.service import ProjectService
from project_tool.storage import open_project

svc = ProjectService(open_project("/path/to/repo"))
svc.call("task.list", {"area": "core"})
svc.call("area.activity", {"days": 7})
```

命令行等价物：

```bash
pjt --json task list --area core      # 输出 {"id":"cli","result":{...}}
pjt --porcelain ...                    # 少数字段命令支持，机器可读
```

**能力发现**（KC 侧应该先问这个，而不是硬编码功能假设）：

```python
svc.call("system.capabilities", {})
```

```json
{
  "protocol_version": 1,
  "schema_version": "1.1",
  "methods": ["area.activity", "area.archive", "… 共 118 个 …"],
  "features": { "area": true, "artifact": true, "git": true,
                "search": false, "web": false, "remote": false, "sync": false }
}
```

> ⚠️ `system.capabilities` **没有 CLI 子命令**，只能走 Python API。
> （`pjt system.capabilities` 会报 "No such command"。）

`features.remote` / `sync` / `web` 明确是 `false` —— **今天不存在远程 API，
KC 只能从 Git 侧取数**。等真的上服务器，这几个会翻成 `true`，届时
`docs/05` §7 有 HTTP 映射约定。KC 侧**应当用 `methods` 列表做能力探测**，
而不是假设某个 method 一定存在。

### 如果 KC 只想读文件（可行，但要知道代价）

- `objects/**` 与 `events/**` 都是单文件单对象/单事件，**天然可并发读**
- 同一分支多人并发写时这些文件几乎不冲突（探针 8/9）
- 但 `.pjt` 里可能有**半写状态**：事务中断会留下 `staged/ + manifest + COMMIT`
  协议。正常路径不会残留，但若读到了脏数据，正确反应是**报错而不是猜**（见 §6）

## 3. 身份映射：KC 用户 ↔ Member（这才是难点）

KC 侧的用户和 Project Tool 的 `Member` **没有共享主键**，必须显式映射。

### Member 的可用锚点

```json
{
  "id": "MBR-01K8H...",        // 项目内主键（ULID）
  "handle": "jichao",          // 项目内唯一句柄
  "display_name": "计超",
  "roles": ["leader"],          // 自由字符串，见下
  "git": { "names": [...], "emails": ["jichao@corp.com"] },
  "external_ids": { "kc_user": "u_12345" },   // ← 官方预留的外部映射位
  "active": true,
  "lifecycle": "active"
}
```

### 推荐的映射方式（按可靠性排序）

| 优先级 | 锚点 | 可靠性 | 说明 |
|---|---|---|---|
| 1 | `external_ids["kc_user"]` | **最高** | 显式写入，无歧义。⚠️ 见下方缺口 |
| 2 | `git.emails` | 高 | 需 KC 侧 email 稳定且唯一 |
| 3 | `git.names` | 中 | 重名、改名都会失效 |
| 4 | `handle` | **最低** | 项目内自由取名，跨项目无意义 |

**建议**：`external_ids` 作为权威映射，`git.emails` 作为自动回退
（很多项目会用 `pjt member map-git` 填它）。**不要用 `handle` 跨项目匹配**。

### ⚠️ 已知缺口：`external_ids` 目前 CLI 没暴露

`Member.external_ids` 在 domain 模型和 service（`member.add` / `member.update`）
里都存在，**但 `pjt member add|edit` 没有对应选项**。所以：

- 只能通过 Python API 写：`svc.call("member.update", {"member": "jichao", "external_ids": {...}})`
- 或者直接 `pjt` 提个 issue 补上 CLI（工作量很小）

KC 侧短期请走 Python API，或者用 `git.emails` 回退。

### 事件里的 actor 是 Member id，不是 KC user id

`actor_id` 是 `MBR-…`，**不是** KC user id。KC 要翻成 KC 用户，同样得走上面的映射表。

### ⚠️ 方法视图 vs 磁盘文件：字段不一样

同一个事件，两种读法拿到的字段**不一样**，KC 别踩：

| 读法 | 字段 |
|---|---|
| `svc.call("log.list", …)` / `pjt log` | `id`, `event_type`, `entity_type`, `entity_id`, `actor_id`, `occurred_at`, `payload` —— **7 个** |
| 直接读 `.pjt/events/YYYY/MM/EVT-*.json` | 上面 7 个 **＋** `schema_version`, `project_id`, `transaction_id`, `base_rev`, `new_rev`, `device_id` —— **13 个** |

- `base_rev` / `new_rev` 是**乐观并发链**：KC 若要做自己的变更审计/对账，用得上。
- `device_id` 来自 `.pjt/local/local.toml`，**KC 侧不要索引**（它不上 Git，
  跨机无意义，只对「同一台机器上的多进程」有意义）。
- 结论：**要完整事件就读文件**；只做「最近发生了什么」的列表用 `log.list` 就够。

## 4. KC 拥有、项目工具刻意不做的事

以下**全部**是 KC 的活，Project Tool 不会也不该做：

| 能力 | 为什么不在 Project Tool |
|---|---|
| 账号 / SSO | 工具没有身份体系，见 `docs/01` §4 |
| 组织 / 项目映射 | KC 侧维护，通过 `external_ids` 回写 |
| 可见性 / ACL | `.pjt` 是可读 JSON 跟着 Git 走，**本地门禁只会制造「已经管住了」的错觉** |
| 「谁被授权改 owner」的强制执行 | 同上；现在只**记录**：每次归属变更都进 append-only 事件，供人和服务器审 |
| 同步 / Webhook | `system.capabilities` 里 `sync` = false |

**`Member.roles` 是自由字符串**，工具内置的 `KNOWN_ROLES = (leader, member, viewer)`
只是**建议词汇表**：未知值让 `pjt doctor` 报 **warning**（不是 error ——
老项目可能有自由写的 role，不能因此判数据损坏）。

> 真实数据提醒：EFW 项目里用的 role 是 `maintainer`，不在建议词汇表内，
> 所以 doctor 会报一条 warning。这是**待决问题**：权限模型落地时要定它
> 是不是第 4 个角色。**KC 侧别把它当错误处理。**

## 5. 实际取数的几个配方

### 全量拉取（快照）

```bash
git clone --filter=blob:none <repo>   # 只拉需要的 blob
# 然后按 project.json → objects/ → events/ 建索引
```

`.pjt` 里对象总数不大（EFW 那种规模：15 task / 4 milestone / 82 事件）。
**按需解析比维护索引简单**。

### 增量（按事件游标）

事件是 append-only 且一事件一文件、ID 是 ULID（时间有序），所以：

- 增量拉取 = 扫 `events/YYYY/MM/` 下比上次水位新的文件
- 或按 `occurred_at` 过滤
- **不要**用 `state.json` 里的 `event_count` 当水位（那是派生缓存，且不跨机一致）

### 想知道「谁最近在动哪块」

```bash
pjt --json area activity --days 7        # 注意是子命令，不是顶层命令
```

输出分两半，**KC 侧必须区别对待**：

- `areas[]` —— 来自 `git log`，**跟着 Git 走，所有人都能看到**
- `local_uncommitted` —— 来自 `git status`，**只有本机可见**

`local_uncommitted` **不包含别人的在途工作**（无服务器 + 无共享文件系统，
这不是 bug 是架构事实）。KC 侧**不要**把它当成「团队当前状态」——
那会让人把「没出现」读成「没人在动」。

## 6. 异常处理

| 症状 | 含义 | KC 该做什么 |
|---|---|---|
| `PROJECT_CORRUPTED`（读对象时） | 该对象文件被改过，但 rev 对不上 | **报错，不要自动修**。让 `pjt doctor` 出报告 |
| `REVISION_CONFLICT` | 你的 rev 落后于磁盘上的 rev | 重读后重试；这是乐观并发的正常结果 |
| `SCHEMA_MIGRATION_REQUIRED` | 项目 schema 落后 | 跑 `pjt migrate`（幂等） |
| `HIERARCHY_CYCLE` | area/goal/task 层级成环 | 人工修；不要自动拆 |
| `doctor` 报 `derived.git_tracked` | 派生缓存被提交进 Git | 提示人跑 `git rm --cached …`（**工具不代劳**） |

**不要自动修数据。** `pjt doctor --repair` 只做两件破坏性操作（事务恢复、
陈旧锁清理），且仅在明确要求时执行。KC 侧最安全的姿势是**只读 + 报错**。

## 7. 红线（碰了就是事故）

1. **不要直接写 `.pjt/objects/**` 或 `.pjt/events/**`。** 写事件必须走事务
   协议（`staged/ + manifest + COMMIT`）；`events/` 只能追加，永不修改或删除。
2. **不要写 `.pjt/local/`**（含 `actor` / `device_id`）—— 不进 Git，是本机状态。
3. **不要把派生缓存写回** —— 没有任何逻辑以它们为准，doctor 会因此报 error。
4. **不要用 `handle` 跨项目做主键** —— 它只在单个项目内唯一。
5. **不要把「没提交改动的人」当成「没在工作」** —— 见 §5。
6. **不要基于文件 mtime / 目录顺序做任何推断** —— 内容才是真相（ID 是 ULID，时间有序）。

## 8. 待 KC 确认 / 目前开放的问题

这几条工具侧没有答案，需要两边对齐：

1. **`external_ids` 的 key 命名**：用 `kc_user`？还是 `kc:<org>:user` 以便一个项目
   对接多个 KC 组织？
2. **`maintainer` 是不是第 4 个标准 role**（见 §4）
3. **KC 侧的「项目」与 Project Tool 的「项目」是否 1:1**：目前 `.pjt` 一仓库一项目。
   多项目怎么办（monorepo？多个 `.pjt`？）没有定论。
4. **KC 要不要索引接口契约（`docs/interfaces/*.md`）**：如果索引，
   `consumers`（Area 名）和 `status=agreed` 就是入口。
5. **上服务器的时间表**：一旦有了服务端，`remote`/`sync` 翻 true，
   权限校验会在服务端做（本地不再有任何门禁）。在那之前 KC 侧只能靠 Git 托管。

## 9. 相关文档

| 文档 | 内容 |
|---|---|
| `docs/01-overview.md` | 三个系统的分工、运行模式 |
| `docs/02-architecture.md` | 分层与依赖方向 |
| `docs/03-data-model.md` | 对象字段、校验规则（含 §4.7b' 活跃度、§4.7c 接口契约、§4.7d 权限边界） |
| `docs/04-storage.md` | 磁盘布局、事务协议、canonical vs 派生 |
| `docs/05-interfaces.md` | 118 个 method、CLI、错误码、未来的 HTTP 映射 |
| `docs/08-events.md` | 事件契约（KC 集成依赖它） |
| `AGENTS.md` | 接手这个仓库必读的不变量 |

**联系方式与上游**：本仓库 `https://github.com/snsnnd/ProjectTool`。
不变量（§7 红线的完整版）以 `AGENTS.md` 为准，改动前请先读。
