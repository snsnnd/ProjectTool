# EFW × ProjectTool V1-A — Area / Artifact Dogfooding 报告

日期：2026-09-30 · 工具：`project-tool 0.2.0`（`SCHEMA_VERSION 1.1`）
范围：V0.1.1 UX / Contract Cleanup + V1-A Domain Completion
可复现：`python3 dogfooding/scripts/v1a_dogfood.py` → `dogfooding/v1a-evidence/v1a-dogfooding.txt`
Area 结论单独成文：`dogfooding/v1a-area-analysis.md`

---

## A. 测试环境

| 项 | 值 |
|---|---|
| framework branch | `tmp/new` |
| framework HEAD | `2cb4a7433d7ff77c769fa083abd8c9e151929633` |
| EFW path | `/mnt/d/framework/new/efw`（Git root = `/mnt/d/framework`） |
| ProjectTool HEAD | `52e1a9f` + 本轮未提交的文档/回归 |
| 真实 `.pjt` 规模 | 27 对象 / 37 事件 / 15 真实任务 / 4 milestone / 3 decision |
| 临时副本 | `/tmp/pjt-v1a-efw-*`（源码 tar + `cp -a .pjt`） |

## B. 污染检查

### B.1 真实 EFW

本轮对真实 `new/efw` 只做了两件事：

```text
pjt migrate     ->  新增空目录 .pjt/objects/areas/；project.json schema_version 1.0 -> 1.1
                    （走标准事务，产生 project.migrated 事件）
pjt doctor/status/area list/artifact list/area tree/log   ->  只读
```

**没有**任何 milestone、task、decision 被自动改写；Area 与 Artifact 只存在于临时副本。
证据见 `dogfooding/v1a-evidence/` 的 section 1。

### B.2 临时副本的整树哈希

脚本在写 Area / Artifact / verify / remove 全流程**前后**对整棵工程源码树
（排除 `.pjt`、`.venv`、`node_modules`、`dist`、`test-results`）取 sha256 逐文件比对：

```text
TREE HASH: IDENTICAL  => ProjectTool 只写 .pjt/**，一个工程文件都没碰
files compared: 161
```

`framework` 仓库的 `git status --porcelain`（138 行）与本轮开始时的 baseline
**逐字节相同**，`git diff --stat -- new/efw` 也完全相同，
分支 `tmp/new` / HEAD `2cb4a74` 未变（无任何 git 写操作）。
证据：`dogfooding/v1a-evidence/00-efw-pollution-check.txt`。

另有针对单文件的直接证据（section 3.10）：

```text
before: studio_core/debug.py  sha256=75509c36396a69ca  size=15806
artifact.remove -> lifecycle=deleted
after : studio_core/debug.py  sha256=75509c36396a69ca  size=15806
file untouched: True
```

**EFW SOURCE POLLUTION: PASS**

## C. 功能验证

