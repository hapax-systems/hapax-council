"""Tests for demo history listing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.demo_pipeline.history import list_demos, get_demo


class TestListDemos:
    @pytest.fixture
    def demos_dir(self, tmp_path) -> Path:
        """Create fake demo output directories."""
        for name, meta in [
            ("20260304-120000-system", {"title": "System Demo", "audience": "family", "format": "slides", "scenes": 3, "duration": 20.0}),
            ("20260304-130000-health", {"title": "Health Demo", "audience": "technical-peer", "format": "video", "scenes": 5, "duration": 35.0}),
        ]:
            d = tmp_path / name
            d.mkdir()
            (d / "metadata.json").write_text(json.dumps(meta, indent=2))
        return tmp_path

    def test_lists_demos_newest_first(self, demos_dir):
        demos = list_demos(demos_dir)
        assert len(demos) == 2
        assert demos[0]["title"] == "Health Demo"

    def test_empty_dir(self, tmp_path):
        demos = list_demos(tmp_path)
        assert demos == []


class TestGetDemo:
    def test_returns_metadata(self, tmp_path):
        d = tmp_path / "20260304-120000-test"
        d.mkdir()
        meta = {"title": "Test", "format": "slides"}
        (d / "metadata.json").write_text(json.dumps(meta))
        (d / "script.json").write_text("{}")
        (d / "demo.mp4").write_bytes(b"fake")

        result = get_demo(d)
        assert result["title"] == "Test"
        assert "demo.mp4" in result["files"]

    def test_returns_metadata_with_relative_paths(self, tmp_path):
        d = tmp_path / "20260304-120000-test"
        d.mkdir()
        ss_dir = d / "screenshots"
        ss_dir.mkdir()
        meta = {"title": "Test", "format": "slides"}
        (d / "metadata.json").write_text(json.dumps(meta))
        (d / "script.json").write_text("{}")
        (ss_dir / "01-dashboard.png").write_bytes(b"fake")

        result = get_demo(d)
        assert "screenshots/01-dashboard.png" in result["files"]
        assert "script.json" in result["files"]

    def test_missing_dir_returns_none(self, tmp_path):
        result = get_demo(tmp_path / "nonexistent")
        assert result is None
