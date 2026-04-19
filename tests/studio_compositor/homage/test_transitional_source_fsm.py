"""FSM invariant tests for HomageTransitionalSource."""

from __future__ import annotations

from typing import Any

import cairo
import pytest

from agents.studio_compositor.homage.transitional_source import (
    HomageTransitionalSource,
    TransitionState,
)


class _Stub(HomageTransitionalSource):
    """Test double — records render_content / render_entering / render_exiting."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(source_id="stub", **kw)
        self.calls: list[tuple[str, float]] = []

    def render_content(self, cr, canvas_w, canvas_h, t, state):
        self.calls.append(("content", t))

    def render_entering(self, cr, canvas_w, canvas_h, t, state, progress):
        self.calls.append(("entering", progress))

    def render_exiting(self, cr, canvas_w, canvas_h, t, state, progress):
        self.calls.append(("exiting", progress))


def _ctx() -> cairo.Context:
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
    return cairo.Context(surf)


@pytest.fixture
def homage_on(monkeypatch):
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")


@pytest.fixture
def homage_off(monkeypatch):
    # Phase 12 flipped the default-ON; explicit disable required now.
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")


class TestFeatureFlagOff:
    def test_feature_flag_off_renders_content_regardless_of_state(self, homage_off):
        src = _Stub(initial_state=TransitionState.ABSENT)
        src.render(_ctx(), 64, 64, 0.0, {})
        assert src.calls == [("content", 0.0)]


class TestAbsentStateNoOp:
    def test_absent_state_renders_nothing(self, homage_on):
        src = _Stub(initial_state=TransitionState.ABSENT)
        src.render(_ctx(), 64, 64, 0.0, {})
        assert src.calls == []


class TestHoldStateRendersContent:
    def test_hold_state_renders_content(self, homage_on):
        src = _Stub(initial_state=TransitionState.HOLD)
        src.render(_ctx(), 64, 64, 0.5, {})
        assert src.calls == [("content", 0.5)]


class TestEnteringDispatch:
    def test_entering_state_renders_entering(self, homage_on):
        # Use real monotonic clock so render()'s internal tick() call
        # sees elapsed < entering_duration_s.
        src = _Stub(initial_state=TransitionState.ABSENT, entering_duration_s=10.0)
        src.apply_transition("ticker-scroll-in")
        src.render(_ctx(), 64, 64, 0.0, {})
        assert src.calls[-1][0] == "entering"


class TestExitingDispatch:
    def test_exiting_state_renders_exiting(self, homage_on):
        src = _Stub(initial_state=TransitionState.HOLD, exiting_duration_s=10.0)
        src.apply_transition("ticker-scroll-out")
        src.render(_ctx(), 64, 64, 0.0, {})
        assert src.calls[-1][0] == "exiting"


class TestApplyTransitionTransitions:
    def test_entry_from_absent_moves_to_entering(self):
        src = _Stub(initial_state=TransitionState.ABSENT)
        state = src.apply_transition("ticker-scroll-in", now=0.0)
        assert state is TransitionState.ENTERING

    def test_entry_from_hold_stays_hold(self):
        src = _Stub(initial_state=TransitionState.HOLD)
        state = src.apply_transition("ticker-scroll-in", now=0.0)
        assert state is TransitionState.HOLD

    def test_exit_from_hold_moves_to_exiting(self):
        src = _Stub(initial_state=TransitionState.HOLD)
        state = src.apply_transition("ticker-scroll-out", now=0.0)
        assert state is TransitionState.EXITING

    def test_exit_from_absent_raises(self):
        src = _Stub(initial_state=TransitionState.ABSENT)
        with pytest.raises(ValueError):
            src.apply_transition("ticker-scroll-out", now=0.0)

    def test_modify_transition_preserves_state(self):
        src = _Stub(initial_state=TransitionState.HOLD)
        state = src.apply_transition("topic-change", now=0.0)
        assert state is TransitionState.HOLD


class TestTickAdvancesState:
    def test_entering_completes_to_hold_after_duration(self):
        src = _Stub(initial_state=TransitionState.ABSENT, entering_duration_s=0.1)
        src.apply_transition("ticker-scroll-in", now=0.0)
        assert src.tick(now=0.05) is TransitionState.ENTERING
        assert src.tick(now=0.2) is TransitionState.HOLD

    def test_exiting_completes_to_absent_after_duration(self):
        src = _Stub(initial_state=TransitionState.HOLD, exiting_duration_s=0.1)
        src.apply_transition("ticker-scroll-out", now=0.0)
        assert src.tick(now=0.05) is TransitionState.EXITING
        assert src.tick(now=0.2) is TransitionState.ABSENT


class TestHookPointsFire:
    class _HookStub(_Stub):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.entry_starts = 0
            self.entry_completes = 0
            self.exit_starts = 0
            self.exit_completes = 0

        def _on_entry_start(self):
            self.entry_starts += 1

        def _on_entry_complete(self):
            self.entry_completes += 1

        def _on_exit_start(self):
            self.exit_starts += 1

        def _on_exit_complete(self):
            self.exit_completes += 1

    def test_full_lifecycle_fires_all_four_hooks(self):
        # Hotfix 2026-04-18: base default flipped to HOLD; the full-lifecycle
        # hook sequence needs to start in ABSENT to exercise on_entry_start.
        src = self._HookStub(
            initial_state=TransitionState.ABSENT,
            entering_duration_s=0.1,
            exiting_duration_s=0.1,
        )
        src.apply_transition("ticker-scroll-in", now=0.0)
        assert src.entry_starts == 1
        src.tick(now=0.2)
        assert src.entry_completes == 1
        src.apply_transition("ticker-scroll-out", now=0.3)
        assert src.exit_starts == 1
        src.tick(now=0.5)
        assert src.exit_completes == 1


class TestProgressBounds:
    def test_progress_clamped_to_unit_interval(self):
        src = _Stub(entering_duration_s=0.1)
        src.apply_transition("ticker-scroll-in", now=0.0)
        # Before tick, state is ENTERING with progress 0..1.
        assert 0.0 <= src._progress(now=0.05) <= 1.0
        # Past duration, progress still capped at 1.0.
        assert src._progress(now=10.0) == 1.0
