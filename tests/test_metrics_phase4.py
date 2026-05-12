"""Phase 4 Prometheus exporter tests.

Pure Python — no GStreamer, no HTTP server. Exercises the metrics module's
public API with fake buffers and role labels.

See docs/superpowers/specs/2026-04-12-v4l2-prometheus-exporter-design.md
"""

from __future__ import annotations

from unittest import mock

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from agents.studio_compositor import metrics  # noqa: E402


def _sample(role: str, metric: object) -> float | None:
    """Read the current value of a labeled counter/gauge for a given role."""
    for s in metric.collect():
        for sample in s.samples:
            if sample.labels.get("role") == role and sample.name.endswith(
                ("_total", "_seconds", "_in_fallback", "_failures", "_state")
            ):
                return sample.value
    return None


class TestRegisterCamera:
    def test_register_initializes_label_set(self) -> None:
        metrics.register_camera("test-cam-a", "brio")
        # After registration the counter should exist with value 0
        v = metrics.CAM_FRAMES_TOTAL.labels(role="test-cam-a", model="brio")._value.get()
        assert v == 0

    def test_register_sets_state_healthy_by_default(self) -> None:
        metrics.register_camera("test-cam-b", "c920")
        healthy = metrics.CAM_STATE.labels(role="test-cam-b", state="healthy")._value.get()
        assert healthy == 1
        offline = metrics.CAM_STATE.labels(role="test-cam-b", state="offline")._value.get()
        assert offline == 0

    def test_register_resets_consecutive_failures(self) -> None:
        metrics.register_camera("test-cam-c", "brio")
        v = metrics.CAM_CONSECUTIVE_FAILURES.labels(role="test-cam-c")._value.get()
        assert v == 0


class TestPadProbeOnBuffer:
    def test_frame_increments_counter(self) -> None:
        metrics.register_camera("probe-role", "brio")
        fake_buf = mock.Mock()
        fake_buf.offset = 100
        fake_buf.get_size.return_value = 1024
        fake_info = mock.Mock()
        fake_info.get_buffer.return_value = fake_buf
        fake_pad = mock.Mock()

        before = metrics.CAM_FRAMES_TOTAL.labels(role="probe-role", model="brio")._value.get()
        metrics.pad_probe_on_buffer(fake_pad, fake_info, "probe-role")
        after = metrics.CAM_FRAMES_TOTAL.labels(role="probe-role", model="brio")._value.get()
        assert after == before + 1

    def test_sequence_gap_increments_kernel_drops(self) -> None:
        metrics.register_camera("drop-role", "brio")
        fake_info = mock.Mock()

        fake_buf = mock.Mock()
        fake_buf.offset = 10
        fake_buf.get_size.return_value = 1024
        fake_info.get_buffer.return_value = fake_buf
        metrics.pad_probe_on_buffer(mock.Mock(), fake_info, "drop-role")

        # Skip 3 frames: offset 14 means seq 11, 12, 13 were dropped
        fake_buf.offset = 14
        metrics.pad_probe_on_buffer(mock.Mock(), fake_info, "drop-role")

        drops = metrics.CAM_KERNEL_DROPS_TOTAL.labels(role="drop-role", model="brio")._value.get()
        assert drops == 3

    def test_pad_probe_with_none_buffer_is_safe(self) -> None:
        fake_info = mock.Mock()
        fake_info.get_buffer.return_value = None
        # Should not raise
        result = metrics.pad_probe_on_buffer(mock.Mock(), fake_info, "none-role")
        assert result == 0


class TestStateTransitionMetric:
    def test_transition_updates_state_gauges(self) -> None:
        metrics.register_camera("trans-role", "brio")
        metrics.on_state_transition("trans-role", "healthy", "degraded")

        degraded = metrics.CAM_STATE.labels(role="trans-role", state="degraded")._value.get()
        healthy = metrics.CAM_STATE.labels(role="trans-role", state="healthy")._value.get()
        assert degraded == 1
        assert healthy == 0

    def test_transition_increments_counter(self) -> None:
        metrics.register_camera("counter-role", "brio")
        before = metrics.CAM_TRANSITIONS_TOTAL.labels(
            role="counter-role", from_state="healthy", to_state="degraded"
        )._value.get()
        metrics.on_state_transition("counter-role", "healthy", "degraded")
        after = metrics.CAM_TRANSITIONS_TOTAL.labels(
            role="counter-role", from_state="healthy", to_state="degraded"
        )._value.get()
        assert after == before + 1


