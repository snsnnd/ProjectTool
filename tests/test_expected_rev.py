"""统一 optimistic concurrency contract：expected_rev（V1-A 任务 2）。

规则（docs/09-v1a-design.md §4）：

```text
expected_rev 省略   -> 用 load 时的当前 rev 作为 transaction base_rev
expected_rev 提供   -> 必须等于当前 canonical rev，否则 REVISION_CONFLICT
```

本文件对 project / task / goal / milestone / member / decision / link
七个领域各测「正确 / 过期 / 省略」三态，并验证所有领域语义一致。
"""

from __future__ import annotations

import pytest

from project_tool.application.context import ServiceContext
from project_tool.domain.errors import RevisionConflict
from project_tool.storage import init_project, open_project

STALE_REV = "sha256:" + "0" * 64


@pytest.fixture()
def project(tmp_path):
    init_project(tmp_path, name="Contract")
    return open_project(tmp_path)


@pytest.fixture()
def svc(project):
    from project_tool.application.service import ProjectService

    return ProjectService(project)


def current_rev(svc, method, params):
    return svc.call(method, params)["rev"]


# --------------------------------------------------------------------- 集中 helper


def test_require_expected_rev_is_single_source_of_truth(project):
    ctx = ServiceContext(project)
    goal = ctx.save(
        _make_goal(ctx),
        None,
        "goal.created",
        {"title": "x"},
        is_create=True,
    )
    model = ctx.load("goal", goal["id"])
    assert ctx.require_expected_rev("goal", model, None) == model.rev
    assert ctx.require_expected_rev("goal", model, model.rev) == model.rev
    with pytest.raises(RevisionConflict):
        ctx.require_expected_rev("goal", model, STALE_REV)


def _make_goal(ctx):
    from project_tool.domain.goal import Goal
    from project_tool.domain.ids import new_id
    from project_tool.domain.timeutil import now_local

    now = now_local()
    return Goal(
        id=new_id("goal"),
        project_id=ctx.opened.project.id,
        title="helper goal",
        created_at=now,
        updated_at=now,
    )


# --------------------------------------------------------------------- 矩阵


def test_project_expected_rev(svc):
    with pytest.raises(RevisionConflict):
        svc.call("project.update", {"name": "x", "expected_rev": STALE_REV})
    rev = svc.call("project.get")["rev"]
    assert svc.call("project.update", {"name": "Renamed", "expected_rev": rev})["name"] == "Renamed"
    assert svc.call("project.update", {"description": "no guard"})["description"] == "no guard"


def test_task_expected_rev(svc):
    task = svc.call("task.create", {"title": "T"})
    with pytest.raises(RevisionConflict):
        svc.call("task.update", {"task_id": task["id"], "title": "x", "expected_rev": STALE_REV})
    with pytest.raises(RevisionConflict):
        svc.call(
            "task.set_status",
            {"task_id": task["id"], "status": "doing", "expected_rev": STALE_REV},
        )
    rev = current_rev(svc, "task.get", {"task_id": task["id"]})
    assert (
        svc.call("task.update", {"task_id": task["id"], "title": "T2", "expected_rev": rev})["title"]
        == "T2"
    )
    assert svc.call("task.update", {"task_id": task["id"], "title": "T3"})["title"] == "T3"


def test_goal_expected_rev(svc):
    goal = svc.call("goal.create", {"title": "G"})
    with pytest.raises(RevisionConflict):
        svc.call("goal.update", {"goal_id": goal["id"], "title": "x", "expected_rev": STALE_REV})
    with pytest.raises(RevisionConflict):
        svc.call(
            "goal.set_status", {"goal_id": goal["id"], "status": "achieved", "expected_rev": STALE_REV}
        )
    rev = current_rev(svc, "goal.get", {"goal_id": goal["id"]})
    assert (
        svc.call("goal.update", {"goal_id": goal["id"], "title": "G2", "expected_rev": rev})["title"]
        == "G2"
    )
    assert svc.call("goal.update", {"goal_id": goal["id"], "title": "G3"})["title"] == "G3"


def test_milestone_expected_rev(svc):
    milestone = svc.call("milestone.create", {"title": "M"})
    with pytest.raises(RevisionConflict):
        svc.call(
            "milestone.update", {"milestone_id": milestone["id"], "title": "x", "expected_rev": STALE_REV}
        )
    for method in ("milestone.activate", "milestone.close", "milestone.cancel"):
        with pytest.raises(RevisionConflict):
            svc.call(method, {"milestone_id": milestone["id"], "expected_rev": STALE_REV})
    rev = current_rev(svc, "milestone.get", {"milestone_id": milestone["id"]})
    assert (
        svc.call(
            "milestone.update",
            {"milestone_id": milestone["id"], "title": "M2", "expected_rev": rev},
        )["title"]
        == "M2"
    )
    assert svc.call("milestone.activate", {"milestone_id": milestone["id"]})["status"] == "active"


def test_member_expected_rev(svc):
    svc.call("member.add", {"handle": "alice", "display_name": "Alice"})
    with pytest.raises(RevisionConflict):
        svc.call("member.update", {"member": "alice", "display_name": "x", "expected_rev": STALE_REV})
    with pytest.raises(RevisionConflict):
        svc.call("member.deactivate", {"member": "alice", "expected_rev": STALE_REV})
    rev = current_rev(svc, "member.get", {"member": "alice"})
    assert (
        svc.call(
            "member.update", {"member": "alice", "display_name": "Alicia", "expected_rev": rev}
        )["display_name"]
        == "Alicia"
    )
    assert svc.call("member.deactivate", {"member": "alice"})["active"] is False
    assert svc.call("member.activate", {"member": "alice"})["active"] is True


