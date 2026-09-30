from __future__ import annotations

import pytest

from project_tool.domain.errors import InvalidArgument


def test_capabilities_exposes_methods_and_features(service):
    caps = service.call("system.capabilities", {})
    assert caps["protocol_version"] == 1
    assert caps["schema_version"] == "1.0"
    for name in (
        "project.get",
        "project.update",
        "project.recover",
        "task.create",
        "task.set_status",
        "system.capabilities",
    ):
        assert name in caps["methods"]
    assert caps["methods"] == sorted(caps["methods"])
    assert set(caps["features"]) == {"artifact", "git", "search", "web", "remote", "sync"}
    assert not any(caps["features"].values())


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
