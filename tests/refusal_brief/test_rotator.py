"""Tests for ``agents.refusal_brief.rotator``."""

from __future__ import annotations

import gzip
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from agents.refusal_brief.rotator import rotate
from agents.refusal_brief.writer import RefusalEvent, append


def _now() -> datetime:
    return datetime.now(UTC)


def _seed(log_path: Path, n: int = 3) -> None:
    for i in range(n):
        append(
            RefusalEvent(timestamp=_now(), axiom="x", surface=f"s{i}", reason=f"r{i}"),
            log_path=log_path,
        )


def _read_archive(archive: Path) -> list[dict]:
    with gzip.open(archive, "rb") as f:
        return [json.loads(line) for line in f.read().decode().splitlines() if line]


# ── happy path ─────────────────────────────────────────────────────


class TestRotate:
    def test_noop_when_log_absent(self, tmp_path: Path):
        outcome = rotate(
            log_path=tmp_path / "missing.jsonl",
            archive_dir=tmp_path / "arch",
        )
        assert outcome == "noop"

    def test_noop_when_log_empty(self, tmp_path: Path):
        log = tmp_path / "log.jsonl"
        log.touch()
        outcome = rotate(log_path=log, archive_dir=tmp_path / "arch")
        assert outcome == "noop"
        assert log.exists()

    def test_ok_archives_and_clears_log(self, tmp_path: Path):
        log = tmp_path / "log.jsonl"
        archive = tmp_path / "arch"
        _seed(log, 3)
        outcome = rotate(
            log_path=log,
            archive_dir=archive,
            now=datetime(2026, 4, 25, tzinfo=UTC),
        )
        assert outcome == "ok"
        # Log is renamed away → original path absent (writers re-open on next append).
        assert not log.exists()
        # Archive carries all 3 events under today's date.
        records = _read_archive(archive / "2026-04-25.jsonl.gz")
        assert len(records) == 3
        assert {r["surface"] for r in records} == {"s0", "s1", "s2"}

    def test_creates_archive_dir(self, tmp_path: Path):
        log = tmp_path / "log.jsonl"
        archive = tmp_path / "deep" / "nested" / "arch"
        _seed(log, 1)
        outcome = rotate(
            log_path=log,
            archive_dir=archive,
            now=datetime(2026, 4, 25, tzinfo=UTC),
        )
        assert outcome == "ok"
        assert (archive / "2026-04-25.jsonl.gz").exists()


# ── multi-rotation same day ────────────────────────────────────────


class TestSameDayConcatenation:
    def test_two_rotations_concat_into_single_archive(self, tmp_path: Path):
        log = tmp_path / "log.jsonl"
        archive = tmp_path / "arch"
        today = datetime(2026, 4, 25, tzinfo=UTC)

        _seed(log, 2)
        assert rotate(log_path=log, archive_dir=archive, now=today) == "ok"
        # Writers continue → new log appears.
        _seed(log, 3)
        assert rotate(log_path=log, archive_dir=archive, now=today) == "ok"

        # gzip transparently concatenates members → all 5 records readable.
        records = _read_archive(archive / "2026-04-25.jsonl.gz")
        assert len(records) == 5


# ── concurrent writers ─────────────────────────────────────────────


class TestRotateUnderConcurrentWrites:
    def test_writers_continue_after_rotate(self, tmp_path: Path):
        """Writes that complete before rename land in archive; writes
        that start after rename land in the new log file. No write is
        lost (POSIX rename + open-on-append semantics)."""
        log = tmp_path / "log.jsonl"
        archive = tmp_path / "arch"
        today = datetime(2026, 4, 25, tzinfo=UTC)

        # Pre-seed so the rotate doesn't no-op.
        _seed(log, 5)

        post_rotate_writes = 10
        write_done = threading.Event()

        def burst():
            for i in range(post_rotate_writes):
                append(
                    RefusalEvent(
                        timestamp=_now(),
                        axiom="x",
                        surface=f"post-{i}",
                        reason="r",
                    ),
                    log_path=log,
                )
            write_done.set()

        t = threading.Thread(target=burst)
        t.start()
        outcome = rotate(log_path=log, archive_dir=archive, now=today)
        t.join()
        write_done.wait(timeout=5)

        assert outcome == "ok"

        # Tally: pre-rotate seeds + any writes that landed before rename = archive count.
        # Post-rotate writes = new log.jsonl count. Total must equal 5 + 10 = 15.
        archived = _read_archive(archive / "2026-04-25.jsonl.gz")
        new_log_lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        assert len(archived) + len(new_log_lines) == 5 + post_rotate_writes
