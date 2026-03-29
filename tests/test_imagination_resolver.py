"""Tests for imagination content resolver and DMN visual surface sensor."""

from __future__ import annotations

import json

from agents.imagination import ContentReference, ImaginationFragment
from agents.imagination_resolver import (
    cleanup_content_dir,
    resolve_references,
    resolve_references_staged,
    resolve_text,
    write_slot_manifest,
)


def _make_fragment(refs: list[ContentReference], fid: str = "test123") -> ImaginationFragment:
    return ImaginationFragment(
        id=fid,
        content_references=refs,
        dimensions={"intensity": 0.5},
        salience=0.3,
        continuation=False,
        narrative="test thought",
    )


# ---------------------------------------------------------------------------
# Task 1: imagination resolver
# ---------------------------------------------------------------------------


def test_resolve_text_creates_jpeg(tmp_path):
    ref = ContentReference(kind="text", source="Hello world", query=None, salience=0.5)
    result = resolve_text(ref, tmp_path, "frag1", 0)
    assert result is not None and result.exists()
    assert result.name == "frag1-0.jpg"
    assert result.stat().st_size > 100


def test_resolve_text_multiline(tmp_path):
    ref = ContentReference(
        kind="text", source="Line one\nLine two\nLine three", query=None, salience=0.5
    )
    result = resolve_text(ref, tmp_path, "frag2", 0)
    assert result is not None and result.exists()


def test_cleanup_removes_old_files(tmp_path):
    (tmp_path / "old1-0.jpg").write_bytes(b"\xff\xd8fake")
    (tmp_path / "old1-1.jpg").write_bytes(b"\xff\xd8fake")
    assert len(list(tmp_path.glob("*.jpg"))) == 2
    cleanup_content_dir(tmp_path)
    assert len(list(tmp_path.glob("*.jpg"))) == 0


def test_resolve_references_skips_fast_kinds(tmp_path):
    refs = [
        ContentReference(kind="camera_frame", source="overhead", query=None, salience=0.8),
        ContentReference(kind="file", source="/some/path.jpg", query=None, salience=0.5),
        ContentReference(kind="text", source="hello", query=None, salience=0.3),
    ]
    frag = _make_fragment(refs)
    results = resolve_references(frag, tmp_path)
    assert len(results) == 1
    assert results[0].name == "test123-2.jpg"


# ---------------------------------------------------------------------------
# Task 1b: staging + slot manifest
# ---------------------------------------------------------------------------


def test_write_slot_manifest(tmp_path):
    refs = [
        ContentReference(kind="text", source="Hello", query=None, salience=0.7),
        ContentReference(kind="text", source="World", query=None, salience=0.4),
    ]
    frag = _make_fragment(refs, fid="m1")
    manifest_path = tmp_path / "slots.json"
    paths = [tmp_path / "m1-0.jpg", tmp_path / "m1-1.jpg"]
    for p in paths:
        p.write_bytes(b"\xff\xd8dummy")
    write_slot_manifest(frag, paths, manifest_path)
    data = json.loads(manifest_path.read_text())
    assert data["fragment_id"] == "m1"
    assert len(data["slots"]) == 2
    assert data["slots"][0]["index"] == 0
    assert data["slots"][0]["salience"] == 0.7
    assert data["material"] == "water"
    assert data["continuation"] is False


def test_resolve_references_staged_atomic(tmp_path):
    staging = tmp_path / "staging"
    active = tmp_path / "active"
    refs = [ContentReference(kind="text", source="Test content", query=None, salience=0.5)]
    frag = _make_fragment(refs, fid="s1")
    resolve_references_staged(frag, staging_dir=staging, active_dir=active)
    assert active.exists()
    assert not staging.exists()
    assert (active / "s1-0.jpg").exists()
    manifest = json.loads((active / "slots.json").read_text())
    assert manifest["fragment_id"] == "s1"


def test_resolve_references_staged_replaces_previous(tmp_path):
    staging = tmp_path / "staging"
    active = tmp_path / "active"
    refs1 = [ContentReference(kind="text", source="First", query=None, salience=0.5)]
    frag1 = _make_fragment(refs1, fid="r1")
    resolve_references_staged(frag1, staging_dir=staging, active_dir=active)
    assert (active / "r1-0.jpg").exists()
    refs2 = [ContentReference(kind="text", source="Second", query=None, salience=0.6)]
    frag2 = _make_fragment(refs2, fid="r2")
    resolve_references_staged(frag2, staging_dir=staging, active_dir=active)
    assert (active / "r2-0.jpg").exists()
    assert not (active / "r1-0.jpg").exists()


def test_manifest_camera_frame_uses_source_path(tmp_path):
    refs = [ContentReference(kind="camera_frame", source="overhead", query=None, salience=0.8)]
    frag = _make_fragment(refs, fid="c1")
    manifest_path = tmp_path / "slots.json"
    write_slot_manifest(frag, [], manifest_path)
    data = json.loads(manifest_path.read_text())
    assert data["slots"][0]["path"] == "/dev/shm/hapax-compositor/overhead.jpg"
    assert data["slots"][0]["kind"] == "camera_frame"


def test_manifest_file_ref_uses_source_path(tmp_path):
    refs = [ContentReference(kind="file", source="/tmp/test.jpg", query=None, salience=0.6)]
    frag = _make_fragment(refs, fid="f1")
    manifest_path = tmp_path / "slots.json"
    write_slot_manifest(frag, [], manifest_path)
    data = json.loads(manifest_path.read_text())
    assert data["slots"][0]["path"] == "/tmp/test.jpg"


def test_manifest_max_four_slots(tmp_path):
    refs = [
        ContentReference(kind="text", source=f"Slot {i}", query=None, salience=0.5)
        for i in range(6)
    ]
    frag = _make_fragment(refs, fid="max")
    manifest_path = tmp_path / "slots.json"
    write_slot_manifest(frag, [tmp_path / f"max-{i}.jpg" for i in range(6)], manifest_path)
    data = json.loads(manifest_path.read_text())
    assert len(data["slots"]) == 4  # capped at MAX_SLOTS


# ---------------------------------------------------------------------------
# Task 2: DMN visual surface sensor
# ---------------------------------------------------------------------------

from agents.dmn.sensor import read_visual_surface


def test_read_visual_surface_missing():
    result = read_visual_surface()
    assert result["source"] == "visual_surface"
    assert result["stale"] is True


def test_read_visual_surface_with_frame(tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
    current = tmp_path / "current.json"
    current.write_text(json.dumps({"id": "abc123", "timestamp": 0.0}))
    result = read_visual_surface(frame_path=frame, imagination_path=current)
    assert result["source"] == "visual_surface"
    assert result["frame_path"] == str(frame)
    assert result["imagination_fragment_id"] == "abc123"
    assert result["stale"] is False
