"""Task 认领（V1-C）：面向多 agent / 多人并发的协调信号。

**它不是锁，也不是权限门禁。** 目的是让「有人在动这个 task」在动手之前可见，
而不是等到写入那一刻撞 `REVISION_CONFLICT` —— 那时人类重试几秒，agent 整个
任务已经做完、全部作废。

关键性质：
- 过期即失效，判定是**派生**的（比时间戳）→ 不需要任何清理任务
- 别人已认领时**不覆盖**，报 `CLAIMED`
- 同一个人重复 claim = 续期，且保留原 claimed_at
- `CLAIMED` 和 `REVISION_CONFLICT` 是两个码：前者该换任务，后者该重试
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from project_tool.application.service import ProjectService
from project_tool.cli.main import app
from project_tool.domain.errors import Claimed
from project_tool.domain.task import Claim, claim_is_active, claim_view
from project_tool.storage import init_project, open_project

runner = CliRunner()


def invoke(args):
    return runner.invoke(app, args)


@pytest.fixture()
def root(tmp_path):
    init_project(tmp_path, name="Claim")
    return tmp_path


@pytest.fixture()
def svc(root):
    service = ProjectService(open_project(root))
    for handle in ("agent-1", "agent-2"):
        service.call("member.add", {"handle": handle})
    return service


def _task(svc, title="任务"):
    return svc.call("task.create", {"title": title})["id"]


# ------------------------------------------------------------------ 基本语义


def test_new_task_has_no_claim(svc):
    task_id = _task(svc)
    record = svc.call("task.get", {"task_id": task_id})
    assert record["claim"] is None
    assert record["claimed"] is False


def test_claim_records_member_and_expiry(svc):
    task_id = _task(svc)
    out = svc.call("task.claim", {"task_id": task_id, "member": "agent-1", "ttl_minutes": 30})
    assert out["claimed"] is True
    assert out["claim"]["member_id"].startswith("MBR-")
    expires = datetime.fromisoformat(out["claim"]["expires_at"])
    delta = expires - datetime.now().astimezone()
    assert timedelta(minutes=25) < delta <= timedelta(minutes=30)


def test_claim_emits_an_event(svc):
    task_id = _task(svc)
    svc.call("task.claim", {"task_id": task_id, "member": "agent-1"})
    types = [e["event_type"] for e in svc.call("task.history", {"task_id": task_id})["events"]]
    assert types[-1] == "task.claimed"


def test_someone_else_cannot_claim_and_overwrite(svc):
    task_id = _task(svc)
    svc.call("task.claim", {"task_id": task_id, "member": "agent-1"})
    with pytest.raises(Claimed) as excinfo:
        svc.call("task.claim", {"task_id": task_id, "member": "agent-2"})
    assert excinfo.value.code == "CLAIMED"
    # 关键：不能被覆盖
    current = svc.call("task.get", {"task_id": task_id})["claim"]
    assert current["member_id"] == svc.call(
        "member.get", {"member": "agent-1"}
    )["id"]


def test_claimed_has_its_own_exit_code(svc):
    """和 REVISION_CONFLICT 分开：前者该换任务，后者该重试。"""
    assert Claimed.exit_code == 6
    task_id = _task(svc)
    svc.call("task.claim", {"task_id": task_id, "member": "agent-1"})
    bad = invoke(
        ["--json", "-C", str(svc.paths.root), "task", "claim", task_id, "--agent", "agent-2"]
    )
    assert bad.exit_code == 6
    assert json.loads(bad.output)["error"]["code"] == "CLAIMED"


def test_renewing_keeps_the_original_claimed_at(svc):
    task_id = _task(svc)
    first = svc.call("task.claim", {"task_id": task_id, "member": "agent-1", "ttl_minutes": 10})
    second = svc.call("task.claim", {"task_id": task_id, "member": "agent-1", "ttl_minutes": 60})
    assert second["claim"]["claimed_at"] == first["claim"]["claimed_at"]
    assert second["claim"]["expires_at"] > first["claim"]["expires_at"]


def test_release_clears_the_claim(svc):
    task_id = _task(svc)
    svc.call("task.claim", {"task_id": task_id, "member": "agent-1"})
    out = svc.call("task.release", {"task_id": task_id, "member": "agent-1"})
    assert out["claim"] is None


def test_release_by_a_stranger_is_refused(svc):
    task_id = _task(svc)
    svc.call("task.claim", {"task_id": task_id, "member": "agent-1"})
    with pytest.raises(Exception) as excinfo:
        svc.call("task.release", {"task_id": task_id, "member": "agent-2"})
    assert "agent-1" in str(excinfo.value)


def test_releasing_an_unclaimed_task_is_a_noop(svc):
    """重复 release 是正常操作，不该报错（过期本来就没有认领）。"""
    task_id = _task(svc)
    out = svc.call("task.release", {"task_id": task_id, "member": "agent-1"})
    assert out["claim"] is None


def test_ttl_is_capped(svc):
    """防止有人 claim 完就占住一整年 —— 那不是协调，是软锁。"""
    task_id = _task(svc)
    out = svc.call("task.claim", {"task_id": task_id, "member": "agent-1", "ttl_minutes": 10**6})
    expires = datetime.fromisoformat(out["claim"]["expires_at"])
    assert expires < datetime.now().astimezone() + timedelta(hours=9)


# ------------------------------------------------------------------ 过期是派生的


def test_expired_claim_reads_as_absent_without_any_cleanup(svc):
    """过期的认领不需要清理任务：判定是比时间戳，过期即 None。"""
    task_id = _task(svc)
    svc.call("task.claim", {"task_id": task_id, "member": "agent-1", "ttl_minutes": 30})
    past = datetime.now().astimezone() - timedelta(minutes=1)
    # 直接改 expires_at 模拟时间流逝（真实场景靠时间自己走）
    record = svc.call("task.get", {"task_id": task_id})
    assert record["claim"] is not None
    expired = Claim(
        member_id=record["claim"]["member_id"],
        claimed_at=record["claim"]["claimed_at"],
        expires_at=past,
    )
    assert claim_is_active(expired) is False
    assert claim_view(expired) is None


def test_claim_is_active_uses_aware_comparison():
    now = datetime.now().astimezone()
    assert claim_is_active(None) is False
    future = Claim(member_id="MBR-x", claimed_at=now, expires_at=now + timedelta(minutes=1))
    past = Claim(member_id="MBR-x", claimed_at=now, expires_at=now - timedelta(minutes=1))
    assert claim_is_active(future) is True
    assert claim_is_active(past) is False


def test_claim_view_handles_naive_and_aware():
    now = datetime.now(UTC)
    assert claim_view(Claim(member_id="MBR-x", claimed_at=now, expires_at=now - timedelta(minutes=1))) is None


# ------------------------------------------------------------------ 列表过滤


def test_unclaimed_filter_excludes_claimed_tasks(svc):
    a, b = _task(svc, "A"), _task(svc, "B")
    svc.call("task.claim", {"task_id": a, "member": "agent-1"})
    remaining = [row["id"] for row in svc.call("task.list", {"unclaimed": True})]
    assert a not in remaining
    assert b in remaining


def test_claimed_by_filter(svc):
    a, b = _task(svc, "A"), _task(svc, "B")
    svc.call("task.claim", {"task_id": a, "member": "agent-1"})
    rows = svc.call("task.list", {"claimed_by": "agent-1"})
    assert [row["id"] for row in rows] == [a]
    assert b not in [row["id"] for row in rows]


def test_task_list_carries_the_claim_field(svc):
    task_id = _task(svc)
    svc.call("task.claim", {"task_id": task_id, "member": "agent-1"})
    row = next(r for r in svc.call("task.list", {}) if r["id"] == task_id)
    assert row["claimed"] is True
    assert row["claim"]["member_id"].startswith("MBR-")


def test_cli_claim_and_unclaimed(root, svc):
    invoke(["-C", str(root), "member", "add", "agent-1"])
    invoke(["-C", str(root), "member", "add", "agent-2"])
    first = json.loads(invoke(["--json", "-C", str(root), "task", "add", "A"]).output)
    invoke(["--json", "-C", str(root), "task", "add", "B"])
    task_id = first["result"]["id"]

    assert invoke(
        ["-C", str(root), "task", "claim", task_id, "--agent", "agent-1", "--ttl", "15"]
    ).exit_code == 0

    free = json.loads(invoke(["--json", "-C", str(root), "task", "list", "--unclaimed"]).output)
    assert task_id not in [r["id"] for r in free["result"]]

    assert invoke(["-C", str(root), "task", "release", task_id, "--agent", "agent-1"]).exit_code == 0
    free = json.loads(invoke(["--json", "-C", str(root), "task", "list", "--unclaimed"]).output)
    assert task_id in [r["id"] for r in free["result"]]


def test_claim_requires_an_actor(tmp_path, monkeypatch):
    """没有 actor 就不知道是谁在认领 —— 静默记成别人更糟。

    用**全新项目**：任何一次 member.add 都会顺手把 local.actor 设成创建者，
    所以不能复用别的 fixture。
    """
    monkeypatch.delenv("PJT_ACTOR", raising=False)
    root = tmp_path / "bare"
    init_project(root, name="Bare")
    service = ProjectService(open_project(root))
    task_id = service.call("task.create", {"title": "无人认领"})["id"]
    # project.init 不设 actor；确认确实为空
    assert service.ctx.actor_id is None
    with pytest.raises(Exception) as excinfo:
        service.call("task.claim", {"task_id": task_id})
    assert "PJT_ACTOR" in str(excinfo.value) or "member use" in str(excinfo.value)


def test_claim_uses_pjt_actor_when_no_member_given(svc, root, monkeypatch):
    task_id = _task(svc)
    alice = svc.call("member.get", {"member": "agent-1"})["id"]
    monkeypatch.setenv("PJT_ACTOR", "agent-1")
    out = ProjectService(open_project(root)).call("task.claim", {"task_id": task_id})
    assert out["claim"]["member_id"] == alice


# ================================================================== task.next


def test_next_is_read_only(svc):
    """认领是决定，不是查询的一部分 —— next 绝不能顺手 claim。"""
    task_id = _task(svc, "可开工")
    out = svc.call("task.next", {})
    assert out["found"] is True
    assert out["task"]["id"] == task_id
    assert out["task"]["claim"] is None
    assert out["skipped_claimed"] == 0
    types = [e["event_type"] for e in svc.call("task.history", {"task_id": task_id})["events"]]
    assert "task.claimed" not in types


def test_next_excludes_blocked_tasks(svc):
    blocker = _task(svc, "blocker")
    blocked = _task(svc, "blocked")
    svc.call("task.add_dependency", {"task_id": blocked, "target_id": blocker})
    chosen = svc.call("task.next", {})["task"]["id"]
    assert chosen == blocker, "应该先做挡路的那个"


def test_next_prefers_unclaimed(svc):
    a, b = _task(svc, "A"), _task(svc, "B")
    svc.call("task.claim", {"task_id": a, "member": "agent-1"})
    out = svc.call("task.next", {})
    assert out["task"]["id"] == b
    assert out["skipped_claimed"] == 1


def test_next_include_claimed_makes_them_candidates_not_preferred(svc):
    """`--include-claimed` 是「让被认领的也进候选」，不是「优先选被认领的」。

    没它的时候被认领的直接跳过；有了它它们进候选，但排序仍然让无人认领的赢。
    """
    a, b = _task(svc, "A"), _task(svc, "B")
    svc.call("task.claim", {"task_id": a, "member": "agent-1"})

    without = svc.call("task.next", {})
    assert without["task"]["id"] == b
    assert without["skipped_claimed"] == 1

    with_claimed = svc.call("task.next", {"include_claimed": True})
    assert with_claimed["task"]["id"] == b, "仍然优先无人认领的"
    assert with_claimed["skipped_claimed"] == 1, "但要说明这里有 1 个被认领"


def test_next_include_claimed_returns_the_claimed_one_when_it_is_the_only_candidate(svc):
    a = _task(svc, "only one")
    svc.call("task.claim", {"task_id": a, "member": "agent-1"})
    out = svc.call("task.next", {"include_claimed": True})
    assert out["found"] is True
    assert out["task"]["id"] == a
    # 理由里要说清它的认领还有效，别让人以为是块无主的活
    assert "无人认领" not in out["reason"]


def test_next_prefers_higher_priority(svc):
    _task(svc, "low one")
    svc.call("task.create", {"title": "high one", "priority": "high"})
    chosen = svc.call("task.next", {})["task"]
    assert chosen["priority"] == "high"
    assert "priority=high" in svc.call("task.next", {})["reason"]


def test_next_respects_area_filter(svc):
    core = svc.call("area.create", {"name": "core"})["id"]
    ui = svc.call("area.create", {"name": "ui"})["id"]
    svc.call("task.create", {"title": "in core", "area_id": core})
    svc.call("task.create", {"title": "in ui", "area_id": ui})
    out = svc.call("task.next", {"area": "core"})
    assert out["task"]["title"] == "in core"


def test_next_reports_when_there_is_nothing(svc):
    out = svc.call("task.next", {})
    assert out["found"] is False
    assert out["task"] is None
    assert "没有可开工的任务" in out["reason"]


def test_next_explains_that_everything_else_is_claimed(svc):
    a = _task(svc, "A")
    svc.call("task.claim", {"task_id": a, "member": "agent-1"})
    out = svc.call("task.next", {})
    assert out["found"] is False
    assert "已被认领" in out["reason"]


def test_next_excludes_doing_tasks(svc):
    """doing 说明有人在做了，把它列进「下一步」等于推荐撞车。"""
    task_id = _task(svc, "有人在做")
    svc.call("task.set_status", {"task_id": task_id, "status": "doing"})
    assert svc.call("task.next", {})["found"] is False


def test_next_includes_interfaces(svc, root):
    area = svc.call("area.create", {"name": "core"})["id"]
    artifact = svc.call("interface.init", {"name": "store.updateModel", "area": "core"})
    task_id = svc.call("task.create", {"title": "改点东西", "area_id": area})["id"]
    svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task_id})
    out = svc.call("task.next", {})
    assert out["task"]["id"] == task_id
    assert [row["reason"] for row in out["interfaces"]] == ["linked"]
    assert out["interfaces"][0]["name"] == "store.updateModel"


def test_next_carries_the_area_caveat(svc):
    area = svc.call("area.create", {"name": "core"})["id"]
    svc.call("task.create", {"title": "x", "area_id": area})
    note = svc.call("task.next", {})["area_note"]
    assert note["area"] == "core"
    assert "只有本机可见" in note["caveat"]


def test_next_suggests_the_claim_command(svc):
    task_id = _task(svc)
    out = svc.call("task.next", {})
    assert task_id in out["next_step"]
    assert "task claim" in out["next_step"]


def test_related_interfaces_and_next_share_one_scan(svc, root):
    """两个入口必须给出一致的接口列表 —— 各自扫一遍迟早分叉。"""
    area = svc.call("area.create", {"name": "core"})["id"]
    artifact = svc.call("interface.init", {"name": "store.updateModel", "area": "core"})
    task_id = svc.call("task.create", {"title": "x", "area_id": area})["id"]
    svc.call("artifact.attach", {"artifact_id": artifact["id"], "task": task_id})
    from_related = svc.call("task.related_interfaces", {"task_id": task_id})["interfaces"]
    from_next = svc.call("task.next", {})["interfaces"]
    assert [r["name"] for r in from_related] == [r["name"] for r in from_next]


def test_cli_next(root, svc):
    invoke(["-C", str(root), "area", "add", "core"])
    invoke(["-C", str(root), "interface", "init", "store.updateModel", "--area", "core"])
    invoke(["-C", str(root), "task", "add", "改点东西", "--area", "core", "--priority", "high"])
    result = invoke(["--json", "-C", str(root), "task", "next"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)["result"]
    assert payload["found"] is True
    assert payload["interfaces"][0]["name"] == "store.updateModel"