class TestReconnectMetrics:
    def test_on_reconnect_result_success(self) -> None:
        metrics.register_camera("rec-ok", "brio")
        before = metrics.CAM_RECONNECT_ATTEMPTS_TOTAL.labels(
            role="rec-ok", result="succeeded"
        )._value.get()
        metrics.on_reconnect_result("rec-ok", succeeded=True)
        after = metrics.CAM_RECONNECT_ATTEMPTS_TOTAL.labels(
            role="rec-ok", result="succeeded"
        )._value.get()
        assert after == before + 1

    def test_on_reconnect_result_failure(self) -> None:
        metrics.register_camera("rec-fail", "brio")
        before = metrics.CAM_RECONNECT_ATTEMPTS_TOTAL.labels(
            role="rec-fail", result="failed"
        )._value.get()
        metrics.on_reconnect_result("rec-fail", succeeded=False)
        after = metrics.CAM_RECONNECT_ATTEMPTS_TOTAL.labels(
            role="rec-fail", result="failed"
        )._value.get()
        assert after == before + 1


class TestSwapMetric:
    def test_on_swap_to_fallback(self) -> None:
        metrics.register_camera("swap-role", "brio")
        metrics.on_swap("swap-role", to_fallback=True)
        v = metrics.CAM_IN_FALLBACK.labels(role="swap-role")._value.get()
        assert v == 1
        metrics.on_swap("swap-role", to_fallback=False)
        v = metrics.CAM_IN_FALLBACK.labels(role="swap-role")._value.get()
        assert v == 0


class TestWatchdogMetric:
    def test_mark_watchdog_fed_updates_monotonic(self) -> None:
        import time

        metrics.mark_watchdog_fed()
        # Give the poll loop a chance to update the gauge (it runs every 1s).
        # For this test we just confirm the internal state advanced.
        assert metrics._last_watchdog_monotonic > 0
        assert metrics._last_watchdog_monotonic <= time.monotonic()


class TestCamerasHealthyGauge:
    """Queue 022 #4 / queue 023 #24: ``studio_compositor_cameras_healthy``
    must increment as cameras register HEALTHY and decrement as they
    transition out. Prior behaviour was to only set ``_total``; _healthy
    sat at 0 forever."""

    def test_register_increments_healthy_and_total(self) -> None:
        # Reset any state leaked from earlier tests.
        metrics._cam_models.clear()
        metrics._cam_states.clear()
        metrics._refresh_counts()

        assert metrics.COMP_CAMERAS_TOTAL._value.get() == 0
        assert metrics.COMP_CAMERAS_HEALTHY._value.get() == 0

        metrics.register_camera("healthy-a", "brio")
        metrics.register_camera("healthy-b", "c920")

        assert metrics.COMP_CAMERAS_TOTAL._value.get() == 2
        assert metrics.COMP_CAMERAS_HEALTHY._value.get() == 2

    def test_transition_out_of_healthy_decrements(self) -> None:
        metrics._cam_models.clear()
        metrics._cam_states.clear()
        metrics._refresh_counts()

        metrics.register_camera("tr-a", "brio")
        metrics.register_camera("tr-b", "c920")
        assert metrics.COMP_CAMERAS_HEALTHY._value.get() == 2

        metrics.on_state_transition("tr-a", "healthy", "degraded")
        assert metrics.COMP_CAMERAS_HEALTHY._value.get() == 1

        metrics.on_state_transition("tr-a", "degraded", "offline")
        assert metrics.COMP_CAMERAS_HEALTHY._value.get() == 1

        metrics.on_state_transition("tr-a", "offline", "recovering")
        assert metrics.COMP_CAMERAS_HEALTHY._value.get() == 1

        metrics.on_state_transition("tr-a", "recovering", "healthy")
        assert metrics.COMP_CAMERAS_HEALTHY._value.get() == 2


