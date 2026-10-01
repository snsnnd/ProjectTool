# Project Tool — KC 接入参考

> **定位**：KC 把 Project Tool 作为平台能力提供，但**只承载初始化与管理工作**——
> 分工（owner / task 归属）、管理员权限分发、成员创建/删除、以及**可视化**。
> **代码与实际开发不经过 KC**：开发者在自己的环境里用 Git + `pjt` CLI 完成，
> 产出通过 Git 汇总。
>
> 这意味着 KC 是**窄写入 + 宽读取**的一层，不是开发平台，也不需要承担 Git 语义。

## 0. 三十秒版本

```text
Git          →  代码发生了什么；开发者在这里干活
Project Tool →  项目发生了什么，以及为什么（.pjt 跟着 Git 走）
KC           →  项目属于谁、谁负责哪块、谁可以参与（初始化 + 可视化）
```

| 能力 | 在哪 |
|---|---|
| 写代码、提交、评审 | Git + 开发者本地 `pjt` |
| task / milestone / area / 决策 / 事件历史 | Project Tool（`.pjt/`） |
| **成员增删、owner 分工、权限分发** | **KC（窄写入）** |
| **看板 / 状态 / 接口状态的可视化** | **KC（宽读取）** |
| 账号、组织、ACL | **KC** |

**关键事实：Project Tool 没有账号体系，也没有权限模型。**
`Member` 只回答「这个人在这个项目里是谁」（handle / role / git 身份），
不是用户，不是权限实体。

## 1. 为什么这个定位在架构上成立（KC 可以放心窄写入）

实测过一次「KC 写 + 开发者写」同分支并发：

```text
.pjt/objects/areas/ARA-….json     ← 权限分发改的就是这个文件
.pjt/objects/members/MBR-….json   ← 成员创建/删除
.pjt/events/YYYY/MM/EVT-….json    ← 一个事件一个文件
```

**KC 的管理操作只碰单对象文件，没有任何共享文件。** 这是 V1-C 存储布局
（一对象一文件 + 一事件一文件）带来的直接好处，也是当初把布局这么设计的原因。

- KC 写 owner、成员，与开发者写 task **结构上不冲突**（不同文件）
- 双方改**同一个**对象时，由 `expected_rev` 在写入时拦住 —— 报
  `REVISION_CONFLICT`，而不是留到 merge 阶段
- 合并探针（`dogfooding/scripts/multiwriter_probe.py`）实测 2 写者 9 个场景
  8 个能干净合并，剩下的一个是"两人改同一个 task"——**本来就该冲突**

## 2. 数据契约：哪些能信，哪些是缓存

**KC 侧最容易踩的坑** —— 读错文件会拿到过期或互相矛盾的数据。

### canonical（跟着 Git 走，是真相）

```text
.pjt/project.json                 项目元信息（含 project.rev）
.pjt/objects/<collection>/*.json  一个对象一个文件
.pjt/events/YYYY/MM/EVT-*.json    一个事件一个文件（append-only）
.pjt/config.toml                  只读配置
```

### 派生缓存（**不要读**，可随时删掉重建）

```text
.pjt/state/state.json      计数 + last_transaction_id
.pjt/refs/labels.json      label 目录（重扫 task 生成）
```

这两份已被**排除出版本控制**（`pjt init` 写 `.gitignore`，`pjt doctor` 把
"它们被 git 跟踪"判为 **error**）。

> **KC 侧不要把 `state/` `refs/` 纳入索引，也不要写回。**
> 需要 label 集合就自己扫 `objects/tasks/*.json` 的 `labels` 字段。
> 也不要拿 `state.json` 的 `event_count` 当增量水位 —— 派生缓存，跨机不一致。

### 接口契约文档

接口定义**不是 `.pjt` 对象**，是工作树里的 markdown + 注册成 `kind=file` 的
Artifact（locator 指向文件路径）：

