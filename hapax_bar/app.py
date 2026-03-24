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
gi.require_version("Gtk", "4.0")
gi.require_version("Astal", "4.0")
gi.require_version("AstalHyprland", "0.1")
gi.require_version("AstalWp", "0.1")
gi.require_version("AstalTray", "0.1")
gi.require_version("AstalNetwork", "0.1")
gi.require_version("AstalMpris", "0.1")

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from hapax_bar.bar import create_bar  # noqa: E402
from hapax_bar.socket_server import SocketServer  # noqa: E402
from hapax_bar.theme import load_initial_theme, switch_theme  # noqa: E402


class HapaxBarApp(Gtk.Application):
    """Main application. Creates bar windows and runs the GLib main loop."""

    def __init__(self) -> None:
        super().__init__(
            application_id="org.hapax.bar",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._bars: list = []
        self._socket: SocketServer | None = None

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        if command_line.get_is_remote():
            return 0

        load_initial_theme()

        # Enumerate monitors and create bars
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display else None

        if monitors is not None and monitors.get_n_items() >= 2:
            # Multi-monitor: primary (index 0) + secondary (index 1)
            bar_primary = create_bar(
                monitor_index=0,
                workspace_ids=[1, 2, 3, 4, 5],
                primary=True,
            )
            self._bars.append(bar_primary)
            self.add_window(bar_primary)

            bar_secondary = create_bar(
                monitor_index=1,
                workspace_ids=[11, 12, 13, 14, 15],
                primary=False,
            )
            self._bars.append(bar_secondary)
            self.add_window(bar_secondary)
        else:
            # Single monitor
            bar = create_bar(primary=True)
            self._bars.append(bar)
            self.add_window(bar)

        # Start control socket
        self._socket = SocketServer()
        self._socket.register("theme", self._handle_theme)
        self._socket.start()

        return 0

    def _handle_theme(self, msg: dict) -> bool:
        mode = msg.get("mode", "rnd")
        switch_theme(mode)
        return False  # GLib.idle_add: don't repeat

    def do_shutdown(self) -> None:
        if self._socket:
            self._socket.stop()
        Gtk.Application.do_shutdown(self)


def main() -> None:
    GLib.set_prgname("hapax-bar")
    app = HapaxBarApp()
    app.run(sys.argv)
