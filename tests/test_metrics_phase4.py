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
