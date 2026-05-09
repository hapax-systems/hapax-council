#!/usr/bin/env -S uv run python
"""Evil Pet base-scene writer — MIDI CC burst for deterministic startup.

Writes every audio-processing parameter on the Evil Pet to the base-config
values from docs/research/2026-04-19-evil-pet-s4-base-config.md §3.8 via
MIDI CCs on the Erica Synths MIDI Dispatch (USB → CalDigit) on channel 1.

Operator runs this once per session start (or we wire it into daimonion
startup once validated). Source select (LINE), input gain trim, and
MIDI channel config are hardware-only and must be set on the device:

  1. Source button: LINE  (front-panel, confirmed on OLED)
  2. SHIFT + ENCODER input trim: ~11 o'clock
  3. Config → MIDI receive channel: 1 (0-indexed on this script, = ch 1 on wire)

After this script runs, vocal_chain.py's semantic CC modulation takes
over on top of the scene.
"""

from __future__ import annotations

import sys
import time

import mido

# Mido port name prefixes — resolver tolerates ALSA client-id drift.
# Erica MIDI Dispatch is normally USB-attached to the workstation, but as
# of 2026-05-03 it lives on Pi-4 and is bridged back here via aseqnet
# (`hapax-midi-bridge-client.service`), where it appears as
# "Net Client:Network <client-id>:0". Try the direct USB name first
# (still wins on direct-attach), then the aseqnet bridge.
PORT_PREFIXES = (
    "MIDI Dispatch:MIDI Dispatch MIDI 1",
    "Net Client:Network",
)
PORT_PREFIX = PORT_PREFIXES[0]  # legacy var for messages
EVIL_PET_CHANNEL = 0  # 0-indexed; MIDI channel 1 on the wire


# Research-doc §3.8 base values. Stepped-type CCs (filter/saturator/reverb
# type) use values in the middle of each mode's documented MIDI range.
# Verify against midi.guide/d/endorphines/evil-pet/ if mode selection
# isn't landing on the intended variant — these values are best-guess
# from typical Endorphin.es CC encoding conventions.
BASE_SCENE: list[tuple[int, int, str]] = [
    # Source layer — kill granular re-synthesis and digital-osc layer so
    # Evil Pet is purely an FX chain on incoming audio.
    (11, 0, "Grains volume → 0 (granular off)"),
    (85, 0, "Overtone volume → 0 (digital osc off)"),
    # Master.
    (40, 95, "Mix → 75% wet (audible Evil-Pet character over dry)"),
    (7, 127, "Volume → max (L6 handles gain staging downstream)"),
    # Filter section.
    (80, 64, "Filter type → bandpass (stepped; mid-range = BP on typical EP encoding)"),
    (70, 76, "Filter freq → 1 o'clock (~60%, centered on voice midband)"),
    (71, 25, "Filter resonance → 9 o'clock (~20%, low — no pitched resonator)"),
    (96, 44, "Env→filter mod → 11 o'clock (~35%, signal-honest envelope follow)"),
    # Saturator section.
    (84, 10, "Saturator type → distortion (stepped; lowest value = distortion)"),
    (39, 38, "Saturator amount → 10 o'clock (~30%, audible harmonics)"),
    # Reverb section.
    (95, 64, "Reverb type → room (stepped; typical room = mid-range)"),
    (91, 38, "Reverb amount → 10 o'clock (~30%, present not drowning)"),
    (92, 64, "Reverb tone → 12 o'clock (neutral; consonant clarity)"),
    (93, 38, "Reverb tail → 10 o'clock (~30%, short tail ~1-1.5s)"),
    (94, 0, "Reverb shimmer → 0 (aesthetic coloration forbidden for voice)"),
    # Disable record enable just in case.
    (69, 0, "Record enable → 0 (no internal capture)"),
]


def _resolve_port(mido_mod, configured) -> str | None:
    """Resolve a port name by exact match, then by stripping the trailing
    ALSA client-id token, then by substring. ``configured`` may be a single
    string or a tuple of candidates tried in order."""
    candidates = (configured,) if isinstance(configured, str) else tuple(configured)
    names = list(mido_mod.get_output_names())
    for cand in candidates:
        if cand in names:
            return cand
        for name in names:
            if name.rsplit(" ", 1)[0] == cand.rsplit(" ", 1)[0]:
                return name
        for name in names:
            if cand in name:
                return name
    return None


def main() -> int:
    resolved = _resolve_port(mido, PORT_PREFIXES)
    if resolved is None:
        print(
            f"MIDI port (none of {PORT_PREFIXES!r}) not found among {mido.get_output_names()}",
            file=sys.stderr,
        )
        return 1
    print(f"Opening MIDI port: {resolved}")
    with mido.open_output(resolved) as port:
        for cc, value, note in BASE_SCENE:
            port.send(
                mido.Message("control_change", channel=EVIL_PET_CHANNEL, control=cc, value=value)
            )
            print(f"  CC{cc:3d} = {value:3d}  ({note})")
            time.sleep(0.02)  # 20ms between messages — well under 50ms rate limit
    print("Evil Pet base scene written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
