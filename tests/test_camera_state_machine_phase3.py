"""Phase 3 camera state machine tests.

Pure-Python FSM tests — no GStreamer imports, no real hardware.

See docs/superpowers/specs/2026-04-12-camera-recovery-state-machine-design.md
"""

from __future__ import annotations

from agents.studio_compositor.camera_state_machine import (
    BACKOFF_CEILING_S,
    MAX_CONSECUTIVE_FAILURES,
    CameraState,
    CameraStateMachine,
    Event,
    EventKind,
)


def make_sm(
    *,
    role: str = "test",
    start: CameraState | None = None,
    consecutive_failures: int = 0,
) -> CameraStateMachine:
    schedule_calls: list[float] = []
    swap_fb_calls: list[int] = []
    swap_primary_calls: list[int] = []
    transitions: list[tuple[CameraState, CameraState, str]] = []

    sm = CameraStateMachine(
        role=role,
        on_schedule_reconnect=lambda d: schedule_calls.append(d),
        on_swap_to_fallback=lambda: swap_fb_calls.append(1),
        on_swap_to_primary=lambda: swap_primary_calls.append(1),
        on_notify_transition=lambda o, n, r: transitions.append((o, n, r)),
    )
    sm._schedule_calls = schedule_calls  # type: ignore[attr-defined]
    sm._swap_fb_calls = swap_fb_calls  # type: ignore[attr-defined]
    sm._swap_primary_calls = swap_primary_calls  # type: ignore[attr-defined]
    sm._transitions = transitions  # type: ignore[attr-defined]

    if start is not None:
        sm._state = start
    sm._consecutive_failures = consecutive_failures
    return sm


class TestHealthyTransitions:
    def test_frame_flow_observed_stays_healthy_and_resets_counter(self) -> None:
        sm = make_sm(consecutive_failures=6)
        sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED))
        assert sm.state == CameraState.HEALTHY
        assert sm.consecutive_failures == 0

    def test_watchdog_fired_to_degraded_increments_counter(self) -> None:
        sm = make_sm()
        sm.dispatch(Event(EventKind.WATCHDOG_FIRED, reason="2s stall"))
        assert sm.state == CameraState.DEGRADED
        assert sm.consecutive_failures == 1
        assert sm._swap_fb_calls  # type: ignore[attr-defined]

    def test_frame_flow_stale_to_degraded_increments_counter(self) -> None:
        sm = make_sm()
        sm.dispatch(Event(EventKind.FRAME_FLOW_STALE))
        assert sm.state == CameraState.DEGRADED
        assert sm.consecutive_failures == 1

    def test_pipeline_error_to_degraded_increments_counter(self) -> None:
        sm = make_sm()
        sm.dispatch(Event(EventKind.PIPELINE_ERROR, reason="EIO"))
        assert sm.state == CameraState.DEGRADED
        assert sm.consecutive_failures == 1

    def test_mid_stream_failure_at_budget_transitions_to_dead(self) -> None:
        # Regression pin for the 2026-04-20 reconnect storm: PLAYING-then-
        # fail on first buffer (USB isoc bandwidth rejection) used to
        # reset the counter every cycle via RECOVERY_SUCCEEDED, so the
        # FSM never escalated. HEALTHY + PIPELINE_ERROR must now count.
        sm = make_sm(consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1)
        sm.dispatch(Event(EventKind.PIPELINE_ERROR, reason="Internal data stream error."))
        assert sm.state == CameraState.DEAD

    def test_device_removed_straight_to_offline(self) -> None:
        sm = make_sm()
        sm.dispatch(Event(EventKind.DEVICE_REMOVED, reason="usb unplug"))
        assert sm.state == CameraState.OFFLINE
        assert sm._schedule_calls  # type: ignore[attr-defined]

    def test_operator_force_reconnect_goes_to_recovering(self) -> None:
        sm = make_sm(consecutive_failures=7)
        sm.dispatch(Event(EventKind.OPERATOR_FORCE_RECONNECT))
        assert sm.state == CameraState.RECOVERING
        assert sm.consecutive_failures == 0


class TestDegradedTransitions:
    def test_swap_completed_to_offline(self) -> None:
        sm = make_sm(start=CameraState.DEGRADED)
        sm.dispatch(Event(EventKind.SWAP_COMPLETED))
        assert sm.state == CameraState.OFFLINE

    def test_device_removed_to_offline(self) -> None:
        sm = make_sm(start=CameraState.DEGRADED)
        sm.dispatch(Event(EventKind.DEVICE_REMOVED))
        assert sm.state == CameraState.OFFLINE

    def test_pipeline_error_to_offline(self) -> None:
        sm = make_sm(start=CameraState.DEGRADED)
        sm.dispatch(Event(EventKind.PIPELINE_ERROR, reason="second error"))
        assert sm.state == CameraState.OFFLINE