| 项 | 结果 | 说明 |
|---|---|---|
| `pjt --version` | PASS | V0.1 实际 exit 2（被「缺少子命令」挡住），本轮修好；无子命令时打印 help 且 exit 0 |
| `pjt task ready` | PASS | inbox→ready / blocked→ready / review→ready / done→ready / cancelled→ready 全部允许（服务层无转换矩阵，见设计记录 §1.1）；重复调用幂等无事件 |
| `pjt task ready` + computed blocked | PASS | ready + 未完成依赖 ⇒ `computed_blocked=true` 但 `status` 仍是 `ready`；依赖完成后 computed blocked 自行消失 |
| `expected_rev` 统一 contract | PASS | 七领域（project/task/goal/milestone/member/decision/link）+ area/artifact 全覆盖；过期 → `REVISION_CONFLICT`；省略 → 用内部 base_rev；**no-op 也不吞过期 rev** |
| Area CRUD / 层级 | PASS | 5 顶层 + 2 二级；self parent / 2 级子 area 当父级均被 `_validate_chain` 拦截 |
| Area ↔ Task 归属 | PASS | 14 个真实任务 100% 有唯一合理主 Area 映射（0 SKIP）；`task list --area` / `task show` / `graph project` 正确 |
| `pjt status` 不列 Area | PASS | status keys 与迁移前逐字一致 |
| 旧 V0.1 项目兼容 | PASS | 真实 EFW 打开正常，`objects.area 0 area object(s)` / `objects.artifact 0 artifact object(s)`，doctor `0 error / 0 warning` |
| `pjt migrate` 幂等 | PASS | 第一次 `1.0→1.1` + 建 `areas/`；第二次 `already up to date` |
| 迁移不重写旧对象 | PASS | 真实 EFW 的 15 个 task 全部 `area_id` 仍为 absent/`<null>`，4 个 milestone `version` 仍为 1、title 未变（`v1a-evidence/00-real-pjt-change-audit.txt`）；单测 `test_legacy_task_without_area_id_reads_as_null` |
| Artifact file locator | PASS | 只对确认存在的路径建引用；`\` 规范化成 `/` |
| Artifact 路径穿越/绝对路径 | PASS | 15/15 拒绝：`../../secret.txt` `../outside/secret.txt` `/etc/passwd` `C:\…` `c:/…` `\\server\…` `~/…` `.pjt/…` `.PJT/…` 空串 纯空白 `example.com` `ftp://…` `git_commit=zzzz` `git_branch=feature/../main` 全部 `INVALID_ARGUMENT` |
| Artifact url 校验 | PASS | `https://…` `http://host:port/…` 接受；`not-a-url` `ftp://…` `https://` `://x` 拒绝；**不发网络请求** |
| Artifact git locator | PASS | `abc123` / `feature/foo` 接受；`zzzz` `feature/../main` `/leading` `trailing/` 拒绝；verify 报「git adapter not enabled (V1-B)」 |
| Artifact ↔ Task | PASS | `T6 serial/tcp 回环 ↔ studio_core/debug.py`；`T8 desktop ↔ package.json`；`T1 store.updateModel ↔ ui/store.tsx`；`T7 真机 hash ↔ docs/04-debug-and-api.md` |
| Artifact ↔ Decision | PASS | `service.py` / `cli.py` / `server.py` 三份引用挂到「CLI 与 GUI 共享同一 Service」同一条 Decision |
| Artifact ↔ Milestone | PASS | `debug.py` 挂到 active milestone |
| `task.related_artifacts` | PASS | 反向派生读（file scan，Task 不存 artifact_ids） |
| `task related_updates` CLI | PASS | 补齐 V0.1 的 API/CLI 缺口 |
| verify：存在 | PASS | `status=ok exists=true` |
| verify：缺失 | PASS | `status=missing exists=false`；doctor `artifacts.locators` 报 **warning** 而非 `PROJECT_CORRUPTED`（实测 2 个：跨仓库的 `dogfooding/report.md` + 未写的 `scripts/never_created.py`） |
| verify 不产生事件 | PASS | 78 events → 78 events（含 `artifact.verify` ×2 + `task.related_artifacts`） |
| Artifact 事件契约 | PASS | `artifact.created/updated/attached/detached/removed`；`artifact.verified` **不存在**（纯查询） |
| Artifact rev | PASS | update/attach/detach/remove 过期 rev 全部 `REVISION_CONFLICT`；正确 rev 成功 |
| Doctor 损坏/警告分层 | PASS | 引用悬空 = error；locator 越界 = error；file 不存在 = warning |
| 事务路径 | PASS | Area create / Artifact attach 崩溃注入 → prepared → roll-forward → 幂等（`tests/test_transaction_recovery.py`） |
| 存储布局 | PASS | `one object per file`；无 `areas.json`/`artifacts.json`；`transactions/` 残留 0；无 write.lock 残留；events 链全部一致 |
| Path boundary（真实场景） | PASS | `dogfooding/report.md` 在 **ProjectTool 仓库**里，不在 EFW root：`as file artifact` 可以创建但 verify=`missing`（warning）；`../../ProjectTool/...` 被拒；正确做法是 `url` 外部引用 |

## D. 真实数据发现

### D.1 `pjt status` 的 active milestone 依然是 `0%`

