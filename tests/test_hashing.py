from __future__ import annotations

from project_tool.domain.hashing import canonical_json, compute_rev, verify_rev


def test_canonical_json_key_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_rev_stable_and_changes():
    base = {"id": "TSK-1", "title": "x", "version": 1}
    rev1 = compute_rev(base)
    rev2 = compute_rev({"version": 1, "title": "x", "id": "TSK-1"})
    assert rev1 == rev2
    assert rev1.startswith("sha256:")
    changed = compute_rev({**base, "title": "y"})
    assert changed != rev1


def test_rev_ignores_rev_field():
    record = {"id": "TSK-1", "title": "x", "rev": "sha256:whatever"}
    assert compute_rev(record) == compute_rev({k: v for k, v in record.items() if k != "rev"})
    record["rev"] = compute_rev(record)
    assert verify_rev(record)


def test_verify_rev_rejects_tamper():
    record = {"id": "TSK-1", "title": "x"}
    record["rev"] = compute_rev(record)
    record["title"] = "tampered"
    assert not verify_rev(record)
