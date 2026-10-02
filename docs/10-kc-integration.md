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

front-matter：`name` / `status`（**自由字符串**，默认 `draft`）/ `area` /
`kind`（**由项目自定义，工具不校验**）/ `owners` / `consumers` / `version`。

> ⚠️ 必填只有 `name` / `status` / `area`——**`kind` 不在其中**（不关心分类的项目
> 可以完全不填）。`status` 的**取值由项目自定义**，工具只校验非空、不校验取值。
>
> ⚠️ 所以下面这段可视化建议**依赖 KC 自己约定一套词表**：工具不认得
> 「已谈定」是什么，`agreed` 只是 `SUGGESTED_STATUSES` 里的一个建议值。
> KC 要么沿用建议值（`draft|review|agreed|deprecated`），要么在自己的
> 配置里声明哪套词表算「已谈定」——**不要假设工具会替你判断**。
>
> **入口**：`status` 表示成熟度，`consumers` 表示谁在依赖。正文是散文，
> **不要试图解析**。`consumers` 是 warning 级别的提醒，不是阻塞项。
> 另外 `owners` / `consumers` / `version` 工具**不维护**——它只读 front-matter、
> 只同步 `area`（和 `kind`），所以别把它们当成会由工具托管的字段。

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
  "methods": ["area.activity", "… 共 123 个 …"],
  "features": { "area": true, "artifact": true, "git": true,
                "search": false, "web": false, "remote": false, "sync": false } }
```

> ⚠️ `system.capabilities` **没有 CLI 子命令**，只能走 Python API
> （`pjt system.capabilities` 会报 "No such command"）。

**想知道 CLI 能做什么**（给人写文档、给用户做输入提示时用）：

```python
svc.call("system.cli", {})
# {"count": 129,
#  "commands": [{"path": ["area","set-owner"], "kind": "command",
#                "method": "area.set_owner", "also_calls": [],
#                "summary": "Add/remove the members responsible for an area.",
#                "params": [{"name":"area_id","flag":null,"positional":true,
#                            "required":true,"is_flag":false,"multiple":false,
#                            "help":""}, ...]}],
#  "method_to_paths": {"task.set_status": ["task block","task cancel", ...]},
#  "unmapped": []}
```

- `path` 是命令路径，`method` 是对应的 registry method
- `pjt graph <scope>` 这类**按运行时分派到多个 method** 的命令，`method` 为
  `null`，实际会调的列在 `also_calls`
- `method_to_paths` 是反向表：`task.set_status` 一条 method 对应 6 条命令
  （`task ready|start|block|review|done|cancel`）
- `unmapped` 是"没对上 method 的可执行命令"，正常应为空 —— 非空说明映射表过期了。
  有测试守着：`tests/test_registry.py::test_every_cli_method_map_target_exists`

`features.remote` / `sync` / `web` 是 `false` —— **今天不存在远程 API**，
KC 通过 Git 取数是唯一正确的方式。要拿 method 的 `mutating` / `category` /
`description`（做权限白名单用），传 `detail=True`，见下。

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

## 4.4 多 agent 运行时：KC 必须给每个 agent 注入 `PJT_ACTOR`

如果 KC 用**多个 agent** 在同一台机器上（或同一个 `.pjt`）上工作，有一件事
必须做，否则事件归属会**静默记错人**。

### 问题

`.pjt/local/local.toml` 里的 `actor` 和 `device_id` 是**整台机器共享**的：

```toml
[local]
device_id = "DEV-9880A634"
actor = "MBR-01M3V9PCD0EBJ3SQS"     # 只有一个
```

所以两个 agent 不做区分时，**两个 task 都会被记成同一个人**（实测）：

```text
task.created    actor=alice    ← 其实是 agent-b 建的
task.created    actor=alice
```

`device_id` 也帮不上忙：它标识的是机器不是进程，而且**根本不在 `log.list` 的
返回字段里**（只有 7 个字段，要看 `device_id` 得读事件文件）。

### 解法：启动每个 agent 时注入 `PJT_ACTOR`

```bash
PJT_ACTOR=agent-7 pjt task add "…"      # 认 handle，也认 MBR- id
```

优先级（实测确认）：`PJT_ACTOR` 环境变量 **>** `.pjt/local/local.toml` 的 `actor`。

```text
PJT_ACTOR=env-agent   pjt task add …   ->  actor=env-agent
                       pjt task add …   ->  actor=local-agent   （回落 local.toml）
