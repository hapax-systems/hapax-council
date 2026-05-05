"""LRR Phase 2 G4 — archive lifecycle integration test.

Queue #146 / #117 gap G4 (MEDIUM). Phase 2 unit tests cover each module in
isolation; this test exercises the full lifecycle from HLS rotation through
archive search + purge, verifying the three modules interop at their real
interface boundary (filesystem + sidecar schema + condition pointer).

The ten Phase 2 PRs each shipped with their own unit tests, so any regression
that breaks the interop between hls_archive.rotate_pass, archive-search
subcommands, and archive-purge.main — without breaking any single module's
public contract — would slip past the existing test suite. This test closes
that gap.

Covers:
- rotate_pass writes sidecars whose schema matches SegmentSidecar.from_path
- archive-search.cmd_by_condition reads the sidecars the rotator just wrote
- archive-purge.main dry-run enumerates the same set of segments
- the purge audit log is written even for dry-run invocations
- a subsequent cmd_stats reports the rotated segment count correctly
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest  # noqa: TC002 — runtime dep for fixtures

from agents.studio_compositor import hls_archive
from shared.stream_archive import SegmentSidecar, archive_root

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_hyphenated_script(name: str) -> object:
    """Import a hyphenated script (e.g. archive-search.py) as a module.

    Phase 2 CLI scripts live in ``scripts/`` with hyphenated filenames that
    Python cannot import directly. Other Phase 2 tests use the same pattern.
    """
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name.replace("-", "_")] = mod
    spec.loader.exec_module(mod)
    return mod


archive_search = _load_hyphenated_script("archive-search")
archive_purge = _load_hyphenated_script("archive-purge")


def _make_ts_segment(path: Path, *, size: int = 2048, age_seconds: float = 30.0) -> None:
    """Create a fake .ts segment with a backdated mtime so is_segment_stable passes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"X" * size)
    if age_seconds > 0:
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))


class TestArchiveLifecycle:
    """End-to-end: rotate → search → purge → audit."""

    def test_full_lifecycle_with_cross_module_handoff(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("HAPAX_ARCHIVE_ROOT", str(tmp_path / "archive"))
        monkeypatch.setattr(hls_archive, "_query_camera_salience_for_archive", lambda: None)

        source_dir = tmp_path / "hls-source"
        source_dir.mkdir()
        for i in range(1, 4):
            _make_ts_segment(source_dir / f"segment{i:05d}.ts")

        condition_pointer = tmp_path / "current.txt"
        condition_pointer.write_text("cond-integration-001")

        stimmung_path = tmp_path / "stimmung-missing.json"

        now_ts = time.time()
        result = hls_archive.rotate_pass(
            source_dir=source_dir,
            now_ts=now_ts,
            condition_pointer=condition_pointer,
            stimmung_path=stimmung_path,
        )

        assert result.scanned == 3
        assert result.rotated == 3
        assert result.skipped_unstable == 0
        assert result.skipped_already_rotated == 0
        assert result.errors == []

        target_date = datetime.fromtimestamp(now_ts, tz=UTC).strftime("%Y-%m-%d")
        archive_dir = archive_root() / "hls" / target_date
        archived_segments = sorted(archive_dir.glob("segment*.ts"))
        archived_sidecars = sorted(archive_dir.glob("segment*.ts.json"))
        assert len(archived_segments) == 3
        assert len(archived_sidecars) == 3

        for sidecar_path in archived_sidecars:
            sidecar = SegmentSidecar.from_path(sidecar_path)
            assert sidecar.condition_id == "cond-integration-001"
            assert sidecar.archive_kind == "hls"
            assert sidecar.stimmung_snapshot == {}

        rc = archive_search.main(
            [
                "--format",
                "json",
                "--archive-root",
                str(archive_root()),
                "by-condition",
                "cond-integration-001",
            ]
        )
        assert rc == 0
        search_out = capsys.readouterr().out
        search_results = json.loads(search_out)
        assert len(search_results) == 3
        assert {r["segment_id"] for r in search_results} == {
            "segment00001",
            "segment00002",
            "segment00003",
        }

        unrelated_pointer = tmp_path / "unrelated-active.txt"
        unrelated_pointer.write_text("cond-unrelated-001")
        rc = archive_purge.main(
            [
                "--condition",
                "cond-integration-001",
                "--archive-root",
                str(archive_root()),
                "--active-condition-pointer",
                str(unrelated_pointer),
            ]
        )
        assert rc == 0
        purge_out = capsys.readouterr().out
        assert '"mode": "dry_run"' in purge_out
        assert '"segments_affected": 3' in purge_out
        assert all(seg.exists() for seg in archived_segments), (
            "dry-run must not delete any segments"
        )

        audit_log = archive_root() / "purge.log"
        assert audit_log.exists(), "dry-run must still write an audit entry"
        audit_entries = [json.loads(line) for line in audit_log.read_text().strip().splitlines()]
        assert len(audit_entries) == 1
        assert audit_entries[0]["condition_id"] == "cond-integration-001"
        assert audit_entries[0]["mode"] == "dry_run"
        assert audit_entries[0]["segments_affected"] == 3

        rc = archive_search.main(
            [
                "--format",
                "json",
                "--archive-root",
                str(archive_root()),
                "stats",
            ]
        )
        assert rc == 0
        stats_out = capsys.readouterr().out
        stats = json.loads(stats_out)
        assert stats["total_segments"] == 3
        assert stats["by_condition"]["cond-integration-001"] == 3

    def test_lifecycle_honors_target_duration_for_sidecar_window(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HAPAX_ARCHIVE_ROOT", str(tmp_path / "archive"))
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        seg_path = source_dir / "segment00001.ts"
        _make_ts_segment(seg_path, age_seconds=30.0)
        seg_mtime = seg_path.stat().st_mtime

        pointer = tmp_path / "cond.txt"
        pointer.write_text("cond-duration-test")

        result = hls_archive.rotate_pass(
            source_dir=source_dir,
            now_ts=time.time(),
            condition_pointer=pointer,
            stimmung_path=tmp_path / "absent.json",
            target_duration_seconds=6.0,
        )
        assert result.rotated == 1

        target_date = datetime.fromtimestamp(seg_mtime, tz=UTC).strftime("%Y-%m-%d")
        archive_dir = archive_root() / "hls" / target_date
        sidecar = SegmentSidecar.from_path(next(archive_dir.glob("*.ts.json")))

        assert sidecar.duration_seconds == 6.0
        end = datetime.fromisoformat(sidecar.segment_end_ts.replace("Z", "+00:00"))
        start = datetime.fromisoformat(sidecar.segment_start_ts.replace("Z", "+00:00"))
        assert (end - start).total_seconds() == 6.0
        assert abs(end.timestamp() - seg_mtime) < 0.01
