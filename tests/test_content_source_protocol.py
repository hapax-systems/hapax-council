"""Tests for the content source protocol output from imagination_resolver."""

import json
import tempfile
from pathlib import Path

from agents.imagination import ImaginationFragment


def test_write_source_manifest_creates_directory():
    """Source protocol should create sources/{source_id}/ directory."""
    from agents.imagination_resolver import write_source_protocol

    fragment = ImaginationFragment(
        id="test-frag-1",
        narrative="test narrative",
        salience=0.5,
        dimensions={},
        continuation=False,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        sources_dir = Path(tmpdir) / "sources"
        write_source_protocol(fragment, [], sources_dir)
        source_dir = sources_dir / f"imagination-{fragment.id}"
        assert source_dir.exists()
        manifest = json.loads((source_dir / "manifest.json").read_text())
        assert manifest["source_id"] == f"imagination-{fragment.id}"
        assert manifest["content_type"] == "rgba"
        assert manifest["width"] == 640
        assert manifest["height"] == 360
        assert (source_dir / "frame.rgba").exists()
        frame_size = (source_dir / "frame.rgba").stat().st_size
        assert frame_size == 640 * 360 * 4  # RGBA


def test_write_source_protocol_opacity_from_salience():
    """Opacity should come from fragment salience."""
    from agents.imagination_resolver import write_source_protocol

    fragment = ImaginationFragment(
        id="test-frag-3",
        narrative="test",
        salience=0.75,
        dimensions={},
        continuation=False,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        sources_dir = Path(tmpdir) / "sources"
        write_source_protocol(fragment, [], sources_dir)
        source_dir = sources_dir / f"imagination-{fragment.id}"
        manifest = json.loads((source_dir / "manifest.json").read_text())
        assert manifest["opacity"] == 0.75


def test_write_source_protocol_has_required_fields():
    """Manifest must have all required fields for the Rust reader."""
    from agents.imagination_resolver import write_source_protocol

    fragment = ImaginationFragment(
        id="test-frag-4",
        narrative="complete test",
        salience=0.6,
        dimensions={},
        continuation=False,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        sources_dir = Path(tmpdir) / "sources"
        write_source_protocol(fragment, [], sources_dir)
        source_dir = sources_dir / f"imagination-{fragment.id}"
        manifest = json.loads((source_dir / "manifest.json").read_text())
        required_fields = [
            "source_id",
            "content_type",
            "opacity",
            "layer",
            "blend_mode",
            "z_order",
            "ttl_ms",
            "tags",
        ]
        for field in required_fields:
            assert field in manifest, f"Missing required field: {field}"


def test_inject_rgba_writes_requested_ttl(monkeypatch, tmp_path):
    """Source-protocol callers can make live surfaces expire instead of stale."""
    from agents.reverie import content_injector

    monkeypatch.setattr(content_injector, "SOURCES_DIR", tmp_path / "sources")

    assert content_injector.inject_rgba("ttl-test", b"\0" * 16, 2, 2, ttl_ms=7000)
    manifest = json.loads((tmp_path / "sources" / "ttl-test" / "manifest.json").read_text())

    assert manifest["ttl_ms"] == 7000
