"""Bluetooth indicator — shows connected device count, click for seam."""

from __future__ import annotations

import subprocess

from gi.repository import GLib, Gtk


def _bt_status() -> tuple[int, list[dict]]:
    """Return (connected_count, [{name, mac, connected}...]) for trusted devices."""
    devices = []
    try:
        result = subprocess.run(
            ["bluetoothctl", "devices", "Trusted"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.strip().split("\n"):
            if not line.startswith("Device "):
                continue
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                devices.append({"mac": parts[1], "name": parts[2], "connected": False})
    except Exception:
        return 0, []

    try:
        result = subprocess.run(
            ["bluetoothctl", "devices", "Connected"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        connected_macs = set()
        for line in result.stdout.strip().split("\n"):
            if line.startswith("Device "):
                connected_macs.add(line.split(" ", 2)[1])
        for d in devices:
            d["connected"] = d["mac"] in connected_macs
    except Exception:
        pass

    connected = sum(1 for d in devices if d["connected"])
    return connected, devices


class BluetoothIndicator(Gtk.Label):
    """Shows BT:N (connected count). Dim when 0."""

    def __init__(self) -> None:
        super().__init__(css_classes=["module", "sysind"])
        self._update()
        GLib.timeout_add(10_000, self._update)

    def _update(self) -> bool:
        connected, _ = _bt_status()
        if connected > 0:
            self.set_label(f"BT:{connected}")
            self.set_css_classes(["module", "sysind"])
        else:
            self.set_label("BT:0")
            self.set_css_classes(["module", "sysind", "dim"])
        return GLib.SOURCE_CONTINUE
