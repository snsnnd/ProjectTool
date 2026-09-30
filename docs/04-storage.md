# Project Tool — 存储与一致性设计

## 1. `.pjt` 目录规范

```text
.pjt/
├── project.json            # Project 对象（canonical）
├── config.toml             # 项目级配置（canonical）
│
├── objects/                # canonical：一个对象一个文件
│   ├── goals/       GOL-….json
│   ├── milestones/  MLS-….json
│   ├── tasks/       TSK-….json
│   ├── members/     MBR-….json
│   ├── updates/     UPD-….json
│   ├── decisions/   DEC-….json
│   ├── artifacts/   ART-….json      （V1）
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
│   └── locks/              # 写锁
│
└── transactions/           # 事务 staging，永不进 Git
```

`pjt init` 自动生成 `.gitignore`（追加，不覆盖已有内容）：

```gitignore
.pjt/local/
.pjt/transactions/
```

**canonical = `project.json` + `objects/` + `events/`。**
只要这三者存在，Project Tool 数据就能恢复；`refs/`、`state/`、SQLite、Web、Server 全部是派生物。

## 2. 为什么一对象一文件

```text
错误：所有任务塞进一个 project.json
→ A 改 TASK-01、B 改 TASK-32，仍然形成同一个文件的 Git 冲突

正确：一个任务一个文件
→ 不同任务 = 不同文件 = Git merge 友好
```

事件同理：`.pjt/events/2026/09/EVT-….json`，而不是 `events.json`。
事件文件名天然唯一（ULID），多人追加互不冲突。

## 3. 磁盘格式

- 对象文件按 `sort_keys=True, indent=2` 落盘（diff 友好）；`rev` 按 canonical（无缩进、无空格）计算。
- 时间戳统一带时区：`2026-09-30T14:20:01+08:00`。
- 编码 UTF-8、`ensure_ascii=False`（中文可读）。
- 原子写：临时文件 → `flush + fsync` → `os.replace`。

## 4. rev 与并发控制

```text
canonical JSON → 删除 rev 字段 → SHA-256 → "sha256:…"
```

使用场景：

| 场景 | 用法 |
|---|---|
| 本地并发 | `set_status` 等操作可传 `expected_rev`，不匹配 → `REVISION_CONFLICT` |
| 未来 REST | `ETag: "sha256:…"` + `If-Match`，不匹配 → `409 CONFLICT` |
| 未来同步 | 比较两端 rev 判断“谁改了” |
| 缓存 | 索引缓存键 |

每次成功修改：`version += 1`，`updated_at = now`，重算 `rev`。

## 5. 事务（Transaction）

一次命令可能同时影响多个对象，例如 `pjt task done TSK-X`：

```text
Task.status → done
Task.completed_at → now
Event task.status_changed
```

流程：

```text
1  获取写锁（.pjt/local/locks/write.lock）
2  读取对象、校验 expected_rev
3  构造新对象（version+1 / updated_at / rev）与事件清单
4  全部写入 staging：.pjt/transactions/<TXN-ULID>/objects/... events/...
5  fsync 后逐个 os.replace 到最终路径（objects 先、events 后）
6  更新派生缓存（state.json、refs/labels.json）
7  删除 staging，释放写锁
```

- staging 目录残留 = 上次事务中途失败；`pjt doctor` 报告，可直接删除。
- 不存在“半写对象”：每个文件本身是原子替换；极端断电下可能出现“对象已更新、事件未落盘”，doctor 通过 rev/事件比对发现。
- **SQLite 索引失败不回滚 canonical 数据**；索引是缓存，`pjt index rebuild`（V1）即可恢复。

### 写锁

- 实现：`O_CREAT|O_EXCL` 创建锁文件，写入 `pid + 时间`，默认等待 10s。
- 锁文件 mtime 超过 60s 视为陈旧锁，自动清除（进程崩溃恢复）。
- 锁粒度：整个项目一个写锁。写操作本身毫秒级，V0 不需要更细粒度。

## 6. state 与 refs（派生数据）

`state/state.json`：

```json
{
  "schema_version": "1.0",
  "last_transaction_id": "TXN-01K8HB38ZF",
  "object_count": 83,
  "event_count": 421,
  "updated_at": "2026-09-30T14:20:01+08:00"
}
```

`refs/labels.json`：项目内出现过的 label 去重集合。

两者都可删除重建（doctor 可校验/修复）。它们**不是**数据源，任何逻辑不得以它们为准。

## 7. 数据完整性

`pjt doctor` 检查项：

```text
project.json 可解析、schema 版本受支持
每个对象：JSON 可解析、rev 匹配、id/type/project_id/集合目录一致
引用完整：milestone_id / goal_ids / owner_ids / parent_task_id / dependencies
          task_ids / supersedes_id 指向存在的对象
依赖无环
member.handle 唯一
事件：可解析、entity 存在（project.initialized 除外）
staging 残留、state/labels 与对象不一致（warning）
```

输出三档：`OK` / `WARNING`（可继续） / `ERROR`（退出码 9）。

## 8. Schema 版本与迁移

- 所有对象 `schema_version = "1.0"`。
- Major 变化不兼容；Minor 向后兼容地加字段。
- 工具遇到 `2.x` 而只支持 `1.x`：**拒绝写入**，尽量只读，不得偷偷修改。
- `pjt migrate` 逐级执行 `1.0 → 1.1 → …`；执行前自动备份到 `.pjt/local/backups/`。

## 9. 本地状态与路径

`.pjt/local/local.toml`：

```toml
[local]
device_id = "DEV-F12A81"
actor = "MBR-01K8H61N2B"

[links.firmware]
path = "D:/workspace/firmware"
```

- 机器特定绝对路径只能出现在这里；link 对象里只存相对路径/URL/project ID。
- 该文件被 `.gitignore` 排除，绝不提交。

## 10. 安全原则

`.pjt` 默认禁止保存：

```text
密码  API Token  SMTP 密钥  OAuth refresh token  Private Key
```

Secrets 必须进 OS Keychain（V2）或 `.pjt/local/`（已 gitignore）。
