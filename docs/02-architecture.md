# Project Tool — 架构设计

## 1. 总体风格

Ports & Adapters / Clean Architecture。依赖方向永远向内：

```text
              CLI        Web(未来)      SDK/KC(未来)
               │            │              │
               └────────────┼──────────────┘
                            ▼
                  Application Service        ← 用例编排、事务边界
                            │
                            ▼
                     Domain Core             ← 模型、规则、状态机
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
       Storage           Graph             (Search V1)
          │                 │
   ┌──────┼──────┐          │
   ▼      ▼      ▼          ▼
 Files   State  Events   依赖/项目图
          │
          ▼
        .pjt/
```

未来扩展（V2）：

```text
Application Service → Remote Adapter → Project Server (FastAPI + PostgreSQL)
```

## 2. 模块结构（V0 实际代码）

```text
project_tool/
│
├── domain/                 # 纯领域层，无 I/O
│   ├── ids.py              # ULID 生成、ID 前缀、短 ID 解析
│   ├── hashing.py          # canonical JSON 与 rev 计算
│   ├── base.py             # BaseObject / Header
│   ├── project.py          # Project
│   ├── goal.py             # Goal
│   ├── milestone.py        # Milestone
│   ├── task.py             # Task、Priority、TaskStatus、Dependency
│   ├── member.py           # Member
│   ├── update.py           # Update
│   ├── decision.py         # Decision
│   ├── link.py             # Project Link
│   ├── event.py            # Event
│   ├── enums.py            # 所有状态枚举与类型常量
│   └── errors.py           # 错误码与异常
│
├── storage/                # 持久化适配器（唯一接触 .pjt 的层）
│   ├── project_store.py    # init/open/find，ProjectPaths
│   ├── object_store.py     # 对象读写、短 ID 解析、集合映射
│   ├── event_store.py      # 事件追加与查询
│   ├── transaction.py      # staging + 原子改名 + 锁
│   ├── local_state.py      # .pjt/local/local.toml、device_id、锁文件
│   └── migrations.py       # schema_version 校验与迁移入口
│
├── application/            # 用例层
│   ├── service.py          # ProjectService：所有 method 的入口
│   ├── queries.py          # status / progress / log / workload
│   └── doctor.py           # 完整性检查
│
├── graph/                  # 图算法
│   ├── dependency.py       # 环检测、computed blocked
│   └── project_graph.py    # 任务树 / 项目树构建
│
├── cli/
│   └── main.py             # Typer CLI（pjt）
│
└── integrations/           # 外部系统适配（V1：git.py、filesystem.py 已有原子写）
```

后续（V1/V2）新增目录，不改变上述依赖方向：

```text
api/        # FastAPI Local Server（V1）
sync/       # push/pull/conflicts（V2）
integrations/git.py   # Git Adapter（V1）
web/        # React + TypeScript（V1，独立包）
```

## 3. 依赖规则

```text
domain       必须零依赖（只允许标准库 + pydantic）
storage      只依赖 domain
graph        只依赖 domain
application  依赖 domain/storage/graph
cli          依赖 application（绝不直接 import storage）
```

CI 与 review 需要拒绝的写法：

```python
# 错误：CLI 直接操作文件
Path(".pjt/objects/tasks/...").write_text(...)

# 错误：Core 依赖 Web
from project_tool.api import ...   # 出现在 application/ 以下
```

## 4. Application Service 接口协议

所有客户端使用同一请求/响应协议（本地直接调用，未来走 HTTP 是同构的）：

```json
{ "id": "req-001", "method": "task.create", "params": { ... } }
```

```json
{ "id": "req-001", "result": { ... } }
```

```json
{
  "id": "req-001",
  "error": { "code": "CONFLICT", "message": "Task 已被其他操作修改", "details": {} }
}
```

- `method` 命名：`<domain>.<action>`，与 CLI 子命令、未来 REST 路由一一对应。
- `params` 校验失败 → `INVALID_ARGUMENT`；找不到 → `NOT_FOUND`。
- CLI `--json` 输出 RPC 响应；默认输出人类可读文本。

## 5. 写路径（所有修改共用一条）

```text
Command
  ↓ 解析参数、补全 Actor、解析短 ID
Validate（对象存在、引用有效、状态合法、无依赖环）
  ↓
Acquire write lock（.pjt/local/locks/write.lock）
  ↓
Load objects（canonical JSON）
  ↓
Check expected_rev（若调用方给了 rev）
  ↓
Build new objects + events（version+1、updated_at、rev）
  ↓
Stage 到 .pjt/transactions/<TXN-…>/
  ↓
原子 rename 到 objects/ 与 events/
  ↓
更新派生缓存（state.json、refs/labels.json）
  ↓
Release lock
```

任何一步失败：staging 目录直接丢弃，canonical 数据未被触碰。
锁内不做网络与 UI 操作，事务保持毫秒级。

## 6. 读路径

```text
Query → Application Service → 扫描 objects/ + events/ → 领域计算（progress/blocked/graph）
```

- V0 直接扫描文件（项目规模 < 10⁴ 对象，性能足够）。
- V1 增加 `.pjt/local/index.sqlite` 只读缓存，可随时 `pjt index rebuild`。
- 任何缓存失效都必须回退到文件扫描，而不是报错。

## 7. 关键设计决策（与规范对应）

| 决策 | 理由 |
|---|---|
| 一个对象一个文件 | 不同成员改不同任务 → 不同文件 → Git merge 友好 |
| ULID 而非自增编号 | 离线多人创建不冲突；ULID 字典序即时间序 |
| rev 为内容哈希 | 并发控制、同步收敛、缓存键三合一 |
| Snapshot + Event 双写 | objects 回答“现在”，events 回答“为什么” |
| 删除 = lifecycle 变更 | 同步才能传播“删除”这一事实 |
| 进度不落库 | 由 Task 状态/weight 推导，避免误导性百分比 |
| computed blocked 不写状态 | 区分人为 blocked 与依赖 blocked |
| SQLite 可删 | canonical 永远是 project.json + objects/ + events/ |
| 不接管 Git | V0 完全不碰 Git；V1 只读集成 |

## 8. Actor 与 Device

- **Actor**：`created_by` / `updated_by` / 事件 `actor_id` 的来源。
  解析顺序：`--as` 参数 > `PJT_ACTOR` 环境变量 > `.pjt/local/local.toml` > 第一个 active member > `null`。
  在 Member 加入前产生的项目初始化事件允许 `actor_id = null`。
- **Device**：首次 `pjt init` 生成 `DEV-XXXXXXXX` 存入 `local.toml`，用于事件溯源区分设备。

## 9. 错误模型

领域异常携带错误码与退出码，CLI 与未来 HTTP 层共用同一张表：

```text
INVALID_ARGUMENT  NOT_FOUND  ALREADY_EXISTS  CONFLICT  REVISION_CONFLICT
DEPENDENCY_CYCLE  BROKEN_LINK  PERMISSION_DENIED  AUTH_REQUIRED
REMOTE_UNAVAILABLE  SYNC_CONFLICT  SCHEMA_UNSUPPORTED  PROJECT_CORRUPTED
GIT_ERROR  IO_ERROR  INTERNAL
```

详见 [05-interfaces.md](05-interfaces.md)。
