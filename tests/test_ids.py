from __future__ import annotations

from project_tool.domain.ids import CROCKFORD, new_id, short_id, split_id, ulid


def test_ulid_shape():
    value = ulid()
    assert len(value) == 26
    assert all(char in CROCKFORD for char in value)


def test_ulid_monotonic_within_same_millisecond():
    values = [ulid(now_ms=1_700_000_000_000) for _ in range(500)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_new_id_prefix():
    assert new_id("task").startswith("TSK-")
    assert new_id("project").startswith("PRJ-")
    assert new_id("event").startswith("EVT-")


def test_split_and_short():
    value = new_id("task")
    prefix, part = split_id(value)
    assert prefix == "TSK"
    assert len(part) == 26
    short = short_id(value, keep=8)
    assert short.startswith("TSK-")
    assert len(short) == 12


def test_split_invalid():
    assert split_id("NOT-AN-ID!!") is None
    assert split_id("") is None
