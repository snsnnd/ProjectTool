# Project Tool — 存储与一致性设计（对齐 v0.6.9）

## 1. `.pjt` 目录规范

```text
.pjt/
├── project.json            # Project 对象（canonical，含 version/rev）
├── config.toml             # 项目级配置（canonical）
│
├── objects/                # canonical：一个对象一个文件
│   ├── goals/       GOL-….json
│   ├── milestones/  MLS-….json
│   ├── tasks/       TSK-….json
│   ├── members/     MBR-….json
│   ├── updates/     UPD-….json
│   ├── decisions/   DEC-….json
│   ├── areas/        ARA-….json
│   ├── artifacts/   ART-….json
│   └── links/       LNK-….json
│
├── events/                 # canonical：不可变事件，按年月分目录
│   └── 2026/09/EVT-….json
│
├── refs/                   # 派生引用（可重建）
│   └── labels.json
│
├── state/                  # 派生状态（可重建）
│   └── state.json
│
├── local/                  # 机器本地，永不进 Git
│   ├── local.toml          # actor、device_id、绝对路径映射
│   ├── index.sqlite        # V1 索引缓存
│   ├── conflicts/          # V2 冲突文件
│   ├── backups/            # migrate 前备份
│   └── locks/              # write.lock
│
└── transactions/           # 事务工作区，永不进 Git
    └── TXN-…/              # manifest.json + COMMIT + staged/
```

`pjt init` 自动生成 `.gitignore`（追加，不覆盖已有内容）：

```gitignore
# Project Tool local state
.pjt/local/
.pjt/transactions/

# Project Tool derived caches (rebuilt on demand; never commit these)
.pjt/state/
.pjt/refs/labels.json
```

**canonical = `project.json` + `objects/` + `events/`。**
只要这三者存在，Project Tool 数据就能恢复；`refs/`、`state/`、SQLite、Web、Server 全部是派生物。

### 派生缓存绝不能提交（V1-C）

规则是**具体的两个文件**，不是整个 `refs/` 目录——将来 `refs/` 里可能放规范数据，
整个目录被忽略就会静默丢数据。

这不是洁癖，是多人协作的硬约束。V1-C 的合并探针
（`dogfooding/scripts/multiwriter_probe.py`）实测 2 个写者的 9 个真实合并场景：

| | 能干净合并 |
|---|---|
| 派生缓存被提交 | **1/9** |
| 派生缓存被忽略 | **8/9** |

`state/state.json` 每次事务都重写、`refs/labels.json` 由重扫 task 生成，
被提交就意味着**每一次**并发合并都撞一次。剩下的 1/9（两人改同一个 task）
是本来就该冲突的真语义冲突。

因此 `pjt doctor` 把「派生缓存被 git 跟踪」判为 **error** 而不是 warning：
`.gitignore` 是静默约定，半年后一次 `git add -f` 就会悄悄回归，没有信号。
doctor **只报告不代劳**——修它需要 `git rm --cached`，那是 Git 写操作，
而 Git 适配器是只读的（`AGENTS.md` §11）。

## 2. 磁盘格式

- 对象文件按 `sort_keys=True, indent=2` 落盘（diff 友好）；`rev` 按 canonical（无缩进、无空格）计算。
- 时间戳统一带时区：`2026-09-30T14:20:01+08:00`。
- 编码 UTF-8、`ensure_ascii=False`（中文可读）。
- 原子写：临时文件 → `flush + fsync` → `os.replace`；目录项尽力 `fsync`（Windows 自动跳过）。

## 3. rev 与并发控制

```text
rev = "sha256:" + sha256( canonical_json(object without "rev") )
```

- **所有对象**（含 Project）都带 `version` / `rev` / `created_by` / `updated_by`。
- 更新时：`version += 1`，`updated_at = now`，重算 `rev`。
- 显式并发控制：`task.set_status(expected_rev=…)`、`project.update(expected_rev=…)`
  不匹配 → `REVISION_CONFLICT`。
- 默认并发控制：每个事务在写入前重新校验全部 `base_rev`，任何对象在“读取→提交”
  之间被改动都会以 `REVISION_CONFLICT` 拒绝，不会静默覆盖。

