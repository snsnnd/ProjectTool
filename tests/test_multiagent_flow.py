"""多 agent 并行接活（V1-C 收尾）：协调流程的端到端验证。

`dogfooding/scripts/multiagent_demo.py` 用**真子进程**跑同一套流程，抓到过一个
真 bug（认领竞态下输的一方拿到 `REVISION_CONFLICT` 而非 `CLAIMED`）。但它要
**210–280 秒**，比整个测试套件还慢 2 倍，不适合每次 CI 跑。

所以这里用**线程 + barrier** 复现同一件事：

- 文件锁是跨线程的，多个线程会真的在 `WriteLock` 上排队 —— 争用是真的
- `barrier` 让所有线程**先各自读到同一个最优 task**，再同时认领，
  于是碰撞**每次必然发生**，不是靠运气
- 124 ms vs 210 秒

线程共享 PID（所以一个线程看别人的锁是「活着的」，会等 —— 这和同一台机器上
多个进程的行为一致），但**不能**验证跨进程的那部分差异（比如 `device_id`、
`PJT_ACTOR` 的环境变量隔离）。那部分由 demo 脚本覆盖，不进 CI。

## 断言的是不变量，不是「恰好没撞上」

无论有没有撞上，下面这些都必须成立 —— 所以测试不会因为时序而假通过：

- 不会有两个人做同一个 task
- 撞上 `CLAIMED` 的 agent **换任务**，不退出、不报错
- 不会有 agent 拿到 `CLAIMED` / `REVISION_CONFLICT` 之外的意外错误
- 数据完整：doctor 干净、无锁/事务残留、事件归属正确
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from project_tool.application.service import ProjectService
from project_tool.domain.errors import Claimed, ProjectToolError
from project_tool.storage import init_project, open_project

AGENTS = ("agent-1", "agent-2", "agent-3")
TASK_COUNT = 4
MAX_ATTEMPTS = 6


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "repo"
    init_project(root, name="MultiAgent")
    setup = ProjectService(open_project(root))
    for handle in AGENTS:
        setup.call("member.add", {"handle": handle})
    core = setup.call("area.create", {"name": "core", "path_patterns": ["studio_core/**"]})
    ui = setup.call("area.create", {"name": "ui", "path_patterns": ["studio_ui/**"]})
    setup.call(
        "interface.init",
        {"name": "store.updateModel", "area": "core", "consumers": ["ui"]},
    )
    setup.call(
        "interface.init",
        {"name": "ui.CommPanel", "area": "ui", "consumers": ["core"]},
    )
    # task 必须落在 area 里，否则 `task next` 带不出任何接口契约
    for index in range(TASK_COUNT):
        setup.call(
            "task.create",
            {
                "title": f"任务 {index}",
                "area_id": core["id"] if index % 2 == 0 else ui["id"],
                "priority": "normal",
            },
        )
    return root


def service_for(root: Path, handle: str) -> ProjectService:
    """每个 agent 一个独立 service 实例，actor **显式传入**。

    不用 `PJT_ACTOR`：线程共享 `os.environ`，那是竞态来源。跨进程那部分
    由 demo 脚本验证。
    """
    return ProjectService(open_project(root), actor_id=handle)


def agent_loop(root: Path, handle: str, results: dict, barrier: threading.Barrier | None = None):
    """一个 agent 的完整开工流程：`next` → 读契约 → `claim` → 干活。"""
    service = service_for(root, handle)
    tried: set[str] = set()
    read_contracts: list[str] = []
    collisions = 0
    # barrier **只能用一次**：它是 parties=3 的一次性汇合，认领成功后这个 agent
    # 就走了，剩下两个再等就永远等不到第三个 -> BrokenBarrierError。
    first_round = True

    for _ in range(MAX_ATTEMPTS):
        brief = service.call("task.next")
        if not brief["found"]:
            results[handle] = {"outcome": "idle", "task": None, "collisions": collisions}
            return
        chosen = brief["task"]

        # 开工前读契约：agent 没有隐性知识，这一步不能省
        for row in brief["interfaces"]:
            read_contracts.append(row["name"])

        if barrier is not None and first_round:
            # 让所有 agent 都先看到同一个最优 task，再同时认领 —— 碰撞必然发生
            first_round = False
            barrier.wait(timeout=30)

        if chosen["id"] in tried:
            continue
        tried.add(chosen["id"])
        try:
            service.call(
                "task.claim",
                {"task_id": chosen["id"], "member": handle, "ttl_minutes": 20},
            )
        except Claimed:
            collisions += 1
            continue
        except ProjectToolError as exc:  # pragma: no cover - 下面会断言不该发生
            results[handle] = {
                "outcome": "error",
                "task": None,
                "collisions": collisions,
                "error": f"{exc.code}: {exc}",
            }
            return

        service.call("task.set_status", {"task_id": chosen["id"], "status": "doing"})
        results[handle] = {
            "outcome": "worked",
            "task": chosen["id"],
            "collisions": collisions,
            "read_contracts": read_contracts,
        }
        return

    results[handle] = {
        "outcome": "gave-up",
        "task": None,
        "collisions": collisions,
        "read_contracts": read_contracts,
    }


def run_agents(root: Path, barrier: threading.Barrier | None = None) -> dict[str, dict]:
    results: dict[str, dict] = {}
    threads = [
        threading.Thread(target=agent_loop, args=(root, handle, results, barrier))
        for handle in AGENTS
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(not thread.is_alive() for thread in threads), "agent 卡住了"
    return results


# ================================================================== 并行


def test_parallel_agents_never_double_work(project):
    """三个 agent 抢同一批 task，不能有两个人做同一个。"""
    results = run_agents(project, barrier=threading.Barrier(len(AGENTS)))

    worked = {h: r for h, r in results.items() if r["outcome"] == "worked"}
    ids = [r["task"] for r in worked.values()]
    assert len(ids) == len(set(ids)), f"同一个 task 被多个 agent 认领: {ids}"
    assert len(worked) >= 1, f"应该至少有一个 agent 干成活: {results}"


def test_parallel_agents_all_hit_the_same_task_and_only_one_wins(project):
    """barrier 让三者必然抢同一个 task —— 输的必须是 CLAIMED，不是别的错。"""
    results = run_agents(project, barrier=threading.Barrier(len(AGENTS)))
    # 第一个认领成功后，后面的 next 会跳过它，所以碰撞次数 >= 2
    assert sum(r["collisions"] for r in results.values()) >= 2, results
    for handle, result in results.items():
        assert result["outcome"] != "error", f"{handle} 拿到意外错误: {result.get('error')}"


def test_a_collision_switches_task_instead_of_failing(project):
    """撞上就换 —— 整个流程成立的前提。"""
    results = run_agents(project, barrier=threading.Barrier(len(AGENTS)))
    worked = [r for r in results.values() if r["outcome"] == "worked"]
    assert worked, f"没有任何 agent 干成活: {results}"
    assert all(r["outcome"] in ("worked", "idle", "gave-up") for r in results.values())
    # 认领过多个的说明真的换了任务
    assert any(r["collisions"] > 0 for r in results.values()), results


def test_parallel_run_leaves_data_intact(project):
    """并发跑完数据必须完整。"""
    run_agents(project, barrier=threading.Barrier(len(AGENTS)))
    service = ProjectService(open_project(project))

    report = service.call("project.doctor")
    assert report["ok"] is True, report
    assert report["summary"]["errors"] == 0

    residue = list((project / ".pjt" / "transactions").glob("*"))
    assert residue == [], f"transactions 残留: {residue}"
    assert not (project / ".pjt" / "write.lock").exists(), "write.lock 残留"

    rows = service.call("task.list")
    claims = {r["id"]: r["claim"]["member_id"] for r in rows if r.get("claim")}
    assert len(set(claims.values())) == len(claims), f"认领不是一对多: {claims}"


def test_every_agent_read_the_interface_contracts_first(project):
    """开工前读契约 —— agent 没有隐性知识，这一步不能省。"""
    results = run_agents(project, barrier=threading.Barrier(len(AGENTS)))
    for handle, result in results.items():
        if result["outcome"] != "worked":
            continue
        assert result["read_contracts"], f"{handle} 没读到任何接口契约就开工了"


def test_events_are_attributed_to_the_right_agent(project):
    run_agents(project, barrier=threading.Barrier(len(AGENTS)))
    service = ProjectService(open_project(project))
    handles = {m["id"]: m["handle"] for m in service.call("member.list")}
    events = service.call("log.list", {"limit": 100})["events"]

    by_actor: dict[str, int] = {}
    for event in events:
        name = handles.get(event["actor_id"], "(none)")
        by_actor[name] = by_actor.get(name, 0) + 1
    for handle in AGENTS:
        assert by_actor.get(handle, 0) > 0, f"{handle} 没有事件，归属可能错了: {by_actor}"


# ================================================================== 确定性路径


def test_second_claimer_is_told_to_pick_another_task(project):
    """确定性地撞一次：输的那个必须拿到 CLAIMED（换任务），不是 REVISION_CONFLICT。"""
    service = ProjectService(open_project(project))
    task_id = service.call("task.list")[0]["id"]

    winner = service_for(project, AGENTS[0])
    loser = service_for(project, AGENTS[1])
    winner.call("task.claim", {"task_id": task_id, "member": AGENTS[0]})

    with pytest.raises(Claimed) as excinfo:
        loser.call("task.claim", {"task_id": task_id, "member": AGENTS[1]})
    assert excinfo.value.code == "CLAIMED"
    assert excinfo.value.exit_code == 6
    assert json.dumps(excinfo.value.details)  # details 里带上是谁占着、到什么时候


def test_unclaimed_filter_hides_taken_work(project):
    """agent 换任务时靠这个找活：被认领的不该再出现。"""
    service = ProjectService(open_project(project))
    first = service.call("task.next")["task"]["id"]
    agent = service_for(project, AGENTS[0])
    agent.call("task.claim", {"task_id": first, "member": AGENTS[0]})

    free = [r["id"] for r in service.call("task.list", {"unclaimed": True})]
    assert first not in free
    assert len(free) == TASK_COUNT - 1