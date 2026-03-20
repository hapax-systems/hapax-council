"""Watch signal reading and stress detection for voice daemon.

Reads JSON state files from ~/hapax-state/watch/ written by the watch-receiver
service. Provides stress detection (EDA + HRV) and watch connectivity checks
for the ContextGate veto chain and PresenceDetector.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from shared.config import HAPAX_HOME

WATCH_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "watch"


def read_watch_signal(path: Path, max_age_seconds: float = 300) -> dict[str, Any] | None:
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
    return is_watch_bt_nearby(watch_dir=watch_dir) is True


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
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return False
            device_id = result.stdout.strip().split("\n")[0]

        result = subprocess.run(
            ["kdeconnect-cli", "--ping-msg", pattern, "--device", device_id],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def is_watch_bt_nearby(bt_mac: str | None = None, watch_dir: Path | None = None) -> bool | None:
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
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return False
        # "Connected: yes" means active connection
        # "Paired: yes" + RSSI means in range
        output = result.stdout
        return "Connected: yes" in output or "RSSI:" in output
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def is_phone_connected(watch_dir: Path | None = None) -> bool:
    """Check if the phone is currently connected via heartbeat.

    Reads phone_connection.json, considers stale after 120s.

    Args:
        watch_dir: Override path to watch state directory.

    Returns:
        True if phone heartbeat is fresh (within 120s).
    """
    watch_dir = watch_dir or WATCH_STATE_DIR
    conn_data = read_watch_signal(watch_dir / "phone_connection.json", max_age_seconds=120)
    return conn_data is not None


# ── Stimmung Haptic Vocabulary ───────────────────────────────────────────────

# Keywords map to haptic patterns on the watch. The watch's HapticNotificationListener
# matches these keywords and plays the corresponding vibration waveform.
HAPTIC_STIMMUNG_KEYWORDS = {
    "nominal": "hapax stimmung calm",
    "cautious": "hapax stimmung cautious",
    "degraded": "hapax stimmung degraded",
    "flow": "hapax stimmung flow",  # silence = the signal
    "stress_ack": "hapax stress ack",
    "transition": "hapax transition",
}

# Rate limit: at most one stimmung haptic every 5 minutes
_MIN_HAPTIC_INTERVAL_S = 300.0
_last_haptic_time: float = 0.0
_last_haptic_stance: str = ""

_log = logging.getLogger(__name__)


def send_stimmung_haptic(stance: str, *, force: bool = False) -> bool:
    """Send a Stimmung-encoded haptic pattern to the watch.

    Only fires on stance transitions, and at most once per 5 minutes.
    The "flow" stance sends nothing (silence IS the signal).

    Args:
        stance: Current Stimmung stance ("nominal", "cautious", "degraded", "critical").
        force: Bypass rate limiting (for testing).

    Returns:
        True if a haptic was sent (or suppressed for flow).
    """
    global _last_haptic_time, _last_haptic_stance

    now = time.time()

    # Only fire on transitions
    if stance == _last_haptic_stance and not force:
        return False

    # Rate limit
    if not force and (now - _last_haptic_time) < _MIN_HAPTIC_INTERVAL_S:
        return False

    _last_haptic_stance = stance

    # Flow = silence (no haptic sent, but we record the transition)
    if stance == "flow" or stance == "nominal":
        keyword = HAPTIC_STIMMUNG_KEYWORDS.get(stance, "")
        if keyword:
            _last_haptic_time = now
            # nominal sends a gentle tap, flow sends nothing
            if stance == "nominal":
                return send_haptic_tap(pattern=keyword)
        return True

    # Critical maps to degraded pattern (we don't want a unique "alarm" feel)
    effective_stance = "degraded" if stance == "critical" else stance
    keyword = HAPTIC_STIMMUNG_KEYWORDS.get(effective_stance)
    if keyword is None:
        return False

    _last_haptic_time = now
    _log.info("Sending stimmung haptic: %s (keyword=%s)", stance, keyword)
    return send_haptic_tap(pattern=keyword)


def send_stress_ack_haptic() -> bool:
    """Send the stress acknowledgment haptic — 'I see your stress, backing off'."""
    keyword = HAPTIC_STIMMUNG_KEYWORDS["stress_ack"]
    _log.info("Sending stress acknowledgment haptic")
    return send_haptic_tap(pattern=keyword)


class WatchSignalReader:
    """Cached reader for watch state files.

    Avoids re-reading files on every gate check by caching results
    with a configurable TTL.
    """

    def __init__(self, watch_dir: Path | None = None, cache_ttl: float = 5.0) -> None:
        self._watch_dir = watch_dir or WATCH_STATE_DIR
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._lock = threading.Lock()

    def read(self, filename: str, max_age_seconds: float = 300) -> dict[str, Any] | None:
        """Read a watch signal file with caching."""
        now = time.time()
        with self._lock:
            cached = self._cache.get(filename)
            if cached and now - cached[0] < self._cache_ttl:
                return cached[1]
        result = read_watch_signal(self._watch_dir / filename, max_age_seconds)
        with self._lock:
            self._cache[filename] = (now, result)
        return result

    def is_stress_elevated(self) -> bool:
        """Cached stress check."""
        return is_stress_elevated(self._watch_dir)

    def is_connected(self) -> bool:
        """Cached connectivity check."""
        return is_watch_connected(self._watch_dir)