## 4. Crash-Recoverable Transaction 协议

V0.1 **不宣称**多文件 ACID 原子提交，而是提供明确保证：

```text
崩溃可检测
状态可判断
恢复可重复（幂等）
恢复结果确定（roll-forward）
```

事务目录结构：

```text
.pjt/transactions/TXN-…/
├── manifest.json
├── COMMIT              # 提交标记（manifest 之后写入）
└── staged/             # 与 .pjt 相对路径镜像的暂存文件
```

manifest 至少包含：

```json
{
  "schema_version": "1.0",
  "transaction_id": "TXN-…",
  "state": "prepared",
  "created_at": "…",
  "actor_id": "MBR-…",
  "device_id": "DEV-…",
  "writes": [
    { "kind": "object", "target": "objects/tasks/TSK-….json",
      "base_rev": "sha256:…", "new_rev": "sha256:…" },
    { "kind": "event", "target": "events/2026/09/EVT-….json",
      "event_id": "EVT-…", "base_rev": null, "new_rev": null }
  ]
}
```

提交顺序（在 WriteLock 内执行）：

```text
1 校验全部 base_rev（不匹配 -> REVISION_CONFLICT，未提交即丢弃）
2 写入 staged/（对象先、事件后）
3 落 manifest（state=prepared）并 fsync
4 落 COMMIT 标记并 fsync
5 roll-forward apply：对象与事件逐个 os.replace
6 manifest -> applied，更新派生 state，删除事务目录
```

- **第 4 步之前失败**：直接清空 staging，canonical 未被触碰。
- **第 4 步之后失败**：事务目录保留（manifest + COMMIT + 残留 staged），
  `pjt doctor --repair` / `project.recover` 会 roll-forward。
- 不存在 rollback journal：apply 只把 staged 替换到 canonical，且以 `new_rev`
  判定是否已生效，因此重复 apply 幂等。

## 5. 恢复（storage/recovery.py）

```text
scan_transactions()     列出事务目录并分类
recover_transaction()   单个事务的恢复
recover_all()           全量恢复（doctor --repair / project.recover 调用）
```

scan 分类：

| status | 条件 | 处理 |
|---|---|---|
| `uncommitted` | 无 COMMIT（含只有 staging / 只有 prepared manifest） | 安全丢弃 |
| `prepared` | 有效 manifest + COMMIT | roll-forward |
| `applied` | manifest state=applied 但目录未清理 | 补写 state 后清理 |
| `invalid` | manifest 缺失/损坏 | 无 COMMIT → 丢弃（repairable）；有 COMMIT → 保留待人工检查 |

恢复输出 `RecoveryResult(action)`：

```text
discarded       已丢弃未提交事务
rolled_forward  已提交事务已补全
error           冲突或无法恢复（保留现场，doctor 报 error）
```

恢复是幂等的；冲突（目标对象被第三方改成第三个 rev）会保留事务目录并报告，
不做猜测性覆盖。

## 6. 写锁（WriteLock）

锁文件 `.pjt/local/locks/write.lock` 为 JSON：

```json
{ "pid": 12345, "lock_id": "LCK-…", "created_at": 1759…, "host": "…" }
```

规则：

1. `O_CREAT|O_EXCL` 创建，默认等待 10s，超时 → `CONFLICT`。
2. **PID 存活 → 永不偷锁**（POSIX `os.kill(pid,0)`；Windows `OpenProcess` 兼容）；
   不再仅凭 `mtime > 60s` 判断，合法长操作不会被抢。
3. PID 死亡或不可解析，且超过 `stale_after`（默认 60s）→ 视为陈旧，可回收。
4. 释放时只在 `lock_id` 与自身一致时删除；锁被他人替换后绝不误删。
5. `pjt doctor --repair` 会清理陈旧锁；持有者是活进程时 repair 会失败并提示。
6. **锁只串行化「写」，挡不住读。** 读（`task next` / `list` / `doctor`）都在锁
   之外，所以它挡不住「读的那一瞬间正好撞上替换」—— 详见下面 §6.1。

### 6.1 Windows 共享冲突（`retry_on_sharing_violation`）

