# Project Tool

> Git tracks code. Project Tool tracks the project.
> Git 记录代码的演化，Project Tool 记录项目的演化。

Project Tool 是一个 **local-first、Git-aware** 的工程项目状态与协作系统。
它不替代 Git、Jira、Notion，而是记录 Git 不记录的东西：

```text
阶段 / 模块 / 任务 / 进展 / 决策 / 依赖 / 产物 / 成员 / 事件历史
```

一个工程目录同时拥有两套版本系统：

```text
my-project/
├── .git/     # 代码版本（Git）
├── .pjt/     # 项目状态（Project Tool）
├── src/
└── README.md
```

`.pjt/` 是一等数据源，和 `.git/` 平级、一起进版本库。

## 定位与边界（重要）

**Project Tool 没有服务器。** 数据只存在于你的磁盘上，协作通过 Git 走：

```text
你 ──编辑──> .pjt/（objects + events）──commit──> Git ──pull──> 别人
```

这是刻意的取舍，不是未完成的功能：

| | 有 remote | 本项目（无 remote） |
|---|---|---|
| 可用性 | 依赖服务器在线 | **完全离线可用** |
| 历史/分支/diff | 依赖服务器 | **直接用 Git**（`.pjt` 是可读 JSON） |
| 并发 | 实时同步 | Git merge + `rev` 链校验（冲突会**显式报出来**，不会静默覆盖） |
| 权限 | 账号 + ACL | 无（`.pjt` 里的 `Member` 只是身份标签，不是账号） |
| 运维 | 要部署、要备份 | **零运维** |

**明确不做**：远程 Server / 账号 / ACL / 实时同步 / Webhook / Web UI。
多人协作的场景走 Git，而不是走我们自己的同步协议。

## 状态（V0.6.7）

| 能力 | 状态 |
|---|---|
| `.pjt` 存储（一对象一文件 / ULID / rev / lifecycle） | ✅ |
| Crash-Recoverable Transaction（manifest + COMMIT + roll-forward） | ✅ |
| 写锁（PID 判活 + ownership token） | ✅ |
| 统一 `expected_rev` 并发契约 | ✅ |
| **读取即校验 rev**（被外部篡改的对象读取即报错，无法靠写入洗白） | ✅ |
| **Schema 写入门**（项目 schema 落后时禁止写，要求先 `migrate`） | ✅ |
| 不可变 Event 历史 + `base_rev → new_rev` 链校验 | ✅ |
| 依赖图 / 层级环检测（task / goal / area / decision supersede） | ✅ |
| 对象：Project / Goal / Milestone / **Area** / Task / Member / Update / Decision / **Artifact** / Link | ✅ |
| 显式 method registry（**123** 个）+ `system.capabilities` 能力发现 | ✅ |
| **派生数据不进 Git**（state / labels 被忽略，doctor 判为 error） | ✅ |
| **Area 归属**（`area set-owner`，单 owner=私有块 / 多 owner=公共接口区） | ✅ |
| **接口契约**（`interface init/register/check/sync`，Artifact 只存引用） | ✅ |
| **Area 活跃度**（`area activity`，Git 历史推导 + 区分本机未提交） | ✅ |
| **多 agent 认领**（`task next/claim/release`，claim 到期自动失效） | ✅ |
| Link 机器本地路径（写 `.pjt/local/`，不产生事件、不进共享状态） | ✅ |
| **Git 感知（只读）**：`git status` / `git log` / commit → `git_commit` Artifact | ✅ |
| **Windows 并发正确性**（共享冲突重试：锁只串行化写，挡不住读） | ✅ |
| 机器可读命令面（`system.cli`，KC 靠它发现可驱动的命令） | ✅ |
| CLI：117 个命令 + 12 个分组 | ✅ |
| 真实项目 dogfooding（EFW Studio，两轮，零源码污染） | ✅（[V0.1](dogfooding/report.md) · [V1-A](dogfooding/v1a-report.md)） |
| ruff + mypy + pytest + CI（Ubuntu + Windows, Py3.12） | ✅ |
| Search / 全文检索 | ⏳ 未排期 |
| Remote / Sync / Accounts / Webhook / Web UI | ❌ **不做**（见上方边界） |

设计文档见 [docs/](docs/)：

- [01-overview.md](docs/01-overview.md) — 产品定义与边界
- [02-architecture.md](docs/02-architecture.md) — 架构设计
- [03-data-model.md](docs/03-data-model.md) — 领域数据模型与校验规则
- [04-storage.md](docs/04-storage.md) — 存储、写锁与恢复协议（含 Windows 共享冲突）
- [05-interfaces.md](docs/05-interfaces.md) — Service API / CLI / 错误码
- [06-roadmap.md](docs/06-roadmap.md) — 路线图与验收标准
- [07-v0.1-audit.md](docs/07-v0.1-audit.md) — V0.1 架构审计与硬化
- [08-events.md](docs/08-events.md) — Event contract
- [09-handover.md](docs/09-handover.md) — 交接文档（状态 / 约定 / 下一步）
- [09-v1a-design.md](docs/09-v1a-design.md) — V1-A 设计记录（Area / Artifact / 并发契约 / 迁移）
- [10-kc-integration.md](docs/10-kc-integration.md) — KC 接入参考（初始化 / 分发 / 身份 / 权限边界）
- [AGENTS.md](AGENTS.md) — 给接手 agent 的速查与禁区

