# Project Tool — 架构设计（V0.1）

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

**没有这一层。** 决定不提供远程服务器（docs/06 §V2）：`.pjt` 跟 Git 走，
多人协作 = 各自的 `.pjt` + Git pull / merge，冲突由 `rev` 链与 `doctor` 暴露。
将来若要加本地 Web，也只是在本进程内多一个 HTTP 入口，仍然没有服务端存储。

## 2. 模块结构（V0.1 实际代码）

```text
project_tool/
│
├── domain/                 # 纯领域层，无 I/O
│   ├── ids.py              # ULID、ID 前缀、短 ID 解析
│   ├── hashing.py          # canonical JSON 与 rev 计算
│   ├── base.py             # BaseObject / Header
│   ├── project.py          # Project（含 version/rev/actor）
│   ├── goal.py / milestone.py / task.py / member.py
│   ├── update.py / decision.py / link.py / event.py
│   ├── enums.py            # 状态枚举与类型常量
│   ├── validation.py       # 标题/文本/标签长度与形态约束
│   └── errors.py           # 错误码与异常（含 HIERARCHY_CYCLE）
│
├── storage/                # 持久化适配器（唯一接触 .pjt 的层）
│   ├── project_store.py    # init/open/find，ProjectPaths，派生 state
│   ├── object_store.py     # 对象读写、短 ID 解析、集合映射
│   ├── event_store.py      # 事件 append-only 查询
│   ├── transaction.py      # staging + manifest + COMMIT + 原子 apply
│   ├── recovery.py         # scan / roll-forward / 幂等恢复
│   ├── local_state.py      # local.toml、device_id、WriteLock（PID+token）
│   └── migrations.py       # schema_version 校验与迁移入口
│
├── application/            # 用例层
│   ├── service.py          # ProjectService：组合 + call/handle
│   ├── registry.py         # 显式 MethodSpec 注册（mutating/category）
│   ├── context.py          # ServiceContext：共享解析/校验/写路径
│   ├── services/           # 领域服务（按 use-case 拆分）
│   │   ├── project.py / system.py / goal.py / milestone.py
│   │   ├── task.py / member.py / update.py / decision.py
│   │   └── link.py / log.py / graph.py
│   ├── queries.py          # status / log / workload
│   └── doctor.py           # 完整性检查（repairable 标记）
│
├── graph/                  # 图算法
│   ├── dependency.py       # 依赖环、computed blocked
│   └── project_graph.py    # 任务树 / 项目树 / 里程碑进度
│
├── integrations/           # 外部系统适配
│   ├── filesystem.py       # 原子写、fsync_dir、JSON 读写
│   │                       # + retry_on_sharing_violation（Windows 共享冲突重试）
│   └── git.py              # Git 只读适配器（运行时子命令白名单）
│
└── cli/
    ├── main.py             # Typer root + 全局选项 + 子命令注册
    ├── common.py           # CliState / execute / 错误映射（仅调 Service）
    ├── render.py           # 输出渲染
    ├── project.py          # init/status/doctor/migrate
    ├── task.py / goal.py / milestone.py / member.py
    ├── update.py / decision.py / link.py / log.py / graph.py
    ├── area.py / artifact.py / interface.py / git.py
    └── __init__.py
```

## 3. 依赖规则

```text
domain       零依赖（标准库 + pydantic）
storage      只依赖 domain
graph        只依赖 domain
application  依赖 domain/storage/graph
cli          依赖 application（绝不 import storage / filesystem）
```

CI 与 review 需要拒绝的写法：

```python
# 错误：CLI 直接操作文件 / storage
from project_tool.storage import ObjectStore

# 错误：领域服务绕过 ServiceContext 直接写文件
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

- method 名称 `<domain>.<action>`，与 CLI 子命令、未来 REST 路由一一对应。
- **显式 registry**（`application/registry.py`）：每个 method 注册
  `MethodSpec(name, handler, mutating, category, description)`；
  未知 method → `INVALID_ARGUMENT`。当前共 123 个 method（V0.1 时是 83）。
- `system.capabilities` 返回 `protocol_version / schema_version / methods / features`，
  供 Web / SDK 做能力发现；features 当前全部为 false（artifact/git/search/web/remote/sync）。
- `ProjectService.call(method, params)` 与 `handle(...)` 与 V0 完全兼容。

## 5. 写路径（所有修改共用一条）

```text
Command
  ↓ 解析参数、补全 Actor、解析短 ID、领域校验
Validate（引用存在且未删除、层级/依赖无环、milestone 开放…）
  ↓
Acquire WriteLock（PID+token；活进程锁不可偷）
  ↓
Load objects
  ↓
Check base_rev（不匹配 -> REVISION_CONFLICT）
  ↓
Build new objects + events（version+1、updated_at、rev）
  ↓
