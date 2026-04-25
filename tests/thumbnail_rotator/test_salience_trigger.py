"""Tests for ``agents.thumbnail_rotator.salience_trigger``."""

from __future__ import annotations

import json
from pathlib import Path

from agents.thumbnail_rotator.salience_trigger import SalienceTrigger


class _Clock:
    """Mutable monotonic clock for deterministic stability-window tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _write_event(path: Path, *, salience: float | None, ts: float = 0.0) -> None:
    """Append one chronicle event to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {} if salience is None else {"salience": salience}
    line = json.dumps(
        {
            "ts": ts,
            "source": "test",
            "event_type": "test",
            "payload": payload,
        }
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _make_trigger(
    events_path: Path,
    *,
    cursor_path: Path | None = None,
    threshold: float = 0.7,
    stability: float = 120.0,
    clock=None,
) -> SalienceTrigger:
    return SalienceTrigger(
        events_path=events_path,
        cursor_path=cursor_path,
        salience_threshold=threshold,
        stability_window_s=stability,
        clock=clock,
    )


# ── No events ──────────────────────────────────────────────────────


class TestNoEvents:
    def test_missing_file_returns_false(self, tmp_path):
        trigger = _make_trigger(tmp_path / "absent.jsonl")
        assert trigger.should_fire() is False

    def test_empty_file_returns_false(self, tmp_path):
        events = tmp_path / "events.jsonl"
        events.touch()
        trigger = _make_trigger(events)
        assert trigger.should_fire() is False

    def test_low_salience_only_returns_false(self, tmp_path):
        events = tmp_path / "events.jsonl"
        _write_event(events, salience=0.4)
        _write_event(events, salience=0.5)
        trigger = _make_trigger(events)
        assert trigger.should_fire() is False


# ── Threshold + stability gates ────────────────────────────────────


class TestThresholdAndStability:
    def test_high_salience_alone_doesnt_fire_immediately(self, tmp_path):
        """Need stability window to pass before firing."""
        events = tmp_path / "events.jsonl"
        clock = _Clock(0.0)
        trigger = _make_trigger(events, clock=clock)
        _write_event(events, salience=0.8)
        assert trigger.should_fire() is False

    def test_fires_after_stability_window_passes(self, tmp_path):
        events = tmp_path / "events.jsonl"
        clock = _Clock(0.0)
        trigger = _make_trigger(events, clock=clock)
        _write_event(events, salience=0.8)
        # First call observes the high-salience event at t=0.
        trigger.should_fire()
        # Within the stability window — still no fire.
        clock.advance(60.0)
        assert trigger.should_fire() is False
        # Past the window — fires.
        clock.advance(70.0)
        assert trigger.should_fire() is True

    def test_subsequent_high_salience_resets_window(self, tmp_path):
        events = tmp_path / "events.jsonl"
        clock = _Clock(0.0)
        trigger = _make_trigger(events, clock=clock)
        _write_event(events, salience=0.8)
        trigger.should_fire()  # observes at t=0
        clock.advance(100.0)  # 20s before window expires
        _write_event(events, salience=0.85)
        trigger.should_fire()  # observes at t=100, no fire (resets)
        clock.advance(100.0)  # only 100s since the new event
        assert trigger.should_fire() is False
        clock.advance(30.0)  # now 130s since the latest event
        assert trigger.should_fire() is True

    def test_threshold_boundary_inclusive(self, tmp_path):
        """salience == threshold counts as high-salience."""
        events = tmp_path / "events.jsonl"
        clock = _Clock(0.0)
        trigger = _make_trigger(events, clock=clock, threshold=0.7)
        _write_event(events, salience=0.7)
        trigger.should_fire()
        clock.advance(130.0)
        assert trigger.should_fire() is True

    def test_fires_only_once_per_event_then_window(self, tmp_path):
        """After firing, must wait for a new event + a new window before refiring."""
        events = tmp_path / "events.jsonl"
        clock = _Clock(0.0)
        trigger = _make_trigger(events, clock=clock)
        _write_event(events, salience=0.9)
        trigger.should_fire()
        clock.advance(130.0)
        assert trigger.should_fire() is True
        # No new event; even after a long delay, no re-fire.
        clock.advance(500.0)
        assert trigger.should_fire() is False


# ── Malformed input tolerance ──────────────────────────────────────


class TestMalformedInput:
    def test_skips_non_json_lines(self, tmp_path):
        events = tmp_path / "events.jsonl"
        clock = _Clock(0.0)
        # Construct the trigger before any events land — the bootstrap
        # cursor would otherwise seek-to-end and skip the events the
        # test wants to feed it.
        trigger = _make_trigger(events, clock=clock)
        events.parent.mkdir(parents=True, exist_ok=True)
        with events.open("w", encoding="utf-8") as fh:
            fh.write("not json\n")
            fh.write(
                json.dumps(
                    {
                        "ts": 0.0,
                        "source": "test",
                        "event_type": "test",
                        "payload": {"salience": 0.9},
                    }
                )
                + "\n"
            )
        trigger.should_fire()
        clock.advance(130.0)
        assert trigger.should_fire() is True

    def test_missing_payload_field_is_skipped(self, tmp_path):
        events = tmp_path / "events.jsonl"
        trigger = _make_trigger(events)
        events.parent.mkdir(parents=True, exist_ok=True)
        with events.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": 0.0, "source": "test", "event_type": "test"}) + "\n")
        assert trigger.should_fire() is False

    def test_non_numeric_salience_is_skipped(self, tmp_path):
        events = tmp_path / "events.jsonl"
        trigger = _make_trigger(events)
        events.parent.mkdir(parents=True, exist_ok=True)
        with events.open("w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": 0.0,
                        "source": "test",
                        "event_type": "test",
                        "payload": {"salience": "high"},
                    }
                )
                + "\n"
            )
        assert trigger.should_fire() is False


# ── Cursor persistence ────────────────────────────────────────────


class TestCursorPersistence:
    def test_first_run_seeks_to_end_skipping_backlog(self, tmp_path):
        events = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        # Pre-existing backlog of high-salience events; first-run trigger
        # must NOT fire from these (they're stale by the time the daemon
        # boots).
        for _ in range(5):
            _write_event(events, salience=0.9)
        clock = _Clock(0.0)
        trigger = _make_trigger(events, cursor_path=cursor, clock=clock)
        clock.advance(500.0)
        assert trigger.should_fire() is False

    def test_resume_from_persisted_cursor(self, tmp_path):
        events = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        # First daemon: bootstrap cursor at end of empty file.
        clock = _Clock(0.0)
        trigger1 = _make_trigger(events, cursor_path=cursor, clock=clock)
        # Event arrives mid-session; first daemon observes it.
        _write_event(events, salience=0.9)
        trigger1.should_fire()  # observes
        clock.advance(130.0)
        assert trigger1.should_fire() is True
        # Restart: new daemon resumes from saved cursor — no replay.
        clock.advance(500.0)
        trigger2 = _make_trigger(events, cursor_path=cursor, clock=clock)
        assert trigger2.should_fire() is False
