"""shared/working_mode.py — Working mode reader/writer.

Tracks the operator's current working state: RESEARCH or RND.
Orthogonal to cycle mode (dev/prod) — you can do research in either cycle.

The mode file is written by the hapax-working-mode script and read by
telemetry, relay protocol, waybar, and fish prompt.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class WorkingMode(StrEnum):
    RESEARCH = "research"
    RND = "rnd"


WORKING_MODE_FILE = Path.home() / ".cache" / "hapax" / "working-mode"


def get_working_mode() -> WorkingMode:
    """Read the current working mode. Defaults to RND if file is missing or invalid."""
    try:
        return WorkingMode(WORKING_MODE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return WorkingMode.RND


def set_working_mode(mode: WorkingMode) -> None:
    """Write the working mode file."""
    WORKING_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKING_MODE_FILE.write_text(mode.value)
