"""Tests for scripts/archive-search.py — LRR Phase 2 item 6."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest  # noqa: TC002 — runtime dep for fixtures

from shared.stream_archive import SegmentSidecar, atomic_write_json, sidecar_path_for

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "archive-search.py"

_spec = importlib.util.spec_from_file_location("archive_search", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
archive_search = importlib.util.module_from_spec(_spec)
sys.modules["archive_search"] = archive_search
_spec.loader.exec_module(archive_search)


def _fake_archive(tmp_path: Path) -> Path:
    """Build a small archive with 3 sidecars for condition A, 1 for B."""
    root = tmp_path / "archive"
    hls_dir = root / "hls" / "2026-04-14"
    hls_dir.mkdir(parents=True)

    base = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)

    sidecars = [
        SegmentSidecar.new(
            segment_id="segment00001",
            segment_path=hls_dir / "segment00001.ts",
            condition_id="cond-a",
            segment_start_ts=base,
            segment_end_ts=base + timedelta(seconds=4),
            reaction_ids=["rx-1", "rx-2"],
            archive_kind="hls",
        ),
        SegmentSidecar.new(
            segment_id="segment00002",
            segment_path=hls_dir / "segment00002.ts",
            condition_id="cond-a",
            segment_start_ts=base + timedelta(seconds=4),
            segment_end_ts=base + timedelta(seconds=8),
            reaction_ids=["rx-3"],
            archive_kind="hls",
        ),
        SegmentSidecar.new(
            segment_id="segment00003",
            segment_path=hls_dir / "segment00003.ts",
            condition_id="cond-a",
            segment_start_ts=base + timedelta(seconds=100),
            segment_end_ts=base + timedelta(seconds=104),
            archive_kind="hls",
        ),
        SegmentSidecar.new(
            segment_id="segment00004",
            segment_path=hls_dir / "segment00004.ts",
            condition_id="cond-b",
            segment_start_ts=base + timedelta(seconds=200),
            segment_end_ts=base + timedelta(seconds=204),
            archive_kind="hls",
        ),
    ]
    for sidecar in sidecars:
        seg_path = Path(sidecar.segment_path)
        seg_path.write_bytes(b"fake ts data")
        atomic_write_json(sidecar_path_for(seg_path), sidecar.to_json())

    return root


class TestByCondition:
    def test_filters_condition(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = _fake_archive(tmp_path)
        rc = archive_search.main(
            ["--archive-root", str(root), "--format", "json", "by-condition", "cond-a"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert len(payload) == 3
        assert all(item["condition_id"] == "cond-a" for item in payload)

    def test_unknown_condition_returns_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _fake_archive(tmp_path)
        rc = archive_search.main(["--archive-root", str(root), "by-condition", "cond-missing"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == []


class TestByReaction:
    def test_filters_reaction(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = _fake_archive(tmp_path)
        rc = archive_search.main(["--archive-root", str(root), "by-reaction", "rx-2"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 1
        assert payload[0]["segment_id"] == "segment00001"


class TestByTimerange:
    def test_overlapping_window(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = _fake_archive(tmp_path)
        rc = archive_search.main(
            [
                "--archive-root",
                str(root),
                "by-timerange",
                "2026-04-14T12:00:00Z",
                "2026-04-14T12:00:10Z",
            ]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        # segments 1 + 2 overlap; 3 + 4 don't
        seg_ids = {item["segment_id"] for item in payload}
        assert seg_ids == {"segment00001", "segment00002"}

    def test_end_before_start(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = _fake_archive(tmp_path)
        rc = archive_search.main(
            [
                "--archive-root",
                str(root),
                "by-timerange",
                "2026-04-14T13:00:00Z",
                "2026-04-14T12:00:00Z",
            ]
        )
        assert rc == 2


class TestExtract:
    def test_extract_copies_segment_and_sidecar(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _fake_archive(tmp_path)
        out_dir = tmp_path / "extracted"
        rc = archive_search.main(
            ["--archive-root", str(root), "extract", "segment00001", str(out_dir)]
        )
        assert rc == 0
        assert (out_dir / "segment00001.ts").exists()
        assert (out_dir / "segment00001.ts.json").exists()

    def test_extract_unknown_segment(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _fake_archive(tmp_path)
        out_dir = tmp_path / "extracted"
        rc = archive_search.main(
            ["--archive-root", str(root), "extract", "segment99999", str(out_dir)]
        )
        assert rc == 1


class TestTableFormat:
    def test_table_output_runs(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = _fake_archive(tmp_path)
        rc = archive_search.main(
            ["--archive-root", str(root), "--format", "table", "by-condition", "cond-a"]
        )
        assert rc == 0
        output = capsys.readouterr().out
        assert "SEGMENT" in output
        assert "segment00001" in output

    def test_empty_table_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = tmp_path / "empty-archive"
        root.mkdir()
        rc = archive_search.main(
            ["--archive-root", str(root), "--format", "table", "by-condition", "cond-a"]
        )
        assert rc == 0
        assert "(no results)" in capsys.readouterr().out
