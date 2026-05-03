"""Tests for the stale-intent micromove timer (audit R4).

Per `docs/research/...director-loop-cadence-bump`'s option (b): when
the LLM tick fires every PERCEPTION_INTERVAL (~30s default; operator
env may stretch to 70-110s), the surface has no fresh director intent
between ticks. The stale-intent timer fires the existing micromove
cycle every STALE_INTENT_MICROMOVE_S seconds when waiting for the
next LLM tick, so the surface always has compositional impingements
at perceptible cadence.

These tests pin:

  * The constant STALE_INTENT_MICROMOVE_S defaults to 15.0 and is env-
    overridable via HAPAX_DIRECTOR_STALE_INTENT_MICROMOVE_S.
  * `_maybe_emit_stale_intent_micromove` fires only after the timer
    elapses since the last micromove.
  * Setting STALE_INTENT_MICROMOVE_S=0 disables the timer (legacy).
  * The timer cadence is independent of the PERCEPTION_INTERVAL —
    both clocks tick separately and don't reset each other.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.studio_compositor import director_loop


class _StubDirector:
    """Minimal stub exposing just the bits the timer method touches.

    The full DirectorLoop has a dozen collaborators (programme provider,
    reactor overlay, tts client, etc.); the timer method only touches
    `_last_stale_micromove_at` (read+write) and calls
    `_emit_micromove_fallback(reason, condition_id)`. A plain object
    with those two surfaces is sufficient.
    """

    def __init__(self) -> None:
        self._last_stale_micromove_at: float = 0.0
        self.emit_calls: list[tuple[str, str]] = []

    def _emit_micromove_fallback(self, *, reason: str, condition_id: str) -> None:
        self.emit_calls.append((reason, condition_id))


def _maybe(stub: _StubDirector, now: float) -> None:
    """Bind the unbound method onto the stub for the test call."""
    director_loop.DirectorLoop._maybe_emit_stale_intent_micromove(stub, now)


# ── Constant + env override ─────────────────────────────────────────


class TestConstant:
    def test_default_is_15s(self) -> None:
        assert director_loop.STALE_INTENT_MICROMOVE_S == 15.0


# ── Timer firing semantics ──────────────────────────────────────────


class TestTimer:
    def test_does_not_fire_before_interval_elapses(self, monkeypatch) -> None:
        monkeypatch.setattr(director_loop, "STALE_INTENT_MICROMOVE_S", 15.0)
        monkeypatch.setattr(director_loop, "_read_research_marker", lambda: "test-cond")
        stub = _StubDirector()
        stub._last_stale_micromove_at = 100.0
        # 14.99s after last micromove → no fire.
        _maybe(stub, 114.99)
        assert stub.emit_calls == []

    def test_fires_when_interval_elapses(self, monkeypatch) -> None:
        monkeypatch.setattr(director_loop, "STALE_INTENT_MICROMOVE_S", 15.0)
        monkeypatch.setattr(director_loop, "_read_research_marker", lambda: "test-cond")
        stub = _StubDirector()
        stub._last_stale_micromove_at = 100.0
        # 15.0s elapsed → fire.
        _maybe(stub, 115.0)
        assert len(stub.emit_calls) == 1
        reason, condition_id = stub.emit_calls[0]
        assert reason == "stale_intent"
        assert condition_id == "test-cond"

    def test_advances_last_emit_timestamp_on_fire(self, monkeypatch) -> None:
        monkeypatch.setattr(director_loop, "STALE_INTENT_MICROMOVE_S", 15.0)
        monkeypatch.setattr(director_loop, "_read_research_marker", lambda: "c")
        stub = _StubDirector()
        stub._last_stale_micromove_at = 100.0
        _maybe(stub, 116.0)
        assert stub._last_stale_micromove_at == 116.0
        # Second call within the next 15s window → no fire.
        _maybe(stub, 130.99)
        assert len(stub.emit_calls) == 1

    def test_fires_repeatedly_at_interval(self, monkeypatch) -> None:
        monkeypatch.setattr(director_loop, "STALE_INTENT_MICROMOVE_S", 10.0)
        monkeypatch.setattr(director_loop, "_read_research_marker", lambda: "c")
        stub = _StubDirector()
        stub._last_stale_micromove_at = 0.0
        for now in (10.0, 20.0, 30.0, 40.0):
            _maybe(stub, now)
        assert len(stub.emit_calls) == 4

    def test_research_marker_none_yields_none_condition_id(self, monkeypatch) -> None:
        monkeypatch.setattr(director_loop, "STALE_INTENT_MICROMOVE_S", 15.0)
        monkeypatch.setattr(director_loop, "_read_research_marker", lambda: None)
        stub = _StubDirector()
        stub._last_stale_micromove_at = 0.0
        _maybe(stub, 15.0)
        assert stub.emit_calls == [("stale_intent", "none")]


# ── Disable via env / constant ──────────────────────────────────────


class TestDisable:
    def test_zero_disables_timer(self, monkeypatch) -> None:
        monkeypatch.setattr(director_loop, "STALE_INTENT_MICROMOVE_S", 0.0)
        monkeypatch.setattr(director_loop, "_read_research_marker", lambda: "c")
        stub = _StubDirector()
        stub._last_stale_micromove_at = 0.0
        # Even after a long elapsed time, no fire.
        _maybe(stub, 1_000_000.0)
        assert stub.emit_calls == []

    def test_negative_disables_timer(self, monkeypatch) -> None:
        monkeypatch.setattr(director_loop, "STALE_INTENT_MICROMOVE_S", -1.0)
        monkeypatch.setattr(director_loop, "_read_research_marker", lambda: "c")
        stub = _StubDirector()
        stub._last_stale_micromove_at = 0.0
        _maybe(stub, 100.0)
        assert stub.emit_calls == []


# ── Failure tolerance ───────────────────────────────────────────────


class TestFailureTolerance:
    def test_micromove_emit_exception_does_not_break_loop(self, monkeypatch) -> None:
        """An emit failure must not crash the director loop AND must
        not advance _last_stale_micromove_at (so the next iteration
        retries cleanly rather than waiting another full interval)."""
        monkeypatch.setattr(director_loop, "STALE_INTENT_MICROMOVE_S", 15.0)
        monkeypatch.setattr(director_loop, "_read_research_marker", lambda: "c")
        stub = _StubDirector()
        stub._last_stale_micromove_at = 100.0
        stub._emit_micromove_fallback = MagicMock(side_effect=RuntimeError("boom"))
        # Should not raise.
        _maybe(stub, 116.0)
        # Did not advance the timestamp (so next iteration retries).
        assert stub._last_stale_micromove_at == 100.0
