# AGENTS.md — Project Tool 交接

> 给下一位接手的 agent / 开发者。先读本文件，再按需读 `docs/09-handover.md`（完整交接）、
> `docs/09-v1a-design.md`（本轮 Area/Artifact/revision 设计记录）、
> `docs/02`（架构）、`docs/03`（数据模型）、`docs/04`（存储/恢复）。
> 仓库：`https://github.com/snsnnd/ProjectTool`

## 0. 一句话

Local-first 的工程项目状态系统：`.pjt/` 与 `.git/` 并列，
`objects/`（现在是什么）+ `events/`（为什么变）是 canonical 数据；
CLI / 未来 Web / SDK 都只经过同一个 Application Service。

## 1. 当前状态

- 版本 `0.3.1`，`SCHEMA_VERSION = "1.1"`。**`version.py` 是唯一版本来源**
  （`pyproject.toml` 用 `dynamic = ["version"]` 指向它）。
  改版本号后本仓库的可编辑安装元数据不会自动刷新，需要
  `uv pip install -e . --reinstall-package project-tool`（CI 的全新 `uv sync` 不受影响）。
- 提交线：`6a19628` V0 → `0fcc628` V0.1 硬化 → `a7ac64e` EFW dogfooding 报告
  → `779a886` 统一 expected_rev → `d73a492` Area → `52e1a9f` Artifact
  → `bdad62d` EFW 二次 dogfooding → V1-A.1 Hardening → V1-B Git 感知层。
- 质量门槛：`uv run ruff check .`、`uv run mypy project_tool`、`uv run pytest`（271 passed）；
  CI 覆盖 Ubuntu + Windows。
- 对象：Project / Goal / Milestone / **Area** / Task / Member / Update / Decision /
  **Artifact** / Link；Service 120 个 method，**CLI 全部触达**（V1-B.2 补齐最后 12 个 +
  `link.map_local_path`/`unmap_local_path` + V1-C 的 `area.set_owner`、`area.activity` 与 6 个 `interface.*`）。V1-C 进行中：派生缓存治理 + Area owner + 接口契约 + Area 活跃度推导。
- 真实使用：EFW Studio（`framework@tmp/new` 的 `new/efw`）已完成两轮 dogfooding，零源码污染；
  数据保留在 `new/efw/.pjt`。报告：`dogfooding/report.md`（V0.1）、
  `dogfooding/v1a-area-analysis.md` + `dogfooding/v1a-evidence/`（V1-A）。
- **无服务器**（已定案）：协作走 Git，不做 Remote / Sync / Accounts / Web UI。
- 已实现 Git 感知（只读）：`git status` / `git log` / `git.link_commit` /
  `Area.path_patterns`。
- 未实现：Search / SQLite 索引 / Web / Artifact 内容快照 / 多人 merge 辅助。

## 2. 最重要十三条（违反即事故）

1. `.pjt` 是唯一数据源；`project.json + objects/ + events/` 不可被缓存替代。
2. Event append-only；禁止任何 update/delete 事件的 API 或脚本。
3. 事务必须走 `staged/ + manifest + COMMIT` 协议；`transactions/` 里的目录只许 `pjt doctor --repair` 处理。
4. WriteLock 活 PID 永不偷锁；释放只删自己的 `lock_id`。
5. `computed blocked` / milestone progress 只推导，绝不写回对象。
6. CLI 不 import `storage`/`filesystem`；Core 不依赖 Web。
7. `.pjt/local/`、`.pjt/transactions/` 不进 Git；绝对路径只进 `local.toml`。
8. 不接管 Git、不做组织账号（KC 职责）；改动必须带 revision 校验。
9. **`expected_rev` 只有一种语义**：实现点只有 `ServiceContext.require_expected_rev`。
   省略 = 用当前 rev 作 base_rev；提供 = 必须相等。禁止任何领域自己写比较。
10. **Milestone ≠ Area**：Milestone 是阶段/交付（有 status/due_at/progress）；
    Area 是稳定模块/工作领域（只有 name/description/parent_area_id，**读视图也没有 progress**）。
    **Area ≠ Label**：Label 是自由标签，Area 是一等对象（有 rev、有层级、doctor 校验）。
    **Artifact 只是引用**：`kind=file` 的 locator 必须是 project-relative 路径；
    任何写路径都不得 copy/move/delete/rename 被引用的工程文件。
11. **Git 适配器只读**：`integrations/git.py` 的 `run()` 有运行时子命令白名单
    （`rev-parse` / `status` / `log` / `show`），且一律加 `--no-optional-locks`。
    绝不 clone/add/commit/checkout/merge/reset/clean/push/fetch。
    `git status` 只**推导**候选 Area，**绝不回写 `Task.area_id`**。
12. **`link.resolve` 不许说谎**：`resolved` 只能为 true 当它真的读到了对方
    `project.json`；没有服务器就没法解析 remote link，如实报 `verifiable=false`。
