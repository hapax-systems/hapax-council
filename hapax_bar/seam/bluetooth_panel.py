"""Bluetooth panel — trusted device list with connect/disconnect toggles."""

from __future__ import annotations

import subprocess

from gi.repository import Gtk


class BluetoothPanel(Gtk.Box):
    """Shows trusted BT devices with connect/disconnect buttons."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            css_classes=["bluetooth-panel"],
        )
        self._header = Gtk.Label(xalign=0, css_classes=["metrics-row"], use_markup=True)
        self._device_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.append(self._header)
        self.append(self._device_box)

    def refresh(self) -> None:
        from hapax_bar.modules.bluetooth import _bt_status

        connected, devices = _bt_status()

        color = "#b8bb26" if connected > 0 else "#665c54"
        self._header.set_markup(
            f'Bluetooth: <span foreground="{color}">{connected} connected</span>'
        )

        # Clear old device rows
        while child := self._device_box.get_first_child():
            self._device_box.remove(child)

        for dev in devices:
            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                css_classes=["bt-device-row"],
            )

            # Status dot + name
            status_color = "#b8bb26" if dev["connected"] else "#665c54"
            label = Gtk.Label(
                xalign=0,
                use_markup=True,
                hexpand=True,
                css_classes=["metrics-row"],
            )
            label.set_markup(f'<span foreground="{status_color}">\u25cf</span> {dev["name"]}')
            row.append(label)

            # Connect/disconnect button
            if dev["connected"]:
                btn = Gtk.Button(label="disconnect", css_classes=["seam-button"])
                btn.connect("clicked", self._on_disconnect, dev["mac"])
            else:
                btn = Gtk.Button(label="connect", css_classes=["seam-button"])
                btn.connect("clicked", self._on_connect, dev["mac"])
            row.append(btn)

            self._device_box.append(row)

    @staticmethod
    def _on_connect(_btn: Gtk.Button, mac: str) -> None:
        subprocess.Popen(["bluetoothctl", "connect", mac])

    @staticmethod
    def _on_disconnect(_btn: Gtk.Button, mac: str) -> None:
        subprocess.Popen(["bluetoothctl", "disconnect", mac])
