"""Tests for agents.studio_compositor.active_wards."""

from __future__ import annotations

import json
import os
import time

from agents.studio_compositor import active_wards as aw


def test_publish_then_read_round_trip(tmp_path):
    target = tmp_path / "active_wards.json"
    aw.publish(["album-cover", "splat-attribution-v1", "youtube-slot-0"], path=target)

    result = aw.read(path=target)

    assert sorted(result) == ["album-cover", "splat-attribution-v1", "youtube-slot-0"]


def test_publish_dedupes(tmp_path):
    target = tmp_path / "active_wards.json"
    aw.publish(["album-cover", "album-cover", "splat-attribution-v1"], path=target)

    result = aw.read(path=target)

    assert sorted(result) == ["album-cover", "splat-attribution-v1"]


def test_publish_sorts_for_stable_serialization(tmp_path):
    """Sorted order means the file content is stable across runs with the
    same input — useful for diffing logs and for staleness checks that
    compare bytes."""
    target = tmp_path / "active_wards.json"
    aw.publish(["zzz", "aaa", "mmm"], path=target)

    payload = json.loads(target.read_text())
    assert payload["ward_ids"] == ["aaa", "mmm", "zzz"]


def test_publish_empty_list_is_valid(tmp_path):
    """No wards rendering is a real state — director should see []."""
    target = tmp_path / "active_wards.json"
    aw.publish([], path=target)

    assert aw.read(path=target) == []


def test_read_returns_empty_when_file_missing(tmp_path):
    target = tmp_path / "absent.json"
    assert aw.read(path=target) == []


def test_read_treats_stale_file_as_empty(tmp_path):
    """Stale-as-empty: a stalled producer must not freeze the consumer's
    view at the last list. Better to emit no badges than badges for
    wards that may have been removed minutes ago."""
    target = tmp_path / "active_wards.json"
    aw.publish(["album-cover"], path=target)
    # Backdate the file beyond the staleness cutoff.
    old = target.stat().st_mtime - aw.ACTIVE_WARDS_STALE_S - 1
    os.utime(target, (old, old))

    assert aw.read(path=target) == []


def test_read_honors_custom_stale_threshold(tmp_path):
    target = tmp_path / "active_wards.json"
    aw.publish(["a"], path=target)
    old = target.stat().st_mtime - 100
    os.utime(target, (old, old))

    # Default threshold treats this as stale.
    assert aw.read(path=target) == []
    # Wider threshold accepts it.
    assert aw.read(path=target, stale_s=200.0) == ["a"]


def test_read_returns_empty_on_malformed_json(tmp_path):
    target = tmp_path / "active_wards.json"
    target.write_text("{not json")

    assert aw.read(path=target) == []


def test_read_returns_empty_when_ward_ids_field_missing(tmp_path):
    target = tmp_path / "active_wards.json"
    target.write_text(json.dumps({"published_t": time.time()}))

    assert aw.read(path=target) == []


def test_read_returns_empty_when_ward_ids_wrong_type(tmp_path):
    """Defensive: a corrupted file with ward_ids as a string (not list)
    must not crash the consumer."""
    target = tmp_path / "active_wards.json"
    target.write_text(json.dumps({"ward_ids": "not-a-list", "published_t": time.time()}))

    assert aw.read(path=target) == []


def test_read_filters_non_string_entries(tmp_path):
    """Defensive: a corrupted file with mixed types in ward_ids must
    yield only the string entries."""
    target = tmp_path / "active_wards.json"
    target.write_text(
        json.dumps(
            {"ward_ids": ["album-cover", 42, None, "youtube-slot-0"], "published_t": time.time()}
        )
    )

    assert sorted(aw.read(path=target)) == ["album-cover", "youtube-slot-0"]


def test_publish_writes_atomically_via_tmp_rename(tmp_path):
    """The temp file should not survive a successful publish."""
    target = tmp_path / "active_wards.json"
    tmp = tmp_path / "active_wards.json.tmp"
    aw.publish(["a"], path=target)

    assert target.exists()
    assert not tmp.exists()


def test_publish_creates_parent_directory(tmp_path):
    """First publish into a fresh subdir should mkdir -p it."""
    target = tmp_path / "nested" / "subdir" / "active_wards.json"
    aw.publish(["a"], path=target)

    assert target.exists()
    assert aw.read(path=target) == ["a"]


def test_publish_includes_published_t_timestamp(tmp_path):
    target = tmp_path / "active_wards.json"
    before = time.time()
    aw.publish(["a"], path=target)
    after = time.time()

    payload = json.loads(target.read_text())
    assert before <= payload["published_t"] <= after


def test_visible_ward_property_ids_filters_hidden_and_bad_entries(tmp_path):
    target = tmp_path / "ward-properties.json"
    target.write_text(
        json.dumps(
            {
                "wards": {
                    "album_overlay": {"visible": True},
                    "hidden": {"visible": False},
                    "implicit_visible": {"alpha": 1.0},
                    "": {"visible": True},
                    "duplicate": {"visible": True},
                }
            }
        ),
        encoding="utf-8",
    )

    assert aw.visible_ward_property_ids(path=target) == [
        "album_overlay",
        "duplicate",
        "implicit_visible",
    ]


def test_visible_ward_property_ids_returns_empty_on_missing_or_malformed(tmp_path):
    assert aw.visible_ward_property_ids(path=tmp_path / "missing.json") == []

    malformed = tmp_path / "ward-properties.json"
    malformed.write_text("{not json", encoding="utf-8")

    assert aw.visible_ward_property_ids(path=malformed) == []


def test_canonical_path_pins_shm_dir():
    """The default file path must live in /dev/shm/hapax-compositor/
    so the publisher and consumer in different processes agree without
    any configuration."""
    assert str(aw.ACTIVE_WARDS_FILE) == "/dev/shm/hapax-compositor/active_wards.json"
    assert str(aw.WARD_PROPERTIES_FILE) == "/dev/shm/hapax-compositor/ward-properties.json"
