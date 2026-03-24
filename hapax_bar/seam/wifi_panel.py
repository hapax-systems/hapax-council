"""Wifi panel — visible networks with connect/disconnect."""

from __future__ import annotations

import subprocess

from gi.repository import Gtk


def _wifi_status() -> tuple[str, list[dict]]:
    """Return (connected_ssid, [{ssid, signal, security, connected}...])."""
    connected = ""
    networks = []
    seen = set()
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.split(":")
            if len(parts) >= 4:
                ssid = parts[0]
                if not ssid or ssid in seen:
                    continue
                seen.add(ssid)
                in_use = parts[3].strip() == "*"
                if in_use:
                    connected = ssid
                networks.append(
                    {
                        "ssid": ssid,
                        "signal": int(parts[1]) if parts[1].isdigit() else 0,
                        "security": parts[2],
                        "connected": in_use,
                    }
                )
    except Exception:
        pass
    # Sort: connected first, then by signal strength
    networks.sort(key=lambda n: (-n["connected"], -n["signal"]))
    return connected, networks


def _signal_color(signal: int) -> str:
    if signal >= 70:
        return "#b8bb26"  # green
    if signal >= 40:
        return "#fabd2f"  # yellow
    return "#fb4934"  # red


class WifiPanel(Gtk.Box):
    """Shows visible wifi networks with connect/disconnect."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            css_classes=["wifi-panel"],
        )
        self._header = Gtk.Label(xalign=0, css_classes=["metrics-row"], use_markup=True)
        self._network_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.append(self._header)
        self.append(self._network_box)

    def refresh(self) -> None:
        connected, networks = _wifi_status()

        color = "#b8bb26" if connected else "#665c54"
        self._header.set_markup(
            f'Wifi: <span foreground="{color}">{connected or "disconnected"}</span>'
        )

        while child := self._network_box.get_first_child():
            self._network_box.remove(child)

        for net in networks[:6]:
            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                css_classes=["wifi-row"],
            )

            sc = _signal_color(net["signal"])
            label = Gtk.Label(
                xalign=0,
                use_markup=True,
                hexpand=True,
                css_classes=["metrics-row"],
            )
            dot = "\u25cf" if net["connected"] else "\u25cb"
            label.set_markup(
                f'<span foreground="{sc}">{dot}</span> {net["ssid"]} '
                f'<span foreground="#665c54">{net["signal"]}% {net["security"]}</span>'
            )
            row.append(label)

            if net["connected"]:
                btn = Gtk.Button(label="disconnect", css_classes=["seam-button"])
                btn.connect("clicked", self._on_disconnect)
            else:
                btn = Gtk.Button(label="connect", css_classes=["seam-button"])
                btn.connect("clicked", self._on_connect, net["ssid"])
            row.append(btn)

            self._network_box.append(row)

    @staticmethod
    def _on_connect(_btn: Gtk.Button, ssid: str) -> None:
        subprocess.Popen(["nmcli", "device", "wifi", "connect", ssid])

    @staticmethod
    def _on_disconnect(_btn: Gtk.Button) -> None:
        subprocess.Popen(["nmcli", "device", "disconnect", "wlan0"])