```

**这是平台该做的事，不是 agent 自己该记得的事** —— agent 不会主动设环境变量，
但 KC 在 spawn 每个 agent 时顺手注入是零成本的。

### 同一台机器上的并发安全（实测）

| 场景 | 结果 |
|---|---|
| 20 次并发写**同一个** task | 无崩溃 · doctor 干净 · 无锁/事务残留 · 状态是确定值 |
| 两个 agent 读同一 rev 各写 | 一个成功，一个 `REVISION_CONFLICT`（**不静默覆盖**） |
| 8 agent 并发各建 task | 8/8 成功，`actor_id` 归属正确 |
| 32 并发写 | 9.1 s 全部成功，doctor ok |

锁只在**真正落盘那一刻**持有（约 280 ms），而 agent 一个循环是几十秒，
所以锁占用率极低，不是瓶颈。

### 认领：`pjt task claim`（可选但强烈建议）

并发写本身是安全的，问题是**冲突的代价**：人类撞了重试几秒钟；agent 撞了意味着
**整个任务已经做完了**（读了代码、改了工作树、调了工具），全部作废。
而 agent 不会像人一样先问一句"有人在改吗"。

```bash
pjt task claim TSK-… --agent <handle> [--ttl 30] [--note "..."]   # 认领，带 TTL
pjt task release TSK-… [--agent <handle>]                        # 主动放弃
pjt task list --unclaimed                                         # 「给我一件没人做的事」
pjt task list --claimed-by <handle>
```

> ⚠️ **`pjt task ready` 不做过滤** —— 它是**状态迁移**（inbox → ready），
> 不是「列出可做的事」。要拿待办入口用 `pjt task list --unclaimed`。

- **带 TTL 是必须的**：agent 会崩，锁不能等它释放
- **过期即失效，不需要清理任务** —— 和其它派生数据一样，不存陈旧状态
- 这是**协调信号**，不是权限门禁：它让冲突在**动手之前**暴露，而不是在
  最贵的写入时刻。别人已认领时 `task claim` 报 `CLAIMED`（退出码 6），
  **不覆盖** —— 要抢得先 release，或等它过期
- `Area.owner_ids`（把 agent 按 Area 分区）是第一道防线，claim 是同区内的第二道

## 4.5 初始化之后怎么分发到每个人

这一节是实测出来的（3 人 × 3 个 Area 走完整流程，见下），**不是推演**。

### 前提：工具永远不做 Git 写操作

`pjt` 不 `push` / `clone` / `merge`（`AGENTS.md` §11：Git 适配器只读，
子命令白名单只有 `rev-parse` / `status` / `log` / `show` / `ls-files`）。
所以"分发"这一步是**普通 Git 操作**，由 KC 或人执行。工具只管 `.pjt` 里的数据。

### ⚠️ 最容易静默失败的一步：裸库的 HEAD

```bash
git init --bare origin.git          # HEAD 指向 refs/heads/master
git push -u origin main             # 实际分支是 main
```

**此时 `git clone` 会给出一个空的检出**，只打一行 warning：

```text
warning: remote HEAD refers to nonexistent ref, unable to checkout.
```

`.pjt` 根本没被 checkout 出去，对方看到的是一个"没有 .pjt 的项目"，
而每个人的本地 `pjt` 全部报 `NOT_FOUND`。**这是整条分发链最容易静默失败的地方。**

修法二选一：

```bash
git init --bare -b main origin.git                      # 建的时候就指定
git -C origin.git symbolic-ref HEAD refs/heads/main     # 或者事后纠正
```

### 完整流程

**KC 侧（一次性）**

```bash
# 1) 在一个 git 仓库里初始化
mkdir kc-workspace && cd kc-workspace && git init -b main
pjt init --name "SerialConsole" --description "串口调试控制台"

# 2) 建成员。--git-name / --git-email **必须和开发者本地 git config 一致**，
#    否则 area.activity 归因不到人（见下）
pjt member add jichao --name "计超" --role leader \
  --external-id kc_user=u_1001 --git-name "计超" --git-email jichao@corp.com
pjt member add shaodong --name "晓东" \
  --external-id kc_user=u_1002 --git-name "晓东" --git-email shaodong@corp.com

# 3) 建 Area 并分工（复数 owner = 公共接口区）
pjt area add core --path-pattern "studio_core/**"
pjt area add ui   --path-pattern "studio_ui/**"
pjt area set-owner core --add jichao
pjt area set-owner ui   --add shaodong
pjt area set-owner core --add shaodong      # core 变公共区

# 4) 推给团队（普通 git，不是 pjt）
git add -A && git commit -m "KC 初始化：成员与分工"
git init --bare -b main ../origin.git
git remote add origin ../origin.git && git push -u origin main
```

**每个开发者（一次性，3 步）**

```bash
git clone <origin> && cd project

# ① 设 pjt actor —— 否则事件会记到"上一个操作者"头上
pjt member use jichao

# ② 让本地 git identity 和 Member.git 对上 —— 否则 area.activity 归因不到人
git config user.name  "计超"
git config user.email "jichao@corp.com"

