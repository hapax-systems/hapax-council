"""Phase 2 hot-swap architecture tests.

These tests exercise the CameraPipeline + FallbackPipeline + PipelineManager
without touching real USB cameras. GStreamer is used with videotestsrc as a
stand-in for v4l2src so tests run in CI without hardware.

See docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md
"""

from __future__ import annotations

import time
from unittest import mock

import pytest

pytest_plugins: list[str] = []


@pytest.fixture(scope="session")
def gst():
    """Import and initialize GStreamer once per test session."""
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

    Gst.init(None)
    return Gst, GLib


def _make_spec(role: str = "test_cam", width: int = 320, height: int = 240) -> mock.Mock:
    spec = mock.Mock()
    spec.role = role
    spec.device = "/dev/null"  # not opened — build is lazy
    spec.width = width
    spec.height = height
    spec.input_format = "raw"
    spec.pixel_format = "YUY2"
    return spec


class TestFallbackPipeline:
    def test_builds_and_reaches_playing(self, gst):
        from agents.studio_compositor.fallback_pipeline import FallbackPipeline

        Gst, _ = gst
        spec = _make_spec("fb-test")
        fb = FallbackPipeline(spec, gst=Gst, fps=30)
        fb.build()
        assert fb.sink_name == "fb_fb_test"
        assert fb.start() is True
        time.sleep(0.1)
        fb.teardown()

    def test_sink_name_collision_safe(self, gst):
        from agents.studio_compositor.fallback_pipeline import FallbackPipeline

        Gst, _ = gst
        fb1 = FallbackPipeline(_make_spec("cam-a"), gst=Gst, fps=30)
        fb2 = FallbackPipeline(_make_spec("cam-b"), gst=Gst, fps=30)
        fb1.build()
        fb2.build()
        assert fb1.sink_name != fb2.sink_name
        fb1.teardown()
        fb2.teardown()


class TestCameraPipelineConstruction:
    def test_sink_name_matches_role(self, gst):
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        spec = _make_spec("brio-operator")
        cam = CameraPipeline(spec, gst=Gst, fps=30)
        assert cam.sink_name == "cam_brio_operator"
        assert cam.role == "brio-operator"

    def test_rebuild_count_increments(self, gst):
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        spec = _make_spec("rebuild-test")
        cam = CameraPipeline(spec, gst=Gst, fps=30)
        assert cam.rebuild_count == 0
        # rebuild without a real device will fail at start() but still bump the counter
        cam.rebuild()
        assert cam.rebuild_count == 1
        cam.rebuild()
        assert cam.rebuild_count == 2
        cam.teardown()

    def test_last_frame_age_infinite_before_first_frame(self, gst):
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        assert cam.last_frame_age_seconds == float("inf")

    def test_stop_without_build_is_idempotent(self, gst):
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        cam.stop()  # no-op
        cam.teardown()  # no-op
        assert cam.is_playing() is False


