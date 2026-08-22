"""Tests for ``agents.payment_processors.event_log``."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path

from agents.operator_awareness.state import PaymentEvent
from agents.payment_processors import event_log as event_log_mod
from agents.payment_processors.event_log import append_event, read_payment_events, tail_events


def _now() -> datetime:
    return datetime.now(UTC)


def _make(rail: str = "lightning", *, ext: str = "abc", sats: int | None = 100) -> PaymentEvent:
    return PaymentEvent(
        timestamp=_now(),
        rail=rail,  # type: ignore[arg-type]
        amount_sats=sats,
        sender_excerpt="hi",
        external_id=ext,
    )


def _hold_path(path: Path) -> Path:
    return event_log_mod._event_log_hold_path(path)


def _track_target_fds(monkeypatch, target_path: Path) -> set[int]:
    """Record every fd ``event_log`` opens for ``target_path`` so injected os
    failures can be scoped to the target line fd and never touch the WAL marker or
    lock fds."""

    target_fds: set[int] = set()
    real_open = event_log_mod.os.open

    def tracking_open(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        try:
            same = event_log_mod.os.fspath(path) == event_log_mod.os.fspath(target_path)
        except TypeError:
            same = False
        if same:
            target_fds.add(fd)
        return fd

    monkeypatch.setattr(event_log_mod.os, "open", tracking_open)
    return target_fds


def _fail_ftruncate(*_args) -> None:
    raise OSError("injected ftruncate failure")


def _child_append_event(log_path: str, external_id: str) -> None:
    event = PaymentEvent(
        timestamp=datetime.now(UTC),
        rail="lightning",
        amount_sats=1,
        sender_excerpt="",
        external_id=external_id,
    )
    if not append_event(event, log_path=Path(log_path)):
        raise SystemExit(1)


class TestAppendEvent:
    def test_writes_one_line_per_event(self, tmp_path):
        path = tmp_path / "events.jsonl"
        assert append_event(_make(ext="x1"), log_path=path)
        assert append_event(_make(ext="x2"), log_path=path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_creates_parent_dir(self, tmp_path):
        path = tmp_path / "deep" / "events.jsonl"
        assert append_event(_make(ext="x1"), log_path=path)
        assert path.exists()


class TestTailEvents:
    def test_missing_file_returns_empty(self, tmp_path):
        assert tail_events(log_path=tmp_path / "absent.jsonl") == []

    def test_returns_events_in_order(self, tmp_path):
        path = tmp_path / "events.jsonl"
        for i in range(3):
            append_event(_make(ext=f"x{i}"), log_path=path)
        events = tail_events(log_path=path)
        assert [e.external_id for e in events] == ["x0", "x1", "x2"]

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make(ext="x1"), log_path=path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("garbage line not json\n")
        append_event(_make(ext="x2"), log_path=path)
        events = tail_events(log_path=path)
        assert [e.external_id for e in events] == ["x1", "x2"]

    def test_respects_limit(self, tmp_path):
        path = tmp_path / "events.jsonl"
        for i in range(5):
            append_event(_make(ext=f"x{i}"), log_path=path)
        events = tail_events(log_path=path, limit=2)
        assert [e.external_id for e in events] == ["x3", "x4"]


def _write_valid_marker(path: Path, start_offset: int, digest: str = "a" * 64) -> Path:
    hold = _hold_path(path)
    header = json.dumps(
        {
            "marker_version": 1,
            "target": str(path),
            "start_offset": start_offset,
            "line_sha256": digest,
        }
    )
    hold.write_bytes((header + "\n").encode("utf-8"))
    return hold


class TestAppendEventFailClosed:
    def test_partial_write_then_oserror_rolls_back_and_retry_appends_once(
        self, tmp_path, monkeypatch, caplog
    ):
        path = tmp_path / "events.jsonl"
        assert append_event(_make(ext="E0"), log_path=path)
        preimage = path.read_bytes()
        target_fds = _track_target_fds(monkeypatch, path)
        real_write = event_log_mod.os.write
        calls = {"n": 0}

        def flaky_write(fd, data):
            if fd in target_fds:
                calls["n"] += 1
                if calls["n"] == 1:
                    return real_write(fd, memoryview(data)[:8])
                raise OSError("injected line write failure")
            return real_write(fd, data)

        monkeypatch.setattr(event_log_mod.os, "write", flaky_write)
        with caplog.at_level(logging.WARNING, logger=event_log_mod.__name__):
            assert append_event(_make(ext="E1"), log_path=path) is False
        assert path.read_bytes() == preimage  # byte-identical rollback
        assert not _hold_path(path).exists()  # marker removed on clean rollback
        assert str(path) in caplog.text
        assert "next action" in caplog.text

        monkeypatch.setattr(event_log_mod.os, "write", real_write)
        assert append_event(_make(ext="E1"), log_path=path) is True
        ids = [e.external_id for e in tail_events(log_path=path)]
        assert ids == ["E0", "E1"]
        assert ids.count("E1") == 1  # exactly one parsed event, no torn duplicate

    def test_short_writes_loop_to_completion(self, tmp_path, monkeypatch):
        path = tmp_path / "events.jsonl"
        target_fds = _track_target_fds(monkeypatch, path)
        real_write = event_log_mod.os.write
        writes: list[int] = []

        def short_write(fd, data):
            if fd in target_fds:
                view = memoryview(data)
                chunk = view[: min(17, len(view))]
                writes.append(len(chunk))
                return real_write(fd, chunk)
            return real_write(fd, data)

        monkeypatch.setattr(event_log_mod.os, "write", short_write)
        assert append_event(_make(ext="S1"), log_path=path) is True
        assert len(writes) > 1
        assert [e.external_id for e in tail_events(log_path=path)] == ["S1"]
        assert not _hold_path(path).exists()

    def test_fsync_failure_rolls_back_byte_identical(self, tmp_path, monkeypatch):
        path = tmp_path / "events.jsonl"
        assert append_event(_make(ext="C0"), log_path=path)
        preimage = path.read_bytes()
        target_fds = _track_target_fds(monkeypatch, path)
        real_fsync = event_log_mod.os.fsync
        fsyncs = {"n": 0}

        def flaky_fsync(fd):
            if fd in target_fds:
                fsyncs["n"] += 1
                if fsyncs["n"] == 1:
                    raise OSError("injected line fsync failure")
            return real_fsync(fd)

        monkeypatch.setattr(event_log_mod.os, "fsync", flaky_fsync)
        assert append_event(_make(ext="C1"), log_path=path) is False
        assert path.read_bytes() == preimage
        assert not _hold_path(path).exists()

    def test_full_line_fsync_and_rollback_failure_holds_and_reader_excludes(
        self, tmp_path, monkeypatch, caplog
    ):
        path = tmp_path / "events.jsonl"
        assert append_event(_make(ext="H0"), log_path=path)
        target_fds = _track_target_fds(monkeypatch, path)
        real_fsync = event_log_mod.os.fsync
        fsyncs = {"n": 0}

        def flaky_fsync(fd):
            if fd in target_fds:
                fsyncs["n"] += 1
                if fsyncs["n"] == 1:
                    raise OSError("injected line fsync failure")
            return real_fsync(fd)

        monkeypatch.setattr(event_log_mod.os, "fsync", flaky_fsync)
        monkeypatch.setattr(event_log_mod.os, "ftruncate", _fail_ftruncate)
        with caplog.at_level(logging.ERROR, logger=event_log_mod.__name__):
            assert append_event(_make(ext="H1"), log_path=path) is False
        raw = path.read_bytes()
        assert raw.endswith(b"\n")  # full H1 line landed and ends in a newline
        assert _hold_path(path).exists()  # HOLD retained despite the newline tail
        assert "rollback failed" in caplog.text
        # Reader coordination: the ambiguous H1 suffix is excluded via the marker
        # prefix while the earlier confirmed H0 remains.
        assert [e.external_id for e in tail_events(log_path=path)] == ["H0"]
        monkeypatch.setattr(event_log_mod.os, "fsync", real_fsync)
        assert append_event(_make(ext="H2"), log_path=path) is False  # HELD by marker
        assert path.read_bytes() == raw
        assert "HELD by pre-append WAL marker" in caplog.text
        # After reconciliation (marker removed), reading returns to normal.
        _hold_path(path).unlink()
        assert [e.external_id for e in tail_events(log_path=path)] == ["H0", "H1"]

    def test_partial_write_and_rollback_failure_holds_torn_suffix(
        self, tmp_path, monkeypatch, caplog
    ):
        path = tmp_path / "events.jsonl"
        assert append_event(_make(ext="D0"), log_path=path)
        target_fds = _track_target_fds(monkeypatch, path)
        real_write = event_log_mod.os.write
        calls = {"n": 0}

        def flaky_write(fd, data):
            if fd in target_fds:
                calls["n"] += 1
                if calls["n"] == 1:
                    return real_write(fd, memoryview(data)[:6])
                raise OSError("injected line write failure")
            return real_write(fd, data)

        monkeypatch.setattr(event_log_mod.os, "write", flaky_write)
        monkeypatch.setattr(event_log_mod.os, "ftruncate", _fail_ftruncate)
        with caplog.at_level(logging.ERROR, logger=event_log_mod.__name__):
            assert append_event(_make(ext="D1"), log_path=path) is False
        raw_after = path.read_bytes()
        assert not raw_after.endswith(b"\n")  # torn suffix
        assert _hold_path(path).exists()
        monkeypatch.setattr(event_log_mod.os, "write", real_write)
        assert append_event(_make(ext="D2"), log_path=path) is False
        assert path.read_bytes() == raw_after  # unchanged, no concatenation
        assert "HELD by pre-append WAL marker" in caplog.text
        assert [e.external_id for e in tail_events(log_path=path)] == ["D0"]

    def test_size_mismatch_holds_without_truncation(self, tmp_path, monkeypatch, caplog):
        path = tmp_path / "events.jsonl"
        assert append_event(_make(ext="Z0"), log_path=path)
        size_before = path.stat().st_size
        target_fds = _track_target_fds(monkeypatch, path)
        real_write = event_log_mod.os.write
        done = {"x": False}

        def foreign_write(fd, data):
            if fd in target_fds and not done["x"]:
                done["x"] = True
                n = real_write(fd, data)
                real_write(fd, b"X")  # simulate a foreign extra byte under the lock
                return n
            return real_write(fd, data)

        monkeypatch.setattr(event_log_mod.os, "write", foreign_write)
        with caplog.at_level(logging.ERROR, logger=event_log_mod.__name__):
            assert append_event(_make(ext="Z1"), log_path=path) is False
        assert path.stat().st_size > size_before  # NOT truncated
        assert _hold_path(path).exists()
        assert "NOT truncating" in caplog.text
        monkeypatch.setattr(event_log_mod.os, "write", real_write)
        assert append_event(_make(ext="Z2"), log_path=path) is False  # HELD

    def test_metric_failure_after_commit_still_returns_true(self, tmp_path, monkeypatch, caplog):
        path = tmp_path / "events.jsonl"

        class _BoomCounter:
            def labels(self, **_kw):
                raise RuntimeError("injected metric failure")

        monkeypatch.setattr(event_log_mod, "payment_events_appended_total", _BoomCounter())
        with caplog.at_level(logging.WARNING, logger=event_log_mod.__name__):
            assert append_event(_make(ext="MET1"), log_path=path) is True
        assert [e.external_id for e in tail_events(log_path=path)] == ["MET1"]
        assert "metric" in caplog.text

    def test_post_commit_marker_cleanup_failure_returns_true_and_next_holds(
        self, tmp_path, monkeypatch, caplog
    ):
        path = tmp_path / "events.jsonl"
        real_remove = event_log_mod._remove_event_log_marker
        calls = {"n": 0}

        def flaky_remove(hold_path):
            calls["n"] += 1
            if calls["n"] == 1:
                return False  # simulate cleanup failure after commit
            return real_remove(hold_path)

        monkeypatch.setattr(event_log_mod, "_remove_event_log_marker", flaky_remove)
        with caplog.at_level(logging.ERROR, logger=event_log_mod.__name__):
            assert append_event(_make(ext="PC1"), log_path=path) is True  # committed
        assert _hold_path(path).exists()  # marker retained
        assert "cleanup is" in caplog.text
        # Reader HOLDs on the retained marker (start_offset 0 excludes everything).
        assert tail_events(log_path=path) == []
        assert append_event(_make(ext="PC2"), log_path=path) is False  # next append HOLDs
        _hold_path(path).unlink()  # reconcile
        assert [e.external_id for e in tail_events(log_path=path)] == ["PC1"]


class TestAppendEventNeverRaises:
    def test_serialisation_failure_returns_false(self, tmp_path):
        path = tmp_path / "events.jsonl"

        class _BoomEvent:
            rail = "lightning"

            def model_dump_json(self):
                raise RuntimeError("boom serialise")

        assert append_event(_BoomEvent(), log_path=path) is False
        assert not path.exists()
        assert not _hold_path(path).exists()

    def test_mkdir_failure_returns_false(self, tmp_path):
        afile = tmp_path / "afile"
        afile.write_text("x")
        path = afile / "events.jsonl"  # parent is a regular file
        assert append_event(_make(ext="M1"), log_path=path) is False

    def test_lock_open_failure_returns_false(self, tmp_path, monkeypatch):
        path = tmp_path / "events.jsonl"
        real_open = event_log_mod.os.open

        def flaky_open(p, *a, **k):
            if str(p).endswith(".lock"):
                raise OSError("injected lock open failure")
            return real_open(p, *a, **k)

        monkeypatch.setattr(event_log_mod.os, "open", flaky_open)
        assert append_event(_make(ext="L1"), log_path=path) is False
        assert not path.exists()

    def test_flock_acquire_failure_returns_false(self, tmp_path, monkeypatch):
        path = tmp_path / "events.jsonl"
        real_flock = event_log_mod.fcntl.flock

        def flaky_flock(fd, op):
            if op == event_log_mod.fcntl.LOCK_EX:
                raise OSError("injected flock failure")
            return real_flock(fd, op)

        monkeypatch.setattr(event_log_mod.fcntl, "flock", flaky_flock)
        assert append_event(_make(ext="F1"), log_path=path) is False
        assert not path.exists()
        assert not _hold_path(path).exists()

    def test_marker_stat_failure_returns_false(self, tmp_path, monkeypatch):
        path = tmp_path / "events.jsonl"
        hold = _hold_path(path)
        real_stat = event_log_mod.os.stat

        def flaky_stat(p, *a, **k):
            if str(p) == str(hold):
                raise OSError("injected marker stat failure")
            return real_stat(p, *a, **k)

        monkeypatch.setattr(event_log_mod.os, "stat", flaky_stat)
        assert append_event(_make(ext="ST1"), log_path=path) is False
        assert not path.exists()

    def test_tail_inspect_failure_returns_false(self, tmp_path, monkeypatch):
        path = tmp_path / "events.jsonl"
        assert append_event(_make(ext="T0"), log_path=path)
        preimage = path.read_bytes()
        target_fds = _track_target_fds(monkeypatch, path)
        real_pread = event_log_mod.os.pread

        def flaky_pread(fd, n, off):
            if fd in target_fds:
                raise OSError("injected pread failure")
            return real_pread(fd, n, off)

        monkeypatch.setattr(event_log_mod.os, "pread", flaky_pread)
        assert append_event(_make(ext="T1"), log_path=path) is False
        assert path.read_bytes() == preimage
        assert not _hold_path(path).exists()  # refused before marker creation

    def test_non_regular_target_refused(self, tmp_path):
        path = tmp_path / "events.jsonl"
        os.mkfifo(path)
        assert append_event(_make(ext="FIFO1"), log_path=path) is False

    def test_target_close_failure_after_commit_retains_marker_and_holds(
        self, tmp_path, monkeypatch, caplog
    ):
        path = tmp_path / "events.jsonl"
        target_fds = _track_target_fds(monkeypatch, path)
        real_close = event_log_mod.os.close

        def flaky_close(fd):
            if fd in target_fds:
                target_fds.discard(fd)  # fail the target-fd close exactly once
                raise OSError("injected close failure")
            return real_close(fd)

        monkeypatch.setattr(event_log_mod.os, "close", flaky_close)
        with caplog.at_level(logging.ERROR, logger=event_log_mod.__name__):
            assert append_event(_make(ext="CL1"), log_path=path) is True  # committed
        assert _hold_path(path).exists()  # marker retained (writeback ambiguous)
        assert "close failed" in caplog.text
        monkeypatch.setattr(event_log_mod.os, "close", real_close)
        assert tail_events(log_path=path) == []  # reader HOLDs on the retained marker

    def test_lock_unlock_failure_after_commit_preserves_true(self, tmp_path, monkeypatch, caplog):
        path = tmp_path / "events.jsonl"
        real_flock = event_log_mod.fcntl.flock

        def flaky_flock(fd, op):
            if op == event_log_mod.fcntl.LOCK_UN:
                raise OSError("injected unlock failure")
            return real_flock(fd, op)

        monkeypatch.setattr(event_log_mod.fcntl, "flock", flaky_flock)
        with caplog.at_level(logging.WARNING, logger=event_log_mod.__name__):
            assert append_event(_make(ext="U1"), log_path=path) is True
        assert not _hold_path(path).exists()  # clean commit → marker removed, no HOLD
        assert "lock release failed" in caplog.text
        monkeypatch.setattr(event_log_mod.fcntl, "flock", real_flock)
        assert [e.external_id for e in tail_events(log_path=path)] == ["U1"]


class TestManyProcessesAppend:
    def test_16_processes_append_newline_complete_distinct_ids_once(self, tmp_path):
        path = tmp_path / "events.jsonl"
        ctx = get_context("spawn")
        n = 20
        procs = [
            ctx.Process(target=_child_append_event, args=(str(path), f"P{i}")) for i in range(n)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        for p in procs:
            assert p.exitcode == 0
        raw = path.read_bytes()
        assert raw.endswith(b"\n")  # newline-complete, no torn tail
        ids = sorted(e.external_id for e in tail_events(log_path=path, limit=n))
        assert ids == sorted(f"P{i}" for i in range(n))  # every id exactly once


class TestTailEventsReaderFailClosed:
    def test_reader_excludes_unterminated_final_row(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make(ext="N0"), log_path=path)
        # A COMPLETE valid PaymentEvent JSON but WITHOUT the terminating newline.
        with path.open("ab") as fh:
            fh.write(_make(ext="N1").model_dump_json().encode("utf-8"))
        assert [e.external_id for e in tail_events(log_path=path)] == ["N0"]

    def test_reader_fail_closed_on_malformed_marker(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make(ext="MM0"), log_path=path)
        hold = _hold_path(path)
        hold.write_bytes(b"not-a-json-header\n")
        assert read_payment_events(log_path=path).status == "unreadable"
        assert tail_events(log_path=path) == []
        hold.unlink()
        assert [e.external_id for e in tail_events(log_path=path)] == ["MM0"]

    def test_reader_fail_closed_on_target_mismatch_marker(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make(ext="TM0"), log_path=path)
        hold = _hold_path(path)
        header = json.dumps(
            {
                "marker_version": 1,
                "target": "/some/other/path",
                "start_offset": 0,
                "line_sha256": "a" * 64,
            }
        )
        hold.write_bytes((header + "\n").encode("utf-8"))
        assert read_payment_events(log_path=path).status == "unreadable"

    def test_reader_fail_closed_on_out_of_range_start_offset(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make(ext="OR0"), log_path=path)
        size = path.stat().st_size
        _write_valid_marker(path, size + 100)
        assert read_payment_events(log_path=path).status == "unreadable"

    def test_reader_fail_closed_on_mid_record_start_offset(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make(ext="MR0"), log_path=path)
        size = path.stat().st_size
        # In range but NOT a record boundary: the byte before is mid-JSON, not "\n".
        _write_valid_marker(path, size - 3)
        assert read_payment_events(log_path=path).status == "unreadable"

    def test_reader_forced_short_pread_loops_to_completion(self, tmp_path, monkeypatch):
        path = tmp_path / "events.jsonl"
        for i in range(3):
            append_event(_make(ext=f"SP{i}"), log_path=path)
        target_fds = _track_target_fds(monkeypatch, path)
        real_pread = event_log_mod.os.pread

        def short_pread(fd, n, off):
            if fd in target_fds and n > 4:
                return real_pread(fd, 4, off)  # force short reads
            return real_pread(fd, n, off)

        monkeypatch.setattr(event_log_mod.os, "pread", short_pread)
        assert [e.external_id for e in tail_events(log_path=path)] == ["SP0", "SP1", "SP2"]

    def test_read_payment_events_status_ok_held_and_missing(self, tmp_path):
        path = tmp_path / "events.jsonl"
        # missing file -> ok, empty (a legitimate zero)
        missing = read_payment_events(log_path=path)
        assert missing.status == "ok" and missing.events == ()
        # normal content -> ok
        append_event(_make(ext="OK0"), log_path=path)
        ok = read_payment_events(log_path=path)
        assert ok.status == "ok"
        assert [e.external_id for e in ok.events] == ["OK0"]
        # a valid marker (append in-flight) -> held
        _write_valid_marker(path, 0)
        held = read_payment_events(log_path=path)
        assert held.status == "held"
        assert held.events == ()  # start_offset 0 → confirmed prefix is empty