class TestOfflineTransitions:
    def test_backoff_elapsed_to_recovering(self) -> None:
        sm = make_sm(start=CameraState.OFFLINE)
        sm.dispatch(Event(EventKind.BACKOFF_ELAPSED))
        assert sm.state == CameraState.RECOVERING

    def test_device_added_resets_backoff_counter(self) -> None:
        sm = make_sm(start=CameraState.OFFLINE, consecutive_failures=5)
        sm.dispatch(Event(EventKind.DEVICE_ADDED))
        assert sm.state == CameraState.RECOVERING
        assert sm.consecutive_failures == 0

    def test_operator_force_reconnect_from_offline(self) -> None:
        sm = make_sm(start=CameraState.OFFLINE, consecutive_failures=3)
        sm.dispatch(Event(EventKind.OPERATOR_FORCE_RECONNECT))
        assert sm.state == CameraState.RECOVERING
        assert sm.consecutive_failures == 0


class TestRecoveringTransitions:
    def test_recovery_succeeded_stays_recovering_until_frame_flow(self) -> None:
        # Reaching PLAYING is not proof of sustained frame flow — the
        # reset happens only when the frame-flow watchdog observes live
        # post-rebuild frames.
        sm = make_sm(start=CameraState.RECOVERING, consecutive_failures=4)
        sm.dispatch(Event(EventKind.RECOVERY_SUCCEEDED))
        assert sm.state == CameraState.RECOVERING
        assert sm.consecutive_failures == 4
        assert sm._swap_primary_calls == []  # type: ignore[attr-defined]

    def test_frame_flow_observed_from_recovering_promotes_to_healthy(self) -> None:
        sm = make_sm(start=CameraState.RECOVERING, consecutive_failures=4)
        sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED, reason="post-rebuild frame"))
        assert sm.state == CameraState.HEALTHY
        assert sm.consecutive_failures == 0
        assert sm._swap_primary_calls  # type: ignore[attr-defined]

    def test_playing_then_immediate_error_accumulates_failures(self) -> None:
        # Exact scenario from the 2026-04-20 reconnect storm: USB isoc
        # bandwidth rejection arrives on the first buffer after PLAYING.
        # The cycle RECOVERING→HEALTHY→DEGRADED→OFFLINE→RECOVERING must
        # grow the counter each pass so exponential backoff engages.
        sm = make_sm(start=CameraState.RECOVERING, consecutive_failures=0)
        for _ in range(3):
            sm.dispatch(Event(EventKind.RECOVERY_SUCCEEDED))
            sm.dispatch(Event(EventKind.FRAME_FLOW_STALE, reason="no frame after rebuild"))
            sm.dispatch(Event(EventKind.BACKOFF_ELAPSED))
        assert sm.consecutive_failures >= 3

    def test_recovery_failed_to_offline_increments_counter(self) -> None:
        sm = make_sm(start=CameraState.RECOVERING, consecutive_failures=0)
        sm.dispatch(Event(EventKind.RECOVERY_FAILED))
        assert sm.state == CameraState.OFFLINE
        assert sm.consecutive_failures == 1

    def test_recovery_failed_at_budget_transitions_to_dead(self) -> None:
        sm = make_sm(
            start=CameraState.RECOVERING,
            consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1,
        )
        sm.dispatch(Event(EventKind.RECOVERY_FAILED))
        assert sm.state == CameraState.DEAD

    def test_device_removed_drops_to_offline(self) -> None:
        sm = make_sm(start=CameraState.RECOVERING, consecutive_failures=2)
        sm.dispatch(Event(EventKind.DEVICE_REMOVED))
        assert sm.state == CameraState.OFFLINE


