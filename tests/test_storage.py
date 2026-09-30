from __future__ import annotations

import pytest

from project_tool.domain.errors import AlreadyExists, InvalidArgument, NotFound
from project_tool.integrations import filesystem
from project_tool.storage import ObjectStore, find_project_root, init_project, open_project
from project_tool.storage.project_store import ProjectPaths


def test_init_layout(project):
    paths = project.paths
    assert paths.project_json.is_file()
    assert paths.config_toml.is_file()
    assert paths.labels_json.is_file()
    assert paths.state_json.is_file()
    assert paths.local_toml.is_file()
    assert paths.locks.is_dir()
    assert paths.transactions.is_dir()
    for collection in ("goals", "milestones", "tasks", "members", "updates", "decisions", "links"):
        assert (paths.objects / collection).is_dir()


def test_init_twice_fails(root):
    init_project(root, name="One")
    with pytest.raises(AlreadyExists):
        init_project(root, name="Two")


def test_gitignore_entries_written_once(root):
    init_project(root, name="One")
    content = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".pjt/local/" in content
    assert ".pjt/transactions/" in content
    assert content.count(".pjt/local/") == 1


def test_find_project_root_from_subdir(root):
    init_project(root, name="One")
    nested = root / "src" / "deep"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == root.resolve()
    assert find_project_root(root / "src" / "missing-dir") == root.resolve()


def test_find_project_root_none(tmp_path_factory):
    standalone = tmp_path_factory.mktemp("standalone")
    assert find_project_root(standalone) is None


def test_open_missing_project(tmp_path):
    with pytest.raises(NotFound):
        open_project(tmp_path)


def test_short_id_resolution_and_ambiguity(root):
    init_project(root, name="One")
    store = ObjectStore(ProjectPaths(root))
    first = "TSK-01K8H2AAA00000000000000000"
    second = "TSK-01K8H2BBB00000000000000000"
    filesystem.write_json(store.path_for("task", first), {"id": first})
    filesystem.write_json(store.path_for("task", second), {"id": second})
    assert store.resolve("task", "TSK-01K8H2AAA") == first
    with pytest.raises(InvalidArgument):
        store.resolve("task", "TSK-01K8H2")
    with pytest.raises(InvalidArgument):
        store.resolve("task", "MLS-01K8H2")
    with pytest.raises(NotFound):
        store.resolve("task", "TSK-01K8H2ZZZ")
