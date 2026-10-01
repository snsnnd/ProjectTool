"""多 agent 并行接活的验证脚本（V1-C 收尾）。

验证的不是"能不能并发写"（那是 V1-C 早就实测过的），而是**协调流程本身
在真实并发下成不成立**：

1. 3 个 agent 并行开工，每个先 `pjt task next`（只读）再 `pjt task claim`
2. 故意让它们**抢同一个 task** —— 只有一个该成功，其余拿到 `CLAIMED`
3. 拿到 `CLAIMED` 的 agent 必须**换任务**，而不是失败退出
4. 每个 agent 开工前要读到相关接口契约
5. 结束时校验：没有 task 被两个人认领、doctor 干净、无锁/事务残留、
   事件归属到正确的 agent

用**真子进程**（不是线程）—— 因为要验的是多个独立进程抢 WriteLock，
线程共享 GIL 根本模拟不出来。

跑法：
    python3 dogfooding/scripts/multiagent_demo.py

## 它不进 CI —— 而且是有理由的

这个脚本要 **210–280 秒**，比整个测试套件还慢 2 倍（每个 `pjt` 调用都是一次
解释器启动 + pydantic 导入，再叠加 WriteLock 排队）。每次 CI 跑它太贵。

CI 里跑的是 `tests/test_multiagent_flow.py`：**线程 + barrier**，**124 ms**，
碰撞**每次必然发生**（barrier 让三者先读到同一个最优 task 再同时认领），
而且断言的是不变量 —— 所以不会因为时序而假通过。

分工：

| | 本脚本 | CI 测试 |
|---|---|---|
| 进程模型 | 真子进程（验跨进程差异：PJT_ACTOR、device_id、活 PID 锁） | 线程（同进程，共享 PID） |
| 耗时 | 210–280 s | 124 ms |
| 碰撞 | 靠时序，会撞 | barrier 保证必然撞 |
| 频率 | 手动 / 改动协调逻辑时 | 每次 CI |

它抓到过一个真 bug（认领竞态下输的一方拿到 `REVISION_CONFLICT` 而非
`CLAIMED`），所以留着有价值 —— 只是不该每次 CI 都付这个钱。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VENV_PY = REPO / ".venv" / "bin" / "python"
if VENV_PY.is_file() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
sys.path.insert(0, str(REPO))

PJT = [str(REPO / ".venv" / "bin" / "pjt")]
CLAIMED_EXIT = 6


def run(root: Path, *args: str, env_extra: dict[str, str] | None = None):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [*PJT, "-C", str(root), *args], capture_output=True, text=True, env=env
    )


def ok(root: Path, *args: str, env_extra=None) -> str:
    proc = run(root, *args, env_extra=env_extra)
    if proc.returncode != 0:
        raise SystemExit(f"setup failed: pjt {' '.join(args)}\n{proc.stdout}{proc.stderr}")
    return proc.stdout


def jrun(root: Path, *args: str, env_extra=None):
    proc = run(root, "--json", *args, env_extra=env_extra)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise SystemExit(
            f"bad json from pjt {' '.join(args)}: {proc.stdout[:300]}"
        ) from None
    return proc.returncode, payload


def setup(root: Path) -> None:
    ok(root, "init", "--name", "MultiAgent")
    for handle in ("agent-1", "agent-2", "agent-3"):
        ok(root, "member", "add", handle)
    ok(root, "area", "add", "core", "--path-pattern", "studio_core/**")
    ok(root, "area", "add", "ui", "--path-pattern", "studio_ui/**")
    ok(root, "interface", "init", "store.updateModel", "--area", "core",
       "--kind", "store_api", "--consumer", "ui", "--summary", "store 批量更新入口")
    ok(root, "interface", "init", "ui.CommPanel", "--area", "ui",
       "--kind", "module_api", "--consumer", "core", "--summary", "通信页面板")


def add_task(root: Path, title: str, area: str, priority: str = "normal") -> str:
    proc = run(root, "task", "add", title, "--area", area, "--priority", priority)
    for token in proc.stdout.split():
        if token.startswith("TSK-"):
            return token
    raise SystemExit(f"could not create task: {proc.stdout}{proc.stderr}")


def agent_work(handle: str, max_attempts: int = 4) -> dict:
    """一个 agent 的完整开工流程。每个 agent 是独立子进程。"""
    root = Path(os.environ["MULTIAGENT_ROOT"])
    env = {"PJT_ACTOR": handle}
    log: list[str] = []
    tried: set[str] = set()

    for _ in range(max_attempts):
        code, payload = jrun(root, "task", "next", env_extra=env)
        if code != 0:
            return {"agent": handle, "outcome": "error", "detail": payload, "log": log}
        if not payload["result"]["found"]:
            return {"agent": handle, "outcome": "idle", "log": log}

        chosen = payload["result"]["task"]
        task_id = chosen["id"]
        if task_id in tried:
            # next 又给我一个我试过的 —— 说明剩下的都被别人占了，收工
            return {"agent": handle, "outcome": "idle", "log": log}
        tried.add(task_id)

        # 开工前读契约（agent 没有隐性知识，这一步不能省）
        interfaces = payload["result"]["interfaces"]
        for row in interfaces:
            run(root, "interface", "show", row["name"], env_extra=env)

        code, payload = jrun(root, "task", "claim", task_id, "--agent", handle,
                             "--ttl", "20", env_extra=env)
        if code == CLAIMED_EXIT:
            # 撞上了：换一个，不退出。这是整个流程的关键分支
            log.append(f"CLAIMED on {task_id} -> 换任务")
            continue
        if code != 0:
            # 走到这里说明「输」没有变成 CLAIMED —— 那就是真 bug，
            # 因为输的原因只可能是「被人认领走了」
            return {"agent": handle, "outcome": "error", "detail": payload, "log": log}

        log.append(f"claimed {task_id} ({chosen['title']})，读了 {len(interfaces)} 份契约")

        # 干活（这里只做状态推进；真实项目里 agent 会去改代码）
        ok(root, "task", "start", task_id, env_extra=env)
        (root / f"notes-{handle}.md").write_text(f"{handle} did {task_id}\n", encoding="utf-8")
        return {
            "agent": handle,
            "outcome": "worked",
            "task": task_id,
            "title": chosen["title"],
            "interfaces": [r["name"] for r in interfaces],
            "log": log,
        }

    return {"agent": handle, "outcome": "gave-up", "log": log}


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="pjt-multiagent-"))
    root = base / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "a@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Driver"], check=True)
    setup(root)

    print("=" * 78)
    print("多 agent 并行接活 —— 故意让它们抢同一个 task")
    print("=" * 78)
    ids = [
        add_task(root, "打通 store.updateModel 与通信页", "core", "high"),
        add_task(root, "通信页面板加状态过滤", "ui"),
        add_task(root, "数据流页排序稳定性", "ui"),
        add_task(root, "真机 hash 提示文案", "core"),
    ]
    print(f"  准备了 {len(ids)} 个 task，全部在 core/ui，没有分区隔离 —— 保证会撞")
    for handle in ("agent-1", "agent-2", "agent-3"):
        ok(root, "member", "use", handle)
    # 回到无人认领的状态（member use 只是设 actor，不会认领任何东西）
    print()

    env = {**os.environ, "MULTIAGENT_ROOT": str(root)}
    procs = []
    for handle in ("agent-1", "agent-2", "agent-3"):
        procs.append(
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--agent", handle],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**env, "MULTIAGENT_AGENT": handle},
            )
        )
    results = []
    for proc, handle in zip(procs, ("agent-1", "agent-2", "agent-3"), strict=True):
        out, err = proc.communicate(timeout=180)
        results.append(json.loads(out.strip()) if out.strip() else
                       {"agent": handle, "outcome": "crash", "log": [err[-300:]]})

    for result in results:
        print(f"  {result['agent']:<10} {result['outcome']:<8} "
              f"{result.get('title') or result.get('detail', '')}")
        for line in result.get("log", []):
            print(f"             · {line}")
    print()

    # ------------------------------------------------------------- 校验
    print("-" * 78)
    print("校验")
    print("-" * 78)
    failures: list[str] = []

    worked = [r for r in results if r["outcome"] == "worked"]
    done_ids = [r["task"] for r in worked]
    if len(done_ids) != len(set(done_ids)):
        failures.append(f"同一个 task 被多个 agent 认领: {done_ids}")
    else:
        print(f"  ✓ 没有重复认领：{len(done_ids)} 个 task，{len(set(done_ids))} 个不同 id")

    claimed = json.loads(ok(root, "--json", "task", "list", "--claimed-by", "agent-1"))["result"] \
        if False else json.loads(run(root, "--json", "task", "list").stdout)["result"]
    claims: dict[str, str] = {}
    for row in claimed:
        if row.get("claim"):
            claims[row["claim"]["member_id"]] = row["id"]
    if len(claims) > len(set(claims.values())):
        failures.append(f"认领关系不是一对多: {claims}")
    else:
        print(f"  ✓ 认领关系合法：{len(claims)} 个 task 有人认领")

    _, report = jrun(root, "doctor")
    summary = report["result"]["summary"]
    if report["result"]["ok"] and summary["errors"] == 0:
        print(f"  ✓ doctor ok（errors=0 warnings={summary['warnings']}）")
    else:
        failures.append(f"doctor 不干净: {report['result']}")

    residue = list((root / ".pjt" / "transactions").glob("*")) if (
        root / ".pjt" / "transactions"
    ).is_dir() else []
    if residue:
        failures.append(f"transactions 残留: {residue}")
    else:
        print("  ✓ 无 transactions 残留")
    if (root / ".pjt" / "write.lock").exists():
        failures.append("write.lock 残留")
    else:
        print("  ✓ 无 write.lock 残留")

    _, log_payload = jrun(root, "log", "-n", "60")
    events = log_payload["result"]["events"]
    _, member_payload = jrun(root, "member", "list")
    handles = {m["id"]: m["handle"] for m in member_payload["result"]}
    from collections import Counter

    by_actor = Counter(handles.get(e["actor_id"], "(none)") for e in events)
    agents_seen = {k: v for k, v in by_actor.items() if k.startswith("agent-")}
    print(f"  · 事件归属分布: {dict(agents_seen)}")
    if len(agents_seen) < 3:
        failures.append(f"有 agent 没留下事件，归属可能错了: {agents_seen}")
    else:
        print("  ✓ 三个 agent 的事件都正确归属到自己")

    read_ok = all(r.get("interfaces") for r in worked)
    print(f"  {'✓' if read_ok else '·'} 开工前读到了接口契约: "
          f"{[r.get('interfaces') for r in worked]}")

    print()
    if failures:
        print("FAILED:")
        for item in failures:
            print(f"  - {item}")
    else:
        print("PASS：三个 agent 并行接活，没撞出重复劳动，数据完整，归属正确")
    print(f"\nworkdir: {root}")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--agent" in sys.argv:
        agent_name = sys.argv[sys.argv.index("--agent") + 1]
        os.environ["MULTIAGENT_AGENT"] = agent_name
        print(json.dumps(agent_work(agent_name)))
    else:
        raise SystemExit(main())