Stage 到 .pjt/transactions/<TXN-…>/staged/
  ↓
写 manifest（prepared）→ 写 COMMIT → fsync
  ↓
roll-forward apply（对象先、事件后，os.replace）
  ↓
manifest applied → 更新派生 state → 删除事务目录
  ↓
Release lock
```

**Windows 上第 11 步会失败，所以它不是裸 `os.replace`。** Python 打开文件不带
`FILE_SHARE_DELETE`，任何读（`task next` / `list` / `doctor` 都在锁**之外**）
落在替换窗口里都会让写的一方拿到 `WinError 32`——而锁只串行化**写**，挡不住
这个。所有原子写、读、删锁都走
`filesystem.retry_on_sharing_violation`（40 × 25ms），非 Windows 上不重试。
详见 `docs/04` §6.1。

## 5.1 读路径上的一个 Area

读不经过 WriteLock，也不经过事务：直接读 `objects/` 并**校验 rev**。
`verify_rev` 是读即校验（被外部篡改的对象读取即 `PROJECT_CORRUPTED`，
不允许靠下一次写入洗白）；只有 `doctor` 与 `resolve_actor` 豁免，
因为数据已经损坏时它们必须仍能工作。

派生视图（`queries.py`：`status` / `log` / `workload` / `area_activity` /
`task_next` / `task_related_interfaces`）都是**只读推导**：computed blocked、
Milestone progress、Area 活跃度、接口契约相关性一个都不落库。
`area_activity` 尤其要注意——`git log` 跟着 Git 走所以所有人可见，
`git status` 只有本机能看，所以两者必须分开输出并标 "THIS machine only"。
```

崩溃语义见 [04-storage.md](04-storage.md) 与 [07-v0.1-audit.md](07-v0.1-audit.md)：

```text
COMMIT 之前失败 -> staging 丢弃，canonical 未被触碰
COMMIT 之后失败 -> 目录保留，doctor --repair / project.recover roll-forward（幂等）
```

SQLite（V1）失败不回滚 canonical 数据；索引只是缓存。

## 6. 读路径

```text
Query → Application Service → 扫描 objects/ + events/ → 领域计算
```

- V0.1 直接扫描文件（项目规模 < 10⁴ 对象，性能足够）。
- V1 增加 `.pjt/local/index.sqlite` 只读缓存，可随时 `pjt index rebuild`。
- 任何缓存失效都必须回退到文件扫描，而不是报错。

## 7. 关键设计决策（与规范对应）

| 决策 | 理由 |
|---|---|
| 一个对象一个文件 | 不同成员改不同任务 → 不同文件 → Git merge 友好 |
| ULID 而非自增编号 | 离线多人创建不冲突；ULID 字典序即时间序 |
| rev 为内容哈希（含 Project） | 并发控制、同步收敛、缓存键三合一 |
| Snapshot + Event 双写 | objects 回答“现在”，events 回答“为什么” |
| crash-recoverable 事务 | 明确 roll-forward 保证，不宣称 ACID |
| 删除 = lifecycle 变更 | 同步才能传播“删除”这一事实 |
| 进度不落库 | 由 Task 状态/weight 推导，避免误导性百分比 |
| computed blocked 不写状态 | 区分人为 blocked 与依赖 blocked |
| 显式 registry | REST / SDK / 权限 / 审计的基础 |
| SQLite 可删 | canonical 永远是 project.json + objects/ + events/ |
| 不接管 Git | V0 完全不碰 Git；V1 只读集成 |

## 8. Actor 与 Device

- **Actor**：`created_by` / `updated_by` / 事件 `actor_id` 的来源。
  解析顺序：`--as` 参数 > `PJT_ACTOR` 环境变量 > `.pjt/local/local.toml` > 第一个 active member > `null`。
  Member 加入前产生的事件允许 `actor_id = null`。
- **Device**：首次 `pjt init` 生成 `DEV-XXXXXXXX` 存入 `local.toml`，事件溯源区分设备。

## 9. 错误模型

领域异常携带错误码与退出码，CLI 与未来 HTTP 层共用同一张表：

```text
INVALID_ARGUMENT  NOT_FOUND  ALREADY_EXISTS  CONFLICT  REVISION_CONFLICT
DEPENDENCY_CYCLE  HIERARCHY_CYCLE  BROKEN_LINK
PERMISSION_DENIED  AUTH_REQUIRED  REMOTE_UNAVAILABLE  SYNC_CONFLICT
SCHEMA_UNSUPPORTED  PROJECT_CORRUPTED  GIT_ERROR  IO_ERROR  INTERNAL
```

`HIERARCHY_CYCLE`（V0.1 新增）用于 goal parent / task parent / decision supersede
链环检测；`DEPENDENCY_CYCLE` 专用于 task dependency 图。

详见 [05-interfaces.md](05-interfaces.md)。