## 快速开始

环境：Python 3.12+（通过 [uv](https://docs.astral.sh/uv/) 管理）。

```bash
# 在项目目录中初始化
cd my-project
uv run --project /path/to/ProjectTool pjt init

# 或者安装为工具
uv tool install /path/to/ProjectTool
pjt init
```

完整体验（注意 **Area 与 Milestone 的分工**：Milestone 是阶段，Area 是模块）：

```bash
pjt member add jichao --name "计超" --role maintainer
pjt member map-git jichao --git-name jichao --git-email jichao@example.com
pjt goal add "完成 EFW Studio 1.0"

# Milestone = 阶段 / 交付节点
pjt milestone add "真机 Debug MVP" --goal GOL-xxx --due 2026-10-20

# Area = 稳定模块 / 工作领域；owner 显式声明，1 个=私有块，多个=公共接口区
pjt area add Debug -d "传输层与真机调试" --path-pattern 'studio_core/**'
pjt area add UI -d "编辑器与面板" --path-pattern 'studio_ui/**'
pjt area set-owner Debug --add jichao          # 私有块
pjt area set-owner UI --add jichao --add ling  # 公共接口区（多 owner）

# Task 同时属于 1 milestone + 1 area + N labels
pjt task add "实现 TCP Transport" \
  --owner jichao --milestone MLS-xxx --area Debug --priority high --weight 2

pjt task ready  TSK-xxx
pjt task start  TSK-xxx
pjt update add --task TSK-xxx "TCP 通信完成，开始处理断线重连"
pjt task review TSK-xxx
pjt task done   TSK-xxx

# Decision + 它的产物引用
pjt decision add --title "Debug Runtime 使用 TCP 而不是 WebSocket" \
  --decision "底层 Transport 使用 TCP" \
  --rationale "实现简单，语言无关"

# Artifact = 工程产物的「引用」（不是文件管理器，绝不修改被引用文件）
pjt artifact add file studio_core/debug.py \
  --name "Debug transport" --task TSK-xxx
pjt artifact verify

# 接口契约：工作树里一份固定模板的 markdown + 注册成 Artifact（纯引用）
pjt interface init store.updateModel --area Debug --consumer UI
pjt interface check

# 提交时带上 trailer，工具就能把 commit 关联回任务
#   git commit -m "fix loopback" -m "PJT-Task: TSK-xxx"
pjt git status                      # 改动的工程文件 + 候选 Area + 引用它的 Artifact
pjt git log --task TSK-xxx          # 这个任务关联过哪些 commit
pjt git link-commit HEAD            # 登记成 git_commit Artifact（只写 .pjt）

pjt status && pjt log --since 7d && pjt graph project && pjt doctor
```

## 多 agent 开工流程

`pjt task next` 是**只读**简报，不认领任何东西——它一次给全：下一个可开工的
task（未阻塞、依赖已满足、无人认领）、**这个 task 相关的接口契约**、以及这块最近
该看谁。**先读契约再动手**：agent 没有隐性知识，它不知道 `store.updateModel` 什么
时候能改、什么算破坏性变更。

```bash
# 1) 看（只读，随便看）
pjt task next

# 2) 读了契约，确认要认领，再 claim（认领是一个决定，不是查询的一部分）
pjt task claim TSK-xxx --agent my-agent --ttl 60

# 3) 干活 → 干完释放（不释放也会到期自动失效）
pjt task start TSK-xxx && pjt task done TSK-xxx
pjt task release TSK-xxx --agent my-agent
```

- 撞上别人认领 → exit 6 `CLAIMED`，**换任务**，不是错误。
- 撞上别人改过 → exit 5 `REVISION_CONFLICT`，**重读再试**。
- claim 是**协调信号，不是锁也不是权限门禁**——`.pjt` 跟着 Git 走，有仓库写权限
  就能绕过它。真正强制要走服务器 / Git ACL。
- 多机协作时给每个 agent 设 `PJT_ACTOR`（优先于 `local.toml`）：
  `export PJT_ACTOR=my-agent`，或启动时 `PJT_ACTOR=my-agent pjt task claim ...`。

## 核心概念

```text
Project
├── Goal                    为什么做
├── Milestone               时间 / 阶段 / 交付          （status / due_at / 派生 progress）
├── Area                    稳定模块 / 工作领域         （name / description / 父子层级 / owner_ids）
├── Task
│     ├── milestone_id      这个工作服务于哪个阶段？
│     ├── area_id           这个工作属于哪块代码？      （单值）
│     ├── owner_ids         谁做
│     ├── claim             多 agent 认领（到期自动失效，派生状态）
│     ├── dependencies      先后关系（computed blocked 只推导，不改状态）
│     ├── labels            自由标签（bug / test / hardware）
│     ├── related_updates   进展记录
│     └── related_artifacts 产物引用（反向派生读）
├── Decision ── artifacts    为什么这么定 + 支撑它的文件（源码 / 文档 / commit）
├── Artifact                 ART-，kind + locator（纯引用，不存内容）
│                              接口契约 = kind=file + metadata.interface=true
├── Member / Update / Link
└── Event History            append-only，base_rev → new_rev 链
```

**Area 不是 Milestone，也不是 Label**：

- Milestone 回答「这批工作服务于哪个交付目标」，有状态、截止时间、派生进度。
- Area 回答「这块工作动的是哪块东西」，**没有** status / progress / due_at。
- Label 是自由标签（`bug` `test` `high-risk`），没有结构。

**Area 分区靠 owner，不靠额外字段**：`owner_ids` 是显式复数，**1 个 = 私有块，
多个 = 公共接口区**（被 UI / 数据流 / 状态机共同依赖的 core 就是这样）。
不需要 `shared` 标记。Milestone 和 Goal **故意没有** owner —— 只有 Area 是分区单元。

**接口契约不是一等对象**：它是工作树里一份固定模板的 markdown，再注册成一份
`kind=file` 的 Artifact，靠 `metadata.interface=true` 标记身份（**不是**靠
`Artifact.kind`——那是个封闭枚举，只有 `file/url/git_commit/git_branch` 和 10 种
不透明形态）。所以手工登记的 `kind=file` Artifact 默认**不会**出现在
`interface list` 里，要用 `pjt interface register`。正文是人写的散文，硬塞进
JSON 只会让人绕过工具 —— diff / blame / 历史 Git 已经做得更好。
`interface check` 只报告不改写，有 error 时退出码 1（可直接当 CI 门禁）。

## CLI 速查

顶层：`init` `status` `doctor [--repair]` `migrate` `log` `graph`

```text
pjt task       add|archive|artifacts|assign|block|cancel|claim|delete|depend|done|edit|history|label|list
               |move|move-area|next|ready|related-interfaces|related-updates|release|restore|review
               |set-parent|show|start|unassign|undepend|unlabel
pjt area       activity|add|archive|edit|history|list|match-path|restore|set-owner|set-parent|show|tasks|tree
pjt interface  check|init|list|register|show|sync
pjt artifact   add|attach|detach|edit|history|list|remove|show|verify
pjt decision   accept|add|edit|history|list|reject|show|supersede
pjt goal       achieve|add|archive|drop|edit|list|restore|show
pjt link       add|edit|list|map-local|remove|resolve|show|status|unmap-local
pjt member     activate|activity|add|deactivate|edit|list|map-git|show|use|workload
pjt milestone  activate|add|cancel|close|edit|list|progress|show
pjt update     add|archive|edit|history|list|show
pjt git        link-commit|log|status        # 只读感知，不写 Git 仓库
pjt project    edit|show
```

共 **117** 个命令 + 12 个分组。`pjt <域> --help` 是权威列表；机器可读版本见
`system.cli`（KC 用它发现能驱动什么）。

编辑类命令（`edit` / `attach` / 状态快捷命令）统一支持 `--expected-rev REV`，
不匹配时 exit 5 `REVISION_CONFLICT`（乐观并发：防止覆盖别人的修改）。

全局选项：

```text
--json        机器可读的 JSON 输出（RPC 结构）
--porcelain   稳定纯文本（仅 pjt log / pjt status / pjt task list 有实现）
              ↑ 这两个是**根命令**选项，必须写在子命令**之前**：
                pjt --json task list ✅   pjt task list --json ❌
--as MEMBER   指定本次操作的 Actor（覆盖 local.toml）
-C PATH       指定项目路径
--version     版本
```

退出码：`0` 成功 · `2` 用法错误 · `3` 校验错误 · `4` 未找到 · `5` 冲突 ·
`6` 已被别人认领（`CLAIMED`，换任务而不是重试）· `9` 需迁移 / 项目损坏。

## 开发

```bash
uv sync                # 安装依赖（含 dev）
uv run ruff check .    # 静态检查
uv run mypy project_tool
uv run pytest          # 具体用例数以实际输出为准
uv run pjt --help      # 运行 CLI
```

改完 `project_tool/version.py` 里的版本号后，可编辑安装的元数据不会自动刷新：

```bash
uv pip install -e . --reinstall-package project-tool
```

架构约束（详见 docs/02-architecture.md）：

1. `.pjt` 是唯一数据源；**没有服务器**。
2. CLI / 未来 SDK 都不直接读写 `.pjt`，统一走 Application Service。
3. SQLite / state / labels 全部只是索引，可随时删除重建。
4. Event 不可修改；纠正历史靠新事件。
5. 所有修改带 revision；`expected_rev` 语义全局统一；**不做静默覆盖**。
6. 进度、blocked 状态由 Task 推导，不落库百分比。
7. 读对象时校验 rev —— 数据被外部改过就报错，不靠下一次写入洗白。
8. Artifact 只是引用，任何写路径都不碰被引用的工程文件。
