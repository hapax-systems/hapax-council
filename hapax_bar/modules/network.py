"""Network status — AstalNetwork, real-time."""

from __future__ import annotations

from gi.repository import AstalNetwork, GObject, Gtk

SYNC = GObject.BindingFlags.SYNC_CREATE


class NetworkModule(Gtk.Box):
    """Shows network connection status: IP for wired, SSID for wifi."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "network"],
        )
        self._label = Gtk.Label()
        self.append(self._label)

        nw = AstalNetwork.get_default()
        nw.connect("notify::primary", self._sync)
        self._binding: GObject.Binding | None = None
        self._sync()

    def _sync(self, *_args: object) -> None:
        nw = AstalNetwork.get_default()

        if self._binding is not None:
            self._binding.unbind()
            self._binding = None

        primary = nw.get_primary()

        if primary == AstalNetwork.Primary.WIRED:
            wired = nw.get_wired()
            if wired is not None:
                self._update_wired(wired)
                self._binding = wired.bind_property(
                    "icon-name",
                    self._label,
                    "label",
                    SYNC,
                    lambda _b, _v: self._format_wired(wired),
                    None,
                )
        elif primary == AstalNetwork.Primary.WIFI:
            wifi = nw.get_wifi()
            if wifi is not None:
                self._update_wifi(wifi)
                self._binding = wifi.bind_property(
                    "ssid",
                    self._label,
                    "label",
                    SYNC,
                    lambda _b, ssid: f"[net:{ssid}]",
                    None,
                )
        else:
            self._label.set_label("[net:--]")
            self.set_css_classes(["module", "network", "disconnected"])

    def _format_wired(self, wired: AstalNetwork.Wired) -> str:
        # Try to get IP address
        try:
            ip = wired.get_property("ip4-address") or ""
        except Exception:
            ip = ""
        return f"[net:{ip}]" if ip else "[net:eth]"

    def _update_wired(self, wired: AstalNetwork.Wired) -> None:
        self._label.set_label(self._format_wired(wired))
        self.set_css_classes(["module", "network", "connected"])

    def _update_wifi(self, wifi: AstalNetwork.Wifi) -> None:
        ssid = wifi.get_ssid() or ""
        self._label.set_label(f"[net:{ssid}]")
        self.set_css_classes(["module", "network", "connected"])
