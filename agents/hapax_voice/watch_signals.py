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
    """Check if the watch is currently connected via WiFi or Bluetooth.

    Fuses two signals: WiFi (connection.json updated within 60s) and BLE
    (bluetoothctl shows device connected or in range). Either is sufficient.

    Args:
        watch_dir: Override path to watch state directory.

    Returns:
        True if watch is reachable via WiFi or Bluetooth.
    """
    watch_dir = watch_dir or WATCH_STATE_DIR

    # WiFi path: connection.json freshness
    conn_data = read_watch_signal(watch_dir / "connection.json", max_age_seconds=60)
    if conn_data is not None:
        return True

    # BLE fallback: check Bluetooth proximity
    bt_nearby = is_watch_bt_nearby(watch_dir=watch_dir)
    if bt_nearby is True:
        return True

    return False


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


def is_watch_bt_nearby(
    bt_mac: str | None = None, watch_dir: Path | None = None
) -> bool | None:
    """Check if the Pixel Watch is nearby via Bluetooth LE.

    Complements WiFi connectivity — BLE works even when WiFi is suspended
    on the watch (screen off, idle). Returns None if BT is unavailable or
    MAC not configured, so callers can fall through to WiFi-based checks.

    The watch BT MAC can be set in connection.json (field "bt_mac") by the
    Wear OS app during its first WiFi handshake, or hardcoded.

    Args:
        bt_mac: Bluetooth MAC address to look for. Auto-read from
            connection.json if not provided.
        watch_dir: Override path to watch state directory.

    Returns:
        True if device is connected/paired and reachable, False if BT is
        available but device not found, None if BT is unavailable.
    """
    import subprocess

    watch_dir = watch_dir or WATCH_STATE_DIR

    # Resolve MAC address
    if bt_mac is None:
        conn_file = watch_dir / "connection.json"
        if conn_file.exists():
            try:
                data = json.loads(conn_file.read_text())
                bt_mac = data.get("bt_mac")
            except (json.JSONDecodeError, OSError):
                pass
        if bt_mac is None:
            return None

    try:
        result = subprocess.run(
            ["bluetoothctl", "info", bt_mac],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return False
        # "Connected: yes" means active connection
        # "Paired: yes" + RSSI means in range
        output = result.stdout
        if "Connected: yes" in output:
            return True
        if "RSSI:" in output:
            return True  # In range even if not connected
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


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
