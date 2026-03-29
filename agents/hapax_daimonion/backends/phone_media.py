"""Phone media perception backend — AVRCP track info via busctl.

Reads current media playback state from the paired phone via BlueZ
DBus MediaPlayer1 interface using busctl (no gi/PyGObject dependency).

Provides:
  - phone_media_playing: bool
  - phone_media_title: str
  - phone_media_artist: str
"""

from __future__ import annotations

import logging
import subprocess
import time

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

_PLAYER_PATH = "/org/bluez/hci0/dev_B0_D5_FB_A5_86_E8/avrcp/player0"


def _busctl_get(prop: str) -> str:
    """Read a property from the BlueZ MediaPlayer1 interface."""
    try:
        result = subprocess.run(
            ["busctl", "get-property", "org.bluez", _PLAYER_PATH, "org.bluez.MediaPlayer1", prop],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _read_media_player() -> dict:
    """Read AVRCP media player state."""
    status_raw = _busctl_get("Status")
    # busctl output: s "paused" or s "playing"
    status = status_raw.split('"')[1] if '"' in status_raw else ""

    # Track is a dict — harder to parse from busctl
    # Use a simpler approach: just get Status + use cached track
    track_raw = _busctl_get("Track")
    title = ""
    artist = ""
    if track_raw:
        # Parse the busctl dict output
        for _part in track_raw.split('"'):
            pass  # busctl dict parsing is complex

    # Simpler: parse via subprocess with json output
    try:
        result = subprocess.run(
            [
                "busctl",
                "--json=short",
                "get-property",
                "org.bluez",
                _PLAYER_PATH,
                "org.bluez.MediaPlayer1",
                "Track",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            import json

            data = json.loads(result.stdout)
            track = data.get("data", {})
            # busctl --json=short wraps values as {"type":"s","data":"..."}
            title_val = track.get("Title", "")
            artist_val = track.get("Artist", "")
            title = title_val.get("data", "") if isinstance(title_val, dict) else str(title_val)
            artist = artist_val.get("data", "") if isinstance(artist_val, dict) else str(artist_val)
    except Exception:
        pass

    return {"status": status, "title": title, "artist": artist}


class PhoneMediaBackend:
    """PerceptionBackend that reads phone media state via AVRCP/busctl."""

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
        return bool(_busctl_get("Status"))

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        info = _read_media_player()

        self._b_playing.update(info["status"] == "playing", now)
        self._b_title.update(info["title"], now)
        self._b_artist.update(info["artist"], now)

        behaviors["phone_media_playing"] = self._b_playing
        behaviors["phone_media_title"] = self._b_title
        behaviors["phone_media_artist"] = self._b_artist

    def start(self) -> None:
        info = _read_media_player()
        log.info("Phone media backend started (status: %s)", info.get("status", "?"))

    def stop(self) -> None:
        log.info("Phone media backend stopped")
