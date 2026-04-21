"""Torso S-4 MIDI interface — scene recall via program change + CC fallback.

Phase B2 of `docs/superpowers/plans/2026-04-21-evilpet-s4-dynamic-dual-processor-plan.md`.

Two emission paths (per spec §4.2):

1. **Primary** — MIDI program change (single 2-byte message, <= 50 ms latency).
   Used when the S-4 has a saved patch in the slot matching the scene's
   `program_number`.
2. **Fallback** — per-slot CC bursts (5–10 messages with 20 ms inter-message
   delay so the S-4 firmware processes each CC before the next, <= 200 ms
   latency). Used when the S-4 patch slot has not yet been populated, or
   when the operator wants to stage a fresh scene without saving.

Hardware-absent posture: when the S-4 is not USB-enumerated,
`find_s4_midi_output()` returns `None` and the router's downgrade-to-single-
engine clamp (`policy.apply_safety_clamps`) routes around the missing
hardware. All public functions tolerate `None` ports — they log and no-op
rather than raising.

Routing path: this module emits to the S-4's MIDI input which the router
reaches via the Erica Dispatch MIDI hub (Erica Dispatch OUT 2 → S-4 MIDI
IN, per spec §6.1). When the Erica Dispatch is the only MIDI port present,
`find_s4_midi_output()` falls back to "Dispatch MIDI 2".
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from mido.ports import BaseOutput

# Runtime import is best-effort so the module loads on systems without
# mido (the daemon's safety-clamp layer downgrades to single-engine when
# ``is_s4_reachable()`` returns False — see ``policy.apply_safety_clamps``).
# Annotations stay typed via the TYPE_CHECKING import + string forms; the
# runtime symbols below are deliberately untyped so MagicMock instances
# from tests pass through cleanly.
try:
    import mido
    from mido import Message

    _MIDO_AVAILABLE = True
except ImportError:
    mido: Any = None  # type: ignore[no-redef]
    Message: Any = None  # type: ignore[no-redef]
    _MIDO_AVAILABLE = False

log = logging.getLogger(__name__)

# Spec §6.1: S-4 listens on MIDI channel 1 (zero-indexed = 0). Channel
# is configurable via the scene CCs but the program-change path uses the
# global channel here. Operator can renumber via S-4 front panel + this
# constant in lockstep if a different channel is needed.
S4_MIDI_CHANNEL: Final[int] = 0

# Inter-message delay for the CC-burst fallback (per spec §4.2 — the S-4
# firmware drops CCs that arrive faster than ~5 ms apart; 20 ms is a safe
# floor with margin for DAW jitter).
DEFAULT_CC_DELAY_MS: Final[float] = 20.0

# Port-name match patterns. mido returns Linux ALSA names like
# "Torso Electronics S-4:S-4 MIDI 1 28:0". Match on the brand / device
# name first, then fall back to the Erica Dispatch fan-out.
_S4_PORT_PATTERNS: Final[tuple[str, ...]] = ("Torso", "S-4", "S_4", "Elektron")
_DISPATCH_PORT_PATTERNS: Final[tuple[str, ...]] = ("MIDI Dispatch MIDI 2", "Dispatch MIDI 2")


def list_midi_outputs() -> list[str]:
    """Return all MIDI output port names visible to mido.

    Returns ``[]`` when mido is unavailable. Used by the audit CLI and
    by the router's hardware-state probe to populate
    ``HardwareState.s4_usb_enumerated``.
    """
    if not _MIDO_AVAILABLE:
        return []
    try:
        return list(mido.get_output_names())
    except Exception:
        log.debug("mido.get_output_names() failed", exc_info=True)
        return []


def find_s4_midi_output() -> BaseOutput | None:
    """Open the best-matching MIDI output for the S-4.

    Search order:
      1. Direct S-4 USB port (matches "Torso", "S-4", "S_4", or
         "Elektron" — covers Torso Electronics naming + the few firmware
         revisions that present the device differently).
      2. Erica Dispatch OUT 2 — fall-back when S-4 is downstream of the
         hub rather than direct-USB. Spec §6.1 designates Dispatch
         OUT 2 as the canonical S-4 lane.

    Returns ``None`` when no candidate matches OR when mido is missing.
    The router's safety-clamp layer translates ``None`` into a
    downgrade-to-single-engine routing intent (`policy.py:120`).
    """
    if not _MIDO_AVAILABLE:
        log.debug("mido not installed; S-4 MIDI lane unavailable")
        return None
    names = list_midi_outputs()
    for pattern in _S4_PORT_PATTERNS:
        for name in names:
            if pattern.lower() in name.lower():
                try:
                    return mido.open_output(name)
                except Exception:
                    log.warning("S-4 port %r open failed", name, exc_info=True)
                    return None
    for pattern in _DISPATCH_PORT_PATTERNS:
        for name in names:
            if pattern.lower() in name.lower():
                try:
                    return mido.open_output(name)
                except Exception:
                    log.warning("Dispatch fallback port %r open failed", name, exc_info=True)
                    return None
    return None


def is_s4_reachable() -> bool:
    """True iff at least one S-4 MIDI candidate port is present.

    Distinct from `HardwareState.s4_usb_enumerated` (which checks the
    audio-side ALSA card) — both are required for full operation but
    can disagree transiently during USB enumeration / WirePlumber
    re-link windows. The router's hardware probe combines both.
    """
    if not _MIDO_AVAILABLE:
        return False
    names = list_midi_outputs()
    return any(
        any(p.lower() in n.lower() for p in _S4_PORT_PATTERNS + _DISPATCH_PORT_PATTERNS)
        for n in names
    )


def emit_program_change(
    output: BaseOutput | None,
    program: int,
    *,
    channel: int = S4_MIDI_CHANNEL,
) -> bool:
    """Send one Program Change to the S-4 (scene recall, primary path).

    Returns True on successful emit, False on hardware-absent or
    underlying mido error. Never raises into caller — the router's hot
    path treats failures as "scene recall not applied" and logs at
    debug; the next tick will re-attempt.
    """
    if output is None or not _MIDO_AVAILABLE:
        log.debug("S-4 program_change skipped (output absent)")
        return False
    if not 0 <= program <= 127:
        log.warning("S-4 program_change out-of-range: %d", program)
        return False
    if not 0 <= channel <= 15:
        log.warning("S-4 program_change channel out-of-range: %d", channel)
        return False
    try:
        msg = Message("program_change", program=program, channel=channel)
        output.send(msg)
        return True
    except Exception:
        log.warning("S-4 program_change emit failed (program=%d)", program, exc_info=True)
        return False


def emit_cc(
    output: BaseOutput | None,
    cc: int,
    value: int,
    *,
    channel: int = S4_MIDI_CHANNEL,
    delay_ms: float = DEFAULT_CC_DELAY_MS,
) -> bool:
    """Send one Control Change message to the S-4 with post-emit delay.

    The delay is critical for the burst-fallback path: the S-4 firmware
    silently drops CCs arriving faster than ~5 ms apart. ``DEFAULT_CC_DELAY_MS``
    (20 ms) gives margin for DAW jitter while keeping a 10-CC burst
    well under the 200 ms scene-recall budget.

    Returns True on successful emit, False on hardware-absent / error.
    """
    if output is None or not _MIDO_AVAILABLE:
        log.debug("S-4 cc skipped (output absent)")
        return False
    if not 0 <= cc <= 127 or not 0 <= value <= 127:
        log.warning("S-4 cc out-of-range: cc=%d value=%d", cc, value)
        return False
    if not 0 <= channel <= 15:
        log.warning("S-4 cc channel out-of-range: %d", channel)
        return False
    try:
        msg = Message("control_change", control=cc, value=value, channel=channel)
        output.send(msg)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        return True
    except Exception:
        log.warning("S-4 cc emit failed (cc=%d value=%d)", cc, value, exc_info=True)
        return False


def emit_cc_burst(
    output: BaseOutput | None,
    ccs: dict[int, int],
    *,
    channel: int = S4_MIDI_CHANNEL,
    delay_ms: float = DEFAULT_CC_DELAY_MS,
) -> int:
    """Emit a sequence of CCs as the scene-recall fallback path.

    Returns the number of CCs successfully emitted. The caller can
    compare against ``len(ccs)`` to detect partial-emit (the S-4 will
    still recall whatever it received; partial state is preferable to
    aborting the whole burst on a single failed CC).
    """
    if output is None or not _MIDO_AVAILABLE or not ccs:
        return 0
    successes = 0
    for cc, value in ccs.items():
        if emit_cc(output, cc, value, channel=channel, delay_ms=delay_ms):
            successes += 1
    return successes


def close_output(output: BaseOutput | None) -> None:
    """Close an open MIDI port. Safe to call with ``None``."""
    if output is None:
        return
    try:
        output.close()
    except Exception:
        log.debug("S-4 MIDI port close failed", exc_info=True)
