"""shared/cycle_mode.py — Cycle mode reader.

Single source of truth for the current cycle mode (dev or prod).
The mode file is written by the hapax-mode CLI script and the
cockpit API. Agents read it at invocation to adjust thresholds.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class CycleMode(StrEnum):
    PROD = "prod"
    DEV = "dev"


MODE_FILE = Path.home() / ".cache" / "hapax" / "cycle-mode"


def get_cycle_mode() -> CycleMode:
    """Read the current cycle mode. Defaults to PROD if file is missing or invalid."""
    try:
        return CycleMode(MODE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return CycleMode.PROD
