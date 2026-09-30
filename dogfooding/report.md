# EFW × ProjectTool V0.1 — Dogfooding / Integration Validation 报告

日期：2026-09-30 · 范围：ProjectTool V0.1（`0fcc628`）× 真实 EFW Studio（`framework@tmp/new`）

---

## A. 测试环境

| 项 | 值 |
|---|---|
| framework branch | `tmp/new` |
| framework HEAD | `2cb4a7433d7ff77c769fa083abd8c9e151929633` |
| EFW path | `/mnt/d/framework/new/efw`（Git root = `/mnt/d/framework`） |
| ProjectTool HEAD | `0fcc628`（本轮未修改 ProjectTool 代码） |
| OS | WSL2 Linux 6.6.87.2-microsoft-standard-WSL2 x86_64 |
| Python | 3.12.13（uv 管理） |

初始工作树状态：framework 全仓 136 项未提交变化；其中 `new/efw` 有 4 个**用户已有**的文档修改
（`AGENTS.md`、`docs/03-runtime.md`、`docs/04-debug-and-api.md`、`docs/05-ui-style.md`），
本轮全程未触碰。

## B. 污染检查

```text
baseline: baseline-git-status.txt (136 lines) / baseline-git-diff-new-efw.txt (397 lines)
final:    final-git-status.txt          / final-git-diff-new-efw.txt

status diff（唯一新增 2 行）:
  +  M new/efw/.gitignore
  + ?? new/efw/.pjt/

new/efw diff diff（唯一新增 hunk）:
  + .pjt/local/
  + .pjt/transactions/
  （追加式，含一行 "# Project Tool local state"；无重排、无格式化、无删除）

真实 .pjt 破坏性测试前后 sha256（全量文件树）:
  before 54d3db09f7788c3a5ddc646e9e8b7d14b3c9ce97088dd647f5987894a8946c56
  after  54d3db09f7788c3a5ddc646e9e8b7d14b3c9ce97088dd647f5987894a8946c56  (一致)
```

**EFW SOURCE POLLUTION: PASS**

## C. 创建的 ProjectTool 数据（保留在 new/efw/.pjt，252K / 68 文件 / 27 对象 / 36 事件）

- Project：`PRJ-01M3R9F6DT0JFPXH0M417888MC`（EFW Studio）
- Member：`jichao`（计超，maintainer，本地默认 actor）
- Goal：`GOL-01M3R9J9…` 完成可实际使用的 EFW Studio（6 条 success criteria）
- Milestones（4）：页面内模型编辑（active）、真机调试链路、桌面壳与打包、工程卫生
- Tasks（15，全部来源于只读审计确认的真实缺口）：
  - M1：T1 store.updateModel 保存通路 · T2 通信页行内编辑 · T3 数据流页句子编辑 ·
    T4 状态机页编辑 · T5 删除引用检查
  - M2：T6 serial/tcp 回环集成测试 · T7 真机 hash 不一致与 observe_port 模板验证
  - M3：T8 desktop 主进程与 preload 桥 · T9 package.json/资源路径修复 ·
    T10 PyInstaller 打包脚本 · T11 发布 smoke test
  - M4：T12 ProcTransport 资源泄漏 · T13 msgq 聚合 · T14 草稿持久化
  - 元任务：T15 ProjectTool dogfooding 记录（ready→doing→review→done 生命周期验证）
  - 任务来源证据：`desktop/` 不存在、`scripts/` 为空、`tests/bridge.test.mjs` 不存在、
    `examples/`/`backend-bin/` 缺失、`efw.h`/`efw_all.c` 未收录 msgq、
    `ProcTransport.close` 未关 stdout、模型页只读。
- Dependencies（5 边）：T2→T1、T3→T1、T11→T8、T11→T10、T7→T6
- Updates（3）：serial/tcp 无集成测试（含 blocker/next）；模型编辑缺统一保存通路；
  desktop/scripts 为空导致打包链路未闭合
- Decisions（3）：ProjectTool 只嵌入 new/efw（accepted）；CLI 与 GUI 共享同一 Service（accepted）；
  Electron 以 stdio 启动 server（draft）

## D. 功能验证

