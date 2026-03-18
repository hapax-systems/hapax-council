"""Unified phone awareness backend — KDE Connect + Bluetooth.

Single perception backend for all phone state: battery, connectivity,
notifications, media, calls. Uses kdeconnect-cli for reliable polling
(no DBus timeouts). BT backends (bt_presence, phone_media) remain
separate for presence and AVRCP track info.

Provides:
  - phone_battery_pct: int (0-100)
  - phone_battery_charging: bool
  - phone_network_type: str ("WiFi", "5G", "LTE", etc)
  - phone_network_strength: int (0-4)
  - phone_notification_count: int
  - phone_media_app: str (active media app name)
  - phone_kde_connected: bool (KDE Connect reachable)
"""

from __future__ import annotations

import logging
import subprocess
import time

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)

_DEVICE_ID = "aecd697f91434f7797836db631b36e3b"


def _cli(*args: str, timeout: float = 3.0) -> str:
    """Run kdeconnect-cli and return stdout."""
    try:
        result = subprocess.run(
            ["kdeconnect-cli", "--device", _DEVICE_ID, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _busctl_prop(path_suffix: str, iface: str, prop: str) -> str:
    """Read a KDE Connect DBus property via busctl."""
    try:
        result = subprocess.run(
            [
                "busctl",
                "--user",
                "--timeout=2",
                "get-property",
                "org.kde.kdeconnect",
                f"/modules/kdeconnect/devices/{_DEVICE_ID}/{path_suffix}",
                f"org.kde.kdeconnect.device.{iface}",
                prop,
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _parse_busctl_int(raw: str) -> int:
    """Parse 'i 62' → 62."""
    parts = raw.split()
    return int(parts[1]) if len(parts) >= 2 else 0


def _parse_busctl_bool(raw: str) -> bool:
    """Parse 'b true' → True."""
    return "true" in raw.lower()


def _parse_busctl_str(raw: str) -> str:
    """Parse 's "5G"' → '5G'."""
    if '"' in raw:
        return raw.split('"')[1]
    return ""


def _parse_busctl_str_list(raw: str) -> list[str]:
    """Parse 'as 2 "Perplexity" "YouTube"' → ['Perplexity', 'YouTube']."""
    parts = raw.split('"')
    return [parts[i] for i in range(1, len(parts), 2)]


class PhoneAwarenessBackend:
    """Unified phone state via KDE Connect + BT."""

    def __init__(self) -> None:
        self._b_battery_pct: Behavior[int] = Behavior(0)
        self._b_battery_charging: Behavior[bool] = Behavior(False)
        self._b_network_type: Behavior[str] = Behavior("")
        self._b_network_strength: Behavior[int] = Behavior(0)
        self._b_notification_count: Behavior[int] = Behavior(0)
        self._b_media_app: Behavior[str] = Behavior("")
        self._b_kde_connected: Behavior[bool] = Behavior(False)

    @property
    def name(self) -> str:
        return "phone_awareness"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset(
            {
                "phone_battery_pct",
                "phone_battery_charging",
                "phone_network_type",
                "phone_network_strength",
                "phone_notification_count",
                "phone_media_app",
                "phone_kde_connected",
            }
        )

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        try:
            result = subprocess.run(
                ["kdeconnect-cli", "--list-available", "--id-only"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return _DEVICE_ID in result.stdout
        except Exception:
            return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()

        # Battery
        raw = _busctl_prop("battery", "battery", "charge")
        self._b_battery_pct.update(_parse_busctl_int(raw), now)

        raw = _busctl_prop("battery", "battery", "isCharging")
        self._b_battery_charging.update(_parse_busctl_bool(raw), now)

        # Connectivity
        raw = _busctl_prop("connectivity_report", "connectivity_report", "cellularNetworkType")
        self._b_network_type.update(_parse_busctl_str(raw), now)

        raw = _busctl_prop("connectivity_report", "connectivity_report", "cellularNetworkStrength")
        self._b_network_strength.update(_parse_busctl_int(raw), now)

        # Notification count
        raw = _busctl_prop("notifications", "notifications", "activeNotifications")
        # Returns 'as N "id1" "id2"...'
        count = 0
        parts = raw.split()
        if len(parts) >= 2:
            try:
                count = int(parts[1])
            except ValueError:
                pass
        self._b_notification_count.update(count, now)

        # MPRIS media app
        raw = _busctl_prop("mprisremote", "mprisremote", "player")
        self._b_media_app.update(_parse_busctl_str(raw), now)

        # KDE Connect reachable
        connected = bool(raw) or bool(_busctl_prop("battery", "battery", "charge"))
        self._b_kde_connected.update(connected, now)

        behaviors["phone_battery_pct"] = self._b_battery_pct
        behaviors["phone_battery_charging"] = self._b_battery_charging
        behaviors["phone_network_type"] = self._b_network_type
        behaviors["phone_network_strength"] = self._b_network_strength
        behaviors["phone_notification_count"] = self._b_notification_count
        behaviors["phone_media_app"] = self._b_media_app
        behaviors["phone_kde_connected"] = self._b_kde_connected

    def start(self) -> None:
        battery = _parse_busctl_int(_busctl_prop("battery", "battery", "charge"))
        network = _parse_busctl_str(
            _busctl_prop("connectivity_report", "connectivity_report", "cellularNetworkType")
        )
        log.info(
            "Phone awareness backend started (battery=%d%%, network=%s)",
            battery,
            network or "unknown",
        )

    def stop(self) -> None:
        log.info("Phone awareness backend stopped")
