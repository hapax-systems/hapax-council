"""Tests for size-based runtime JSONL rotation."""

from __future__ import annotations

import gzip
import os
from datetime import UTC, datetime
from pathlib import Path

from shared.runtime_jsonl_rotator import RotationTarget, rotate_target, rotate_targets


def _target(tmp_path: Path, *, max_bytes: int = 12, keep_archives: int = 2) -> RotationTarget:
    return RotationTarget(
        name="sample",
        path=tmp_path / "live" / "sample.jsonl",
        max_bytes=max_bytes,
        archive_dir=tmp_path / "archive",
        keep_archives=keep_archives,
    )


def _read_gzip(path: Path) -> str:
    with gzip.open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def test_noop_when_file_is_under_cap(tmp_path: Path) -> None:
    target = _target(tmp_path, max_bytes=100)
    target.path.parent.mkdir(parents=True)
    target.path.write_text('{"ok": true}\n', encoding="utf-8")

    result = rotate_target(target, now=datetime(2026, 6, 11, tzinfo=UTC))

    assert result.status == "noop_under_cap"
    assert target.path.read_text(encoding="utf-8") == '{"ok": true}\n'
    assert not target.archive_dir.exists()


def test_rotates_over_cap_to_gzip_archive_and_fresh_live_file(tmp_path: Path) -> None:
    target = _target(tmp_path, max_bytes=10)
    target.path.parent.mkdir(parents=True)
    target.path.write_text('{"n": 1}\n{"n": 2}\n', encoding="utf-8")

    result = rotate_target(target, now=datetime(2026, 6, 11, tzinfo=UTC))

    assert result.status == "rotated"
    assert result.size_before > target.max_bytes
    assert target.path.exists()
    assert target.path.read_text(encoding="utf-8") == ""
    archive = target.archive_dir / "sample.2026-06-11.jsonl.gz"
    assert result.archive_path == str(archive)
    assert _read_gzip(archive) == '{"n": 1}\n{"n": 2}\n'


def test_same_day_rotations_append_to_one_gzip_archive(tmp_path: Path) -> None:
    target = _target(tmp_path, max_bytes=1)
    now = datetime(2026, 6, 11, tzinfo=UTC)
    target.path.parent.mkdir(parents=True)

    target.path.write_text("first\n", encoding="utf-8")
    assert rotate_target(target, now=now).status == "rotated"
    target.path.write_text("second\n", encoding="utf-8")
    assert rotate_target(target, now=now).status == "rotated"

    assert _read_gzip(target.archive_dir / "sample.2026-06-11.jsonl.gz") == "first\nsecond\n"


def test_recovers_stale_rotating_slice_before_noop(tmp_path: Path) -> None:
    target = _target(tmp_path, max_bytes=100)
    target.path.parent.mkdir(parents=True)
    target.path.write_text("live\n", encoding="utf-8")
    stale = target.path.with_name("sample.jsonl.20260611T010203Z.123.rotating")
    stale.write_text("stale\n", encoding="utf-8")

    result = rotate_target(target, now=datetime(2026, 6, 11, tzinfo=UTC))

    assert result.status == "noop_under_cap"
    assert result.recovered_slices == 1
    assert not stale.exists()
    assert _read_gzip(target.archive_dir / "sample.2026-06-11.jsonl.gz") == "stale\n"


def test_prunes_old_archives_by_generation_count(tmp_path: Path) -> None:
    target = _target(tmp_path, max_bytes=100, keep_archives=2)
    target.path.parent.mkdir(parents=True)
    target.path.write_text("live\n", encoding="utf-8")
    target.archive_dir.mkdir()
    old = target.archive_dir / "sample.2026-06-01.jsonl.gz"
    middle = target.archive_dir / "sample.2026-06-02.jsonl.gz"
    new = target.archive_dir / "sample.2026-06-03.jsonl.gz"
    for index, path in enumerate((old, middle, new), start=1):
        path.write_bytes(b"x")
        mtime = 1_800_000_000 + index
        path.touch()
        path.chmod(0o600)
        # pathlib.touch cannot set a specific mtime.
        os.utime(path, (mtime, mtime))

    result = rotate_target(target, now=datetime(2026, 6, 11, tzinfo=UTC))

    assert result.pruned_archives == 1
    assert not old.exists()
    assert middle.exists()
    assert new.exists()


def test_rotate_targets_uses_one_timestamp_for_all_targets(tmp_path: Path) -> None:
    first = RotationTarget(
        name="first",
        path=tmp_path / "first.jsonl",
        max_bytes=1,
        archive_dir=tmp_path / "archive",
    )
    second = RotationTarget(
        name="second",
        path=tmp_path / "second.jsonl",
        max_bytes=1,
        archive_dir=tmp_path / "archive",
    )
    first.path.write_text("aa\n", encoding="utf-8")
    second.path.write_text("bb\n", encoding="utf-8")

    results = rotate_targets((first, second), now=datetime(2026, 6, 11, tzinfo=UTC))

    assert [result.status for result in results] == ["rotated", "rotated"]
    assert (tmp_path / "archive" / "first.2026-06-11.jsonl.gz").exists()
    assert (tmp_path / "archive" / "second.2026-06-11.jsonl.gz").exists()