13. **Schema 写入门 + 读即校验 rev**：项目 schema 落后时禁止所有写操作
    （`SCHEMA_MIGRATION_REQUIRED`）；`load_model`/`list_models` 强制 `verify_rev`，
    被外部篡改的对象读取即 `PROJECT_CORRUPTED`，不允许靠下一次写入洗白。
    例外只有 `doctor` 与 `resolve_actor`（数据已损坏时它们必须仍能工作）。

14. **派生缓存不进版本控制**：`.pjt/state/state.json` 与 `.pjt/refs/labels.json`
    是每次写入都会变的缓存，被提交就会让**每一次**并发合并都冲突
    （V1-C 探针实测 1/9 vs 8/9）。`pjt init` 写好 ignore 规则、`pjt migrate`
    给老项目幂等补齐、`pjt doctor` 把「被 git 跟踪」判为 **error**。
    工具只报告，`git rm --cached` 由人执行（Git 适配器只读，§11）。

15. **Area 分区靠 owner，公共区靠复数**：每个 Area 显式设置 `owner_ids`
    （不推导）。**1 个 owner = 私有块，多个 = 公共接口区**（如被 UI/数据流/
    状态机共同依赖的 core）——不需要额外的 `shared` 字段。**不要**给
    Milestone/Goal 也加 owner：只有 Area 是分区单元，到处加会让它退化成
    第二个 Milestone（V1-A 的核心不变量）。
16. **不做本地权限门禁**：工具将来上服务器，权限以服务器为准。`.pjt/objects/**`
    是可读 JSON 跟着 Git 走，本地门禁只会制造「已经管住了」的错觉。
    `Member.roles` 是自由字符串，`KNOWN_ROLES` 只是建议词汇表（未知值 = warning，
    不是 error——老项目可能有自由 role，不能因此判 corrupted）。谁改了什么一律
    记进 append-only 事件，供人和服务器去审。
17. **接口契约不是一等对象**：它是工作树里一份**固定模板**的 markdown + 注册成
    `kind=file` 的 Artifact。正文是人写的散文，硬塞进 JSON 只会让人绕过工具；
    diff/blame/历史 Git 已经做得更好。`pjt interface check` 只报告不改写，
    有 error 时退出码 1（可直接当 CI 门禁）。
18. **别人的在途工作看不见，这是架构事实不是 bug**：`git log` 跟着 Git 走所以
    所有人都能看到；`git status` 只有本机能看。`area activity` 因此把两者
    分开输出并标 "THIS machine only"。**不要**把两者混成一张「谁在做什么」
    的表——那会让人以为缺席就是没人在动。

## 3. 常用命令

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy project_tool
uv run pjt --help

# 本地体验（用临时目录，不要动真实项目）
cd /tmp && mkdir -p demo && cd demo
uv run --project /path/to/ProjectTool pjt init --name Demo

# 老项目升级：补齐 objects/areas 等空目录 + 抬 schema_version（幂等）
pjt migrate

# EFW 回归（临时副本，3-4 分钟）
python3 dogfooding/scripts/v1a_dogfood.py
python3 dogfooding/scripts/v1b_dogfood.py     # Git 感知层
```

## 4. 加一个 method（固定流程）

```text
domain 模型/校验 → application/services/<域>.py → registry.py 注册
→ cli/<域>.py（只 execute(method, params)）→ tests → 文档（05/03/08）
→ ruff + mypy + pytest
```

## 5. 禁区

- `new/efw`（真实 dogfooding 项目）与 framework 仓库：**禁止任何 EFW 源码修改，
  禁止任何 git 写操作**；只允许 `new/efw/.pjt/**` 的 ProjectTool 数据。
- 破坏性实验（rev 篡改 / 锁 / 事务恢复 / event 校验 / Area+Artifact 写入）
  只能对 `.pjt` 的临时副本执行（`dogfooding/scripts/destructive_checks.py`、
  `dogfooding/scripts/v1a_dogfood.py` 是范例）。
- 不要删除或手工修改 `.pjt/transactions/`、`.pjt/events/`。

## 6. 验证习惯

- 任何改动：`ruff check .` + `mypy project_tool` + `pytest` 全绿再提交。
- 看 CI（Ubuntu + Windows）：`./dogfooding/scripts/ci_status.sh`，公开仓库匿名 API，不需要 gh / token。
- 测试只用 `tmp_path` + monkeypatch，禁止 sleep/网络/随机依赖；失败注入参考
  `tests/test_transaction_recovery.py`。
- 公共行为变化必须同步 `docs/05`（接口）、`docs/03`（模型/校验）、`docs/08`（事件 payload）。
- 下一阶段目标与待决模型问题见 `docs/09-handover.md` §8/§9。
  V1-C 当前主线：**降低同对象并发**（合并本身已不是瓶颈，见 §14 与 docs/06 的 V1-C）。
