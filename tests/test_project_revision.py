from __future__ import annotations

import json

import pytest

from project_tool.application.service import ProjectService
from project_tool.domain.errors import RevisionConflict
from project_tool.domain.hashing import verify_rev
from project_tool.storage import EventSpec, ObjectChange, Transaction, WriteLock


def test_project_has_revision(service):
    project = service.call("project.get", {})
    assert project["version"] == 1
    assert project["rev"].startswith("sha256:")
    assert verify_rev(project)
    assert project["created_by"] is None
    assert project["updated_by"] is None


def test_project_init_event_has_new_rev(project):
    events = [record for record in project.paths.events.rglob("EVT-*.json")]
    payload = json.loads(events[0].read_text(encoding="utf-8"))
    assert payload["event_type"] == "project.initialized"
    assert payload["new_rev"] == project.project.rev


def test_project_version_increments_and_rev_changes(service):
    before = service.call("project.get", {})
    after = service.call("project.update", {"name": "Renamed"})
    assert after["version"] == before["version"] + 1
    assert after["rev"] != before["rev"]
    assert after["name"] == "Renamed"


def test_project_expected_rev_conflict(service):
    before = service.call("project.get", {})
    service.call("project.update", {"description": "race"})
    with pytest.raises(RevisionConflict) as excinfo:
        service.call("project.update", {"name": "Late", "expected_rev": before["rev"]})
    assert excinfo.value.to_error()["code"] == "REVISION_CONFLICT"


def test_concurrent_project_update_rejected(project):
    first = ProjectService(project)
    stale = first.call("project.get", {})
    first.call("project.update", {"description": "first wins"})
    record = stale
    with pytest.raises(RevisionConflict):
        with WriteLock(project.paths):
            Transaction(project, first.actor_id).commit(
                [ObjectChange("project", stale["id"], {**record, "name": "stale"}, stale["rev"])],
                [EventSpec("project.updated", "project", stale["id"], {})],
            )


def test_project_update_requires_no_actor(project):
    service = ProjectService(project)
    updated = service.call("project.update", {"description": "no member yet"})
    assert updated["updated_by"] is None
