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
        content_references=[],
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
        assert manifest["content_type"] == "text"
        assert manifest["text"] == "test narrative"


def test_write_source_protocol_opacity_from_salience():
    """Opacity should come from fragment salience."""
    from agents.imagination_resolver import write_source_protocol

    fragment = ImaginationFragment(
        id="test-frag-3",
        narrative="test",
        content_references=[],
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
        content_references=[],
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