```text
docs/interfaces/<slug>.md
```

front-matter：`name` / `status`（`draft|review|agreed|deprecated`）/ `area` /
`kind`（**由项目自定义，工具不校验**）/ `owners` / `consumers` / `version`。

> **做"接口状态"可视化的话，入口是这两个**：`status == "agreed"` 表示已谈定，
> `consumers` 表示谁在依赖。正文是散文，**不要试图解析**。

## 3. 接入点

**推荐读 registry，不要直接解析 JSON 做业务逻辑。**

```python
from project_tool.application.service import ProjectService
from project_tool.storage import open_project

svc = ProjectService(open_project("/path/to/repo"))
svc.call("task.list", {"area": "core"})
svc.handle("task.list", {"area": "core"}, request_id="r1")
# -> {"id": "r1", "result": [...]}
```

`handle()` 已经带了 `{"id", "result" | "error"}` 协议，**HTTP/WebSocket 层可以直接复用**。

### 能力发现

```python
svc.call("system.capabilities", {})
```

```json
{ "protocol_version": 1, "schema_version": "1.1",
  "methods": ["area.activity", "… 共 118 个 …"],
  "features": { "area": true, "artifact": true, "git": true,
                "search": false, "web": false, "remote": false, "sync": false } }
```

> ⚠️ `system.capabilities` **没有 CLI 子命令**，只能走 Python API
> （`pjt system.capabilities` 会报 "No such command"）。

`features.remote` / `sync` / `web` 是 `false` —— **今天不存在远程 API**，
KC 通过 Git 取数是唯一正确的方式。`system.capabilities` 返回的是**方法名列表**；
`MethodSpec` 里还有 `mutating` / `category` / `description`（见 §7 已知缺口）。

## 4. KC 建议调用的方法

### 窄写入（初始化与管理）

| 目的 | method |
|---|---|
| 建项目 | `project.init` |
| 建成员 / 改角色 / 停用 | `member.add` / `member.update` / `member.deactivate` |
| 设当前操作者（用于事件归属） | `member.use` |
| 建 Area | `area.create` / `area.update` |
| **权限/分工分发** | `area.set_owner` |
| 建 task / 指派 | `task.create` / `task.assign` / `task.unassign` |
| 建里程碑 | `milestone.create` |

### 宽读取（可视化）

| 用途 | method |
|---|---|
| 项目总览 | `project.status` |
| 看板：按 Area / 里程碑看 task | `task.list` / `area.tasks` / `milestone.progress` |
| 成员与工作量 | `member.list` / `member.workload` |
| 阻塞情况 | `project.status`（含派生的 `blocked`，含 area 名与里程碑标题） |
| 接口状态 | `interface.list` |
| 依赖图 | `graph.tasks` / `graph.dependencies` |
| 变更历史 | `log.list` / `log.entity` / `area.history` / `task.history` |
| 谁在动哪块 | `area.activity` |

### 写入必须带 `expected_rev`

所有写方法都接受 `expected_rev`。**KC 侧建议一律带上**：先读出对象的
`rev`，回传时带上；对象已被别人改过就返回 `REVISION_CONFLICT`，
KC 重新读一次再让用户确认。**不要静默重试覆盖**。

## 5. 身份映射：KC 用户 ↔ Member

KC 用户和 `Member` **没有共享主键**，必须显式映射。

```json
{
  "id": "MBR-01K8H...",
  "handle": "jichao",
  "display_name": "计超",
  "roles": ["leader"],
  "git": { "names": [...], "emails": ["jichao@corp.com"] },
  "external_ids": { "kc_user": "u_12345" },
  "active": true
}
```

| 优先级 | 锚点 | 可靠性 |
|---|---|---|
| 1 | `external_ids["kc_user"]` | **最高**（显式、无歧义）⚠️ 见 §7 |
| 2 | `git.emails` | 高 |
| 3 | `git.names` | 中（重名/改名会失效） |
| 4 | `handle` | **最低**（只在单项目内唯一，禁止跨项目匹配） |

