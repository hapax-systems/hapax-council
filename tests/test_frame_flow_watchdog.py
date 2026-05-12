"""Frame-flow watchdog tests for PipelineManager.

Pure-Python tests — no GStreamer, no real cameras. Constructs a
PipelineManager with mocked ``gst``/``glib`` modules, injects state
directly, and drives ``_frame_flow_tick_once`` to exercise the watchdog
logic. Also covers the SWAP_COMPLETED dispatch from ``swap_to_fallback``.

Livestream-performance-map W5 NEW (silent-failure class).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from agents.studio_compositor.camera_state_machine import (
    STALENESS_THRESHOLD_S,
    CameraState,
    CameraStateMachine,
    Event,
    EventKind,
)
from agents.studio_compositor.pipeline_manager import (
    _FRAME_FLOW_GRACE_S,
    _RECOVERY_FRAME_PROOF_S,
    PipelineManager,
)


def _make_pm(roles: list[str]) -> PipelineManager:
    specs = []
    for role in roles:
        spec = MagicMock()
        spec.role = role
        spec.camera_class = "test"
        specs.append(spec)
    pm = PipelineManager(specs=specs, gst=MagicMock(), glib=MagicMock(), fps=30)
    # Bypass build() — construct minimal state directly.
    for role in roles:
        sm = CameraStateMachine(role=role)
        pm._state_machines[role] = sm
        cam = MagicMock()
        cam.last_frame_age_seconds = 0.0
        pm._cameras[role] = cam
    return pm


def _set_age(pm: PipelineManager, role: str, age: float) -> None:
    pm._cameras[role].last_frame_age_seconds = age


class TestFrameFlowWatchdog:
    def test_healthy_recent_frames_no_dispatch(self) -> None:
        pm = _make_pm(["brio-operator"])
        _set_age(pm, "brio-operator", 0.05)  # 50 ms — fresh
        pm._frame_flow_tick_once()
        assert pm._state_machines["brio-operator"].state == CameraState.HEALTHY

    def test_healthy_stale_frames_dispatches_stale(self) -> None:
        pm = _make_pm(["brio-operator"])
        _set_age(pm, "brio-operator", STALENESS_THRESHOLD_S + 1.0)
        pm._frame_flow_tick_once()
        # FRAME_FLOW_STALE → DEGRADED
        assert pm._state_machines["brio-operator"].state == CameraState.DEGRADED

    def test_post_recovery_grace_suppresses_dispatch(self) -> None:
        pm = _make_pm(["brio-operator"])
        _set_age(pm, "brio-operator", STALENESS_THRESHOLD_S + 1.0)
        # Mark the camera as freshly recovered. Within the grace window
        # the watchdog must NOT dispatch even though frames are stale.
        pm._last_recovery_at["brio-operator"] = time.monotonic()
        pm._frame_flow_tick_once()
        assert pm._state_machines["brio-operator"].state == CameraState.HEALTHY

    def test_grace_expires_and_then_dispatches(self) -> None:
        pm = _make_pm(["brio-operator"])
        _set_age(pm, "brio-operator", STALENESS_THRESHOLD_S + 1.0)
        # Recovery happened more than the grace window ago.
        pm._last_recovery_at["brio-operator"] = time.monotonic() - _FRAME_FLOW_GRACE_S - 1.0
        pm._frame_flow_tick_once()
        assert pm._state_machines["brio-operator"].state == CameraState.DEGRADED

    def test_offline_camera_ignored(self) -> None:
        pm = _make_pm(["brio-operator"])
        # OFFLINE cameras are owned by the reconnect supervisor. The
        # frame-flow watchdog must not add extra failure pressure there.
        pm._state_machines["brio-operator"]._state = CameraState.OFFLINE
        _set_age(pm, "brio-operator", STALENESS_THRESHOLD_S + 5.0)
        pm._frame_flow_tick_once()
        assert pm._state_machines["brio-operator"].state == CameraState.OFFLINE

    def test_recovering_camera_inside_grace_waits_for_frame_proof(self) -> None:
        pm = _make_pm(["brio-operator"])
        pm._state_machines["brio-operator"]._state = CameraState.RECOVERING
        pm._last_recovery_at["brio-operator"] = time.monotonic()
        _set_age(pm, "brio-operator", 0.05)
        pm._frame_flow_tick_once()
        assert pm._state_machines["brio-operator"].state == CameraState.RECOVERING

    def test_recovering_camera_promotes_after_frame_proof_window(self) -> None:
        pm = _make_pm(["brio-operator"])
        pm._state_machines["brio-operator"]._state = CameraState.RECOVERING
        pm._last_recovery_at["brio-operator"] = time.monotonic() - _RECOVERY_FRAME_PROOF_S - 0.1
        _set_age(pm, "brio-operator", 0.05)
        pm._frame_flow_tick_once()
        assert pm._state_machines["brio-operator"].state == CameraState.HEALTHY

    def test_recovering_camera_stale_after_grace_goes_offline(self) -> None:
        pm = _make_pm(["brio-operator"])
        pm._state_machines["brio-operator"]._state = CameraState.RECOVERING
        pm._last_recovery_at["brio-operator"] = time.monotonic() - _FRAME_FLOW_GRACE_S - 1.0
        _set_age(pm, "brio-operator", STALENESS_THRESHOLD_S + 5.0)
        pm._frame_flow_tick_once()
        assert pm._state_machines["brio-operator"].state == CameraState.OFFLINE

    def test_only_stale_camera_is_dispatched_in_mixed_set(self) -> None:
        pm = _make_pm(["brio-operator", "c920-desk", "brio-room"])
        _set_age(pm, "brio-operator", STALENESS_THRESHOLD_S + 1.0)  # stale
        _set_age(pm, "c920-desk", 0.03)  # fresh
        _set_age(pm, "brio-room", 0.02)  # fresh
        pm._frame_flow_tick_once()
        assert pm._state_machines["brio-operator"].state == CameraState.DEGRADED
        assert pm._state_machines["c920-desk"].state == CameraState.HEALTHY
        assert pm._state_machines["brio-room"].state == CameraState.HEALTHY


class TestSwapToFallbackSwapCompletedDispatch:
    def test_dispatches_swap_completed_when_degraded(self) -> None:
        pm = _make_pm(["brio-operator"])
        # Wire interpipe + fallback mocks so swap_to_fallback can run.
        src = MagicMock()
        fb = MagicMock()
        fb.sink_name = "fb_brio_operator"
        pm._interpipe_srcs["brio-operator"] = src
        pm._fallbacks["brio-operator"] = fb

        # Force FSM into DEGRADED so the dispatch path activates.
        pm._state_machines["brio-operator"]._state = CameraState.DEGRADED

        pm.swap_to_fallback("brio-operator")
        # SWAP_COMPLETED moves DEGRADED → OFFLINE.
        assert pm._state_machines["brio-operator"].state == CameraState.OFFLINE

    def test_does_not_dispatch_when_healthy(self) -> None:
        pm = _make_pm(["brio-operator"])
        src = MagicMock()
        fb = MagicMock()
        fb.sink_name = "fb_brio_operator"
        pm._interpipe_srcs["brio-operator"] = src
        pm._fallbacks["brio-operator"] = fb

        # FSM is HEALTHY — registration-time path. swap_to_fallback should
        # set the listen-to but NOT dispatch SWAP_COMPLETED.
        assert pm._state_machines["brio-operator"].state == CameraState.HEALTHY
        pm.swap_to_fallback("brio-operator")
        assert pm._state_machines["brio-operator"].state == CameraState.HEALTHY


class TestEndToEndStaleRecoveryLoop:
    def test_stale_dispatch_swap_completes_offline_progression(self) -> None:
        """Simulates the silent-failure scenario:
        HEALTHY → stale → FRAME_FLOW_STALE → DEGRADED → swap → SWAP_COMPLETED → OFFLINE.
        """
        pm = _make_pm(["brio-synths"])
        # Wire fallback infra for the post-degraded swap.
        src = MagicMock()
        fb = MagicMock()
        fb.sink_name = "fb_brio_synths"
        pm._interpipe_srcs["brio-synths"] = src
        pm._fallbacks["brio-synths"] = fb
        # Replace the FSM with one whose on_swap_to_fallback callback
        # actually invokes pm.swap_to_fallback (the production wiring).
        sm = CameraStateMachine(
            role="brio-synths",
            on_swap_to_fallback=lambda: pm.swap_to_fallback("brio-synths"),
        )
        pm._state_machines["brio-synths"] = sm

        # Stale frames — watchdog should fire.
        _set_age(pm, "brio-synths", STALENESS_THRESHOLD_S + 5.0)
        pm._frame_flow_tick_once()

        # End state: OFFLINE (DEGRADED briefly, then SWAP_COMPLETED → OFFLINE).
        assert sm.state == CameraState.OFFLINE


class TestStopJoinsWatchdog:
    def test_start_and_stop_joins_watchdog_thread(self) -> None:
        pm = _make_pm(["brio-operator"])
        pm._start_frame_flow_watchdog()
        assert pm._frame_flow_thread is not None
        assert pm._frame_flow_thread.is_alive()
        pm._frame_flow_stop.set()
        pm._frame_flow_thread.join(timeout=3.0)
        assert not pm._frame_flow_thread.is_alive()


class TestFrameFlowFromHealthyToDegradedToFsm:
    def test_dispatched_event_has_watchdog_source(self) -> None:
        captured: list[Event] = []
        pm = _make_pm(["brio-operator"])

        # Replace the SM with one whose dispatch we capture, while still
        # forwarding to a real CameraStateMachine so transitions happen.
        real_sm = CameraStateMachine(role="brio-operator")
        original = real_sm.dispatch

        def capture_and_forward(event: Event) -> None:
            captured.append(event)
            original(event)

        real_sm.dispatch = capture_and_forward  # type: ignore[method-assign]
        pm._state_machines["brio-operator"] = real_sm

        _set_age(pm, "brio-operator", STALENESS_THRESHOLD_S + 1.0)
        pm._frame_flow_tick_once()

        assert len(captured) == 1
        assert captured[0].kind == EventKind.FRAME_FLOW_STALE
        assert captured[0].source == "watchdog"
        assert "pad-probe age" in captured[0].reason