def test_decision_expected_rev(svc):
    decision = svc.call("decision.create", {"title": "D"})
    with pytest.raises(RevisionConflict):
        svc.call("decision.update", {"decision_id": decision["id"], "title": "x", "expected_rev": STALE_REV})
    with pytest.raises(RevisionConflict):
        svc.call("decision.accept", {"decision_id": decision["id"], "expected_rev": STALE_REV})
    with pytest.raises(RevisionConflict):
        svc.call("decision.reject", {"decision_id": decision["id"], "expected_rev": STALE_REV})
    rev = current_rev(svc, "decision.get", {"decision_id": decision["id"]})
    assert (
        svc.call(
            "decision.update", {"decision_id": decision["id"], "title": "D2", "expected_rev": rev}
        )["title"]
        == "D2"
    )
    assert svc.call("decision.accept", {"decision_id": decision["id"]})["status"] == "accepted"


def test_decision_supersede_expected_rev(svc):
    old = svc.call("decision.create", {"title": "old"})
    new = svc.call("decision.create", {"title": "new"})
    with pytest.raises(RevisionConflict):
        svc.call(
            "decision.supersede",
            {"old_id": old["id"], "new_id": new["id"], "expected_rev": STALE_REV},
        )
    assert svc.call("decision.get", {"decision_id": old["id"]})["status"] == "draft"
    assert svc.call("decision.get", {"decision_id": new["id"]})["supersedes_id"] is None
    rev = current_rev(svc, "decision.get", {"decision_id": old["id"]})
    result = svc.call(
        "decision.supersede", {"old_id": old["id"], "new_id": new["id"], "expected_rev": rev}
    )
    assert result["superseded"]["status"] == "superseded"
    assert result["superseded_by"]["supersedes_id"] == old["id"]


def test_link_expected_rev(svc):
    svc.call("link.add", {"name": "fw", "locator": "../firmware"})
    with pytest.raises(RevisionConflict):
        svc.call("link.update", {"name": "fw", "locator": "../other", "expected_rev": STALE_REV})
    link = svc.call("link.get", {"name": "fw"})
    assert (
        svc.call(
            "link.update", {"name": "fw", "locator": "../other", "expected_rev": link["rev"]}
        )["target"]["locator"]
        == "../other"
    )
    assert svc.call("link.update", {"name": "fw", "mode": "aggregate"})["mode"] == "aggregate"


def test_update_expected_rev(svc):
    record = svc.call("update.create", {"summary": "U"})
    with pytest.raises(RevisionConflict):
        svc.call("update.update", {"update_id": record["id"], "summary": "x", "expected_rev": STALE_REV})
    assert (
        svc.call("update.update", {"update_id": record["id"], "body": "detail"})["body"] == "detail"
    )


# --------------------------------------------------------------------- 语义一致性


def test_stale_rev_never_partially_applies(svc):
    task = svc.call("task.create", {"title": "T", "labels": ["a"]})
    before = svc.call("task.get", {"task_id": task["id"]})
    with pytest.raises(RevisionConflict):
        svc.call(
            "task.add_label",
            {"task_id": task["id"], "label": "b", "expected_rev": STALE_REV},
        )
    assert svc.call("task.get", {"task_id": task["id"]}) == before


def test_stale_rev_fails_even_when_operation_is_a_noop(svc):
    """guard 在业务逻辑之前：no-op 短路也不能吞掉过期的 expected_rev。"""
    task = svc.call("task.create", {"title": "T", "labels": ["a"]})
    with pytest.raises(RevisionConflict):
        svc.call("task.add_label", {"task_id": task["id"], "label": "a", "expected_rev": STALE_REV})
    with pytest.raises(RevisionConflict):
        svc.call("task.archive", {"task_id": task["id"], "expected_rev": STALE_REV})
    assert svc.call("task.get", {"task_id": task["id"]})["lifecycle"] == "active"


def test_expected_rev_works_for_short_ids(svc):
    member = svc.call("member.add", {"handle": "bob"})
    svc.call("task.create", {"title": "T", "owner_ids": [member["id"]]})
    task = svc.call("task.list")[0]
    prefix, ulid = task["id"].split("-", 1)
    short = f"{prefix}-{ulid[:6]}"
    with pytest.raises(RevisionConflict):
        svc.call("task.assign", {"task_id": short, "member": "bob", "expected_rev": STALE_REV})
    rev = current_rev(svc, "task.get", {"task_id": short})
    assert svc.call("task.unassign", {"task_id": short, "member": "bob", "expected_rev": rev})


def test_transaction_still_guards_when_expected_rev_omitted(svc):
    """省略 expected_rev 时，事务层的 base_rev 校验依然是最后一道门。"""
    task = svc.call("task.create", {"title": "T"})
    loaded = svc.call("task.get", {"task_id": task["id"]})
    assert loaded["rev"]

    # 两个 Service 实例先后读取同一 rev；第二个的写入基于陈旧 base_rev 时被事务拒绝。
    from project_tool.application.service import ProjectService

    other = ProjectService(open_project(svc.opened.paths.root))
    assert current_rev(other, "task.get", {"task_id": task["id"]}) == loaded["rev"]
    svc.call("task.update", {"task_id": task["id"], "title": "first writer wins"})
    assert other.call("task.get", {"task_id": task["id"]})["title"] == "first writer wins"
    assert svc.call("task.get", {"task_id": task["id"]})["version"] == 2