class TestDeadTransitions:
    def test_operator_rearm_from_dead_to_offline_resets_counter(self) -> None:
        sm = make_sm(start=CameraState.DEAD, consecutive_failures=MAX_CONSECUTIVE_FAILURES)
        sm.dispatch(Event(EventKind.OPERATOR_REARM))
        assert sm.state == CameraState.OFFLINE
        assert sm.consecutive_failures == 0

    def test_operator_force_reconnect_from_dead_ignored(self) -> None:
        sm = make_sm(start=CameraState.DEAD, consecutive_failures=MAX_CONSECUTIVE_FAILURES)
        sm.dispatch(Event(EventKind.OPERATOR_FORCE_RECONNECT))
        assert sm.state == CameraState.DEAD

    def test_backoff_elapsed_from_dead_ignored(self) -> None:
        sm = make_sm(start=CameraState.DEAD)
        sm.dispatch(Event(EventKind.BACKOFF_ELAPSED))
        assert sm.state == CameraState.DEAD

    def test_device_added_from_dead_ignored(self) -> None:
        sm = make_sm(start=CameraState.DEAD)
        sm.dispatch(Event(EventKind.DEVICE_ADDED))
        assert sm.state == CameraState.DEAD


class TestBackoff:
    def test_backoff_schedule_at_increasing_failures(self) -> None:
        sm = make_sm(start=CameraState.OFFLINE)
        assert sm._compute_backoff() == 1.0  # n=0
        sm._consecutive_failures = 1
        assert sm._compute_backoff() == 2.0
        sm._consecutive_failures = 2
        assert sm._compute_backoff() == 4.0
        sm._consecutive_failures = 3
        assert sm._compute_backoff() == 8.0
        sm._consecutive_failures = 4
        assert sm._compute_backoff() == 16.0
        sm._consecutive_failures = 5
        assert sm._compute_backoff() == 32.0
        sm._consecutive_failures = 6
        assert sm._compute_backoff() == BACKOFF_CEILING_S
        sm._consecutive_failures = 9
        assert sm._compute_backoff() == BACKOFF_CEILING_S

    def test_schedule_callback_fires_on_recovery_failed(self) -> None:
        sm = make_sm(start=CameraState.RECOVERING)
        sm.dispatch(Event(EventKind.RECOVERY_FAILED))
        assert sm._schedule_calls  # type: ignore[attr-defined]
        assert sm._schedule_calls[-1] == 2.0  # type: ignore[attr-defined]  # n=1 → 2s


class TestThreadSafety:
    def test_concurrent_dispatch_no_drift(self) -> None:
        import threading

        sm = make_sm()

        def worker() -> None:
            for _ in range(500):
                sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sm.state == CameraState.HEALTHY

    def test_concurrent_error_then_rebuild(self) -> None:
        import threading

        sm = make_sm()

        def error_worker() -> None:
            sm.dispatch(Event(EventKind.WATCHDOG_FIRED, reason="stall"))
            sm.dispatch(Event(EventKind.SWAP_COMPLETED))

        def rebuild_worker() -> None:
            sm.dispatch(Event(EventKind.BACKOFF_ELAPSED))
            sm.dispatch(Event(EventKind.RECOVERY_SUCCEEDED))
            sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED, reason="post-rebuild frame"))

        t1 = threading.Thread(target=error_worker)
        t2 = threading.Thread(target=rebuild_worker)
        t1.start()
        t1.join()
        t2.start()
        t2.join()
        assert sm.state == CameraState.HEALTHY


class TestTransitionCallbacks:
    def test_transition_notification_fires_once_per_transition(self) -> None:
        sm = make_sm()
        sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED))
        sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED))
        # HEALTHY → HEALTHY doesn't fire a notification
        assert len(sm._transitions) == 0  # type: ignore[attr-defined]

        sm.dispatch(Event(EventKind.WATCHDOG_FIRED, reason="stall"))
        assert len(sm._transitions) == 1  # type: ignore[attr-defined]
        assert sm._transitions[0] == (  # type: ignore[attr-defined]
            CameraState.HEALTHY,
            CameraState.DEGRADED,
            "stall",
        )

    def test_full_recovery_sequence_records_all_transitions(self) -> None:
        sm = make_sm()
        sm.dispatch(Event(EventKind.WATCHDOG_FIRED, reason="stall"))
        sm.dispatch(Event(EventKind.SWAP_COMPLETED, reason="swapped"))
        sm.dispatch(Event(EventKind.BACKOFF_ELAPSED, reason="retry"))
        sm.dispatch(Event(EventKind.RECOVERY_SUCCEEDED, reason="reconnect ok"))
        sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED, reason="post-rebuild frame"))
        states = [(t[0], t[1]) for t in sm._transitions]  # type: ignore[attr-defined]
        assert states == [
            (CameraState.HEALTHY, CameraState.DEGRADED),
            (CameraState.DEGRADED, CameraState.OFFLINE),
            (CameraState.OFFLINE, CameraState.RECOVERING),
            (CameraState.RECOVERING, CameraState.HEALTHY),
        ]