| 项 | 结果 | 说明 |
|---|---|---|
| init | PASS | `--name "EFW Studio"`；仅 `.gitignore` 追加 + `.pjt/` 新增 |
| member | PASS | add / use / workload（6 任务归属正确） |
| goal | PASS | 6 条 criteria 正常保存 |
| milestone | PASS | 4 个阶段；progress 动态推导（M1 0/13 weight） |
| task | PASS | 15 任务、属性过滤（status/owner/label/milestone） |
| dependency | PASS | 5 边；`graph tasks` 正确表达；环检测此前已单测覆盖 |
| computed blocked | PASS | T2/T3/T7/T11 blocked，`status` 保持 `inbox`（未被改写） |
| update | PASS | 3 条；`update list --task` 关联正确 |
| decision | PASS | 3 条；context/decision/rationale/alternatives/consequences 完整 |
| log | PASS | `--task` / `--member` / `--type` / `--since` 全部可用且排序正确 |
| status | PASS | 当前 milestone、状态分布、computed blocked、成员负载、最近活动可读 |
| graph | PASS | 项目树 / 任务树 / 依赖行均正确 |
| doctor（真实） | PASS | 0 error / 0 warning / repairable 0 |
| 短 ID | PASS | 18 字符前缀唯一解析成功；歧义前缀 `TSK-01M3R9M` exit 3 且给出候选 |
| revision（副本） | PASS | `task.set_status` 携带过期 `expected_rev` → REVISION_CONFLICT |
| recovery（副本） | PASS | 崩溃注入 → prepared 事务 → roll-forward；重复 recover 幂等 |
| event 不可变（副本） | PASS | 旧事件哈希在后续操作后完全一致 |
| rev 篡改 / 断链 / 层级环 / 陈旧锁 / 未提交 staging（副本） | PASS | doctor 全部准确报告，repair 处理正确 |
| monorepo（project root ≠ git root） | PASS | 子目录向上解析；`new/` 与 Git root 均 exit 4；代码无 `.git` 假设 |
| `.pjt` Git 友好性 | PASS | project/objects/events 为可读 JSON；`git check-ignore` 确认 local/transactions 被忽略 |

## E. 真实使用评价

- **比 README/TODO 更有价值吗**：对“状态 + 依赖 + 为什么”明显更有价值（computed blocked、
  decision、update 的 blocker/next 是普通 TODO 无法表达且不会再花时间维护的部分）；
  但**代码/文档/提交等产物关联缺失**（无 Artifact/Git Adapter），目前仍要在 Task 文本里
  写路径描述，这是最大的价值缺口。
- **是否太繁琐**：录入 15 个任务需要重复 `--milestone/--owner/--weight`，一条命令可完成但略啰嗦；
  单条 Task 的字段负担可接受（title 必填，其余可选）。
- **最有价值的对象**：Task + dependency/computed blocked ＞ Update（blocker/next）＞ Decision ＞ Milestone。
- **最不自然的**：Task 的 `ready` 状态没有独立 CLI 命令（只能创建时 `--status ready` 或走服务）；
  Milestone 只能表达“阶段”，模块维度只能靠 label。
- **最难用的 CLI**：没有 `task ready` / `task related_updates`；其余命令结构一致、可预测。
- **EFW 是否适合持续 dogfooding**：适合。Project root ≠ Git root 的嵌套结构工作正常，
  真实缺口清晰可转成任务，`doctor` 给维护者安全感。

## F. 问题清单

### P0（数据损坏 / 污染）
无。

### P1（真实工作流无法完成）
无。本轮所有目标工作流均完成，且破坏性场景全部按设计处理。

### P2（能完成但体验明显差）
1. **CLI 缺少 inbox→ready 状态命令**（CLI UX）。服务端 `task.set_status` 支持 ready，
   但 CLI 未暴露；真实工作中“细化后标记可开始”是常用动作。
2. **`expected_rev` 覆盖面**（CLI UX / consistency）：仅 `task.set_status`、`project.update` 暴露；
   编辑类操作（`task.update`）无法显式携带。当前有事务级 base_rev 兜底，不构成数据风险。
3. **状态/日志中的 computed blocked 未附带 milestone**（CLI UX，轻微）：
   任务多时需要自己看 ID。

### P3（未来增强）
4. **无 Artifact**：无法把 `docs/AGENTS.md`、`ui/pages/Communication.tsx`、commit hash、
   调试录制文件与 Task 关联（真实摩擦，优先级最高）。
5. **无 Git Adapter**：commit trailer 关联、`git status` 展示缺失（按计划 V1）。
6. **无 `task related_updates` CLI**（API 已存在）。
7. **中文长标题在终端表格/树中折行**（纯显示问题）。
8. **列表/搜索**：15 任务规模无压力；规模上 10³ 需 Search/Index。

## G. V1 建议（基于本轮真实使用）

原路线：Git Adapter → Artifact → Search → SQLite → Web。
**建议调整为：Artifact（含 file/url/git_commit locator）→ Git Adapter → Search + SQLite → FastAPI/Web。**
理由：真实摩擦最大的是“任务 ↔ 产物”关联（文档、源码路径、提交、录制），Artifact 是最直接价值；
Git Adapter 的自然落点也是 Artifact 的 `git:commit` locator；Search/Index 在任务量增大后才有必要；
个人主维护者场景下 CLI 已足够，Web/FastAPI 优先级最低。

## H. 结论

- **V0.1 是否适合真实项目持续使用**：是。真实 EFW 已完成一轮完整录入与日常路径验证，
  零污染、零数据完整性问题；`computed blocked 不改写状态`、`doctor`、recover、event 不可变
  等核心约束在真实数据上成立。
- **是否可以进入 V1**：可以。
- **进入 V1 前是否有阻断问题**：没有阻断问题；建议顺手补两个 P2 CLI 小项
  （`task ready` 命令、`task.update` 支持 `expected_rev`），不构成本轮否决项。
- 真实 `.pjt` 已保留为持续 dogfooding 数据（§41），未删除。

附件：`dogfooding/evidence/`（baseline/final status、diff、seed 输出、正常路径验证、
破坏性检查、monorepo 验证、最终快照）、`dogfooding/scripts/`（可复现脚本）。
