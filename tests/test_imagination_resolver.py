"""Tests for imagination content resolver and DMN visual surface sensor."""

from __future__ import annotations

import json

from agents.imagination import ContentReference, ImaginationFragment
from agents.imagination_resolver import cleanup_content_dir, resolve_references, resolve_text


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
