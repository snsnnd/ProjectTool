from __future__ import annotations


def test_task_graph_contains_parent_and_dependency_edges(service):
    parent = service.call("task.create", {"title": "Parent"})["id"]
    child = service.call("task.create", {"title": "Child", "parent_task_id": parent})["id"]
    service.call("task.add_dependency", {"task_id": child, "target_id": parent})

    graph = service.call("graph.tasks", {})
    node_ids = {node["id"] for node in graph["nodes"]}
    assert {parent, child} <= node_ids
    kinds = {(edge["from"], edge["to"], edge["kind"]) for edge in graph["edges"]}
    assert (parent, child, "contains") in kinds
    assert (child, parent, "depends_on") in kinds


def test_dependency_graph_depth(service):
    a = service.call("task.create", {"title": "A"})["id"]
    b = service.call("task.create", {"title": "B"})["id"]
    c = service.call("task.create", {"title": "C"})["id"]
    service.call("task.add_dependency", {"task_id": a, "target_id": b})
    service.call("task.add_dependency", {"task_id": b, "target_id": c})

    graph = service.call("graph.dependencies", {"task_id": a, "depth": 1})
    ids = {node["id"] for node in graph["nodes"]}
    assert ids == {a, b}

    graph = service.call("graph.dependencies", {"task_id": a, "depth": 5})
    ids = {node["id"] for node in graph["nodes"]}
    assert ids == {a, b, c}


def test_project_tree(service, seeded):
    tree = service.call("graph.project", {})
    assert tree["project"]["id"] == seeded["task"]["project_id"]
    assert [goal["id"] for goal in tree["goals"]] == [seeded["goal"]["id"]]
    milestone = tree["milestones"][0]
    assert milestone["id"] == seeded["milestone"]["id"]
    assert seeded["task"]["id"] in milestone["task_ids"]


def test_parent_cycle_rejected(service):
    a = service.call("task.create", {"title": "A"})["id"]
    b = service.call("task.create", {"title": "B", "parent_task_id": a})["id"]
    from project_tool.domain.errors import InvalidArgument

    import pytest

    with pytest.raises(InvalidArgument):
        service.call("task.set_parent", {"task_id": a, "parent_task_id": b})
