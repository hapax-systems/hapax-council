"""Steam Deck HDMI capture → broadcast PiP bridge.

Closes cc-task ``re-splay-homage-ward-steam-deck`` (HOMAGE family
extension after M8 + DURF). When the operator plugs the Steam Deck
into the host via the Magewell USB Capture HDMI Plus, this package
spawns a GStreamer capture pipeline that mirrors the Deck's HDMI
output (1080p60) into ``/dev/shm/hapax-sources/steamdeck-display.rgba``;
the studio compositor consumes that SHM via the existing
``external_rgba`` source-kind / ``shm_rgba`` backend (same path as
the M8 ward).

Two-stage activation matches the cc-task spec:

* **Stage 1 — USB plug** — udev rule
  (``systemd/udev/99-hapax-steamdeck.rules``) matches the Magewell
  VID/PID and pulls ``hapax-steamdeck-monitor.service`` into the
  user dependency graph. The monitor stays alive while the Magewell
  is present.
* **Stage 2 — HDMI signal** — :class:`monitor.SteamDeckMonitor`
  polls ``v4l2-ctl --query-dv-timings`` at 2 Hz; when the Steam Deck
  starts driving HDMI into the Magewell, the monitor spawns
  :class:`capture.SteamDeckCapture` which runs the GStreamer
  appsink loop and writes RGBA frames + sidecar JSON.

Audio is hardware-side only — wireplumber + pipewire loudnorm config
ships separately when the operator's audio chain matures around the
Magewell UAC source. This package owns the video / SHM / monitor
software path.

Privacy: ``redaction.steam_notification_mask()`` returns the default
top-right rectangle (1700, 0, 220, 80) that the GStreamer videobox
element blanks before the frame ever reaches SHM. Fail-CLOSED — if
the redaction chain fails to build, the capture pipeline does not
start.
"""

from agents.hapax_steamdeck_bridge.capture import (
    DEFAULT_CAPTURE_HEIGHT,
    DEFAULT_CAPTURE_WIDTH,
    DEFAULT_SHM_PATH,
    DEFAULT_SIDECAR_PATH,
    SteamDeckCapture,
)
from agents.hapax_steamdeck_bridge.monitor import (
    DEFAULT_POLL_INTERVAL_S,
    DEFAULT_V4L2_DEVICE,
    SignalState,
    SteamDeckMonitor,
)
from agents.hapax_steamdeck_bridge.redaction import (
    DEFAULT_REDACTION_MODE,
    RedactionMode,
    RedactionZone,
    redaction_zones_for_mode,
    steam_notification_mask,
)

__all__ = [
    "DEFAULT_CAPTURE_HEIGHT",
    "DEFAULT_CAPTURE_WIDTH",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_REDACTION_MODE",
    "DEFAULT_SHM_PATH",
    "DEFAULT_SIDECAR_PATH",
    "DEFAULT_V4L2_DEVICE",
    "RedactionMode",
    "RedactionZone",
    "SignalState",
    "SteamDeckCapture",
    "SteamDeckMonitor",
    "redaction_zones_for_mode",
    "steam_notification_mask",
]