class TestMemoryFootprintGauge:
    """Queue 022 #6 / queue 023 #25: compositor self-reports its RSS so the
    grafana memory panel does not need to cross-reference node_exporter."""

    def test_update_memory_footprint_reads_vm_rss(self) -> None:
        metrics._update_memory_footprint()
        v = metrics.COMP_MEMORY_FOOTPRINT._value.get()
        # VmRSS is always > 0 for a running Python process.
        assert v > 0
        # And not absurdly large (upper bound 100 GB — sanity guard).
        assert v < 100 * 1024 * 1024 * 1024


class TestTtsClientTimeoutCounter:
    """Queue 023 #32: repeated DaimonionTtsClient readall timeouts
    should be visible in Prometheus, not only in the journal."""

    def test_record_timeout_increments(self) -> None:
        before = metrics.COMP_TTS_CLIENT_TIMEOUT_TOTAL._value.get()
        metrics.record_tts_client_timeout()
        metrics.record_tts_client_timeout()
        after = metrics.COMP_TTS_CLIENT_TIMEOUT_TOTAL._value.get()
        assert after == before + 2


class TestCompositorContainmentMetrics:
    def test_scaled_blit_cache_state_metrics(self) -> None:
        metrics.set_scaled_blit_cache_state(entries=3, bytes_used=4096)

        assert metrics.COMP_SCALED_BLIT_CACHE_ENTRIES._value.get() == 3
        assert metrics.COMP_SCALED_BLIT_CACHE_BYTES._value.get() == 4096

    def test_scaled_blit_cache_eviction_counter(self) -> None:
        before = metrics.COMP_SCALED_BLIT_CACHE_EVICTIONS_TOTAL.labels(
            reason="capacity"
        )._value.get()

        metrics.record_scaled_blit_cache_eviction(reason="capacity", count=2)

        after = metrics.COMP_SCALED_BLIT_CACHE_EVICTIONS_TOTAL.labels(
            reason="capacity"
        )._value.get()
        assert after == before + 2

    def test_v4l2_appsink_copy_counters(self) -> None:
        before_bytes = metrics.COMP_V4L2_APPSINK_COPIED_BYTES_TOTAL._value.get()
        before_frames = metrics.COMP_V4L2_APPSINK_COPIED_FRAMES_TOTAL._value.get()

        metrics.record_v4l2_appsink_copy(1024)

        assert metrics.COMP_V4L2_APPSINK_COPIED_BYTES_TOTAL._value.get() == before_bytes + 1024
        assert metrics.COMP_V4L2_APPSINK_COPIED_FRAMES_TOTAL._value.get() == before_frames + 1


class TestCameraFrameIntervalHistogram:
    """Livestream-performance-map Sprint 6 F4 / W1.3: per-camera frame
    interval histogram. The research map's headline target is
    ``p99 ≤ 34 ms``; prior to this, the compositor published
    frames_total (counter) + last_frame_age_seconds (gauge) which can
    compute mean fps but cannot produce p99 — a long tail of 100 ms
    frames hides inside the 30 fps counter-derived mean."""

    def test_frame_interval_histogram_exists_with_expected_buckets(self) -> None:
        assert metrics.CAM_FRAME_INTERVAL is not None
        # Force bucket sample emission by observing once.
        metrics.CAM_FRAME_INTERVAL.labels(role="hist-test", model="brio").observe(0.033)
        expected = (
            0.005,
            0.010,
            0.016,
            0.020,
            0.025,
            0.030,
            0.033,
            0.040,
            0.050,
            0.067,
            0.100,
            0.200,
            0.500,
        )
        # Use the parent metric's .collect(); the labeled child's
        # .collect() emits samples without the ``role``/``model`` labels.
        samples = [
            s
            for metric in metrics.CAM_FRAME_INTERVAL.collect()
            for s in metric.samples
            if s.name.endswith("_bucket") and s.labels.get("role") == "hist-test"
        ]
        observed = sorted({float(s.labels["le"]) for s in samples if s.labels.get("le") != "+Inf"})
        assert observed == sorted(expected), (
            f"bucket edges drifted: {observed} != {sorted(expected)}"
        )

    def test_pad_probe_observes_frame_interval(self) -> None:
        metrics.register_camera("interval-probe", "brio")
        fake_buf = mock.Mock()
        fake_buf.offset = 100
        fake_buf.get_size.return_value = 1024
        fake_info = mock.Mock()
        fake_info.get_buffer.return_value = fake_buf

        # First probe: no prior timestamp, so no histogram observation.
        before_count = _histogram_total_count(metrics.CAM_FRAME_INTERVAL, role="interval-probe")
        metrics.pad_probe_on_buffer(mock.Mock(), fake_info, "interval-probe")
        after_first = _histogram_total_count(metrics.CAM_FRAME_INTERVAL, role="interval-probe")
        assert after_first == before_count, "first probe must not observe (prev_mono == 0)"

        # Second probe: now there is a prior timestamp, so one observation.
        fake_buf.offset = 101
        metrics.pad_probe_on_buffer(mock.Mock(), fake_info, "interval-probe")
        after_second = _histogram_total_count(metrics.CAM_FRAME_INTERVAL, role="interval-probe")
        assert after_second == after_first + 1, (
            f"second probe expected +1 observation, got {after_second - after_first}"
        )