**`pjt member use <handle>`** 设置当前操作者，事件的 `actor_id` 就会记成这个
Member id。KC 每次代用户操作前应调用它，否则 `actor_id` 会落到上一个操作者身上。

### 事件的两种读法，字段不一样

| 读法 | 字段 |
|---|---|
| `svc.call("log.list", …)` | `id`, `event_type`, `entity_type`, `entity_id`, `actor_id`, `occurred_at`, `payload` —— **7 个** |
| 直接读 `.pjt/events/…/EVT-*.json` | 上面 7 个 **＋** `schema_version`, `project_id`, `transaction_id`, `base_rev`, `new_rev`, `device_id` —— **13 个** |

- 要完整事件（含 `base_rev`/`new_rev` 乐观并发链、KC 自己做对账时有用）
  **必须读文件**；只做"最近发生了什么"的列表用 `log.list` 就够
- `device_id` 来自 `.pjt/local/local.toml`（不上 Git）—— **KC 侧不要索引**
- `actor_id` 是 `MBR-…`，**不是** KC user id，要用 §5 的映射表翻译

## 6. ⚠️ 一个必须说清的落差：KC 门禁 ≠ 数据门禁

KC 分发的管理员权限，**只能管住"通过 KC 的操作"**。

开发者手里有 Git 写权限，他可以 `git commit` 一份改过 `owner_ids` 的 `.pjt`
直接推上去 —— **KC 侧任何检查都拦不住**，因为 `.pjt` 是可读 JSON 跟着 Git 走。
工具本身也不做本地门禁（加本地门禁只会制造"已经管住了"的错觉）。

所以 KC 需要明确一件事：

| KC 权限的含义 | 需要什么 |
|---|---|
| 「谁能通过 KC 建成员/分发 owner」 | 只要 KC 自己的认证 —— **现在就能做到** |
| 「谁真的不能改 owner」 | **Git 仓库的 ACL 必须与之一致**（分支保护 / 仓库权限） |

工具侧的对应设计：每次 owner 变更都进 **append-only 事件**
（`area.updated`，payload 带 `from` / `to` / `added` / `removed`），
所以即使有人绕过 KC 直接改 Git，**改动仍然可审**。这是"记录"而非"拦截"。

## 7. 已知缺口 / 需要 KC 配合的

1. **`external_ids` 目前没有 CLI 选项**。模型和 service（`member.add` /
   `member.update`）里都有，但 `pjt member add|edit` 没有 `--external-id`。
   KC 走 Python API 可用；也可以只用 `git.emails` 回退。
2. **`system.capabilities` 只返回方法名**，不含 `MethodSpec.mutating` /
   `category`。若 KC 要在 method 级别做白名单，目前得 import 内部类。
   KC 若只调 §4 那几十个方法，硬编码白名单也够用。
3. **`external_ids` 的 key 命名**待定：`kc_user`？还是 `kc:<org>:user`
   （一个项目对接多个 KC 组织）？
4. **`maintainer` 角色**：EFW 项目在用，不在工具建议词汇表
   （`leader` / `member` / `viewer`）内，`pjt doctor` 会报 **warning**
   （不是 error —— 老项目可能有自由 role，不能因此判数据损坏）。
   **KC 侧别把它当错误处理。**
5. **可视化怎么产出**：见下节。

## 8. 可视化：建议静态报告，不建议在服务端渲染

KC 要的"可视化"，最省事也最不容易腐化的做法是**单文件 HTML 报告**：

```bash
pjt area activity --days 7 --html > area-report.html
pjt --json project.status        # 配合前端渲染
```

- 一个自包含 HTML，**无框架、无构建、无 SSR、无认证**
- 可以放进 CI：push 后重新生成，作为 artifact 或 GitHub Pages 发布
- 与项目取向一致：local-first、无服务器、Git 当底座
- 维护成本 = 一个渲染函数，而不是一个前端工程