4 个 milestone 全部 `0%`，一个 `done` 里程碑都没有。**不是没做，是它们本来就不是阶段。**
这是 Area 存在的直接证据（详见 `v1a-area-analysis.md`）。

### D.2 `工程卫生` 装不下它自己的 3 个任务

```text
ProcTransport.close 资源泄漏  -> Core
efw.h 聚合 msgq.h             -> Runtime
源码草稿持久化                 -> UI
```

一个装不下任何任务的容器，说明它不是这个维度的东西。

### D.3 `ui/store.tsx` 而不是 `ui/store.ts`

指令里写的是 `ui/store.ts`；真实文件是 `ui/store.tsx`（`ls ui/` 确认）。
Artifact 引用必须先确认真实路径存在，否则会造出一条永久 `missing` 的引用。

### D.4 `scripts/` 存在但是空目录

`desktop/` 不存在（V0.1 报告已记录）。`artifact add file scripts/never_created.py`
能创建成功，verify 报 `missing`，doctor 报 warning——**这正是想要的语义**：
「计划中的产物还没写」和「数据损坏」是两件事。

## E. 真实使用评价

- **最有用的一条命令**：`pjt task list --area Debug`。
  迁移前想知道「调试这块还差什么」只能读 milestone 标题猜；现在是按模块直接筛。
- **最有价值的一条能力**：`artifact attach <art> --decision <dec>`。
  「CLI 与 GUI 共用同一 Service」这条 Decision 之前只在文字里列了三个路径，
  现在三条 `file` 引用都是可 `verify` 的一等关联。
- **仍然啰嗦**：录入 15 个真实任务时 `--area` 是第 5 个选项
  （`--owner --milestone --area --priority --weight`）。CLI 没有批量从目录推断 Area 的能力，
  这也是 V1-B「先定 Area↔目录」的原因。
- **最不自然**：`pjt artifact show ART-01M3RQH1` 因同毫秒创建的 Artifact 共享时间戳前缀而
  报 ambiguous。必须多打几位。`ObjectStore.resolve` 的既有行为（同 task/milestone），
  但 Artifact 一次创建多个时最容易撞上。
- **Area 名称不唯一**：刻意不强制（与 title 一致）。真实使用时「UI 只有一个」是自然约束，
  但脚本批量建 Area 时可能踩到。

## F. 未解决问题

1. **`pjt status` 的 computed blocked 不带 area/milestone**（纯渲染，V0.1 就有的 P2-3）。
2. **Artifact 短 ID 歧义**：`ART-<10 char timestamp>` 在批量创建时必然歧义。
3. **单 Area 的代价**：EFW 15 个任务里 2 个（T5 引用检查、T12 ProcTransport 泄漏）跨域，
   只能取主 Area。真实使用中「主 Area 说不清」的比例上升就该升多 Area。
4. **Area ↔ 目录无绑定**：`Area=UI ↔ ui/` 靠人维护。这是 Git Adapter 的前置决策
   （`docs/09-handover.md` §8）。
5. **Artifact `file` 缺失只能单条 remove**，没有批量清理入口。
6. **中文长标题在终端表格/树中折行**（纯显示，V0.1 就有）。

## G. 结论

- **V1-A 是否解决了 dogfooding 提出的 P2/P3**：
  `task ready` ✓、统一 `expected_rev` ✓、Artifact ✓、Area 维度 ✓、`task related_updates` ✓。
- **现有 V0.1 数据是否向后兼容**：兼容。真实 EFW `.pjt` 从 1.0 migrate 到 1.1 后
  doctor 仍 `0 error / 0 warning`，全部旧对象可读可写，**没有要求删库重建**。
- **EFW 是否零源码污染**：是。整树 sha256 前后一致（161 个文件）。
- **是否可以进入 V1-B Git Adapter**：可以，但**先定 Area↔目录**（F.4）。
- **进 Git Adapter 前是否还有模型阻断项**：有一个待决问题（Area↔目录绑定），
  它是决策不是阻断；其余（多 Area、名称唯一）都可以在有真实压力时再处理。
