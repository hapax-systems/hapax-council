#!/usr/bin/env -S uv run python
"""Torso S-4 empirical post-recall gain-ladder writer.

Writes the measured 2026-06-10 S-4 gain ladder from
``config/equipment/s4-gain-ladder-20260610.yaml``. The old Ring/Deform/Vast
CC chart is intentionally not used: both the official chart and the prior repo
map were falsified on the live analog insert.

Hardware path (operator):
    MIDI: RK-006 OUT_2 DIN → A/B shim → S-4 MIDI IN
          - Program Change ON, CC Control ON
    Audio: mk5 OUT3/4 (AUX2/3) → S-4 line in; S-4 line out → mk5 IN3/4

Scene recall is zero-based: program 0 recalls slot 1. Recalls wipe runtime
CC state, so this ladder must be reasserted after every recall.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import mido

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.s4_scenes import EMPIRICAL_S4_GAIN_LADDER

PORT_PREFIXES = (
    "RK-006",
    "RK006",
    "Retrokits",
)


def _resolve_port(mido_mod, configured: tuple[str, ...]) -> str | None:
    names = list(mido_mod.get_output_names())
    for name in names:
        if any(pattern == name for pattern in configured):
            return name
    for name in names:
        if any(pattern in name for pattern in configured):
            return name
    return None


def main() -> int:
    resolved = _resolve_port(mido, PORT_PREFIXES)
    if resolved is None:
        print(
            f"MIDI port matching {PORT_PREFIXES!r} not found among {mido.get_output_names()}",
            file=sys.stderr,
        )
        return 1
    print(f"Opening MIDI port: {resolved}")
    print("Target: S-4 empirical gain ladder (0-indexed mido channels shown)")
    with mido.open_output(resolved) as port:
        for command in EMPIRICAL_S4_GAIN_LADDER:
            port.send(
                mido.Message(
                    "control_change",
                    channel=command.channel,
                    control=command.cc,
                    value=command.value,
                )
            )
            print(
                f"  ch{command.channel:2d} CC{command.cc:3d} = {command.value:3d}  ({command.note})"
            )
            time.sleep(0.02)
    print("S-4 empirical gain ladder written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