Python 打开文件时**没有** `FILE_SHARE_DELETE`。所以只要**任何人**打开着目标文件，
`os.replace` / `unlink` 就会拿到 `WinError 32`。配合上面第 6 条：读和写都跑得
好好的，读落在 `os.replace` 的微秒级窗口里，写的一方就会崩 —— **这是真实的多
agent 用法在 Windows 上的 bug，不是测试的抖动**（CI 上就是靠它抓到的）。

处理方式是**重试**，不是放弃：临时文件在 replace 之前已经写完并 fsync 过，
重试只是把同一份内容再放一次，不会丢数据。

- `atomic_write_text` / `read_json` / 两处删锁文件都走
  `filesystem.retry_on_sharing_violation(path, action)`。
- 预算 40 次 × 25ms = 1s：够覆盖瞬时句柄，又不会变成挂死。
- **非 Windows 上完全不重试** —— 那里 `PermissionError` 是真的权限问题，
  等它只会变成无谓的延迟。
- 开关是 `filesystem.IS_WINDOWS` 常量而不是内联 `os.name` 检查，
  这样 Linux 上也能直接测 Windows 分支（`tests/test_windows_sharing.py`）。

一个坑：这个重试**不能**写成 `@contextmanager` —— generator 被 `throw()` 重新
进入后**不允许再次 yield**，于是重试会变成 `RuntimeError: generator didn't stop`。
必须用回调。

## 7. state 与 refs（派生数据）

`state/state.json`：`last_transaction_id / object_count / event_count / updated_at`。
`refs/labels.json`：项目内 label 去重集合。

两者都可删除重建，**不是**数据源；任何逻辑不得以它们为准。

### 3.1 读取即校验（V1-A.1 起）

```text
get_raw / list_raw / load_raw   ->  读字节，不校验 rev
load_model / list_models         ->  强制 verify_rev(record)
```

对象文件被手改、Git merge 或冲突解决动过之后，**读取时**就报 `PROJECT_CORRUPTED`，
而不是等到下一次写入把内容「洗白」（重算一个 rev 签上名，掩盖掉篡改）。
这对 V1-B 尤其重要：Git Adapter 一旦开始介入，`.pjt` 被外部修改的概率大幅上升。

两处刻意例外：

- `doctor` 用 `check_rev=False` —— 数据已经损坏时诊断本身必须还能跑完并指出是哪条；
- `resolve_actor` 用 `check_rev=False` —— 解析 actor 是尽力而为的记账问题，
  一个坏掉的 member 对象不该让 `ServiceContext` 构造失败（否则 `doctor` 也起不来）。

## 8. 数据完整性（pjt doctor）

```text
project.json：header、schema、rev（legacy 无 rev -> warning）
每个对象：JSON、rev、id/type/project_id/集合目录一致
引用完整：milestone/goal/owner/parent/dependency/task_ids/supersedes
依赖无环 + 层级无环（goal parent / task parent / decision supersede）
member.handle 唯一
events：可解析、entity 存在、base_rev/new_rev 链一致、对象 rev 与最后事件一致
transactions：未完成 / 已提交未应用 / manifest 损坏（标注能否自动恢复）
write.lock：活锁 / 陈旧锁
refs/state 存在性
```

每个 check 带 `repairable` 标记；`pjt doctor --repair` 先执行
`project.recover`（roll-forward + 清理陈旧锁）再重新检查。
doctor 发现 error 时退出码 9。

## 9. Schema 版本与迁移

- 所有对象 `schema_version = "1.0"`。
- 工具遇到 `2.x` 而只支持 `1.x`：**拒绝写入**，尽量只读，不得偷偷修改。
- `pjt migrate` 逐级执行；执行前自动备份到 `.pjt/local/backups/`（当前 1.0 → 1.1 补齐 objects/areas 等空目录并抬版本）。

## 10. 本地状态与安全

`.pjt/local/local.toml` 保存 `device_id`、默认 `actor`、机器特定绝对路径映射。

`.pjt` 默认禁止保存：

```text
密码  API Token  SMTP 密钥  OAuth refresh token  Private Key
```

Secrets 必须进 OS Keychain（V2）或 `.pjt/local/`（已 gitignore）。
