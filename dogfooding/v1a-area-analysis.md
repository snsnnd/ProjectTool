# V1-A Area 分析：Milestone 与 Area 是否真的该分开

日期：2026-09-30 · 工具：`project-tool 0.2.0`（`SCHEMA_VERSION 1.1`）
数据：真实 EFW Studio `.pjt`（`framework@tmp/new`，`new/efw`，1 goal / 4 milestone / 15 task /
3 decision / 3 update / 1 member）的**临时副本**；真实项目只跑只读命令 + `pjt migrate`。
可复现脚本：`dogfooding/scripts/v1a_dogfood.py`，输出：`dogfooding/v1a-evidence/`。

---

## 1. 起点：真实数据里的 4 个 Milestone

EFW 的 milestone 是这样建的（`dogfooding/report.md` §C）：

| # | Milestone | 实际承担的工作 |
|---|---|---|
| M1 | 页面内模型编辑 | UI（store / 3 个页面编辑 / 引用检查） |
| M2 | 真机调试链路 | Debug（serial/tcp 回环、真机 hash 校验、端口模板） |
| M3 | 桌面壳与打包 | Distribution（desktop 主进程、package.json、PyInstaller、smoke test） |
| M4 | 工程卫生 | 混合（ProcTransport 泄漏=Core/Runtime、msgq 聚合=Runtime、草稿持久化=UI/Core） |

**没有一个是按时间交付的**。`dogfooding/evidence/final-snapshot.txt` 里 active milestone
的 progress 是 `0%`，4 个 milestone 全部 `0%`——不是没做，是因为它们不是阶段。

M4「工程卫生」尤其说明问题：它既不是 UI 也不是 Debug，是一个**跨领域的杂物袋**。
这类 milestone 会在真实项目里持续膨胀，最终既不能回答「这阶段做完没有」，
也不能回答「这块代码归谁管」。

## 2. 真实测试：加上 Area 之后

在临时副本上建 5 个顶层 Area + 2 个二级 Area，把 14 个真实任务按主 Area 映射：

```text
Core         3 task(s)   studio_core service/cli/server、model store
UI           4 task(s)   Electron renderer（pages / store / RPC）
Debug        2 task(s)   transport、真机调试、observe_port 模板
Runtime      1 task(s)   C runtime：header 聚合、msgq、ProcTransport
Distribution 4 task(s)   desktop 壳、package.json、PyInstaller、installer
  UI ├── Editor        （页面内模型编辑面）
  UI └── Debug UI      （debug 页 + 端口模板）
```

`pjt graph project` 的实际输出（`dogfooding/v1a-evidence/03-*`）：

```text
EFW Studio (PRJ-01M3R9F6DT0JFPXH0M417888MC)
├── Goal: 完成可实际使用的 EFW Studio (active)
│   ├── Milestone: 页面内模型编辑 0%
│   ├── Milestone: 真机调试链路 0%
│   ├── Milestone: 桌面壳与打包 0%
│   └── Milestone: 工程卫生 0%
└── Areas (stable partitions)
    ├── ARA-…  Core  3 task(s)
    ├── ARA-…  Debug 2 task(s)
    ├── ARA-…  Distribution 4 task(s)
    ├── ARA-…  Runtime 1 task(s)
    └── ARA-…  UI 4 task(s)
        ├── ARA-…  Debug UI 0 task(s)
        └── ARA-…  Editor 0 task(s)
```

### 回答 §59 的三个问题

#### Q1. EFW 当前 4 个 Milestone 中哪些更像 Area？

| Milestone | 像 Area 还是像 Milestone | 理由 |
|---|---|---|
| 页面内模型编辑 | **Area** | 是能力域（store + 3 个页面），没有时间承诺 |
| 真机调试链路 | **Area** | 是能力域（Debug），但也隐含「先串口后 TCP」的阶段顺序 |
| 桌面壳与打包 | **Area** | 是能力域（Distribution） |
| 工程卫生 | **两者都不是** | 跨领域杂物袋，应拆成 `Core` / `Runtime` / `UI` |

**4 个里 3–4 个更像 Area，0 个是真正的交付阶段。**

#### Q2. 重构为 Area + Milestone 之后结构是否更清晰？

清晰，且是**可验证的**清晰：

1. **提问方式变了。** 迁移前问「这个任务属于哪个阶段」，但 4 个答案都是「不是阶段」；
   迁移后问「这段代码归哪块」，14 个任务全部有唯一且合理的答案。
2. **M4 消失了。** `工程卫生` 不是一个可以交付的东西；它的 3 个任务分别落到
   `Core`（ProcTransport 泄漏）、`Runtime`（msgq 聚合）、`UI`（草稿持久化）。
   一个装不下任何任务的容器，说明它本来就不是这个维度的东西。
