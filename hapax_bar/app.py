"""Hapax bar application — GTK4 + Astal layer-shell.

Dual-bar architecture: Horizon (top) + Bedrock (bottom).
"""

from __future__ import annotations

import sys
from ctypes import CDLL

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

from hapax_bar.bedrock import create_bedrock  # noqa: E402
from hapax_bar.horizon import create_horizon  # noqa: E402
from hapax_bar.logos_client import fetch_gpu, fetch_health, poll_api  # noqa: E402
from hapax_bar.seam.controls_panel import ControlsPanel  # noqa: E402
from hapax_bar.seam.metrics_panel import MetricsPanel  # noqa: E402
from hapax_bar.seam.seam_window import SeamWindow  # noqa: E402
from hapax_bar.seam.session_panel import SessionPanel  # noqa: E402
from hapax_bar.seam.stimmung_detail import StimmungDetailPanel  # noqa: E402
from hapax_bar.seam.temporal_panel import TemporalPanel  # noqa: E402
from hapax_bar.seam.voice_panel import VoicePanel  # noqa: E402
from hapax_bar.socket_server import SocketServer  # noqa: E402
from hapax_bar.stimmung import StimmungState  # noqa: E402
from hapax_bar.theme import load_initial_theme, switch_theme  # noqa: E402


class HapaxBarApp(Gtk.Application):
    """Dual-bar application: Horizon (top) + Bedrock (bottom)."""

    def __init__(self) -> None:
        super().__init__(
            application_id="org.hapax.bar",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._windows: list = []
        self._stimmung_fields: list = []
        self._socket: SocketServer | None = None
        self._stimmung: StimmungState | None = None
        self._last_health: dict = {}
        self._last_gpu: dict = {}
        self._bedrock_seam: SeamWindow | None = None

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        if command_line.get_is_remote():
            return 0

        load_initial_theme()

        # Stimmung state reader (shared)
        self._stimmung = StimmungState()
        self._stimmung.subscribe(self._on_stimmung_update)
        self._stimmung.start_polling()

        # Create bars per monitor
        display = Gdk.Display.get_default()
        monitors = display.get_monitors() if display else None
        n_monitors = monitors.get_n_items() if monitors else 1

        for i in range(min(n_monitors, 2)):
            primary = i == 0
            ws_ids = [1, 2, 3, 4, 5] if i == 0 else [11, 12, 13, 14, 15]

            # Horizon seam (slides down from top)
            horizon_seam = SeamWindow(position="top")
            horizon_seam.add_panel(TemporalPanel())
            self.add_window(horizon_seam)
            self._windows.append(horizon_seam)

            # Bedrock seam (slides up from bottom)
            bedrock_seam = SeamWindow(position="bottom")
            bedrock_seam.add_panel(MetricsPanel())
            bedrock_seam.add_panel(StimmungDetailPanel())
            bedrock_seam.add_panel(VoicePanel())
            bedrock_seam.add_panel(ControlsPanel())
            bedrock_seam.add_panel(SessionPanel())
            self.add_window(bedrock_seam)
            self._windows.append(bedrock_seam)
            if primary:
                self._bedrock_seam = bedrock_seam

            # Horizon bar (top)
            horizon = create_horizon(
                monitor_index=i if n_monitors >= 2 else None,
                workspace_ids=ws_ids,
                primary=primary,
                seam_toggle=horizon_seam.toggle,
            )
            self.add_window(horizon)
            self._windows.append(horizon)

            # Bedrock bar (bottom)
            bedrock, stimmung_field = create_bedrock(
                monitor_index=i if n_monitors >= 2 else None,
                primary=primary,
                seam_window=bedrock_seam,
            )
            self.add_window(bedrock)
            self._windows.append(bedrock)
            self._stimmung_fields.append(stimmung_field)

        # API polling for seam layer data
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

    def _on_health(self, data: dict) -> None:
        self._last_health = data

    def _on_gpu(self, data: dict) -> None:
        self._last_gpu = data

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
