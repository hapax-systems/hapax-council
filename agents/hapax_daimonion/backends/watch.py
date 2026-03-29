"""Watch perception backend — physiological signals from Pixel Watch + phone.

Provides heart rate, HRV, stress, physiological load, and sleep quality
by reading JSON state files via WatchSignalReader.
"""

from __future__ import annotations

import logging
import time

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)


def _compute_physiological_load(
    current_rmssd: float | None,
    mean_rmssd: float | None,
    eda_duration: float,
) -> float:
    """Compute physiological load from HRV drop and EDA duration.

    Returns a float in [0.0, 1.0].
    """
    hrv_drop_pct = 0.0
    if current_rmssd is not None and mean_rmssd is not None and mean_rmssd > 0:
        hrv_drop_pct = max(0.0, 1.0 - current_rmssd / mean_rmssd)
    eda_component = min(eda_duration / 300.0, 0.5)
    return min(1.0, hrv_drop_pct + eda_component)


def _compute_sleep_quality(
    sleep_min: float,
    deep_min: float = 0.0,
    rem_min: float = 0.0,
) -> float:
    """Compute sleep quality score from duration and composition.

    Returns a float in [0.0, 1.0]. 7h sleep = 1.0.
    """
    score = min(sleep_min / 420.0, 1.0)
    if sleep_min < 360:
        score *= 0.8
    if deep_min + rem_min >= 120:
        score = min(score + 0.1, 1.0)
    return score


class WatchBackend:
    """PerceptionBackend that reads physiological signals from watch state files.

    Provides:
      - heart_rate_bpm: int
      - hrv_rmssd_ms: float
      - stress_elevated: bool
      - physiological_load: float (0.0-1.0)
      - watch_activity_state: str
      - sleep_quality: float (0.0-1.0)
    """

    def __init__(self, watch_dir=None, cache_ttl: float = 5.0) -> None:
        from agents.hapax_daimonion.watch_signals import WatchSignalReader

        self._reader = WatchSignalReader(watch_dir=watch_dir, cache_ttl=cache_ttl)

        self._b_heart_rate: Behavior[int] = Behavior(0)
        self._b_hrv_rmssd: Behavior[float] = Behavior(0.0)
        self._b_stress: Behavior[bool] = Behavior(False)
        self._b_load: Behavior[float] = Behavior(0.0)
        self._b_activity: Behavior[str] = Behavior("unknown")
        self._b_sleep: Behavior[float] = Behavior(1.0)
        self._b_connected: Behavior[bool] = Behavior(False)

    @property
    def name(self) -> str:
        return "watch"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset(
            {
                "heart_rate_bpm",
                "hrv_rmssd_ms",
                "stress_elevated",
                "physiological_load",
                "watch_activity_state",
                "sleep_quality",
                "watch_connected",
            }
        )

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        return True  # Graceful degradation — always register, use defaults

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()

        # Heart rate from heartrate.json (primary) or hrv.json (fallback)
        hr_data = self._reader.read("heartrate.json")
        if hr_data is not None:
            current = hr_data.get("current", {})
            hr = int(current.get("bpm", 0))
            self._b_heart_rate.update(hr, now)

        # HRV data (separate file, not always available)
        hrv_data = self._reader.read("hrv.json")
        current_rmssd = None
        mean_rmssd = None
        if hrv_data is not None:
            current = hrv_data.get("current", {})
            window = hrv_data.get("window_1h", {})
            current_rmssd = current.get("rmssd_ms")
            mean_rmssd = window.get("mean")
            # Fallback HR from HRV if heartrate.json not available
            if hr_data is None:
                hr = current.get("heart_rate_bpm", 0)
                self._b_heart_rate.update(hr, now)
            if current_rmssd is not None:
                self._b_hrv_rmssd.update(current_rmssd, now)
            activity = current.get("activity_state", "unknown")
            self._b_activity.update(activity, now)

        # Activity state from activity.json (if HRV didn't provide it)
        if hrv_data is None:
            act_data = self._reader.read("activity.json")
            if act_data is not None:
                activity = act_data.get("state", "unknown").lower()
                self._b_activity.update(activity, now)

        # EDA data
        eda_data = self._reader.read("eda.json")
        eda_duration = 0.0
        if eda_data is not None:
            current = eda_data.get("current", {})
            if current.get("eda_event"):
                eda_duration = current.get("duration_seconds", 0.0)

        # Compute stress
        stress = self._reader.is_stress_elevated()
        self._b_stress.update(stress, now)

        # Compute physiological load
        load = _compute_physiological_load(current_rmssd, mean_rmssd, eda_duration)
        self._b_load.update(load, now)

        # Sleep quality from phone health summary
        phone_data = self._reader.read("phone_health_summary.json", max_age_seconds=86400)
        if phone_data is not None:
            sleep_min = phone_data.get("sleep_duration_min", 420)
            deep_min = phone_data.get("deep_min", 0)
            rem_min = phone_data.get("rem_min", 0)
            sq = _compute_sleep_quality(sleep_min, deep_min, rem_min)
            self._b_sleep.update(sq, now)
        else:
            self._b_sleep.update(1.0, now)

        # Watch connected: connection.json exists and was updated within 5 minutes
        conn_data = self._reader.read("connection.json", max_age_seconds=300)
        connected = conn_data is not None
        self._b_connected.update(connected, now)

        behaviors["heart_rate_bpm"] = self._b_heart_rate
        behaviors["hrv_rmssd_ms"] = self._b_hrv_rmssd
        behaviors["stress_elevated"] = self._b_stress
        behaviors["physiological_load"] = self._b_load
        behaviors["watch_activity_state"] = self._b_activity
        behaviors["sleep_quality"] = self._b_sleep
        behaviors["watch_connected"] = self._b_connected

    def start(self) -> None:
        log.info("Watch backend started")

    def stop(self) -> None:
        log.info("Watch backend stopped")