# ③ 验证：应该能在 area activity 里看到自己
pjt area activity --days 7
```

### ②为什么必须做

`area activity` 的归因链是：commit 的 author name/email → `Member.git` 匹配。
两边对不上时，它会**如实报 `unmapped_authors` 而不是猜**：

```text
authors with no Member.git mapping:
  snsnnd  6 commit(s)      ← 这是某台机器的全局 git identity
  KC      1 commit(s)
```

所以 KC 建成员时**要同时填 `--git-name` 和 `--git-email`**，只填 email 的话，
开发者本地用中文名提交就匹配不上（名字匹配不到、email 也不同）。

### 日常协作

每人一个特性分支，推上去，在集成分支汇合：

```bash
git checkout -b work/jichao
# …干活…
pjt task add "…" --area core && pjt task start <id>
git add -A && git commit -m "…" && git push -u origin work/jichao
# 集成分支上
git merge --no-edit origin/work/jichao
```

### 实测结果

3 人 / 3 个 Area 跑完整流程：

- **3/3 分支合并全部干净**（与 `dogfooding/scripts/multiwriter_probe.py`
  的 8/9 结论一致 —— 剩下那一个才是真冲突）
- 事件 `actor_id` 正确分散到三个人
- `area activity` 正确把人归到对应 Area
- 归因不上的历史提交被如实标为 unmapped，没有猜错

### 已知摩擦

| 现象 | 原因 | 处置 |
|---|---|---|
| clone 后没有 `.pjt` | 裸库 HEAD 指向不存在的分支（见上） | `git symbolic-ref HEAD refs/heads/main` |
| `area activity` 出现机器全局用户名 | 开发者本地 git identity 没和 `Member.git` 对上 | 让开发者设 `git config`，或 KC 补 `member edit --git-name` |
| KC 自己的提交显示为 unmapped | KC 不是 Member | 可接受；`pjt init` 产生的事件本来就没有 actor |

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

⚠️ 上表只说了**工具侧**能做到什么，**服务器端的权限模型本身尚未定义**
（谁授予、怎么撤、`maintainer` 是不是第 4 个角色，都还没定，见 §7）。
KC 上线前需要先定那部分，否则「一致」没有基准可比。

工具侧的对应设计：每次 owner 变更都进 **append-only 事件**
（`area.updated`，payload 带 `from` / `to` / `added` / `removed`），
所以即使有人绕过 KC 直接改 Git，**改动仍然可审**。这是"记录"而非"拦截"。

## 7. 已知缺口 / 需要 KC 配合的

**本轮已补齐**

1. ✅ **`external_ids` 的 CLI 入口** —— `pjt member add|edit --external-id k=v`
   （可重复；值里含 `=` 也没问题，只 split 一次）
2. ✅ **`system.capabilities` 的 method 元信息** ——
   `svc.call("system.capabilities", {"detail": True})` 额外给出 `specs` /
   `read_only_methods` / `mutating_methods`（**65 写 / 58 读**）。
   不传 `detail` 时形状不变，不破坏既有调用方。
3. ✅ **完整 CLI 命令面** —— `svc.call("system.cli", {})`，见 §3

**仍待 KC 决定**

4. **`external_ids` 的 key 命名**：`kc_user`？还是 `kc:<org>:user`
   （一个项目对接多个 KC 组织）？—— **§5 的优先级表里已经把 `kc_user` 当成
   既定锚点在用了**，那是待决问题的一个假设答案，不是结论。定下来之前，
   KC 侧建表别把 `kc_user` 这个字符串焊死。
5. **`maintainer` 角色**：EFW 项目在用，不在工具建议词汇表
   （`leader` / `member` / `viewer`）内，`pjt doctor` 会报 **warning**
   （不是 error —— 老项目可能有自由 role，不能因此判数据损坏）。
   **KC 侧别把它当错误处理。**
6. **可视化怎么产出**：见 §8。

## 8. 可视化：建议静态报告，不建议在服务端渲染

KC 要的"可视化"，最省事也最不容易腐化的做法是**单文件 HTML 报告**：

```bash
# ⚠️ 工具**没有** `--html`，HTML 由 KC 侧生成；工具负责给数据。
# ⚠️ `--json` / `--porcelain` 是**全局**选项，必须放在子命令**之前**。
pjt --json area activity --area core --days 7

# ⚠️ `status` 是**顶层命令**；`project.status` 是 method 名，CLI 上不能这么写
pjt --json status
```

**`system.cli` 在 CLI 上没有对应命令**——它是 SDK / service 层的 method，
只能从代码里调：

```python
surface = ProjectService(opened).call("system.cli", {})
```

（`pjt --json system.cli` 会报 `No such command`。同理 `system.capabilities`。）

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
| `docs/05-interfaces.md` | 123 个 method、CLI、错误码、未来的 HTTP 映射 |
| `docs/08-events.md` | 事件契约 |
| `AGENTS.md` | **接手本仓库必读的不变量**（红线的完整版） |

本仓库 `https://github.com/snsnnd/ProjectTool`。
改动前请先读 `AGENTS.md`。
