"""Phone media perception backend — AVRCP track info via Bluetooth.

Reads current media playback state from the paired phone via BlueZ
DBus MediaPlayer1 interface. Provides track title, artist, play state.

No dependencies beyond gi (GObject Introspection) which ships with GNOME/KDE.

Provides:
  - phone_media_playing: bool
  - phone_media_title: str
  - phone_media_artist: str
"""

from __future__ import annotations

import logging
import time

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)


def _read_media_player() -> dict:
    """Read AVRCP media player state from BlueZ DBus."""
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        result = bus.call_sync(
            "org.bluez",
            "/",
            "org.freedesktop.DBus.ObjectManager",
            "GetManagedObjects",
            None,
            GLib.VariantType(
                "(a{oa{sa{sv}}})",
            ),
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        )

        objects = result.unpack()[0]
        for _path, ifaces in objects.items():
            if "org.bluez.MediaPlayer1" in ifaces:
                player = ifaces["org.bluez.MediaPlayer1"]
                track = player.get("Track", {})
                return {
                    "status": str(player.get("Status", "stopped")),
                    "title": str(track.get("Title", "")),
                    "artist": str(track.get("Artist", "")),
                    "album": str(track.get("Album", "")),
                    "name": str(player.get("Name", "")),
                }
    except Exception:
        pass
    return {}


class PhoneMediaBackend:
    """PerceptionBackend that reads phone media state via AVRCP/BlueZ."""

    def __init__(self) -> None:
        self._b_playing: Behavior[bool] = Behavior(False)
        self._b_title: Behavior[str] = Behavior("")
        self._b_artist: Behavior[str] = Behavior("")

    @property
    def name(self) -> str:
        return "phone_media"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"phone_media_playing", "phone_media_title", "phone_media_artist"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        try:
            from gi.repository import Gio  # noqa: F401

            return True
        except ImportError:
            return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        info = _read_media_player()

        playing = info.get("status") == "playing"
        title = info.get("title", "")
        artist = info.get("artist", "")

        self._b_playing.update(playing, now)
        self._b_title.update(title, now)
        self._b_artist.update(artist, now)

        behaviors["phone_media_playing"] = self._b_playing
        behaviors["phone_media_title"] = self._b_title
        behaviors["phone_media_artist"] = self._b_artist

    def start(self) -> None:
        info = _read_media_player()
        if info:
            log.info(
                "Phone media backend started (player: %s, status: %s)",
                info.get("name", "?"),
                info.get("status", "?"),
            )
        else:
            log.info("Phone media backend started (no player connected)")

    def stop(self) -> None:
        log.info("Phone media backend stopped")
