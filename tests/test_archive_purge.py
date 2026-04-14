"""Tests for scripts/archive-purge.py — LRR Phase 2 item 9."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest  # noqa: TC002 — runtime dep for fixtures

from shared.stream_archive import SegmentSidecar, atomic_write_json, sidecar_path_for

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "archive-purge.py"

_spec = importlib.util.spec_from_file_location("archive_purge", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
archive_purge = importlib.util.module_from_spec(_spec)
sys.modules["archive_purge"] = archive_purge
_spec.loader.exec_module(archive_purge)


def _seed_archive(tmp_path: Path) -> tuple[Path, list[Path], list[Path]]:
    """Seed an archive with 2 cond-a segments + 1 cond-b segment.

    Returns (root, cond_a_segment_paths, cond_a_sidecar_paths).
    """
    root = tmp_path / "archive"
    hls_dir = root / "hls" / "2026-04-14"
    hls_dir.mkdir(parents=True)

    base = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
    cond_a_segments: list[Path] = []
    cond_a_sidecars: list[Path] = []
    specs = [
        ("segment00001", "cond-a"),
        ("segment00002", "cond-a"),
        ("segment00003", "cond-b"),
    ]
    for i, (seg_id, cond_id) in enumerate(specs):
        seg_path = hls_dir / f"{seg_id}.ts"
        seg_path.write_bytes(b"X" * 1024)
        sidecar = SegmentSidecar.new(
            segment_id=seg_id,
            segment_path=seg_path,
            condition_id=cond_id,
            segment_start_ts=base + timedelta(seconds=4 * i),
            segment_end_ts=base + timedelta(seconds=4 * (i + 1)),
        )
        sidecar_p = sidecar_path_for(seg_path)
        atomic_write_json(sidecar_p, sidecar.to_json())
        if cond_id == "cond-a":
            cond_a_segments.append(seg_path)
            cond_a_sidecars.append(sidecar_p)
    return root, cond_a_segments, cond_a_sidecars


class TestDryRunDefault:
    def test_dry_run_does_not_delete(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, segs, sidecars = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        assert rc == 0
        # No files deleted
        for p in segs + sidecars:
            assert p.exists(), f"{p} should still exist in dry-run mode"

        stdout = capsys.readouterr().out
        assert '"mode": "dry_run"' in stdout
        assert '"segments_affected": 2' in stdout

    def test_dry_run_still_writes_audit_log(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, _, _ = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        log = (root / "purge.log").read_text(encoding="utf-8").strip().splitlines()
        assert len(log) == 1
        entry = json.loads(log[0])
        assert entry["mode"] == "dry_run"
        assert entry["condition_id"] == "cond-a"
        assert entry["segments_affected"] == 2


class TestConfirmDelete:
    def test_confirm_deletes(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root, segs, sidecars = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        assert rc == 0
        for p in segs + sidecars:
            assert not p.exists(), f"{p} should be deleted"

        # cond-b segment should still exist
        cond_b_segments = list((root / "hls" / "2026-04-14").glob("segment00003*"))
        assert len(cond_b_segments) == 2  # segment + sidecar

    def test_confirmed_run_writes_audit_entry(self, tmp_path: Path) -> None:
        root, _, _ = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-inactive")

        archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--reason",
                "consent revocation",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        log = (root / "purge.log").read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(log[-1])
        assert entry["mode"] == "confirmed"
        assert entry["reason"] == "consent revocation"


class TestActiveConditionGuard:
    def test_refuses_to_purge_active(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, segs, sidecars = _seed_archive(tmp_path)
        pointer = tmp_path / "current.txt"
        pointer.write_text("cond-a")  # active

        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(pointer),
            ]
        )
        assert rc == 2
        for p in segs + sidecars:
            assert p.exists(), f"{p} must NOT be deleted when condition is active"

    def test_allows_purge_when_pointer_absent(self, tmp_path: Path) -> None:
        root, segs, _ = _seed_archive(tmp_path)
        rc = archive_purge.main(
            [
                "--condition",
                "cond-a",
                "--confirm",
                "--archive-root",
                str(root),
                "--active-condition-pointer",
                str(tmp_path / "no-pointer.txt"),
            ]
        )
        assert rc == 0
        for p in segs:
            assert not p.exists()
