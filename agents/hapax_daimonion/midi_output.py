"""MidiOutput — thin mido wrapper for sending MIDI CC messages.

Lazy-initializes the MIDI output port on first send. Fails gracefully
if no MIDI hardware is available (logs warning, becomes a no-op).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Lazy-import mido so the module loads even without the dependency installed.
mido: Any = None


def _ensure_mido() -> Any:
    global mido  # noqa: PLW0603
    if mido is None:
        import mido as _mido

        mido = _mido
    return mido


class MidiOutput:
    """Send MIDI CC messages to external hardware."""

    def __init__(self, port_name: str = "") -> None:
        self._port_name = port_name
        self._port: Any = None
        self._init_failed = False

    def send_cc(self, channel: int, cc: int, value: int) -> None:
        """Send a MIDI Control Change message.

        Args:
            channel: MIDI channel (0-indexed, 0-15).
            cc: CC number (0-127).
            value: CC value (0-127, clamped).
        """
        if self._init_failed:
            return
        if self._port is None:
            self._open_port()
            if self._port is None:
                return

        value = max(0, min(127, value))
        m = _ensure_mido()
        msg = m.Message("control_change", channel=channel, control=cc, value=value)
        self._port.send(msg)

    def _open_port(self) -> None:
        """Lazy-open the MIDI output port."""
        try:
            m = _ensure_mido()
            name = self._port_name or None  # None = mido picks first available
            self._port = m.open_output(name)
            log.info("MIDI output opened: %s", self._port.name)
        except OSError as exc:
            log.warning("No MIDI output available (%s) — vocal chain disabled", exc)
            self._init_failed = True

    def close(self) -> None:
        """Close the MIDI output port."""
        if self._port is not None:
            self._port.close()
            self._port = None

    def is_open(self) -> bool:
        """Return True if the MIDI port is open and accepting messages.

        False means either the port has never been opened yet, or a prior
        open attempt latched off (port absent). Callers (the impingement
        consumer loop) use this to skip activation entirely when the
        hardware isn't connected — no noisy log spam, no pointless work.
        """
        return self._port is not None and not self._init_failed