3. **粒度对上了真实目录。** Area 名和真实代码目录一一对应
   （`studio_core`→Core、`ui`→UI、`runtime`→Runtime、`package.json`/`dist`→Distribution），
   而 milestone 名和目录没有对应关系。**「这个任务要改哪些文件」现在可以直接从 Area 推出来**——
   这对下一步接 Git Adapter 是关键：Artifact 的 `file` locator 可以直接从 Area 推导候选路径。
4. **真正的 milestone 该长什么样，现在清楚了。** 应该是「0.2 发布」「真机 Debug MVP 可用」
   这种**有截止条件和完成定义**的东西。EFW 现在一个都没有，这本身是有用的发现：
   不是 Area 不好用，是原来被 milestone 占着的位置从来没被正确使用过。
5. **视图不再过载。** Area 刻意不进 `pjt status`（`status` 的 keys 里没有 `areas`），
   只在 `task show` / `task list --area` / `graph project` 出现。
   迁移前后 `pjt status` 输出逐字不变（除了原有内容），没有新增噪音。

**M4「工程卫生」的处置建议**：不迁成 Area。**保持 milestone 但改名并给出完成定义**
（例如「工程卫生：ProcTransport 无泄漏 / msgq 全部收录 / 草稿崩溃可恢复」），
等它真的变成一批可交付的清理工作时再作为 milestone 关闭。这正是 milestone 的正确用法。

#### Q3. Area 是否真的比 Label 有价值？

**有，但价值不在「多了一个分类字段」，而在三点具体差别：**

| | Label | Area |
|---|---|---|
| 类型 | 自由字符串，`refs/labels.json` 聚合 | 一等对象（`ARA-`），有 `rev`/`version`/`lifecycle`/层级 |
| 引用完整性 | 拼错就静默失效 | doctor 校验 `task.area_id` 悬空引用 |
| 可回答的问题 | 「这任务有什么属性」（`bug` `test` `high-risk`） | 「这块工作动的是哪块东西」 |

真实使用里的具体收益：

- **过滤组合**：`task list --area Debug --status inbox` 是一条命令；
  用 Label 只能 `--label debug`，而 `debug` 这个 label 在 EFW 里同时被
  「真机调试」和「draft 持久化」相关任务使用，语义漂移了。
- **不会漏拼**：label 是每个 task 手打的字符串，14 个任务里已经出现
  `debug, test` 这种随手组合。Area 名来自一次性的 5 个顶层定义，一致性有保证。
- **给下一步 Git Adapter 铺路**：Area → 候选路径集合 → Artifact `file` locator，
  这条链路让「这个任务应该产生什么产物」可以被推导，而不是靠人回忆。

**但也必须说清楚 Area 的代价**：单值 `area_id`。T5「删除引用检查」同时改
`ui/store.tsx` 和删除逻辑（Core），T12「ProcTransport 泄漏」同时属于 Core 和 Debug。
V1-A 强制取主 Area，跨域信息只能进 description 或 label。这是个真实的信息损失，
我保留它是因为多 Area 会立刻引入「Task ↔ Area 多对多引用谁来维护、冲突怎么解」的问题，
而 EFW 15 个任务里需要多 Area 的只有 2 个。**如果实际使用中「主 Area 说不清」的比例上升，
就该升到多 Area，而不是硬塞。**

## 4. 结论：保留 Area

Area 经过了真实 EFW 数据验证，不是理论设计：

- 14 个真实任务 **100% 有唯一合理的主 Area 映射**（0 个 SKIP）；
- `工程卫生` 这个 milestone 被证明装不下它自己的任务；
- 相比 Label，多出了 doctor 引用校验 + 与真实目录结构的一致性；
- 视图零过载（`pjt status` 输出不变）；
- 层级（`UI → Editor` / `UI → Debug UI`）在真实数据上有意义，
  环检测与 goal/task parent 复用同一套实现（`tests/test_area.py::test_area_parent_cycle_rejected`）。

**不做的部分**（明确的取舍，不是遗漏）：

- 不强制 Area 名唯一（同 goal/milestone/task 的 title）；按名引用不唯一时报
  `INVALID_ARGUMENT` 要求用 ID 消歧，不猜。
- Area 不派生 progress（`area.get` 也不返回 progress）——加了它 Area 就变成第二个 Milestone。
- 不参与 `pjt status`。
- 真实 EFW `.pjt` **没有被自动改写**：4 个 milestone 原样保留，Area 只存在于临时副本。
  是否迁移真实数据是维护者的决定，不是工具的自动行为。
  建议映射见上表，若决定迁移，用
  `pjt task move-area <task> <area>` 逐条走（每条都是事务 + 事件，可回溯）。
