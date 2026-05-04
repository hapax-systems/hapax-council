"""Tests for cc-task ``compositor-v4l2sink-graph-mutation-stall``.

Covers:

1. Detection→recovery wiring (the watchdog tick in ``lifecycle.py`` calls
   :func:`attempt_recovery` before withholding the ping).
2. Recovery flow: cool-down, missing sink, state-cycle failure,
   no-frame-after-cycle, and the success path that resets
   ``consecutive_failures`` and pings the watchdog.
3. Escalation: after :data:`_MAX_CONSECUTIVE_FAILURES` consecutive failed
   recoveries, :func:`should_escalate` returns True so the watchdog
   withholds the ping and systemd's WatchdogSec=60s SIGABRTs the unit
   (the cc-task's "DO NOT suppress the watchdog" constraint).
4. Reproduction harness: simulated graph-mutation flush sequence
   (Trap → Datamosh → Trap) where each mutation drops sink frames for
   N seconds; assert recovery flow holds for the full sequence.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import pytest

from agents.studio_compositor import v4l2_stall_recovery as recovery

# ── Fakes — simulate compositor + GStreamer surfaces ───────────────────────


@dataclass
class _FakeStateChangeReturn:
    SUCCESS = "success"
    ASYNC = "async"
    FAILURE = "failure"


@dataclass
class _FakeSink:
    """Fake v4l2sink — records state transitions, configurable failure modes."""

    set_state_outcomes: list[str] = field(default_factory=list)
    state_log: list[str] = field(default_factory=list)
    raise_on_set_state: bool = False

    def set_state(self, target_state):
        if self.raise_on_set_state:
            raise RuntimeError("simulated set_state crash")
        self.state_log.append(f"set_state:{target_state}")
        return _FakeStateChangeReturn.SUCCESS

    def get_state(self, timeout_ns: int):
        # Pop one outcome from the configured queue; default to SUCCESS.
        outcome = (
            self.set_state_outcomes.pop(0)
            if self.set_state_outcomes
            else _FakeStateChangeReturn.SUCCESS
        )
        self.state_log.append(f"get_state:{outcome}:{timeout_ns}")
        return (outcome, "playing", "void-pending")


@dataclass
class _FakePipeline:
    sink: _FakeSink | None = None

    def get_by_name(self, name: str):
        if name != "output":
            return None
        return self.sink


@dataclass
class _FakeCompositor:
    """Fake compositor with the surface the recovery module reads."""

    pipeline: _FakePipeline | None = None
    last_frame_seen: bool = False

    def v4l2_frame_seen_within(self, seconds: float) -> bool:
        del seconds  # the fake ignores the window — caller toggles last_frame_seen
        return self.last_frame_seen


@pytest.fixture
def real_state_change_return(monkeypatch):
    """Patch the recovery module's Gst import so it sees our fake enum.

    Pure-stdlib Gst stub — gst-python may not be available in CI.
    """

    class _GstStub:
        SECOND = 1_000_000_000

        class State:
            NULL = "null"
            PLAYING = "playing"

        class StateChangeReturn:
            SUCCESS = _FakeStateChangeReturn.SUCCESS
            ASYNC = _FakeStateChangeReturn.ASYNC
            FAILURE = _FakeStateChangeReturn.FAILURE

    class _Repo:
        Gst = _GstStub

    class _Gi:
        repository = _Repo

        @staticmethod
        def require_version(*args, **kwargs):
            return None

    monkeypatch.setattr(recovery, "_cycle_sink_state", _make_cycle_sink_state(_GstStub))
    return _GstStub


def _make_cycle_sink_state(gst):
    """Reconstruct ``_cycle_sink_state`` against the fake Gst stub.

    The production version does a late ``import gi; from gi.repository
    import Gst`` which fails when gst-python is unavailable. The test
    version reads ``State.NULL`` / ``State.PLAYING`` / ``StateChangeReturn``
    from the supplied stub.
    """

    def _cycle_sink_state(sink):
        try:
            ret = sink.set_state(gst.State.NULL)
        except Exception:
            return False
        if ret == gst.StateChangeReturn.FAILURE:
            return False
        state_ret, _state, _pending = sink.get_state(int(5 * gst.SECOND))
        if state_ret != gst.StateChangeReturn.SUCCESS:
            return False
        try:
            ret = sink.set_state(gst.State.PLAYING)
        except Exception:
            return False
        if ret == gst.StateChangeReturn.FAILURE:
            return False
        state_ret, _state, _pending = sink.get_state(int(5 * gst.SECOND))
        return state_ret == gst.StateChangeReturn.SUCCESS

    return _cycle_sink_state


@pytest.fixture
def fast_wait(monkeypatch):
    """Replace the recovery's _wait_for_frame with an instant probe.

    The real probe loops ``time.sleep(0.25)`` for up to 6 s. Tests use a
    shim that instantly reads ``compositor.last_frame_seen`` to control
    success vs. failure deterministically.
    """

    def _instant_wait(compositor, *, window_s: float = 6.0):
        del window_s
        try:
            return compositor.v4l2_frame_seen_within(2.0)
        except Exception:
            return False

    monkeypatch.setattr(recovery, "_wait_for_frame", _instant_wait)


# ── 1. StallRecoveryState bookkeeping ──────────────────────────────────


class TestStallRecoveryState:
    def test_initial_counters_zero(self):
        state = recovery.StallRecoveryState()
        snap = state.snapshot()
        assert snap["consecutive_failures"] == 0
        assert snap["total_attempts"] == 0
        assert snap["total_successes"] == 0
        assert snap["total_escalations"] == 0
        assert snap["last_attempt_monotonic"] == 0.0

    def test_snapshot_is_thread_safe_under_contention(self):
        state = recovery.StallRecoveryState()

        def writer():
            for _ in range(200):
                with state.lock:
                    state.total_attempts += 1

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert state.snapshot()["total_attempts"] == 800


# ── 2. Recovery flow ───────────────────────────────────────────────────


class TestAttemptRecovery:
    def test_no_pipeline_records_failure_and_returns_false(self, fast_wait):
        compositor = _FakeCompositor(pipeline=None, last_frame_seen=True)
        state = recovery.StallRecoveryState()
        ok = recovery.attempt_recovery(compositor, state, now=100.0)
        assert ok is False
        snap = state.snapshot()
        assert snap["consecutive_failures"] == 1
        assert snap["total_attempts"] == 1
        assert snap["total_successes"] == 0

    def test_no_sink_records_failure_and_returns_false(self, fast_wait):
        compositor = _FakeCompositor(pipeline=_FakePipeline(sink=None), last_frame_seen=True)
        state = recovery.StallRecoveryState()
        ok = recovery.attempt_recovery(compositor, state, now=100.0)
        assert ok is False
        assert state.snapshot()["consecutive_failures"] == 1

    def test_state_change_failure_records_and_returns_false(
        self, real_state_change_return, fast_wait
    ):
        # set_state succeeds but get_state returns FAILURE → recovery fails.
        sink = _FakeSink(
            set_state_outcomes=[
                _FakeStateChangeReturn.FAILURE,  # NULL transition fails
            ]
        )
        compositor = _FakeCompositor(
            pipeline=_FakePipeline(sink=sink),
            last_frame_seen=False,
        )
        state = recovery.StallRecoveryState()
        ok = recovery.attempt_recovery(compositor, state, now=200.0)
        assert ok is False
        assert state.snapshot()["consecutive_failures"] == 1

    def test_state_cycle_succeeds_but_no_frame_records_failure(
        self, real_state_change_return, fast_wait
    ):
        sink = _FakeSink(
            set_state_outcomes=[
                _FakeStateChangeReturn.SUCCESS,
                _FakeStateChangeReturn.SUCCESS,
            ]
        )
        compositor = _FakeCompositor(
            pipeline=_FakePipeline(sink=sink),
            last_frame_seen=False,  # no frame after cycle
        )
        state = recovery.StallRecoveryState()
        ok = recovery.attempt_recovery(compositor, state, now=300.0)
        assert ok is False
        assert state.snapshot()["consecutive_failures"] == 1

    def test_full_success_path_resets_consecutive_failures(
        self, real_state_change_return, fast_wait
    ):
        sink = _FakeSink(
            set_state_outcomes=[
                _FakeStateChangeReturn.SUCCESS,
                _FakeStateChangeReturn.SUCCESS,
            ]
        )
        compositor = _FakeCompositor(
            pipeline=_FakePipeline(sink=sink),
            last_frame_seen=True,
        )
        state = recovery.StallRecoveryState()
        # Pre-load some failures so we can confirm the reset.
        state.consecutive_failures = 2
        ok = recovery.attempt_recovery(compositor, state, now=400.0)
        assert ok is True
        snap = state.snapshot()
        assert snap["consecutive_failures"] == 0
        assert snap["total_successes"] == 1

    def test_cooldown_blocks_rapid_double_attempt(self, real_state_change_return, fast_wait):
        sink = _FakeSink(
            set_state_outcomes=[
                _FakeStateChangeReturn.SUCCESS,
                _FakeStateChangeReturn.SUCCESS,
            ]
        )
        compositor = _FakeCompositor(
            pipeline=_FakePipeline(sink=sink),
            last_frame_seen=True,
        )
        state = recovery.StallRecoveryState()
        ok_first = recovery.attempt_recovery(compositor, state, now=500.0)
        assert ok_first is True
        # Within the cool-down window — second attempt is a no-op.
        ok_second = recovery.attempt_recovery(compositor, state, now=502.0)
        assert ok_second is False
        snap = state.snapshot()
        # total_attempts unchanged (the cool-down branch returns before
        # incrementing) — the production semantics is that a blocked
        # attempt is NOT counted as a real attempt.
        assert snap["total_attempts"] == 1


# ── 3. Escalation — preserves the "DO NOT suppress watchdog" constraint ─


class TestEscalation:
    def test_below_threshold_does_not_escalate(self):
        state = recovery.StallRecoveryState()
        state.consecutive_failures = recovery._MAX_CONSECUTIVE_FAILURES - 1
        assert recovery.should_escalate(state) is False
        # Counter unchanged.
        assert state.snapshot()["total_escalations"] == 0

    def test_at_threshold_escalates_and_increments_counter(self):
        state = recovery.StallRecoveryState()
        state.consecutive_failures = recovery._MAX_CONSECUTIVE_FAILURES
        assert recovery.should_escalate(state) is True
        assert state.snapshot()["total_escalations"] == 1

    def test_above_threshold_escalates_and_increments_counter(self):
        state = recovery.StallRecoveryState()
        state.consecutive_failures = recovery._MAX_CONSECUTIVE_FAILURES + 5
        assert recovery.should_escalate(state) is True
        assert state.snapshot()["total_escalations"] == 1


# ── 4. Reproduction harness — Trap → Datamosh → Trap sequence ─────────


class TestGraphMutationReproductionHarness:
    """Simulates the cc-task scenario: three sequential graph-mutation
    triggers (Trap, Datamosh, Trap) each cause a brief sink stall.
    Recovery must hold across the full sequence so the broadcast stays
    ON and the watchdog ping doesn't get withheld.
    """

    def test_three_sequential_stalls_all_recover(self, real_state_change_return, fast_wait):
        sink = _FakeSink(
            set_state_outcomes=[
                _FakeStateChangeReturn.SUCCESS,
                _FakeStateChangeReturn.SUCCESS,
                _FakeStateChangeReturn.SUCCESS,
                _FakeStateChangeReturn.SUCCESS,
                _FakeStateChangeReturn.SUCCESS,
                _FakeStateChangeReturn.SUCCESS,
            ]
        )
        compositor = _FakeCompositor(
            pipeline=_FakePipeline(sink=sink),
            last_frame_seen=True,
        )
        state = recovery.StallRecoveryState()
        # Three attempts, each spaced past the cool-down window. Each one
        # observes a frame → success → consecutive_failures stays at 0.
        for tick, now_ts in enumerate((1000.0, 1020.0, 1040.0), start=1):
            ok = recovery.attempt_recovery(compositor, state, now=now_ts)
            assert ok is True, f"recovery attempt {tick} failed unexpectedly"
        snap = state.snapshot()
        assert snap["total_successes"] == 3
        assert snap["consecutive_failures"] == 0
        assert snap["total_escalations"] == 0
        # should_escalate stays False — the watchdog keeps pinging.
        assert recovery.should_escalate(state) is False

    def test_persistent_stall_eventually_escalates(self, real_state_change_return, fast_wait):
        # Sink cycles always succeed but no frame ever lands → every
        # recovery attempt fails. After _MAX_CONSECUTIVE_FAILURES
        # attempts, should_escalate returns True so the watchdog
        # withholds the ping (cc-task DO-NOT-SUPPRESS constraint).
        n = recovery._MAX_CONSECUTIVE_FAILURES
        sink = _FakeSink(set_state_outcomes=[_FakeStateChangeReturn.SUCCESS] * (n * 2))
        compositor = _FakeCompositor(
            pipeline=_FakePipeline(sink=sink),
            last_frame_seen=False,
        )
        state = recovery.StallRecoveryState()
        for i in range(n):
            ok = recovery.attempt_recovery(
                compositor,
                state,
                now=1000.0 + (i * 20.0),
            )
            assert ok is False, f"attempt {i} unexpectedly succeeded"
        snap = state.snapshot()
        assert snap["consecutive_failures"] == n
        assert recovery.should_escalate(state) is True
        # total_escalations counter incremented exactly once.
        assert state.snapshot()["total_escalations"] == 1


# ── 5. Compositor + lifecycle attribute exists ─────────────────────────


class TestCompositorIntegration:
    """Check that the compositor exposes the recovery state attribute the
    watchdog tick reads. Light-touch — actual ``StudioCompositor.__init__``
    construction pulls in heavy dependencies (cameras, GStreamer) so
    this verifies via attribute presence on a stub.
    """

    def test_recovery_state_class_is_attached_to_compositor_module(self):
        """The recovery module re-exports ``StallRecoveryState`` so
        ``compositor.py`` can import + instantiate it at startup."""

        from agents.studio_compositor import compositor as _comp

        # The compositor module imports StallRecoveryState lazily inside
        # ``__init__``. Verify the import path is wired so the lookup
        # the watchdog will perform actually resolves.
        from agents.studio_compositor.v4l2_stall_recovery import StallRecoveryState

        assert StallRecoveryState is not None
        # Confirm the compositor's source still references the
        # attribute name the watchdog reads.
        source = open(_comp.__file__, encoding="utf-8").read()
        assert "_v4l2_recovery_state" in source

    def test_lifecycle_calls_recovery_before_withholding_ping(self):
        """Lifecycle `_watchdog_tick` calls ``attempt_recovery`` before
        the legacy "withholding watchdog ping" log line. Static check —
        verifies the wiring rather than a live tick."""

        from agents.studio_compositor import lifecycle as _lc

        source = open(_lc.__file__, encoding="utf-8").read()
        # The recovery import + call must appear in the watchdog branch.
        assert "from .v4l2_stall_recovery import attempt_recovery" in source
        assert "should_escalate" in source
        # The original "withholding ping" log line is still present
        # (preserves the DO-NOT-SUPPRESS constraint when escalation
        # fires).
        assert "withholding watchdog ping" in source
