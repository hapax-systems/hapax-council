"""Watch signal reading and stress detection for voice daemon.

Reads JSON state files from ~/hapax-state/watch/ written by the watch-receiver
service. Provides stress detection (EDA + HRV) and watch connectivity checks
for the ContextGate veto chain and PresenceDetector.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from shared.config import HAPAX_HOME

WATCH_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "watch"


def read_watch_signal(
    path: Path, max_age_seconds: float = 300
) -> dict[str, Any] | None:
    """Read a JSON watch state file, returning None if missing or stale.

    Args:
        path: Path to the JSON file.
        max_age_seconds: Maximum file age in seconds before considering stale.

    Returns:
        Parsed JSON dict, or None if file is missing, unreadable, or stale.
    """
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        if time.time() - mtime > max_age_seconds:
            return None
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def is_stress_elevated(watch_dir: Path | None = None) -> bool:
    """Check if physiological stress indicators are elevated.

    Uses two signals:
    - HRV: current RMSSD dropped >30% below 1-hour mean
    - EDA: electrodermal activity event with duration >120s

    Returns False (graceful degradation) when no watch data available.

    Args:
        watch_dir: Override path to watch state directory.

    Returns:
        True if stress signals indicate elevated stress.
    """
    watch_dir = watch_dir or WATCH_STATE_DIR

    # Check HRV
    hrv_data = read_watch_signal(watch_dir / "hrv.json")
    if hrv_data is not None:
        current = hrv_data.get("current", {})
        window = hrv_data.get("window_1h", {})
        current_rmssd = current.get("rmssd_ms")
        mean_rmssd = window.get("mean")
        if current_rmssd is not None and mean_rmssd is not None and mean_rmssd > 0:
            if current_rmssd < mean_rmssd * 0.7:
                return True

    # Check EDA
    eda_data = read_watch_signal(watch_dir / "eda.json")
    if eda_data is not None:
        current = eda_data.get("current", {})
        if current.get("eda_event") and current.get("duration_seconds", 0) > 120:
            return True

    return False


def is_watch_connected(watch_dir: Path | None = None) -> bool:
    """Check if the watch is currently connected (data received within 60s).

    Args:
        watch_dir: Override path to watch state directory.

    Returns:
        True if connection.json exists and was updated within 60 seconds.
    """
    watch_dir = watch_dir or WATCH_STATE_DIR
    conn_data = read_watch_signal(watch_dir / "connection.json", max_age_seconds=60)
    return conn_data is not None


def send_haptic_tap(device_id: str | None = None, pattern: str = "hapax-presence-check") -> bool:
    """Send a haptic tap to the watch via KDE Connect notification.

    Args:
        device_id: KDE Connect device ID (auto-detected if None).
        pattern: Notification tag for haptic pattern routing.

    Returns:
        True if the notification was sent successfully.
    """
    import subprocess
    try:
        if device_id is None:
            # Auto-detect first available device
            result = subprocess.run(
                ["kdeconnect-cli", "--list-available", "--id-only"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            device_id = result.stdout.strip().split("\n")[0]

        result = subprocess.run(
            ["kdeconnect-cli", "--ping-msg", pattern, "--device", device_id],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


class WatchSignalReader:
    """Cached reader for watch state files.

    Avoids re-reading files on every gate check by caching results
    with a configurable TTL.
    """

    def __init__(self, watch_dir: Path | None = None, cache_ttl: float = 5.0) -> None:
        self._watch_dir = watch_dir or WATCH_STATE_DIR
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

    def read(self, filename: str, max_age_seconds: float = 300) -> dict[str, Any] | None:
        """Read a watch signal file with caching."""
        now = time.time()
        cached = self._cache.get(filename)
        if cached and now - cached[0] < self._cache_ttl:
            return cached[1]
        result = read_watch_signal(self._watch_dir / filename, max_age_seconds)
        self._cache[filename] = (now, result)
        return result

    def is_stress_elevated(self) -> bool:
        """Cached stress check."""
        return is_stress_elevated(self._watch_dir)

    def is_connected(self) -> bool:
        """Cached connectivity check."""
        return is_watch_connected(self._watch_dir)
