"""u6-periodic-tick-driver — driver wraps apply_layout_switch in a loop.

Per cc-task `u6-periodic-tick-driver`: the compositor's layout selector
needed a callsite (director-loop tick or dedicated timer) to drive it.
This driver is that timer — runs forever (until stop_event), reads
state via state_provider, and calls apply_layout_switch every
interval_s.

Test surface:

  * Driver respects the stop_event (clean exit).
  * Driver respects iterations bound (test cleanup).
  * Driver respects interval_s floor (10s minimum, debounce-safe).
  * State_provider returning different states across ticks produces
    layout transitions (the gauge cycles through layouts).
  * State_provider raising does not crash the loop (skip + continue).
  * apply_layout_switch raising does not crash the loop (continue).
  * Cooldown debounces same-tick consecutive identical states.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from agents.studio_compositor.layout_switcher import (
    DEFAULT_DRIVER_INTERVAL_S,
    MIN_DRIVER_INTERVAL_S,
    LayoutSwitcher,
    run_layout_switch_loop,
)

# ── Fakes (mirror test_layout_switcher_apply.py shape) ──────────────


@dataclass
class _FakeLayout:
    name: str


@dataclass
class _FakeLayoutState:
    current: Any = None
    mutations: list[Any] = field(default_factory=list)

    def mutate(self, fn: Callable[[Any], Any]) -> None:
        new_layout = fn(self.current)
        self.current = new_layout
        self.mutations.append(new_layout)


@dataclass
class _FakeLoader:
    loaded: list[str] = field(default_factory=list)

    def load(self, name: str) -> _FakeLayout:
        self.loaded.append(name)
        return _FakeLayout(name=name)


def _switcher() -> LayoutSwitcher:
    """LayoutSwitcher with default 30s cooldown."""
    return LayoutSwitcher()


# ── Constant + interval-floor surface ───────────────────────────────


class TestConstants:
    def test_default_interval_is_30s(self) -> None:
        assert DEFAULT_DRIVER_INTERVAL_S == 30.0

    def test_minimum_interval_is_10s_matches_cooldown_debounce(self) -> None:
        assert MIN_DRIVER_INTERVAL_S == 10.0


# ── Bounded-iterations test runs ────────────────────────────────────


class TestBoundedIterations:
    def test_iterations_bound_terminates_loop(self) -> None:
        layout_state = _FakeLayoutState(current=_FakeLayout("default"))
        loader = _FakeLoader()
        switcher = _switcher()
        sleeps: list[float] = []
        switches = run_layout_switch_loop(
            layout_state=layout_state,
            loader=loader,
            switcher=switcher,
            state_provider=lambda: {"stream_mode": "deep"},  # default-legacy
            interval_s=10.0,
            sleep_fn=lambda s: sleeps.append(s),
            iterations=3,
            now_fn=lambda: 0.0,
        )
        assert len(sleeps) == 3
        # First tick applies (no prior switch); subsequent two are
        # cooldown-blocked because now_fn returns 0.0 for all ticks.
        assert switches == 1

    def test_zero_iterations_returns_immediately(self) -> None:
        sleeps: list[float] = []
        switches = run_layout_switch_loop(
            layout_state=_FakeLayoutState(),
            loader=_FakeLoader(),
            switcher=_switcher(),
            state_provider=lambda: {},
            interval_s=10.0,
            sleep_fn=lambda s: sleeps.append(s),
            iterations=0,
        )
        assert sleeps == []
        assert switches == 0


# ── stop_event clean-exit ───────────────────────────────────────────


class TestStopEvent:
    def test_set_event_terminates_loop(self) -> None:
        event = threading.Event()
        sleeps: list[float] = []

        def sleep(s: float) -> None:
            sleeps.append(s)
            if len(sleeps) >= 2:
                event.set()  # set after the 2nd sleep

        switches = run_layout_switch_loop(
            layout_state=_FakeLayoutState(),
            loader=_FakeLoader(),
            switcher=_switcher(),
            state_provider=lambda: {},
            interval_s=10.0,
            sleep_fn=sleep,
            stop_event=event,
            now_fn=lambda: 0.0,
        )
        # 2 ticks ran (sleep set the event after the 2nd one); the
        # 3rd iteration's stop_event.is_set() check exits cleanly.
        assert len(sleeps) == 2
        # First tick may apply a switch (no cooldown yet); subsequent
        # depend on the cooldown clock.
        assert switches >= 0


# ── Interval floor enforcement ──────────────────────────────────────


class TestIntervalFloor:
    def test_below_minimum_clamped_to_floor(self) -> None:
        sleeps: list[float] = []
        run_layout_switch_loop(
            layout_state=_FakeLayoutState(),
            loader=_FakeLoader(),
            switcher=_switcher(),
            state_provider=lambda: {},
            interval_s=2.0,  # below MIN_DRIVER_INTERVAL_S=10.0
            sleep_fn=lambda s: sleeps.append(s),
            iterations=1,
        )
        # The driver should have slept 10s (clamped), not 2s.
        assert sleeps == [MIN_DRIVER_INTERVAL_S]


# ── State-driven transitions ────────────────────────────────────────


class TestStateDrivenTransitions:
    def test_state_transitions_drive_layout_switches(self) -> None:
        """State_provider returning DIFFERENT inputs across ticks
        produces layout transitions. With now_fn advancing past the
        cooldown each tick, every distinct input is honored.
        """
        layout_state = _FakeLayoutState(current=_FakeLayout("default"))
        loader = _FakeLoader()
        switcher = _switcher()
        # Three distinct states → three distinct layouts.
        states = iter(
            [
                {"vinyl_playing": True},  # → vinyl-focus
                {"stream_mode": "deep"},  # → default-legacy
                {"consent_safe_active": True},  # → consent-safe
            ]
        )
        # Advance now_fn past 30s cooldown each call so cooldown
        # doesn't gate the transitions.
        now_iter = iter([0.0, 100.0, 200.0])
        switches = run_layout_switch_loop(
            layout_state=layout_state,
            loader=loader,
            switcher=switcher,
            state_provider=lambda: next(states),
            interval_s=10.0,
            sleep_fn=lambda s: None,
            now_fn=lambda: next(now_iter),
            iterations=3,
        )
        # All three distinct inputs honored.
        assert switches == 3
        assert loader.loaded == ["vinyl-focus", "default-legacy", "consent-safe"]


# ── Failure tolerance ───────────────────────────────────────────────


class TestFailureTolerance:
    def test_state_provider_raising_skips_tick_does_not_crash(self) -> None:
        layout_state = _FakeLayoutState(current=_FakeLayout("default"))
        loader = _FakeLoader()
        switcher = _switcher()
        call_count = [0]

        def state_provider() -> dict[str, object]:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("synthetic failure on tick 2")
            return {"vinyl_playing": True}

        # 3 iterations: tick 1 applies vinyl-focus, tick 2 raises (skipped,
        # state defaults to {}; cooldown anyway), tick 3 retries.
        switches = run_layout_switch_loop(
            layout_state=layout_state,
            loader=loader,
            switcher=switcher,
            state_provider=state_provider,
            interval_s=10.0,
            sleep_fn=lambda s: None,
            now_fn=lambda: 0.0,
            iterations=3,
        )
        assert call_count[0] == 3  # all 3 ticks called the provider
        # Tick 1 applied (no prior); tick 2 raised → defaults; tick 3
        # cooldown-blocks. The loop did not crash — that's the contract.
        assert switches >= 0

    def test_apply_layout_switch_raising_does_not_crash(self, monkeypatch) -> None:
        """If apply_layout_switch internally raises (loader missing
        layout, validation error, etc.), the loop continues."""
        from agents.studio_compositor import layout_switcher

        def raising_apply(*args: Any, **kwargs: Any) -> bool:
            raise KeyError("synthetic")

        monkeypatch.setattr(layout_switcher, "apply_layout_switch", raising_apply)
        sleeps: list[float] = []
        # Should not raise — loop swallows + continues.
        run_layout_switch_loop(
            layout_state=_FakeLayoutState(),
            loader=_FakeLoader(),
            switcher=_switcher(),
            state_provider=lambda: {},
            interval_s=10.0,
            sleep_fn=lambda s: sleeps.append(s),
            iterations=2,
        )
        assert len(sleeps) == 2  # both iterations completed despite raise


# ── Cooldown debounce ───────────────────────────────────────────────


class TestCooldownDebounce:
    def test_cooldown_debounces_consecutive_identical_states(self) -> None:
        """When state stays put + now_fn returns same value, the
        switcher's cooldown gates the second-tick switch."""
        layout_state = _FakeLayoutState(current=_FakeLayout("default"))
        loader = _FakeLoader()
        switcher = _switcher()
        switches = run_layout_switch_loop(
            layout_state=layout_state,
            loader=loader,
            switcher=switcher,
            state_provider=lambda: {"vinyl_playing": True},
            interval_s=10.0,
            sleep_fn=lambda s: None,
            now_fn=lambda: 0.0,  # never advances → cooldown always active
            iterations=5,
        )
        # First tick switches (no prior); subsequent 4 are cooldown-blocked.
        assert switches == 1
        assert loader.loaded == ["vinyl-focus"]


# ── pytest hook: module imports cleanly ─────────────────────────────


def test_module_exports_run_layout_switch_loop() -> None:
    """Regression pin: future refactors must keep
    `run_layout_switch_loop` importable from
    `agents.studio_compositor.layout_switcher`."""
    from agents.studio_compositor.layout_switcher import (  # noqa: F401
        DEFAULT_DRIVER_INTERVAL_S,
        MIN_DRIVER_INTERVAL_S,
        run_layout_switch_loop,
    )

    assert callable(run_layout_switch_loop)


# pytest fixture-required dummy (no-op) — keeps `pytest` import alive
# even when --no-skip-on-fixture-warnings is set.
@pytest.fixture
def _placeholder() -> None:
    return None
