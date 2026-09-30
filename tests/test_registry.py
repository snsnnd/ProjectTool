from __future__ import annotations

import pytest

from project_tool.domain.errors import InvalidArgument
from project_tool.version import SCHEMA_VERSION


def test_capabilities_exposes_methods_and_features(service):
    caps = service.call("system.capabilities", {})
    assert caps["protocol_version"] == 1
    assert caps["schema_version"] == SCHEMA_VERSION
    for name in (
        "project.get",
        "project.update",
        "project.recover",
        "area.create",
        "area.list",
        "artifact.create",
        "artifact.verify",
        "task.related_artifacts",
        "git.available",
        "git.status",
        "git.log",
        "git.link_commit",
        "task.create",
        "task.move_area",
        "task.set_status",
        "system.capabilities",
    ):
        assert name in caps["methods"]
    assert caps["methods"] == sorted(caps["methods"])
    assert set(caps["features"]) == {
        "area",
        "artifact",
        "git",
        "search",
        "web",
        "remote",
        "sync",
    }
    # 已落地：area / artifact / git（只读感知）
    assert caps["features"]["area"] is True
    assert caps["features"]["artifact"] is True
    assert caps["features"]["git"] is True
    # 明确不做 / 未做：serverless 决定砍掉 remote 与 sync
    assert not any(
        caps["features"][name] for name in ("search", "web", "remote", "sync")
    )


def test_registry_covers_every_declared_domain(service):
    categories = {spec.category for spec in service.registry.values()}
    assert {"system", "project", "area", "artifact", "task", "milestone", "goal",
            "member", "update", "decision", "link", "git", "log", "graph"} <= categories


def test_registry_specs_have_metadata(service):
    spec = service.registry["task.set_status"]
    assert spec.mutating is True
    assert spec.category == "task"
    assert spec.description
    read_spec = service.registry["task.get"]
    assert read_spec.mutating is False
    assert all(callable(item.handler) for item in service.registry.values())


def test_registry_names_unique(service):
    names = list(service.registry)
    assert len(names) == len(set(names))


def test_unknown_method_rejected(service):
    with pytest.raises(InvalidArgument):
        service.call("task.explode", {})
    with pytest.raises(InvalidArgument):
        service.call("nonsense", {})


def test_handle_returns_error_payload(service):
    response = service.handle("task.get", {"task_id": "TSK-01K8H2MBQX"}, request_id="r1")
    assert response["id"] == "r1"
    assert response["error"]["code"] == "NOT_FOUND"


def test_handle_returns_result_payload(service):
    response = service.handle("system.info", {}, request_id="r2")
    assert response["id"] == "r2"
    assert response["result"]["tool"] == "project-tool"
