"""Tests for ``agents.hapax_daimonion.awareness_digest_watcher``.

Covers the three behaviors required by the cc-task acceptance:

- no-event: same mode + same stimmung bucket on consecutive ticks ⇒
  no events fire (after the initial transition).
- new-event: a mode flip OR a stimmung bucket crossing fires the
  appropriate typed event.
- duplicate-event: repeated identical observations after the initial
  transition do not fire further events.

Plus fortress-specific guards:

- Entering fortress fires ``fortress_enter``; exiting fires
  ``fortress_exit``.
- Stimmung crossings WITHIN fortress fire as
  ``suppressed_within_fortress`` (audit signal — handler should not
  speak), the bucket state still advances.
- A handler that raises does not break the watcher — the next tick
  still dispatches.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.hapax_daimonion.awareness_digest import AwarenessDigestState
from agents.hapax_daimonion.awareness_digest_watcher import (
    WatcherEvent,
    awareness_digest_watcher_loop,
    tick_once,
)


def _capture() -> tuple[list[WatcherEvent], object]:
    """Return (events_list, sync_handler) — handler appends each event."""
    events: list[WatcherEvent] = []

    def handler(event: WatcherEvent) -> None:
        events.append(event)

    return events, handler


# ── no-event / new-event / duplicate-event ───────────────────────────────


class TestTickNoEvent:
    @pytest.mark.asyncio
    async def test_steady_state_after_first_tick(self):
        """After the initial transition, repeated identical observations
        produce no further events."""
        events, handler = _capture()
        state = AwarenessDigestState()

        await tick_once(
            state,
            get_mode=lambda: "rnd",
            get_stimmung=lambda: 0.5,
            handler=handler,
        )
        # Two events on the first tick: the initial mode and stimmung.
        assert len(events) == 2

        # Subsequent identical ticks: no further events.
        events.clear()
        for _ in range(3):
            await tick_once(
                state,
                get_mode=lambda: "rnd",
                get_stimmung=lambda: 0.5,
                handler=handler,
            )
        assert events == []

    @pytest.mark.asyncio
    async def test_absent_signals_skipped(self):
        """Getters returning None never produce events nor advance state."""
        events, handler = _capture()
        state = AwarenessDigestState()

        await tick_once(
            state,
            get_mode=lambda: None,
            get_stimmung=lambda: None,
            handler=handler,
        )
        assert events == []
        assert state.last_mode is None
        assert state.last_stimmung_bucket is None


class TestTickNewEvent:
    @pytest.mark.asyncio
    async def test_mode_flip_fires_mode_shift(self):
        events, handler = _capture()
        state = AwarenessDigestState(last_mode="rnd")

        await tick_once(
            state,
            get_mode=lambda: "research",
            get_stimmung=lambda: None,
            handler=handler,
        )
        assert len(events) == 1
        assert events[0].kind == "mode_shift"
        assert events[0].mode == "research"
        assert state.last_mode == "research"

    @pytest.mark.asyncio
    async def test_stimmung_bucket_cross_fires_stimmung_cross(self):
        events, handler = _capture()
        state = AwarenessDigestState(last_mode="rnd", last_stimmung_bucket="low_load")

        await tick_once(
            state,
            get_mode=lambda: "rnd",
            get_stimmung=lambda: 0.7,  # → high_load
            handler=handler,
        )
        assert len(events) == 1
        assert events[0].kind == "stimmung_cross"
        assert events[0].stimmung_bucket_value == "high_load"
        assert events[0].stimmung_value == pytest.approx(0.7)


class TestTickDuplicateEvent:
    @pytest.mark.asyncio
    async def test_same_value_within_bucket_no_event(self):
        """Two stimmung observations in the same bucket: only first
        fires; the second is a no-op."""
        events, handler = _capture()
        state = AwarenessDigestState()

        await tick_once(
            state,
            get_mode=lambda: None,
            get_stimmung=lambda: 0.4,
            handler=handler,
        )
        await tick_once(
            state,
            get_mode=lambda: None,
            get_stimmung=lambda: 0.5,  # same bucket (nominal)
            handler=handler,
        )
        assert len(events) == 1
        assert events[0].stimmung_bucket_value == "nominal"


# ── Fortress entry / exit / suppression ─────────────────────────────────


class TestFortressTransitions:
    @pytest.mark.asyncio
    async def test_entering_fortress_fires_fortress_enter(self):
        events, handler = _capture()
        state = AwarenessDigestState(last_mode="rnd")

        await tick_once(
            state,
            get_mode=lambda: "fortress",
            get_stimmung=lambda: None,
            handler=handler,
        )
        assert len(events) == 1
        assert events[0].kind == "fortress_enter"
        assert events[0].mode == "fortress"

    @pytest.mark.asyncio
    async def test_exiting_fortress_fires_fortress_exit(self):
        events, handler = _capture()
        state = AwarenessDigestState(last_mode="fortress")

        await tick_once(
            state,
            get_mode=lambda: "research",
            get_stimmung=lambda: None,
            handler=handler,
        )
        assert len(events) == 1
        assert events[0].kind == "fortress_exit"
        assert events[0].mode == "research"

    @pytest.mark.asyncio
    async def test_stimmung_cross_within_fortress_is_suppressed(self):
        """Bucket cross while last_mode is fortress: emits the
        ``suppressed_within_fortress`` audit kind, NOT
        ``stimmung_cross``. State still advances."""
        events, handler = _capture()
        state = AwarenessDigestState(last_mode="fortress", last_stimmung_bucket="low_load")

        await tick_once(
            state,
            get_mode=lambda: "fortress",  # same mode, no transition
            get_stimmung=lambda: 0.7,  # bucket cross to high_load
            handler=handler,
        )
        assert len(events) == 1
        assert events[0].kind == "suppressed_within_fortress"
        assert state.last_stimmung_bucket == "high_load"

    @pytest.mark.asyncio
    async def test_mode_processed_before_stimmung_for_same_tick(self):
        """If a tick observes both fortress entry and a stimmung bucket
        cross, the suppression applies to the stimmung event because
        the mode update lands first."""
        events, handler = _capture()
        state = AwarenessDigestState(last_mode="rnd", last_stimmung_bucket="low_load")

        await tick_once(
            state,
            get_mode=lambda: "fortress",
            get_stimmung=lambda: 0.7,
            handler=handler,
        )
        assert [e.kind for e in events] == [
            "fortress_enter",
            "suppressed_within_fortress",
        ]


# ── Handler robustness ──────────────────────────────────────────────────


class TestHandlerRobustness:
    @pytest.mark.asyncio
    async def test_handler_exception_does_not_break_loop(self):
        """A handler that raises is logged and skipped; the next tick
        still fires events."""
        delivered: list[WatcherEvent] = []
        call_count = {"n": 0}

        def handler(event: WatcherEvent) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first call boom")
            delivered.append(event)

        state = AwarenessDigestState()

        # First tick: handler raises on the initial mode event but the
        # state still advances; the stimmung event delivers.
        await tick_once(
            state,
            get_mode=lambda: "rnd",
            get_stimmung=lambda: 0.5,
            handler=handler,
        )
        assert state.last_mode == "rnd"
        assert state.last_stimmung_bucket == "nominal"
        assert len(delivered) == 1
        assert delivered[0].stimmung_bucket_value == "nominal"

        # Next tick: mode flip fires, handler delivers.
        await tick_once(
            state,
            get_mode=lambda: "research",
            get_stimmung=lambda: 0.5,  # same bucket, no-op
            handler=handler,
        )
        assert delivered[-1].kind == "mode_shift"

    @pytest.mark.asyncio
    async def test_async_handler_is_awaited(self):
        """Coroutine handler results are awaited."""
        seen: list[str] = []

        async def handler(event: WatcherEvent) -> None:
            await asyncio.sleep(0)
            seen.append(event.kind)

        state = AwarenessDigestState(last_mode="rnd", last_stimmung_bucket="nominal")
        await tick_once(
            state,
            get_mode=lambda: "research",
            get_stimmung=lambda: 0.5,
            handler=handler,
        )
        assert seen == ["mode_shift"]


# ── Loop wrapper ───────────────────────────────────────────────────────


class TestLoopWrapper:
    @pytest.mark.asyncio
    async def test_loop_stops_when_is_running_returns_false(self):
        """The loop exits cleanly when ``is_running`` flips false."""
        events, handler = _capture()
        ticks = {"n": 0}
        max_ticks = 3

        def is_running() -> bool:
            ticks["n"] += 1
            return ticks["n"] <= max_ticks

        await awareness_digest_watcher_loop(
            is_running,
            get_mode=lambda: "rnd",
            get_stimmung=lambda: 0.5,
            handler=handler,
            poll_interval_s=0.001,
        )
        # First tick fires two events (initial mode + stimmung); subsequent
        # identical ticks are no-ops. The loop body runs exactly max_ticks
        # times, so the event count should equal the first-tick yield.
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_loop_survives_getter_exception(self):
        """If a getter raises, the loop logs and continues to next tick."""
        events, handler = _capture()
        ticks = {"n": 0}

        def is_running() -> bool:
            ticks["n"] += 1
            return ticks["n"] <= 3

        def flaky_mode() -> str | None:
            if ticks["n"] == 1:
                raise OSError("transient")
            return "rnd"

        await awareness_digest_watcher_loop(
            is_running,
            get_mode=flaky_mode,
            get_stimmung=lambda: None,
            handler=handler,
            poll_interval_s=0.001,
        )
        # tick 1 raised, tick 2 fired the initial mode event, tick 3 was a no-op.
        assert len(events) == 1
        assert events[0].kind == "mode_shift"
        assert events[0].mode == "rnd"
