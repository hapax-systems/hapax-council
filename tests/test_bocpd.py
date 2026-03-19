"""Tests for Bayesian Online Change Point Detection."""

from __future__ import annotations

import math

from agents.bocpd import BOCPDDetector, ChangePoint, MultiSignalBOCPD


class TestBOCPDDetector:
    def test_stable_signal_no_change_points(self):
        det = BOCPDDetector(hazard_lambda=50, threshold=0.5, signal_name="test")
        for i in range(100):
            det.update(5.0 + 0.01 * (i % 3), timestamp=float(i))
        assert len(det.recent_change_points) == 0

    def test_abrupt_shift_detected(self):
        """After a regime of stable values, an abrupt shift raises CP probability."""
        # High hazard rate = sensitive to changes
        det = BOCPDDetector(hazard_lambda=3, threshold=0.15, signal_name="flow")
        # Stable regime
        for i in range(20):
            det.update(5.0, timestamp=float(i))
        cps_before = len(det.recent_change_points)
        # Abrupt shift — the new regime should trigger a change point
        for i in range(20, 50):
            det.update(500.0, timestamp=float(i))
        cps_after = len(det.recent_change_points)
        assert cps_after > cps_before

    def test_change_point_has_fields(self):
        det = BOCPDDetector(hazard_lambda=10, threshold=0.2, signal_name="hr")
        # Force a change point with dramatic shift
        for i in range(20):
            det.update(0.0, timestamp=float(i))
        for i in range(20, 40):
            cp = det.update(100.0, timestamp=float(i))
            if cp is not None:
                assert isinstance(cp, ChangePoint)
                assert cp.signal_name == "hr"
                assert 0.0 <= cp.probability <= 1.0
                assert cp.run_length_before >= 0
                break

    def test_current_run_length_increases(self):
        det = BOCPDDetector(hazard_lambda=50, signal_name="test")
        for i in range(20):
            det.update(5.0, timestamp=float(i))
        rl = det.current_run_length
        assert rl > 0

    def test_reset_clears_state(self):
        det = BOCPDDetector(hazard_lambda=50, signal_name="test")
        for i in range(20):
            det.update(5.0, timestamp=float(i))
        det.reset()
        assert det.current_run_length == 0
        assert len(det.recent_change_points) == 0

    def test_no_nan_or_inf(self):
        det = BOCPDDetector(hazard_lambda=30, signal_name="test")
        for i in range(100):
            # Wild signal with zeros and large values
            val = 0.0 if i % 10 == 0 else float(i * 100)
            det.update(val, timestamp=float(i))
        rl = det.current_run_length
        assert not math.isnan(rl)
        assert not math.isinf(rl)


class TestMultiSignalBOCPD:
    def test_multiple_signals_independent(self):
        ms = MultiSignalBOCPD(
            signals=["flow", "audio"],
            hazard_lambda=10,
            threshold=0.1,
        )
        # Both stable at 0
        for i in range(50):
            ms.update({"flow": 0.0, "audio": 0.0}, timestamp=float(i))

        # Shift flow dramatically, keep audio stable
        for i in range(50, 100):
            ms.update({"flow": 100.0, "audio": 0.0}, timestamp=float(i))

        # Should detect change in flow
        flow_cps = [cp for cp in ms.all_recent_change_points if cp.signal_name == "flow"]
        assert len(flow_cps) > 0

    def test_dynamic_signal_addition(self):
        ms = MultiSignalBOCPD(signals=["flow"], hazard_lambda=50)
        ms.update({"flow": 1.0, "new_signal": 5.0})
        # new_signal should have been auto-created
        assert "new_signal" in ms._detectors

    def test_reset_all(self):
        ms = MultiSignalBOCPD(signals=["a", "b"], hazard_lambda=50)
        for _i in range(10):
            ms.update({"a": 1.0, "b": 2.0})
        ms.reset()
        assert len(ms.all_recent_change_points) == 0
