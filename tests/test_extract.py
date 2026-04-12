"""Tests for agents/studio_compositor/extract.py — Extract phase.

Phase 2b of the compositor unification epic. The Extract phase produces
immutable FrameDescription snapshots from a Layout. These tests validate
that the snapshot is truly immutable, that input mutations don't leak
into the snapshot, and that the cross-thread safety guarantees hold.
"""

from __future__ import annotations

import threading
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agents.studio_compositor.extract import FrameDescription, extract_frame_description
from shared.compositor_model import Layout

GARAGE_DOOR_PATH = Path(__file__).parent.parent / "config" / "layouts" / "garage-door.json"


@pytest.fixture
def garage_door_layout() -> Layout:
    return Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())


@pytest.fixture
def minimal_layout() -> Layout:
    return Layout.model_validate(
        {
            "name": "minimal",
            "sources": [{"id": "s1", "kind": "camera", "backend": "v4l2"}],
            "surfaces": [{"id": "f1", "geometry": {"kind": "tile"}}],
            "assignments": [{"source": "s1", "surface": "f1"}],
        }
    )


# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------


class TestExtract:
    def test_basic_returns_frame_description(self, minimal_layout):
        fd = extract_frame_description(minimal_layout, frame_index=0)
        assert isinstance(fd, FrameDescription)
        assert fd.frame_index == 0
        assert fd.layout is minimal_layout
        assert fd.source_versions == {}
        assert fd.source_metadata == {}

    def test_frame_index_preserved(self, minimal_layout):
        fd = extract_frame_description(minimal_layout, frame_index=42)
        assert fd.frame_index == 42

    def test_default_timestamp_is_monotonic(self, minimal_layout):
        before = time.monotonic()
        fd = extract_frame_description(minimal_layout, frame_index=0)
        after = time.monotonic()
        assert before <= fd.timestamp <= after

    def test_explicit_timestamp_used(self, minimal_layout):
        fd = extract_frame_description(minimal_layout, frame_index=0, timestamp=100.5)
        assert fd.timestamp == 100.5

    def test_source_versions_passed_through(self, minimal_layout):
        versions = {"s1": 5, "s2": 12}
        fd = extract_frame_description(minimal_layout, frame_index=0, source_versions=versions)
        assert fd.source_versions == versions

    def test_source_versions_copied_not_aliased(self, minimal_layout):
        """Mutating the input dict after extract should not affect the snapshot."""
        versions = {"s1": 5}
        fd = extract_frame_description(minimal_layout, frame_index=0, source_versions=versions)
        versions["s1"] = 999
        versions["s2"] = 1
        # Snapshot should still have the original values
        assert fd.source_versions == {"s1": 5}

    def test_source_metadata_deep_copied(self, minimal_layout):
        """Mutating nested dicts after extract should not affect the snapshot."""
        meta = {"s1": {"mtime": 100.0, "version": 1}}
        fd = extract_frame_description(minimal_layout, frame_index=0, source_metadata=meta)
        meta["s1"]["mtime"] = 999.0
        meta["s2"] = {"new": True}
        # Snapshot should still have the original values
        assert fd.source_metadata == {"s1": {"mtime": 100.0, "version": 1}}


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestFrameDescriptionImmutable:
    def test_cannot_assign_fields(self, minimal_layout):
        fd = extract_frame_description(minimal_layout, frame_index=0)
        with pytest.raises(FrozenInstanceError):
            fd.frame_index = 99  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            fd.timestamp = 0.0  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            fd.layout = None  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helper accessors
# ---------------------------------------------------------------------------


class TestAccessors:
    def test_source_version_default_zero(self, minimal_layout):
        fd = extract_frame_description(minimal_layout, frame_index=0)
        assert fd.source_version("nonexistent") == 0

    def test_source_version_returns_value(self, minimal_layout):
        fd = extract_frame_description(minimal_layout, frame_index=0, source_versions={"s1": 7})
        assert fd.source_version("s1") == 7

    def test_source_meta_default_empty(self, minimal_layout):
        fd = extract_frame_description(minimal_layout, frame_index=0)
        assert fd.source_meta("nonexistent") == {}

    def test_source_meta_returns_value(self, minimal_layout):
        fd = extract_frame_description(
            minimal_layout, frame_index=0, source_metadata={"s1": {"k": "v"}}
        )
        assert fd.source_meta("s1") == {"k": "v"}


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_reads_from_multiple_threads(self, garage_door_layout):
        """Multiple threads can read the same FrameDescription concurrently."""
        fd = extract_frame_description(
            garage_door_layout,
            frame_index=100,
            source_versions={"cam-brio-operator": 5},
        )

        results: list[bool] = []

        def reader():
            ok = (
                fd.frame_index == 100
                and fd.layout.name == "garage-door"
                and fd.source_version("cam-brio-operator") == 5
                and len(fd.layout.sources) > 0
            )
            results.append(ok)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)
        assert len(results) == 10


# ---------------------------------------------------------------------------
# Garage-door integration
# ---------------------------------------------------------------------------


class TestGarageDoorExtract:
    """Validates that the canonical layout can be extracted into a FrameDescription."""

    def test_garage_door_extract(self, garage_door_layout):
        fd = extract_frame_description(garage_door_layout, frame_index=0)
        assert fd.layout is garage_door_layout
        assert fd.layout.name == "garage-door"
        assert len(fd.layout.sources) > 0
        assert len(fd.layout.surfaces) > 0
        assert len(fd.layout.assignments) > 0

    def test_garage_door_with_versions(self, garage_door_layout):
        versions = {s.id: i for i, s in enumerate(garage_door_layout.sources)}
        fd = extract_frame_description(garage_door_layout, frame_index=0, source_versions=versions)
        for i, s in enumerate(garage_door_layout.sources):
            assert fd.source_version(s.id) == i
