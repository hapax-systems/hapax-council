"""Tests for LogosMoodValenceBridge and LogosMoodCoherenceBridge calibration (Phase B+C).

Verifies:
1. Each accessor returns None when data files are missing.
2. Each accessor returns None when data is stale (>120s).
3. Each accessor returns correct bool when data is fresh.
4. RollingQuantile baselines work correctly with the bridges.
5. Edge cases: zero values, boundary conditions.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

# ── Valence bridge tests ────────────────────────────────────────────────


class TestMoodValenceBridge:
    """Tests for LogosMoodValenceBridge (Phase B calibration)."""

    def _make_bridge(self):
        from logos.api.app import LogosMoodValenceBridge

        return LogosMoodValenceBridge()

    def test_hrv_below_baseline_missing_file(self, tmp_path: Path) -> None:
        """Missing hrv.json → None."""
        bridge = self._make_bridge()
        with patch.object(type(bridge), "_load_watch_file", return_value=None):
            assert bridge.hrv_below_baseline() is None

    def test_hrv_below_baseline_stale(self, tmp_path: Path) -> None:
        """Stale hrv.json (>120s) → None."""
        bridge = self._make_bridge()
        stale_data = {
            "updated_at": "2020-01-01T00:00:00+00:00",
            "current": {"rmssd_ms": 40.0},
            "window_1h": {"min": 30, "max": 60, "mean": 45, "readings": 10},
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=stale_data):
            assert bridge.hrv_below_baseline() is None

    def test_hrv_below_baseline_fresh_below(self) -> None:
        """Fresh HRV below baseline → True after baseline bootstraps."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()

        # Bootstrap baseline with 15 observations at 50ms
        for _ in range(15):
            bridge._hrv_baseline.observe(50.0)

        data = {
            "updated_at": now,
            "current": {"rmssd_ms": 30.0},  # well below 50ms median
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            result = bridge.hrv_below_baseline()
            assert result is True

    def test_hrv_below_baseline_fresh_above(self) -> None:
        """Fresh HRV above baseline → False after baseline bootstraps."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()

        for _ in range(15):
            bridge._hrv_baseline.observe(50.0)

        data = {
            "updated_at": now,
            "current": {"rmssd_ms": 60.0},  # above 50ms median
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            result = bridge.hrv_below_baseline()
            assert result is False

    def test_skin_temp_drop_missing(self) -> None:
        """Missing skin_temp.json → None."""
        bridge = self._make_bridge()
        with patch.object(type(bridge), "_load_watch_file", return_value=None):
            assert bridge.skin_temp_drop() is None

    def test_skin_temp_drop_detected(self) -> None:
        """Skin temp drop >0.3°C from median → True."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()

        # Bootstrap baseline at 33°C
        for _ in range(15):
            bridge._skin_temp_tracker.observe(33.0)

        data = {
            "updated_at": now,
            "current": {"temp_c": 32.5},  # 0.5°C drop > 0.3°C threshold
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            result = bridge.skin_temp_drop()
            assert result is True

    def test_skin_temp_no_drop(self) -> None:
        """Skin temp stable → False."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()

        for _ in range(15):
            bridge._skin_temp_tracker.observe(33.0)

        data = {
            "updated_at": now,
            "current": {"temp_c": 33.1},  # slight increase, no drop
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            result = bridge.skin_temp_drop()
            assert result is False

    def test_sleep_debt_high_missing(self) -> None:
        """Missing perception-state.json → None."""
        bridge = self._make_bridge()
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert bridge.sleep_debt_high() is None

    def test_sleep_debt_high_good_sleep(self) -> None:
        """Sleep quality 0.9 → False (not in debt)."""
        bridge = self._make_bridge()
        perception = json.dumps(
            {
                "timestamp": time.time(),
                "sleep_quality": 0.9,
            }
        )
        with patch("pathlib.Path.read_text", return_value=perception):
            assert bridge.sleep_debt_high() is False

    def test_sleep_debt_high_bad_sleep(self) -> None:
        """Sleep quality 0.4 → True (in debt)."""
        bridge = self._make_bridge()
        perception = json.dumps(
            {
                "timestamp": time.time(),
                "sleep_quality": 0.4,
            }
        )
        with patch("pathlib.Path.read_text", return_value=perception):
            assert bridge.sleep_debt_high() is True

    def test_voice_pitch_missing_returns_none(self) -> None:
        """Missing voice pitch state → None."""
        bridge = self._make_bridge()
        with patch(
            "agents.hapax_daimonion.voice_pitch_baseline.operator_voice_pitch_is_elevated",
            return_value=None,
        ):
            assert bridge.voice_pitch_elevated() is None

    def test_voice_pitch_elevated_returns_true(self) -> None:
        """Elevated operator voice pitch → True."""
        bridge = self._make_bridge()
        with patch(
            "agents.hapax_daimonion.voice_pitch_baseline.operator_voice_pitch_is_elevated",
            return_value=True,
        ):
            assert bridge.voice_pitch_elevated() is True

    def test_voice_pitch_baseline_returns_false(self) -> None:
        """Fresh voice pitch at baseline → False."""
        bridge = self._make_bridge()
        with patch(
            "agents.hapax_daimonion.voice_pitch_baseline.operator_voice_pitch_is_elevated",
            return_value=False,
        ):
            assert bridge.voice_pitch_elevated() is False


# ── Coherence bridge tests ──────────────────────────────────────────────


class TestMoodCoherenceBridge:
    """Tests for LogosMoodCoherenceBridge (Phase C calibration)."""

    def _make_bridge(self):
        from logos.api.app import LogosMoodCoherenceBridge

        return LogosMoodCoherenceBridge()

    def test_hrv_variability_missing(self) -> None:
        """Missing hrv.json → None."""
        bridge = self._make_bridge()
        with patch.object(type(bridge), "_load_watch_file", return_value=None):
            assert bridge.hrv_variability_high() is None

    def test_hrv_variability_low(self) -> None:
        """Low HRV variability (tight range) → False."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()
        data = {
            "updated_at": now,
            "current": {"rmssd_ms": 45.0},
            "window_1h": {
                "min": 40,
                "max": 50,
                "mean": 45,
                "readings": 20,
            },
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            result = bridge.hrv_variability_high()
            # CV approx = (50-40)/(2*45) = 10/90 ≈ 0.11 < 0.30
            assert result is False

    def test_hrv_variability_high(self) -> None:
        """High HRV variability (wide range) → True."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()
        data = {
            "updated_at": now,
            "current": {"rmssd_ms": 45.0},
            "window_1h": {
                "min": 20,
                "max": 80,
                "mean": 50,
                "readings": 20,
            },
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            result = bridge.hrv_variability_high()
            # CV approx = (80-20)/(2*50) = 60/100 = 0.60 > 0.30
            assert result is True

    def test_hrv_variability_insufficient_readings(self) -> None:
        """Too few readings in window → None."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()
        data = {
            "updated_at": now,
            "current": {"rmssd_ms": 45.0},
            "window_1h": {
                "min": 20,
                "max": 80,
                "mean": 50,
                "readings": 3,
            },
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            assert bridge.hrv_variability_high() is None

    def test_respiration_missing_returns_none(self) -> None:
        """Missing respiration.json → None."""
        bridge = self._make_bridge()
        with patch.object(type(bridge), "_load_watch_file", return_value=None):
            assert bridge.respiration_irregular() is None

    def test_respiration_stale_returns_none(self) -> None:
        """Stale respiration.json → None."""
        bridge = self._make_bridge()
        data = {
            "updated_at": "2020-01-01T00:00:00+00:00",
            "current": {"breaths_per_min": 14.0},
            "window_1h": {"min": 12.0, "max": 20.0, "mean": 15.0, "readings": 8},
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            assert bridge.respiration_irregular() is None

    def test_respiration_regular_returns_false(self) -> None:
        """Low breath-rate variation → False."""
        bridge = self._make_bridge()
        data = {
            "updated_at": datetime.now(UTC).isoformat(),
            "current": {"breaths_per_min": 14.0},
            "window_1h": {"min": 13.0, "max": 15.0, "mean": 14.0, "readings": 12},
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            assert bridge.respiration_irregular() is False

    def test_respiration_irregular_returns_true(self) -> None:
        """High breath-rate variation → True."""
        bridge = self._make_bridge()
        data = {
            "updated_at": datetime.now(UTC).isoformat(),
            "current": {"breaths_per_min": 21.0},
            "window_1h": {"min": 10.0, "max": 22.0, "mean": 15.0, "readings": 12},
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            assert bridge.respiration_irregular() is True

    def test_movement_jitter_low_load(self) -> None:
        """Low physiological load → False."""
        bridge = self._make_bridge()
        perception = json.dumps(
            {
                "timestamp": time.time(),
                "physiological_load": 0.3,
            }
        )
        with patch("pathlib.Path.read_text", return_value=perception):
            assert bridge.movement_jitter_high() is False

    def test_movement_jitter_high_load(self) -> None:
        """High physiological load → True."""
        bridge = self._make_bridge()
        perception = json.dumps(
            {
                "timestamp": time.time(),
                "physiological_load": 0.8,
            }
        )
        with patch("pathlib.Path.read_text", return_value=perception):
            assert bridge.movement_jitter_high() is True

    def test_movement_jitter_missing(self) -> None:
        """Missing perception-state.json → None."""
        bridge = self._make_bridge()
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert bridge.movement_jitter_high() is None

    def test_skin_temp_volatility_missing(self) -> None:
        """Missing skin_temp.json → None."""
        bridge = self._make_bridge()
        with patch.object(type(bridge), "_load_watch_file", return_value=None):
            assert bridge.skin_temp_volatility_high() is None

    def test_skin_temp_volatility_stable(self) -> None:
        """Stable skin temp → False."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()

        # Bootstrap at 33.0°C
        for _ in range(15):
            bridge._skin_temp_vol_tracker.observe(33.0)

        data = {
            "updated_at": now,
            "current": {"temp_c": 33.05},  # 0.15% deviation < 10%
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            result = bridge.skin_temp_volatility_high()
            assert result is False

    def test_skin_temp_volatility_high(self) -> None:
        """Volatile skin temp → True."""
        bridge = self._make_bridge()
        now = datetime.now(UTC).isoformat()

        # Bootstrap at 33.0°C
        for _ in range(15):
            bridge._skin_temp_vol_tracker.observe(33.0)

        data = {
            "updated_at": now,
            "current": {"temp_c": 37.0},  # 12% deviation > 10%
        }
        with patch.object(type(bridge), "_load_watch_file", return_value=data):
            result = bridge.skin_temp_volatility_high()
            assert result is True
