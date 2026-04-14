"""Tests for shared/stream_archive.py — the LRR Phase 2 sidecar schema."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.stream_archive import (
    SIDECAR_SCHEMA_VERSION,
    SegmentSidecar,
    archive_root,
    atomic_write_json,
    audio_archive_dir,
    hls_archive_dir,
    sidecar_path_for,
)


class TestSegmentSidecarConstruction:
    def test_basic_new(self) -> None:
        start = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        end = start + timedelta(seconds=4)
        sidecar = SegmentSidecar.new(
            segment_id="segment00042",
            segment_path="/tmp/segment00042.ts",
            condition_id="cond-phase-a-baseline-qwen-001",
            segment_start_ts=start,
            segment_end_ts=end,
        )
        assert sidecar.schema_version == SIDECAR_SCHEMA_VERSION
        assert sidecar.segment_id == "segment00042"
        assert sidecar.segment_path == "/tmp/segment00042.ts"
        assert sidecar.condition_id == "cond-phase-a-baseline-qwen-001"
        assert sidecar.duration_seconds == 4.0
        assert sidecar.archive_kind == "hls"
        assert sidecar.reaction_ids == []
        assert sidecar.stimmung_snapshot == {}
        assert sidecar.segment_start_ts.endswith("Z")
        assert sidecar.segment_end_ts.endswith("Z")

    def test_end_before_start_rejected(self) -> None:
        start = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        end = start - timedelta(seconds=1)
        with pytest.raises(ValueError, match="precedes"):
            SegmentSidecar.new(
                segment_id="s",
                segment_path="/tmp/s.ts",
                condition_id=None,
                segment_start_ts=start,
                segment_end_ts=end,
            )

    def test_invalid_archive_kind_rejected(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="archive_kind"):
            SegmentSidecar.new(
                segment_id="s",
                segment_path="/tmp/s.ts",
                condition_id=None,
                segment_start_ts=now,
                segment_end_ts=now,
                archive_kind="video_mkv",  # not one of the allowed values
            )

    def test_audio_flac_kind(self) -> None:
        now = datetime.now(UTC)
        sidecar = SegmentSidecar.new(
            segment_id="s",
            segment_path="/tmp/s.flac",
            condition_id="cond-x",
            segment_start_ts=now,
            segment_end_ts=now,
            archive_kind="audio_flac",
        )
        assert sidecar.archive_kind == "audio_flac"

    def test_condition_id_optional(self) -> None:
        now = datetime.now(UTC)
        sidecar = SegmentSidecar.new(
            segment_id="s",
            segment_path="/tmp/s.ts",
            condition_id=None,
            segment_start_ts=now,
            segment_end_ts=now,
        )
        assert sidecar.condition_id is None


class TestSegmentSidecarSerialization:
    def test_round_trip(self) -> None:
        now = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        original = SegmentSidecar.new(
            segment_id="segment00042",
            segment_path="/tmp/segment00042.ts",
            condition_id="cond-phase-a-baseline-qwen-001",
            segment_start_ts=now,
            segment_end_ts=now + timedelta(seconds=4),
            reaction_ids=["rx-001", "rx-002"],
            active_activity="study",
            stimmung_snapshot={"stance": "READY", "dimensions": {"intensity": 0.4}},
            directives_hash="sha256:deadbeef",
        )
        payload = original.to_json()
        parsed = SegmentSidecar.from_dict(json.loads(payload))
        assert parsed == original

    def test_schema_version_rejection(self) -> None:
        bogus = {
            "schema_version": SIDECAR_SCHEMA_VERSION + 1,
            "segment_id": "s",
            "segment_path": "/tmp/s.ts",
            "condition_id": None,
            "segment_start_ts": "2026-04-14T12:00:00Z",
            "segment_end_ts": "2026-04-14T12:00:04Z",
            "duration_seconds": 4.0,
            "reaction_ids": [],
            "active_activity": None,
            "stimmung_snapshot": {},
            "directives_hash": None,
            "archive_kind": "hls",
            "created_at": "2026-04-14T12:00:05Z",
        }
        with pytest.raises(ValueError, match="schema_version"):
            SegmentSidecar.from_dict(bogus)

    def test_missing_schema_version_rejected(self) -> None:
        with pytest.raises(ValueError, match="schema_version"):
            SegmentSidecar.from_dict({"segment_id": "s"})


class TestAtomicWrite:
    def test_atomic_write_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "file.json"
        atomic_write_json(target, '{"hello": "world"}')
        assert target.read_text(encoding="utf-8") == '{"hello": "world"}'

    def test_atomic_write_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "file.json"
        atomic_write_json(target, "first")
        atomic_write_json(target, "second")
        assert target.read_text(encoding="utf-8") == "second"


class TestArchivePaths:
    def test_archive_root_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HAPAX_ARCHIVE_ROOT", raising=False)
        root = archive_root()
        assert root.name == "stream-archive"
        assert root.parent.name == "hapax-state"

    def test_archive_root_env_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        override = tmp_path / "custom-archive"
        monkeypatch.setenv("HAPAX_ARCHIVE_ROOT", str(override))
        assert archive_root() == override

    def test_hls_archive_dir_uses_date(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HAPAX_ARCHIVE_ROOT", str(tmp_path))
        at = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        assert hls_archive_dir(at=at) == tmp_path / "hls" / "2026-04-14"

    def test_audio_archive_dir_uses_date(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HAPAX_ARCHIVE_ROOT", str(tmp_path))
        at = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        assert audio_archive_dir(at=at) == tmp_path / "audio" / "2026-04-14"

    def test_sidecar_path_for(self) -> None:
        segment = Path("/archive/hls/2026-04-14/segment00042.ts")
        assert sidecar_path_for(segment) == Path("/archive/hls/2026-04-14/segment00042.ts.json")
