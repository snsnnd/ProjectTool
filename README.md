# Project Tool

> Git tracks code. Project Tool tracks the project.
> Git 记录代码的演化，Project Tool 记录项目的演化。

Project Tool 是一个 **Local-first、Git-aware** 的工程项目状态与协作系统。
它不替代 Git、Jira、Notion，而是记录 Git 不记录的东西：

```text
目标 / 里程碑 / 任务 / 进展 / 决策 / 依赖 / 成员 / 产物 / 事件历史
```

一个工程目录同时拥有两套版本系统：

```text
my-project/
├── .git/     # 代码版本（Git）
├── .pjt/     # 项目状态（Project Tool）
├── src/
└── README.md
```

## 状态（V0.1）

| 能力 | 状态 |
|---|---|
| `.pjt` 存储（一对象一文件 / ULID / rev / lifecycle） | ✅ |
| Project 参与 revision concurrency（`expected_rev`） | ✅ |
| Crash-Recoverable Transaction（manifest + COMMIT + roll-forward） | ✅ |
| 写锁（PID 判活 + ownership token） | ✅ |
| 对象：Project / Goal / Milestone / Task / Member / Update / Decision / Link | ✅ |
| 不可变 Event 历史 + event 链校验 | ✅ |
| 依赖图 / 层级环检测（DEPENDENCY_CYCLE / HIERARCHY_CYCLE） | ✅ |
| 显式 method registry + `system.capabilities` | ✅ |
| CLI：init / status / doctor [--repair] / migrate / goal / milestone / task / member / update / decision / link / log / graph | ✅ |
| ruff + mypy + CI | ✅ |
| 真实项目 dogfooding（EFW Studio，零污染） | ✅（[报告](dogfooding/report.md)） |
| Artifact / Git Adapter / Search / SQLite 索引 / Local Web UI | V1 |
| Remote Server / Sync / Accounts / Webhook / SDK | V2 |
| KC 集成 | V3 |

设计文档见 [docs/](docs/)：

- [01-overview.md](docs/01-overview.md) — 产品定义与边界
- [02-architecture.md](docs/02-architecture.md) — 架构设计
- [03-data-model.md](docs/03-data-model.md) — 领域数据模型与校验规则
- [04-storage.md](docs/04-storage.md) — 存储、写锁与恢复协议
- [05-interfaces.md](docs/05-interfaces.md) — Service API / CLI / 错误码
- [06-roadmap.md](docs/06-roadmap.md) — 路线图与验收标准
- [07-v0.1-audit.md](docs/07-v0.1-audit.md) — V0.1 架构审计与硬化
- [08-events.md](docs/08-events.md) — Event contract
- [09-handover.md](docs/09-handover.md) — 交接文档（状态 / 约定 / V1 第一步）
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

完整体验：

```bash
pjt member add jichao --name "计超" --role maintainer

pjt goal add "完成 EFW Studio 1.0"

pjt milestone add "Debug Runtime" --goal GOL-xxx --due 2026-10-20

pjt task add "实现 TCP Transport" \
  --owner jichao --milestone MLS-xxx --priority high --weight 2 --label debug

pjt task start TSK-xxx
pjt update add --task TSK-xxx "TCP 通信完成，开始处理断线重连"
pjt task review TSK-xxx
pjt task done TSK-xxx

pjt decision add --title "Debug Runtime 使用 TCP 而不是 WebSocket" \
  --decision "底层 Transport 使用 TCP" \
  --rationale "实现简单，语言无关，适合低依赖环境"

pjt status
pjt log --since 7d
pjt graph tasks
pjt doctor
```

## CLI 速查

```text
pjt init [PATH]                 初始化项目（生成 .pjt/）
pjt status                      项目状态摘要
pjt doctor                      完整性检查（损坏时 exit 9）
pjt migrate                     schema 升级

pjt goal add|list|show|edit|achieve|drop
pjt milestone add|list|show|edit|activate|close|cancel|progress
pjt task add|list|show|start|block|review|done|cancel|assign|unassign
          |depend|undepend|label|unlabel|move|archive|restore|delete|history
pjt member add|list|show|edit|deactivate|activate|workload|activity|use
pjt update add|list|show
pjt decision add|list|show|accept|reject|supersede
pjt link add|list|show|remove|resolve
pjt log [--task TSK-x] [--member jichao] [--since 7d] [--type task.status_changed]
pjt graph [tasks|milestone MLS-x|projects]
```

全局选项：

```text
--json        机器可读的 JSON 输出（RPC 结构）
--porcelain   稳定纯文本，供脚本解析
--as MEMBER   指定本次操作的 Actor（覆盖 local.toml）
-C PATH       指定项目路径
```

退出码：`0` 成功 · `2` 用法错误 · `3` 校验错误 · `4` 未找到 · `5` 冲突 ·
`6` 权限 · `7` 远程 · `8` 同步冲突 · `9` 项目损坏。

## 开发

```bash
uv sync                # 安装依赖（含 dev）
uv run ruff check .    # 静态检查
uv run mypy project_tool
uv run pytest          # 运行测试
uv run pjt --help      # 运行 CLI
```

架构约束（详见 docs/02-architecture.md）：

1. `.pjt` 是唯一数据源；服务器不是项目存在的前提。
2. CLI / Web / SDK 都不直接读写 `.pjt`，统一走 Application Service。
3. Core 不依赖 Web；SQLite 只是索引，可随时删除重建。
4. Event 不可修改；纠正历史靠新事件。
5. 所有修改带 revision，不做静默覆盖。
6. 进度由 Task 状态推导，不落库百分比。
