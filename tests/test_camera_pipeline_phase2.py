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

    def test_clear_frame_observation_resets_prior_frame_proof(self, gst):
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        cam._last_frame_monotonic = time.monotonic()  # type: ignore[attr-defined]
        assert cam.last_frame_age_seconds < 1.0
        cam.clear_frame_observation()
        assert cam.last_frame_age_seconds == float("inf")

    def test_buffer_allocation_context_names_loopback_producer(
        self, gst, monkeypatch: pytest.MonkeyPatch
    ):
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        monkeypatch.setattr(cam, "_is_v4l2loopback_source", lambda: True)
        context = cam._buffer_allocation_error_context()
        assert "loopback producer" in context
        assert "USB bus-kick" not in context

    def test_buffer_allocation_context_names_physical_device(
        self, gst, monkeypatch: pytest.MonkeyPatch
    ):
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        monkeypatch.setattr(cam, "_is_v4l2loopback_source", lambda: False)
        context = cam._buffer_allocation_error_context()
        assert "USB bus-kick" in context
        assert "loopback producer" not in context

    def test_http_duplicate_last_good_is_opt_in(self, gst, monkeypatch: pytest.MonkeyPatch) -> None:
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        monkeypatch.delenv(
            "HAPAX_HTTP_JPEG_CAMERA_DUPLICATE_LAST_GOOD_ON_FETCH_FAILURE", raising=False
        )
        assert cam._http_duplicate_last_good_on_fetch_failure() is False
        monkeypatch.setenv("HAPAX_HTTP_JPEG_CAMERA_DUPLICATE_LAST_GOOD_ON_FETCH_FAILURE", "true")
        assert cam._http_duplicate_last_good_on_fetch_failure() is True

    def test_http_fetch_failure_does_not_push_last_good_by_default(self, gst) -> None:
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        frame, last_good = cam._select_http_frame_for_push(
            None,
            b"previous-frame",
            duplicate_last_good=False,
        )
        assert frame is None
        assert last_good == b"previous-frame"

    def test_http_fetch_failure_can_duplicate_last_good_when_enabled(self, gst) -> None:
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        frame, last_good = cam._select_http_frame_for_push(
            None,
            b"previous-frame",
            duplicate_last_good=True,
        )
        assert frame == b"previous-frame"
        assert last_good == b"previous-frame"

    def test_http_fresh_frame_replaces_last_good(self, gst) -> None:
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        frame, last_good = cam._select_http_frame_for_push(
            b"fresh-frame",
            b"previous-frame",
            duplicate_last_good=False,
        )
        assert frame == b"fresh-frame"
        assert last_good == b"fresh-frame"

    def test_stop_without_build_is_idempotent(self, gst):
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec(), gst=Gst, fps=30)
        cam.stop()  # no-op
        cam.teardown()  # no-op
        assert cam.is_playing() is False


