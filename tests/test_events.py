from __future__ import annotations

import hashlib

from project_tool.storage.event_store import EventStore


def event_hashes(paths) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths.events.rglob("EVT-*.json"))
    }


def test_events_are_immutable(service, seeded):
    before = event_hashes(service.paths)
    assert before

    task_id = seeded["task"]["id"]
    service.call("task.set_status", {"task_id": task_id, "status": "doing"})
    service.call("task.add_label", {"task_id": task_id, "label": "net"})
    service.call("task.assign", {"task_id": task_id, "member": "alice"})
    service.call("update.create", {"summary": "progress", "task_ids": [task_id]})
    service.call("decision.create", {"title": "D"})
    service.call("project.update", {"description": "updated"})

    after = event_hashes(service.paths)
    for name, digest in before.items():
        assert after[name] == digest, f"event {name} was modified"
    assert len(after) > len(before)


def test_event_store_has_no_mutation_api():
    assert not hasattr(EventStore, "update_event")
    assert not hasattr(EventStore, "delete_event")
    assert not hasattr(EventStore, "remove")


def test_task_status_changed_payload_contract(service, seeded):
    service.call("task.set_status", {"task_id": seeded["task"]["id"], "status": "doing"})
    events = service.call("log.list", {"event_type": "task.status_changed"})["events"]
    assert events[0]["payload"] == {"from": "inbox", "to": "doing"}


def test_task_updated_payload_contract(service, seeded):
    service.call("task.update", {"task_id": seeded["task"]["id"], "title": "Renamed"})
    events = service.call("log.list", {"event_type": "task.updated"})["events"]
    assert events[0]["payload"]["fields"] == ["title"]


def test_task_assigned_payload_contract(service, seeded):
    service.call("member.add", {"handle": "bob", "display_name": "Bob"})
    bob = service.call("member.get", {"member": "bob"})
    service.call("task.assign", {"task_id": seeded["task"]["id"], "member": "bob"})
    events = service.call("log.list", {"event_type": "task.assigned"})["events"]
    assert events[0]["payload"] == {"member_id": bob["id"]}


def test_dependency_added_payload_contract(service):
    first = service.call("task.create", {"title": "A"})["id"]
    second = service.call("task.create", {"title": "B"})["id"]
    service.call("task.add_dependency", {"task_id": first, "target_id": second})
    events = service.call("log.list", {"event_type": "task.dependency_added"})["events"]
    assert events[0]["payload"] == {"target_id": second, "relation": "depends_on"}


def test_project_updated_payload_contract(service):
    service.call("project.update", {"name": "Renamed"})
    events = service.call("log.list", {"event_type": "project.updated"})["events"]
    assert events[0]["payload"]["fields"] == ["name"]
