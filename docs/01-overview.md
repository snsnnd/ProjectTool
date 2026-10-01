# Project Tool — 产品总览

> Git tracks code. Project Tool tracks the project.
> Git 记录代码的演化，Project Tool 记录项目的演化。

## 1. 它是什么

Project Tool 是一个 **Local-first、Git-aware 的工程项目状态与协作系统**。

它记录 Git 不记录的东西：

- 项目为什么存在（Goal）
- 现在做到哪里（Milestone / Task / Update）
- 为什么这样决定（Decision）
- 谁被什么阻塞（Dependency / Blocked）
- 最终产出了什么（Artifact，V1）
- 项目之间是什么关系（Link / Graph）

一个工程目录可以同时拥有两套版本系统，互不替代：

```text
my-project/
├── .git/     # 代码版本
├── .pjt/     # 项目状态
├── src/
└── README.md
```

## 2. 核心属性

| 属性 | 含义 |
|---|---|
| Local-first | 没有服务器也完整可用，`.pjt` 是唯一数据源（**永久性**，不是过渡状态） |
| CLI-first | CLI 能完整操作的能力，Web 才有资格调用 |
| Git-aware | 有 Git 自动增强，没有 Git 不影响使用 |
| Composable | 多项目可通过 Project Link 组成项目树 |
| Serverless | **没有服务器**，协作交给 Git（决定见 docs/06 §V2） |

两种运行组合（**只有这两种**）：

```text
无 Git   完整可用，只是无法自动关联代码产物
有 Git   完整形态：commit / 分支 / diff / 协作全部复用 Git
```

**不做「有服务器」那一档**。`.pjt` 跟 Git 走，权限、冲突检测、历史全部由 Git 承担；
自建同步服务器要重新实现其中一半还要自己运维。

## 3. 职责边界

Project Tool 负责：

```text
Goal / Milestone / Task / Member（项目内身份）
**Area**（稳定模块/工作领域，owner 分区）/ Update / Decision / Artifact / Link
接口契约（工作树里的 markdown + Artifact 引用，不是一等对象）
Event History / Dependency / Project Graph
**不做** Web UI / 远程同步 / 账号（docs/06 §V2）。可视化由 KC 侧生成静态报告
```

Project Tool 不负责：

```text
Git 文件版本控制        聊天系统
组织人事 / 学号 / 班级   库存 / 资金
邮件审批                组织级账号系统
```

## 4. 三个系统的最终分工

```text
Git          →  代码发生了什么
Project Tool →  项目发生了什么，以及为什么
KC           →  项目属于谁、谁可以参与、组织如何运行
```

Project Tool 中的 `Member` 只回答“这个人在这个项目中是谁”（handle、role、git 身份映射），
不是账号，不是权限实体。**没有账号体系，也没有权限模型**——`.pjt` 跟着 Git 走，
访问控制交给 Git 托管（私有仓库）或文件系统权限。

## 5. 三种运行模式（同一套 Core）

```text
CLI 模式（当前唯一）
  CLI → Application Service → Domain Core → .pjt/ → Git

可选：本地 Web（V1-B，尚未实现）
  Browser → Local HTTP Server → 同一个 Service → 同一个 .pjt/

不存在：Remote Collaboration
  Developer A/B 之间的协作 = 各自的 .pjt + Git（pull / merge / 冲突由 rev 链暴露）
```

三条铁律（任何时候不得破坏）：

1. `.pjt` 是项目真实数据源，服务器不是项目存在的前提。
2. CLI / Web / SDK 都不直接读写 `.pjt`，统一走 Application Service。
3. Core 永远不依赖 Web。

## 6. 术语表

| 术语 | 含义 |
|---|---|
| 对象（Object） | Goal/Task/Milestone 等 JSON 实体，一对象一文件 |
| 事件（Event） | 不可变历史记录，append-only |
| rev | 对象内容的 SHA-256，用于并发控制与冲突检测 |
| 事务（Transaction） | 一次命令的多对象写入单元，要么全写要么不生效 |
| 短 ID | 对象主键的前缀片段，项目内无歧义即可 |
| computed blocked | 由依赖推导出的阻塞，不修改任务自身状态 |
| 派生缓存 | 可由 canonical 数据重建的数据（state/refs/index） |

## 7. 文档索引

| 文档 | 内容 |
|---|---|
| [02-architecture.md](02-architecture.md) | 分层架构、模块结构、依赖规则 |
| [03-data-model.md](03-data-model.md) | ID、Header、各对象 schema、状态机 |
| [04-storage.md](04-storage.md) | `.pjt` 布局、rev、事务、锁、恢复 |
| [05-interfaces.md](05-interfaces.md) | Service API、错误码、CLI 规范 |
| [06-roadmap.md](06-roadmap.md) | V0–V3 路线图与验收标准 |
| [07-v0.1-audit.md](07-v0.1-audit.md) | V0.1 审计发现与处理结果 |
| [08-events.md](08-events.md) | Event contract |
| [09-handover.md](09-handover.md) | 交接文档（状态 / 不可破坏的约定 / 排障）|
| [09-v1a-design.md](09-v1a-design.md) | V1-A 设计记录（Area / Artifact / 并发契约 / 迁移）|
| [10-kc-integration.md](10-kc-integration.md) | KC 接入参考（初始化 / 分发 / 身份 / 权限边界）|
| [../AGENTS.md](../AGENTS.md) | 给接手 agent 的速查与禁区 |