class TestPipelineManagerBandwidthGuard:
    def test_build_rejects_1080p_spec(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        good = _make_spec("cam-ok", width=1280, height=720)
        bad = _make_spec("cam-1080p", width=1920, height=1080)
        pm = PipelineManager(specs=[good, bad], gst=Gst, glib=GLib, fps=30)
        with pytest.raises(ValueError, match="exceeds 720p"):
            pm.build()

    def test_build_accepts_720p_specs(self, gst):
        from agents.studio_compositor.pipeline_manager import PipelineManager

        Gst, GLib = gst
        specs = [_make_spec("cam-720p", width=1280, height=720)]
        pm = PipelineManager(specs=specs, gst=Gst, glib=GLib, fps=30)
        try:
            pm.build()  # must not raise
        finally:
            pm.stop()


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


class TestDecodeQueueCapacity:
    """Delta drop #31 cam-stability rollup Ring 2 Fix C regression pin.

    The MJPEG producer path has a ``queue`` element between ``v4l2src``
    and ``jpegdec`` to decouple decode latency from USB capture (drop
    #28 Finding 1, shipped in PR #807). The queue's original
    ``max-size-buffers=1`` could only absorb a single stalled jpegdec
    frame — brio-operator's drop #2 H6 (CPU jpegdec back-pressure)
    needed more cushion. Fix bumps to 5 buffers (~165 ms at 30 fps),
    still well under the 2 s STALENESS_THRESHOLD_S window.

    This test pins the capacity so any future refactor that touches
    the queue size is caught in CI.
    """

    def _mjpeg_spec(self, role: str = "decqtest") -> mock.Mock:
        spec = mock.Mock()
        spec.role = role
        spec.device = "/dev/null"
        spec.width = 1280
        spec.height = 720
        spec.input_format = "mjpeg"
        spec.pixel_format = None
        return spec

    def test_decode_queue_max_size_buffers_is_5(self, gst) -> None:
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        spec = self._mjpeg_spec()
        cam = CameraPipeline(spec=spec, gst=Gst, fps=30)
        # build() constructs every element before attempting to link;
        # even if link fails downstream the decode_queue is already
        # on self._pipeline with its properties set.
        try:
            cam.build()
        except Exception:
            pass
        pipeline = cam._pipeline
        assert pipeline is not None, "build() must construct the pipeline object"
        decode_queue = pipeline.get_by_name(f"decq_{spec.role}")
        assert decode_queue is not None, (
            "MJPEG decode_queue must be present in the pipeline (drop #28 F1 shipped in PR #807)"
        )
        max_buffers = decode_queue.get_property("max-size-buffers")
        assert max_buffers == 5, (
            f"decode_queue max-size-buffers must be 5 for 165 ms decode-stall "
            f"cushion (drop #31 Ring 2 Fix C); got {max_buffers}"
        )
        # leaky=downstream (2) is the pre-existing property and must
        # survive — sustained back-pressure must drop oldest frames at
        # the queue, not backpressure into v4l2src.
        leaky = decode_queue.get_property("leaky")
        assert int(leaky) == 2, (
            f"decode_queue must remain leaky=downstream (2) so jpegdec "
            f"stalls never backpressure into v4l2src; got {leaky}"
        )
        cam.teardown()


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


class TestStopWaitsForNullTransition:
    """FDL-1 regression pins (drop #52 + commit ec3d85883).

    Without a synchronous wait after ``set_state(NULL)``, fast rebuild
    cycles interrupt GStreamer's async cleanup before v4l2src's buffer
    pool releases its dmabuf handles. The pipeline bin stays in ASYNC
    NULL transition while ``teardown()`` drops the Python reference —
    the cleanup cascade stops mid-flight with dmabuf fds still open in
    the process fd table. Observed ~150 fds/min leak under the
    c920-desk rebuild-thrash fault documented in drop #51.

    Fix (``camera_pipeline.py::stop``): call ``get_state(5 * SECOND)``
    after ``set_state(NULL)`` to block until the NULL transition
    actually completes, logging a warning on FAILURE or
    timeout-mid-transition.
    """

    def _cam_with_mock_pipeline(self, gst, mock_pipeline):
        """Build a CameraPipeline and inject a mock _pipeline directly.

        Bypasses build() because the real construction requires a
        working v4l2 device. The stop() logic only touches
        ``self._pipeline`` and ``self._Gst``, so a mock is sufficient
        to exercise the FDL-1 fix path.
        """
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec("fdl1-test"), gst=Gst, fps=30)
        cam._pipeline = mock_pipeline
        cam._started = True
        return cam

    def test_stop_calls_get_state_with_5s_timeout(self, gst):
        """Regression pin: stop() MUST call get_state() after
        set_state(NULL) with a 5-second timeout. Reverting this to a
        bare set_state(NULL) without a wait will reintroduce the
        dmabuf leak."""
        Gst, _ = gst

        mock_pipeline = mock.Mock()
        mock_pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.NULL,
            Gst.State.VOID_PENDING,
        )

        cam = self._cam_with_mock_pipeline(gst, mock_pipeline)
        cam.stop()

        mock_pipeline.set_state.assert_called_once_with(Gst.State.NULL)
        mock_pipeline.get_state.assert_called_once()
        timeout_arg = mock_pipeline.get_state.call_args.kwargs.get("timeout")
        if timeout_arg is None:
            timeout_arg = mock_pipeline.get_state.call_args.args[0]
        assert timeout_arg == 5 * Gst.SECOND, (
            f"stop() must wait up to 5 seconds for NULL transition; "
            f"got timeout={timeout_arg}. Reverting this value lets fast "
            f"rebuild cycles interrupt cleanup and leak dmabufs. See "
            f"drop #52 + commit ec3d85883."
        )
        assert cam._started is False

    def test_stop_set_state_before_get_state(self, gst):
        """set_state(NULL) must be called BEFORE get_state() — the
        inverse ordering would block indefinitely on a still-PLAYING
        pipeline."""
        Gst, _ = gst

        call_order: list[str] = []
        mock_pipeline = mock.Mock()
        mock_pipeline.set_state.side_effect = lambda _state: call_order.append("set_state")
        mock_pipeline.get_state.side_effect = lambda **_kw: (
            call_order.append("get_state"),
            (Gst.StateChangeReturn.SUCCESS, Gst.State.NULL, Gst.State.VOID_PENDING),
        )[1]

        cam = self._cam_with_mock_pipeline(gst, mock_pipeline)
        cam.stop()

        assert call_order == ["set_state", "get_state"], (
            f"stop() must call set_state(NULL) THEN get_state(); observed order: {call_order}"
        )

    def test_stop_logs_warning_on_failure(self, gst, caplog):
        """When the NULL transition returns FAILURE, stop() must log a
        warning so operators notice resource leaks on pathological
        teardowns. Silent failure would let the leak rate accumulate
        unnoticed."""
        import logging

        Gst, _ = gst

        mock_pipeline = mock.Mock()
        mock_pipeline.get_state.return_value = (
            Gst.StateChangeReturn.FAILURE,
            Gst.State.PLAYING,
            Gst.State.NULL,
        )

        cam = self._cam_with_mock_pipeline(gst, mock_pipeline)
        with caplog.at_level(logging.WARNING, logger="agents.studio_compositor.camera_pipeline"):
            cam.stop()

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("NULL transition failed" in r.getMessage() for r in warnings), (
            f"stop() must log a WARNING on NULL transition FAILURE; "
            f"observed log records: {[r.getMessage() for r in warnings]}"
        )
        assert cam._started is False

    def test_stop_logs_warning_on_timeout_mid_transition(self, gst, caplog):
        """When get_state times out with the pipeline still not at
        NULL, stop() must log the stuck state so operators can
        correlate with fd-count or rebuild-rate alerts."""
        import logging

        Gst, _ = gst

        mock_pipeline = mock.Mock()
        mock_pipeline.get_state.return_value = (
            Gst.StateChangeReturn.ASYNC,
            Gst.State.READY,
            Gst.State.NULL,
        )

        cam = self._cam_with_mock_pipeline(gst, mock_pipeline)
        with caplog.at_level(logging.WARNING, logger="agents.studio_compositor.camera_pipeline"):
            cam.stop()

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("NULL transition timed out" in r.getMessage() for r in warnings), (
            f"stop() must log a WARNING when NULL transition times out; "
            f"observed log records: {[r.getMessage() for r in warnings]}"
        )

    def test_stop_silent_on_successful_transition(self, gst, caplog):
        """Normal teardowns (NULL reached within timeout) must NOT
        emit warnings — the warning log is reserved for pathological
        cases so it serves as a signal, not noise."""
        import logging

        Gst, _ = gst

        mock_pipeline = mock.Mock()
        mock_pipeline.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.NULL,
            Gst.State.VOID_PENDING,
        )

        cam = self._cam_with_mock_pipeline(gst, mock_pipeline)
        with caplog.at_level(logging.WARNING, logger="agents.studio_compositor.camera_pipeline"):
            cam.stop()

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warnings == [], (
            f"successful NULL transition must not log warnings; "
            f"got: {[r.getMessage() for r in warnings]}"
        )

    def test_stop_idempotent_when_pipeline_is_none(self, gst):
        """Existing invariant preserved by FDL-1: stop() with no
        pipeline built is a no-op, not a crash. This pins the early
        return at ``if self._pipeline is None: return`` so the fix
        doesn't accidentally regress the idempotency guarantee from
        ``test_stop_without_build_is_idempotent``.
        """
        from agents.studio_compositor.camera_pipeline import CameraPipeline

        Gst, _ = gst
        cam = CameraPipeline(_make_spec("idempotent-test"), gst=Gst, fps=30)
        assert cam._pipeline is None

        cam.stop()
        cam.stop()
        assert cam._started is False