class TestPipelineManagerSwap:
    def test_build_with_missing_devices_yields_offline(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        specs = [_make_spec("cam1"), _make_spec("cam2")]
        pm = PipelineManager(specs=specs, gst=Gst, glib=GLib, fps=30)
        pm.build()
        try:
            # Both devices are /dev/null — start fails cleanly and status is offline
            status = pm.status_all()
            assert "cam1" in status
            assert "cam2" in status
        finally:
            pm.stop()

    def test_swap_to_fallback_sets_listen_to(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        specs = [_make_spec("swap-test")]
        pm = PipelineManager(specs=specs, gst=Gst, glib=GLib, fps=30)
        pm.build()
        try:
            fake_src = Gst.ElementFactory.make("interpipesrc", "fake_consumer")
            pm.register_consumer("swap-test", fake_src)
            pm.swap_to_fallback("swap-test")
            listen_to = fake_src.get_property("listen-to")
            assert listen_to == "fb_swap_test"
        finally:
            pm.stop()

    def test_swap_to_primary_after_fallback(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        specs = [_make_spec("primary-swap")]
        pm = PipelineManager(specs=specs, gst=Gst, glib=GLib, fps=30)
        pm.build()
        try:
            fake_src = Gst.ElementFactory.make("interpipesrc", "fake_primary_consumer")
            pm.register_consumer("primary-swap", fake_src)
            pm.swap_to_fallback("primary-swap")
            assert fake_src.get_property("listen-to") == "fb_primary_swap"
            pm.swap_to_primary("primary-swap")
            assert fake_src.get_property("listen-to") == "cam_primary_swap"
        finally:
            pm.stop()

    def test_register_consumer_twice_idempotent(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        pm = PipelineManager(specs=[_make_spec("c1")], gst=Gst, glib=GLib, fps=30)
        pm.build()
        try:
            src1 = Gst.ElementFactory.make("interpipesrc", "c1_src_a")
            src2 = Gst.ElementFactory.make("interpipesrc", "c1_src_b")
            pm.register_consumer("c1", src1)
            pm.register_consumer("c1", src2)
            # Second registration replaces the first
            assert pm.get_consumer_element("c1") is src2
        finally:
            pm.stop()

    def test_swap_unknown_role_is_noop(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        pm = PipelineManager(specs=[_make_spec("exists")], gst=Gst, glib=GLib, fps=30)
        pm.build()
        try:
            # Should not raise
            pm.swap_to_fallback("does-not-exist")
            pm.swap_to_primary("also-not-there")
        finally:
            pm.stop()


class TestColdStartFrameFlowGrace:
    """Delta 2026-04-14-brio-operator-startup-stall-reproducible regression pins.

    The frame-flow watchdog consults ``_last_recovery_at[role]`` to skip
    its staleness check within ``_FRAME_FLOW_GRACE_S``. Before this fix
    the dict was only populated by the ``on_recovery`` callback after a
    camera had already recovered from a prior failure. On the very first
    HEALTHY transition after cold start, the dict entry was missing, the
    grace branch no-oped, the watchdog fired ``FRAME_FLOW_STALE`` ~1s
    after build() because the first frame hadn't arrived, and
    brio-operator lost ~3s of data per compositor restart on 4/4 cold
    starts observed.

    Fix: prime ``_last_recovery_at[role]`` to ``time.monotonic()`` at
    state-machine construction in ``build()``.
    """

    def test_build_primes_last_recovery_at_for_every_role(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        specs = [_make_spec("cam1"), _make_spec("cam2"), _make_spec("brio-operator")]
        pm = PipelineManager(specs=specs, gst=Gst, glib=GLib, fps=30)
        before = time.monotonic()
        pm.build()
        after = time.monotonic()
        try:
            for role in ("cam1", "cam2", "brio-operator"):
                assert role in pm._last_recovery_at, (
                    f"{role} missing from _last_recovery_at after build() — "
                    f"cold-start grace won't apply and FRAME_FLOW_STALE will "
                    f"fire before the first frame arrives"
                )
                primed_at = pm._last_recovery_at[role]
                assert before <= primed_at <= after, (
                    f"{role} primed_at={primed_at} outside build() window "
                    f"[{before}, {after}] — clock source mismatch with watchdog?"
                )
        finally:
            pm.stop()

    def test_watchdog_grace_window_absorbs_cold_start(self, gst):
        """After build(), ``_frame_flow_tick_once`` must NOT dispatch
        FRAME_FLOW_STALE for any role within _FRAME_FLOW_GRACE_S, even
        though no frames have arrived yet (all ages are +inf).
        """
        from agents.studio_compositor import pipeline_manager as pm_mod
        from agents.studio_compositor.camera_state_machine import CameraState
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        specs = [_make_spec("c1"), _make_spec("c2")]
        pm = PipelineManager(specs=specs, gst=Gst, glib=GLib, fps=30)
        pm.build()
        try:
            # Force every state machine into HEALTHY so the watchdog tick
            # reaches the staleness branch.
            with pm._lock:
                for sm in pm._state_machines.values():
                    sm._state = CameraState.HEALTHY

            dispatched: list[tuple[str, str]] = []

            # Record any dispatches during the tick.
            with mock.patch.object(pm_mod, "Event", wraps=pm_mod.Event):
                # Tag each SM with its role so the recorder can attribute
                # dispatches.
                for role, sm in pm._state_machines.items():
                    sm._role = role  # type: ignore[attr-defined]
                    # Monkeypatch only this instance's dispatch.
                    original = sm.dispatch

                    def make_recording(orig, r):
                        def _rec(event):
                            dispatched.append((r, event.kind.name))

                        return _rec

                    sm.dispatch = make_recording(original, role)  # type: ignore[method-assign]

                pm._frame_flow_tick_once()

            # Within the grace window, zero FRAME_FLOW_STALE dispatches.
            stale_events = [e for e in dispatched if e[1] == "FRAME_FLOW_STALE"]
            assert stale_events == [], (
                f"cold-start grace must absorb zero frames; got {stale_events}"
            )
        finally:
            pm.stop()

    def test_watchdog_fires_stale_after_grace_expires(self, gst):
        """Once the grace window passes, normal staleness checking resumes."""
        from agents.studio_compositor import pipeline_manager as pm_mod
        from agents.studio_compositor.camera_state_machine import CameraState
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        specs = [_make_spec("stale-cam")]
        pm = PipelineManager(specs=specs, gst=Gst, glib=GLib, fps=30)
        pm.build()
        try:
            # Age the primed _last_recovery_at beyond _FRAME_FLOW_GRACE_S.
            grace = pm_mod._FRAME_FLOW_GRACE_S
            with pm._lock:
                pm._last_recovery_at["stale-cam"] = time.monotonic() - grace - 1.0
                sm = pm._state_machines["stale-cam"]
                sm._state = CameraState.HEALTHY

            dispatched: list[str] = []

            def record(event):
                dispatched.append(event.kind.name)

            sm.dispatch = record  # type: ignore[method-assign]

            pm._frame_flow_tick_once()

            stale = [d for d in dispatched if d == "FRAME_FLOW_STALE"]
            assert len(stale) == 1, (
                f"after grace expires, watchdog MUST dispatch FRAME_FLOW_STALE "
                f"on the +inf-age first-frame state; got {dispatched}"
            )
        finally:
            pm.stop()

    def test_on_transition_callback_fires_on_error(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        transitions: list[tuple[str, str, str, str]] = []

        def on_transition(role, from_s, to_s, reason):
            transitions.append((role, from_s, to_s, reason))

        specs = [_make_spec("error-test")]
        pm = PipelineManager(specs=specs, gst=Gst, glib=GLib, fps=30, on_transition=on_transition)
        pm.build()
        try:
            # Force the role to active so the transition callback fires.
            # (Build-time start fails on /dev/null devices, leaving it offline.)
            with pm._lock:
                pm._status["error-test"] = "active"
            pm._handle_camera_error("error-test", "fake error")
            assert any(
                t[0] == "error-test" and t[1] == "active" and t[2] == "offline" for t in transitions
            )
        finally:
            pm.stop()
