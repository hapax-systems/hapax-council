"""Hapax bar application — GTK4 + Astal layer-shell."""

from __future__ import annotations

import sys
from ctypes import CDLL

# Must load gtk4-layer-shell before GTK4 init
CDLL("libgtk4-layer-shell.so")

import gi  # noqa: E402

gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
gi.require_version("GObject", "2.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Astal", "4.0")
gi.require_version("AstalHyprland", "0.1")
gi.require_version("AstalWp", "0.1")
gi.require_version("AstalTray", "0.1")
gi.require_version("AstalNetwork", "0.1")
gi.require_version("AstalMpris", "0.1")

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from hapax_bar.bar import create_bar  # noqa: E402
from hapax_bar.logos_client import fetch_gpu, fetch_health, poll_api  # noqa: E402
from hapax_bar.seam.seam_window import SeamWindow  # noqa: E402
from hapax_bar.socket_server import SocketServer  # noqa: E402
from hapax_bar.stimmung import StimmungState  # noqa: E402
from hapax_bar.theme import load_initial_theme, switch_theme  # noqa: E402


class HapaxBarApp(Gtk.Application):
    """Main application. Creates bar windows, seam layer, and stimmung wiring."""

    def __init__(self) -> None:
        super().__init__(
            application_id="org.hapax.bar",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._bars: list = []
        self._stimmung_fields: list = []
        self._socket: SocketServer | None = None
        self._seam: SeamWindow | None = None
        self._stimmung: StimmungState | None = None
        self._last_health: dict = {}
        self._last_gpu: dict = {}

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        if command_line.get_is_remote():
            return 0

        load_initial_theme()

        # Create seam layer (shared across monitors)
        self._seam = SeamWindow()
        self.add_window(self._seam)

        # Create stimmung state reader
        self._stimmung = StimmungState()
        self._stimmung.subscribe(self._on_stimmung_update)
        self._stimmung.start_polling()

        # Enumerate monitors and create bars
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display else None

        if monitors is not None and monitors.get_n_items() >= 2:
            win1, field1 = create_bar(
                monitor_index=0,
                workspace_ids=[1, 2, 3, 4, 5],
                primary=True,
                seam_window=self._seam,
            )
            self._bars.append(win1)
            self._stimmung_fields.append(field1)
            self.add_window(win1)

            win2, field2 = create_bar(
                monitor_index=1,
                workspace_ids=[11, 12, 13, 14, 15],
                primary=False,
                seam_window=self._seam,
            )
            self._bars.append(win2)
            self._stimmung_fields.append(field2)
            self.add_window(win2)
        else:
            win, field = create_bar(primary=True, seam_window=self._seam)
            self._bars.append(win)
            self._stimmung_fields.append(field)
            self.add_window(win)

        # Poll Logos API for seam layer data + agent activity
        poll_api(fetch_health, 30_000, self._on_health)
        poll_api(fetch_gpu, 30_000, self._on_gpu)
        poll_api(self._fetch_agent_count, 10_000, self._on_agent_activity)

        # Control socket
        self._socket = SocketServer()
        self._socket.register("theme", self._handle_theme)
        self._socket.register("stimmung", self._handle_stimmung_push)
        self._socket.start()

        return 0

    def _on_stimmung_update(self, state: StimmungState) -> None:
        for field in self._stimmung_fields:
            field.update_stimmung(state)
        if self._seam:
            self._seam.update_data(self._last_health, self._last_gpu, state)

    def _on_health(self, data: dict) -> None:
        self._last_health = data
        if self._seam and self._stimmung:
            self._seam.update_data(data, self._last_gpu, self._stimmung)

    def _on_gpu(self, data: dict) -> None:
        self._last_gpu = data
        if self._seam and self._stimmung:
            self._seam.update_data(self._last_health, data, self._stimmung)

    @staticmethod
    def _fetch_agent_count() -> dict:
        from hapax_bar.logos_client import _fetch_json

        data = _fetch_json("/api/agents/runs/current")
        if data and isinstance(data, list):
            return {"running": len(data)}
        return {"running": 0}

    def _on_agent_activity(self, data: dict) -> None:
        count = data.get("running", 0)
        for field in self._stimmung_fields:
            field.set_agent_speed(count)

    def _handle_theme(self, msg: dict) -> bool:
        switch_theme(msg.get("mode", "rnd"))
        return False

    def _handle_stimmung_push(self, msg: dict) -> bool:
        # Socket push for instant stimmung update (supplements file polling)
        if self._stimmung:
            stance = msg.get("stance")
            if stance:
                self._stimmung.stance = stance
                self._stimmung._notify()
        return False

    def do_shutdown(self) -> None:
        if self._socket:
            self._socket.stop()
        Gtk.Application.do_shutdown(self)


def main() -> None:
    GLib.set_prgname("hapax-bar")
    app = HapaxBarApp()
    app.run(sys.argv)
