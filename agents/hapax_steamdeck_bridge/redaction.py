"""Steam Deck redaction zones.

Pre-decoded geometry that the capture pipeline applies via GStreamer
``videobox`` (or equivalent) elements before the frame reaches
``/dev/shm/hapax-sources/steamdeck-display.rgba``. Pure data — no
GStreamer dependency — so unit tests can assert zone math without
the runtime stack.

The default mode is ``FULL`` per the cc-task constraint
("structural redaction mask blanks Steam notification + friends-list
zones by default"). Operators can downgrade per session via
``HAPAX_STEAMDECK_REDACT={partial,off}`` but the daemon never
auto-downgrades.

Coordinates are in capture-resolution pixels (1920×1080); the
compositor's source surface is the same resolution.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "DEFAULT_REDACTION_MODE",
    "REDACT_ENV",
    "RedactionMode",
    "RedactionZone",
    "friends_list_mask",
    "mode_from_env",
    "redaction_zones_for_mode",
    "steam_notification_mask",
]

REDACT_ENV = "HAPAX_STEAMDECK_REDACT"


class RedactionMode(StrEnum):
    """Operator-selectable redaction posture.

    * ``FULL`` — both notification and friends-list zones masked.
    * ``PARTIAL`` — notification only; friends-list passes through.
    * ``OFF`` — no redaction. Operator-explicit; daemon never picks
      this on its own.
    """

    FULL = "full"
    PARTIAL = "partial"
    OFF = "off"


DEFAULT_REDACTION_MODE = RedactionMode.FULL


@dataclass(frozen=True)
class RedactionZone:
    """Rectangle in capture-resolution pixels.

    The four ints map directly to GStreamer ``videobox`` properties
    (``top``, ``left``, ``bottom``, ``right`` after coordinate
    inversion) or to a simple in-RAM blanking pass on the captured
    buffer when the pipeline composes the mask itself.
    """

    name: str
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


def steam_notification_mask() -> RedactionZone:
    """Top-right Steam notification toast zone.

    Approximate dimensions confirmed against Steam Big Picture mode
    in 1080p output: notification toasts render in a 220×80 rect
    anchored to the top-right corner with ~0 padding. The cc-task
    pins the geometry explicitly so the compositor never depends on
    runtime feature detection.
    """

    return RedactionZone(name="steam_notification", x=1700, y=0, w=220, h=80)


def friends_list_mask() -> RedactionZone:
    """Steam friends-list popup zone (right-edge drawer)."""

    return RedactionZone(name="steam_friends", x=1620, y=120, w=300, h=720)


def redaction_zones_for_mode(mode: RedactionMode) -> tuple[RedactionZone, ...]:
    """Return the active zones for a given operator mode.

    ``OFF`` collapses to an empty tuple — the capture pipeline still
    runs the mask element for shape consistency (so a switch between
    modes does not require pipeline rebuild) but the element receives
    a zero-zone configuration and passes pixels through unchanged.
    """

    if mode is RedactionMode.OFF:
        return ()
    if mode is RedactionMode.PARTIAL:
        return (steam_notification_mask(),)
    return (steam_notification_mask(), friends_list_mask())


def mode_from_env(default: RedactionMode = DEFAULT_REDACTION_MODE) -> RedactionMode:
    """Read ``HAPAX_STEAMDECK_REDACT`` and resolve to a :class:`RedactionMode`.

    Unknown values fall back to ``default`` (NOT ``OFF``) — the daemon
    must not silently disable redaction when the operator typoes the
    env var.
    """

    raw = os.environ.get(REDACT_ENV, "").strip().lower()
    if not raw:
        return default
    try:
        return RedactionMode(raw)
    except ValueError:
        return default
