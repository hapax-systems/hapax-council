"""Always-visible system indicators: network, CPU, GPU."""

from __future__ import annotations

import subprocess

from gi.repository import GLib, Gtk

from hapax_bar.logos_client import _fetch_json


class NetworkIndicator(Gtk.Label):
    """Shows wifi SSID or eth status."""

    def __init__(self) -> None:
        super().__init__(css_classes=["module", "sysind"], use_markup=True)
        self._update()
        GLib.timeout_add(10_000, self._update)

    def _update(self) -> bool:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in result.stdout.strip().split("\n"):
                parts = line.split(":")
                if len(parts) >= 3 and parts[1] == "connected":
                    if parts[0] == "wifi":
                        self.set_label(f"W:{parts[2][:8]}")
                        return GLib.SOURCE_CONTINUE
                    elif parts[0] == "ethernet":
                        self.set_label("E:up")
                        return GLib.SOURCE_CONTINUE
            self.set_label("net:--")
        except Exception:
            self.set_label("net:?")
        return GLib.SOURCE_CONTINUE


class CpuIndicator(Gtk.Label):
    """Shows CPU load average."""

    def __init__(self) -> None:
        super().__init__(css_classes=["module", "sysind"])
        self._update()
        GLib.timeout_add(5_000, self._update)

    def _update(self) -> bool:
        try:
            with open("/proc/loadavg") as f:
                load1 = f.read().split()[0]
            self.set_label(f"C:{load1}")
        except Exception:
            self.set_label("C:?")
        return GLib.SOURCE_CONTINUE


class GpuIndicator(Gtk.Label):
    """Shows GPU temp and VRAM from Logos API."""

    def __init__(self) -> None:
        super().__init__(css_classes=["module", "sysind"])
        self._update()
        GLib.timeout_add(30_000, self._update)

    def _update(self) -> bool:
        data = _fetch_json("/api/gpu") or {}
        temp = data.get("temperature_c", "?")
        used = data.get("used_mb", 0)
        used_g = used / 1024 if isinstance(used, (int, float)) else 0
        self.set_label(f"G:{temp}° {used_g:.0f}G")
        return GLib.SOURCE_CONTINUE
