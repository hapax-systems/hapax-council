"""Tests for clip_extractor module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.auto_clip.clip_extractor import _discover_segments
from shared.stream_archive import SegmentSidecar


def _write_sidecar(
    day_dir: Path,
    segment_id: str,
    start: datetime,
    end: datetime,
) -> Path:
    sidecar = SegmentSidecar.new(
        segment_id=segment_id,
        segment_path=str(day_dir / f"{segment_id}.ts"),
        condition_id=None,
        segment_start_ts=start,
        segment_end_ts=end,
    )
    sidecar_path = day_dir / f"{segment_id}.sidecar.json"
    sidecar_path.write_text(sidecar.to_json(), encoding="utf-8")
    ts_path = day_dir / f"{segment_id}.ts"
    ts_path.write_bytes(b"\x00" * 100)
    return sidecar_path


def test_discover_segments_filters_by_time(tmp_path: Path):
    day_dir = tmp_path / "hls" / "2026-05-11"
    day_dir.mkdir(parents=True)

    base = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
    _write_sidecar(day_dir, "seg001", base, base + timedelta(seconds=2))
    _write_sidecar(day_dir, "seg002", base + timedelta(seconds=2), base + timedelta(seconds=4))
    _write_sidecar(day_dir, "seg003", base + timedelta(seconds=10), base + timedelta(seconds=12))

    query_start = base + timedelta(seconds=1)
    query_end = base + timedelta(seconds=5)
    results = _discover_segments(tmp_path, "2026-05-11", query_start, query_end)

    assert len(results) == 2
    ids = [s.segment_id for _, s in results]
    assert "seg001" in ids
    assert "seg002" in ids
    assert "seg003" not in ids


def test_discover_segments_empty_dir(tmp_path: Path):
    results = _discover_segments(
        tmp_path,
        "2026-01-01",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )
    assert results == []