**为什么不建议 KC 在服务端渲染整套界面**：`.pjt` 的文件浏览、diff、blame、
历史、PR review，GitHub/GitLab 已经全都有了。在服务端重做一遍是重复劳动，
而且会引入第二套渲染逻辑要跟着 schema 变。

KC 的**增量价值**应该放在 GitHub 给不了的东西上：里程碑进度、按 Area 的
分工与阻塞、接口的 `agreed` 状态、以及"谁负责哪块"。

## 9. 异常处理

| 症状 | 含义 | KC 该做什么 |
|---|---|---|
| `PROJECT_CORRUPTED` | 对象文件被改过但 rev 对不上 | **报错，不要自动修**。让 `pjt doctor` 出报告 |
| `REVISION_CONFLICT` | 你的 rev 落后于磁盘 | 重读后让用户确认再重试；**不要静默覆盖** |
| `SCHEMA_MIGRATION_REQUIRED` | 项目 schema 落后 | 跑 `pjt migrate`（幂等） |
| `HIERARCHY_CYCLE` | area/goal/task 层级成环 | 人工修，不要自动拆 |
| `doctor` 报 `derived.git_tracked` | 派生缓存被提交进 Git | 提示人跑 `git rm --cached …`（**工具不代劳**） |
| 未知 method | 版本不匹配 | 查 `system.capabilities` 的 `methods` 列表，不要硬编码假设 |

**KC 侧最安全的姿势是「只读 + 报错」**，不要自动修数据。
`pjt doctor --repair` 只做两件破坏性操作（事务恢复、陈旧锁清理），
且仅在明确要求时执行。

## 10. 红线

1. **不要直接写 `.pjt/objects/**` 或 `.pjt/events/**`** —— 写事件必须走事务
   协议（`staged/ + manifest + COMMIT`）；`events/` 只能追加，永不修改或删除
2. **不要写 `.pjt/local/`**（含 `actor` / `device_id`）—— 不进 Git，是本机状态
3. **不要把派生缓存写回** —— 没有任何逻辑以它们为准，doctor 会报 error
4. **不要用 `handle` 跨项目做主键** —— 它只在单个项目内唯一
5. **不要把"没提交改动的人"当成"没在工作"** —— 别人的在途工作你看不见
   （见下）
6. **不要基于文件 mtime / 目录顺序做推断** —— 内容才是真相（ID 是 ULID，时间有序）
7. **不要假设"没权限 = 改不了"** —— 见 §6

### 关于"谁在做什么"的重要限制

`pjt area activity` 的输出**分两半**，KC 必须区别对待：

- `areas[]` —— 来自 `git log`，**跟着 Git 走，所有人都能看到**
- `local_uncommitted` —— 来自 `git status`，**只有该机器可见**

`local_uncommitted` **不包含别人的在途工作**（无服务器 + 无共享文件系统，
这是架构事实不是 bug）。KC **不要**把它当成"团队当前状态"，
否则会让人把"没出现"读成"没人在动"。要展示在途状态，就明示"仅本机可见"。

## 11. 相关文档

| 文档 | 内容 |
|---|---|
| `docs/01-overview.md` | 三个系统的分工、运行模式 |
| `docs/03-data-model.md` | 对象字段与校验（§4.7b' 活跃度、§4.7c 接口契约、§4.7d 权限边界） |
| `docs/04-storage.md` | 磁盘布局、事务协议、canonical vs 派生 |
| `docs/05-interfaces.md` | 118 个 method、CLI、错误码、未来的 HTTP 映射 |
| `docs/08-events.md` | 事件契约 |
| `AGENTS.md` | **接手本仓库必读的不变量**（红线的完整版） |

本仓库 `https://github.com/snsnnd/ProjectTool`。
改动前请先读 `AGENTS.md`。
