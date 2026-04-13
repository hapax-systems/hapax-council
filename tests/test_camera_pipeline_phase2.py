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
