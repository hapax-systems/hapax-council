"""Tests for clip_catalog module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.auto_clip.clip_catalog import (
    CatalogEntry,
    build_catalog_metadata,
    collect_month_entries,
    write_catalog,
)


def test_collect_month_entries_empty_dir(tmp_path: Path):
    with patch("agents.auto_clip.clip_catalog.LEDGER_DIR", tmp_path):
        entries = collect_month_entries(2026, 5)
    assert entries == []


def test_collect_month_entries_filters_by_month(tmp_path: Path):
    may_entry = {
        "clip_id": "clip-20260511-120000-abc12345",
        "timestamp": "2026-05-11T12:00:00Z",
        "candidate": {
            "suggested_title": "May clip",
            "decoder_channels": ["visual"],
        },
        "uploads": [{"success": True, "platform": "youtube", "url": "https://yt/123"}],
    }
    june_entry = {
        "clip_id": "clip-20260611-120000-def67890",
        "timestamp": "2026-06-11T12:00:00Z",
        "candidate": {"suggested_title": "June clip", "decoder_channels": ["sonic"]},
        "uploads": [],
    }

    (tmp_path / "clip-20260511-120000-abc12345.json").write_text(
        json.dumps(may_entry), encoding="utf-8"
    )
    (tmp_path / "clip-20260611-120000-def67890.json").write_text(
        json.dumps(june_entry), encoding="utf-8"
    )

    with patch("agents.auto_clip.clip_catalog.LEDGER_DIR", tmp_path):
        entries = collect_month_entries(2026, 5)
    assert len(entries) == 1
    assert entries[0].title == "May clip"


def test_build_catalog_metadata_structure():
    entries = [
        CatalogEntry(
            clip_id="clip-001",
            timestamp="2026-05-11T12:00:00Z",
            title="Test",
            decoder_channel="visual",
            platforms=["youtube"],
            urls=["https://yt/123"],
        )
    ]
    meta = build_catalog_metadata(entries, 2026, 5)
    assert meta["license"] == "cc-by-4.0"
    assert "1" in meta["description"]
    assert meta["access_right"] == "open"


def test_write_catalog_no_entries(tmp_path: Path):
    with patch("agents.auto_clip.clip_catalog.LEDGER_DIR", tmp_path):
        result = write_catalog(2026, 1)
    assert result is None
