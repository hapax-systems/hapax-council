"""Tests for shared.mood_calibration.RollingQuantile."""

from __future__ import annotations

import time

from shared.mood_calibration import RollingQuantile


class TestRollingQuantile:
    """Core RollingQuantile behavior."""

    def test_insufficient_samples_returns_none(self) -> None:
        """Before min_samples observations, is_above_quantile returns None."""
        rq = RollingQuantile(min_samples=5)
        for i in range(4):
            rq.observe(float(i), now=float(i))
        assert rq.is_above_quantile(0.5, now=4.0) is None

    def test_sufficient_samples_returns_bool(self) -> None:
        """After min_samples, is_above_quantile returns a bool."""
        rq = RollingQuantile(min_samples=5, window_s=100.0, stale_s=100.0)
        for i in range(10):
            rq.observe(float(i) / 10.0, now=float(i))
        result = rq.is_above_quantile(0.5, now=10.0)
        assert isinstance(result, bool)

    def test_value_above_quantile_returns_true(self) -> None:
        """Value above q80 returns True."""
        rq = RollingQuantile(min_samples=5, quantile=0.8, window_s=100.0, stale_s=100.0)
        # Observations: 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0
        for i in range(10):
            rq.observe((i + 1) / 10.0, now=float(i))
        # q80 of [0.1..1.0] = 0.82
        assert rq.is_above_quantile(0.95, now=10.0) is True

    def test_value_below_quantile_returns_false(self) -> None:
        """Value below q80 returns False."""
        rq = RollingQuantile(min_samples=5, quantile=0.8, window_s=100.0, stale_s=100.0)
        for i in range(10):
            rq.observe((i + 1) / 10.0, now=float(i))
        # 0.3 is well below q80
        assert rq.is_above_quantile(0.3, now=10.0) is False

    def test_stale_data_returns_none(self) -> None:
        """When most recent observation is too old, returns None."""
        rq = RollingQuantile(min_samples=5, stale_s=10.0, window_s=1000.0)
        for i in range(10):
            rq.observe(0.5, now=float(i))
        # Jump 20s into the future — stale
        assert rq.is_above_quantile(0.6, now=30.0) is None

    def test_window_expiry(self) -> None:
        """Old observations are pruned from the window."""
        rq = RollingQuantile(min_samples=5, window_s=10.0, stale_s=20.0)
        # Record 10 observations at t=0..9
        for i in range(10):
            rq.observe(float(i), now=float(i))
        # At t=15, observations at t=0..4 are expired (older than 10s)
        # Remaining: t=5..9 = 5 observations
        assert rq.current_quantile(now=15.0) is not None
        # At t=20, all but t=10+ are expired — but we didn't add any,
        # so observations at t=10..19 are needed
        assert rq.current_quantile(now=25.0) is None  # all expired

    def test_current_quantile_matches_expected(self) -> None:
        """Quantile computation matches expected value."""
        rq = RollingQuantile(min_samples=5, quantile=0.5, window_s=100.0, stale_s=100.0)
        # 5 observations: [10, 20, 30, 40, 50] → median = 30
        for i, v in enumerate([10.0, 20.0, 30.0, 40.0, 50.0]):
            rq.observe(v, now=float(i))
        q = rq.current_quantile(now=5.0)
        assert q is not None
        assert abs(q - 30.0) < 0.01

    def test_thread_safety(self) -> None:
        """Multiple threads can observe concurrently."""
        import threading

        rq = RollingQuantile(min_samples=10, window_s=100.0, stale_s=100.0)
        errors: list[Exception] = []

        def worker(start: int) -> None:
            try:
                for i in range(20):
                    rq.observe(float(start + i), now=float(start + i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestLogosMoodArousalBridge:
    """Tests for the calibrated LogosStimmungBridge."""

    def _make_bridge_with_mock_data(
        self,
        perception_data: dict,
        monkeypatch: object | None = None,
    ) -> object:
        """Create a bridge that reads from mock perception data."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()

        # Patch _load to return our mock data
        bridge._load = lambda: perception_data  # type: ignore[assignment]
        return bridge

    def test_ambient_rms_returns_none_when_stale(self) -> None:
        """Stale perception state → None."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        bridge._load = lambda: {"timestamp": time.time() - 200}  # type: ignore[assignment]
        assert bridge.ambient_audio_rms_high() is None

    def test_ambient_rms_returns_none_when_missing(self) -> None:
        """Missing perception state → None."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        bridge._load = lambda: None  # type: ignore[assignment]
        assert bridge.ambient_audio_rms_high() is None

    def test_ambient_rms_returns_none_insufficient_samples(self) -> None:
        """Before 10 samples, returns None (quantile not ready)."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        data = {"timestamp": time.time(), "audio_energy_rms": 0.5}
        bridge._load = lambda: data  # type: ignore[assignment]
        # Single call — only 1 sample, needs 10
        assert bridge.ambient_audio_rms_high() is None

    def test_ambient_rms_tracks_rolling_baseline(self) -> None:
        """After enough samples, returns bool based on quantile."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        ts = time.time()
        # Feed 15 samples with low RMS
        for i in range(15):
            data = {"timestamp": ts, "audio_energy_rms": 0.1 + i * 0.01}
            bridge._load = lambda d=data: d  # type: ignore[assignment]
            bridge.ambient_audio_rms_high()

        # Now test with a high value
        data = {"timestamp": ts, "audio_energy_rms": 0.9}
        bridge._load = lambda: data  # type: ignore[assignment]
        result = bridge.ambient_audio_rms_high()
        assert result is True

    def test_contact_mic_returns_none_when_missing_key(self) -> None:
        """Missing desk_onset_rate key → None."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        data = {"timestamp": time.time()}
        bridge._load = lambda: data  # type: ignore[assignment]
        assert bridge.contact_mic_onset_rate_high() is None

    def test_midi_clock_not_playing_returns_none(self) -> None:
        """MIDI not playing → None (no tempo evidence)."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        data = {"timestamp": time.time(), "midi_clock_transport": "STOPPED"}
        bridge._load = lambda: data  # type: ignore[assignment]
        assert bridge.midi_clock_bpm_high() is None

    def test_midi_clock_high_bpm_returns_true(self) -> None:
        """High BPM with PLAYING transport → True."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        data = {
            "timestamp": time.time(),
            "midi_clock_transport": "PLAYING",
            "midi_tempo_bpm": 150.0,
        }
        bridge._load = lambda: data  # type: ignore[assignment]
        assert bridge.midi_clock_bpm_high() is True

    def test_midi_clock_low_bpm_returns_false(self) -> None:
        """Low BPM with PLAYING transport → False."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        data = {
            "timestamp": time.time(),
            "midi_clock_transport": "PLAYING",
            "midi_tempo_bpm": 80.0,
        }
        bridge._load = lambda: data  # type: ignore[assignment]
        assert bridge.midi_clock_bpm_high() is False

    def test_hr_returns_none_when_zero(self) -> None:
        """Zero heart rate (sensor not active) → None."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        data = {"timestamp": time.time(), "heart_rate_bpm": 0}
        bridge._load = lambda: data  # type: ignore[assignment]
        assert bridge.hr_bpm_above_baseline() is None

    def test_hr_above_baseline_detects_elevation(self) -> None:
        """HR well above rolling median → True."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        ts = time.time()
        # Build baseline: 15 readings at ~70 BPM
        for i in range(15):
            data = {"timestamp": ts, "heart_rate_bpm": 70 + (i % 3)}
            bridge._load = lambda d=data: d  # type: ignore[assignment]
            bridge.hr_bpm_above_baseline()

        # Now spike to 95 (>70 + 15 = 85)
        data = {"timestamp": ts, "heart_rate_bpm": 95}
        bridge._load = lambda: data  # type: ignore[assignment]
        result = bridge.hr_bpm_above_baseline()
        assert result is True

    def test_hr_near_baseline_returns_false(self) -> None:
        """HR near rolling median → False."""
        from logos.api.app import LogosStimmungBridge

        bridge = LogosStimmungBridge()
        ts = time.time()
        for _i in range(15):
            data = {"timestamp": ts, "heart_rate_bpm": 70}
            bridge._load = lambda d=data: d  # type: ignore[assignment]
            bridge.hr_bpm_above_baseline()

        # 75 is below median (70) + 15 = 85
        data = {"timestamp": ts, "heart_rate_bpm": 75}
        bridge._load = lambda: data  # type: ignore[assignment]
        result = bridge.hr_bpm_above_baseline()
        assert result is False