class TestCompositorVramGauge:
    """Sprint 1 F4 / W1.9: compositor self-reports its GPU VRAM footprint
    via nvidia-smi --query-compute-apps. On CI / test environments without
    nvidia-smi the gauge stays at 0 (no crash)."""

    def test_update_gpu_vram_does_not_crash_without_nvidia_smi(self) -> None:
        # Don't patch anything — on CI nvidia-smi is missing, so this
        # exercises the FileNotFoundError path. On the dev rig it
        # exercises the happy path. Either way the call must not raise.
        metrics._update_gpu_vram()
        v = metrics.COMP_GPU_VRAM_BYTES._value.get()
        # VRAM is bytes; valid values are 0 (no context / missing
        # nvidia-smi) or a positive integer up to ~100 GB.
        assert v >= 0
        assert v < 100 * 1024 * 1024 * 1024


class TestAudioDspHistogram:
    """Sprint 3 F5 / W1.7: audio DSP timing histogram surfaces whether the
    93 fps DSP loop is keeping up with its 10.7 ms chunk period."""

    def test_observe_dsp_ms_registers_histogram_and_records(self) -> None:
        from agents.studio_compositor import audio_capture

        # Reset module-level handle so we exercise the registration path.
        # Use a local fresh value to avoid cross-test interference.
        before = 0
        if audio_capture._AUDIO_DSP_MS_HISTOGRAM is not None:
            samples = list(audio_capture._AUDIO_DSP_MS_HISTOGRAM.collect())
            for metric in samples:
                for s in metric.samples:
                    if s.name.endswith("_count"):
                        before = int(s.value)

        audio_capture._observe_dsp_ms(3.5)
        audio_capture._observe_dsp_ms(11.2)

        assert audio_capture._AUDIO_DSP_MS_HISTOGRAM is not None
        after = 0
        for metric in audio_capture._AUDIO_DSP_MS_HISTOGRAM.collect():
            for s in metric.samples:
                if s.name.endswith("_count"):
                    after = int(s.value)
        assert after == before + 2


def _histogram_total_count(hist: object, role: str) -> int:
    """Helper — sum the per-labelset ``_count`` of a labeled Histogram."""
    total = 0
    for metric in hist.collect():  # type: ignore[attr-defined]
        for s in metric.samples:
            if s.name.endswith("_count") and s.labels.get("role") == role:
                total += int(s.value)
    return total


class TestConcurrentUpdates:
    def test_concurrent_pad_probes_no_drift(self) -> None:
        import threading

        metrics.register_camera("concurrent-role", "brio")
        fake_info = mock.Mock()
        fake_buf = mock.Mock()
        fake_buf.offset = 0
        fake_buf.get_size.return_value = 256
        fake_info.get_buffer.return_value = fake_buf

        def worker() -> None:
            for _ in range(500):
                metrics.pad_probe_on_buffer(mock.Mock(), fake_info, "concurrent-role")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        frames = metrics.CAM_FRAMES_TOTAL.labels(role="concurrent-role", model="brio")._value.get()
        # Exactly 10 * 500 = 5000 increments expected
        assert frames == 5000
