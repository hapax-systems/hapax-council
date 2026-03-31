"""agents/hapax_daimonion/ir_signals.py — Read Pi NoIR state files.

Follows the same pattern as watch_signals.py: read JSON state files
from ~/hapax-state/pi-noir/ with staleness checking.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from agents._config import HAPAX_HOME

log = logging.getLogger(__name__)

IR_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "pi-noir"
IR_ROLES: tuple[str, ...] = ("desk", "room", "overhead")


def read_ir_signal(path: Path, max_age_seconds: float = 10.0) -> dict[str, object] | None:
    """Read a Pi NoIR JSON state file, returning None if missing or stale."""
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        if time.time() - mtime > max_age_seconds:
            return None
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def read_all_ir_reports(
    state_dir: Path | None = None, max_age_seconds: float = 10.0
) -> dict[str, dict[str, object]]:
    """Read all Pi NoIR state files, keyed by role.

    Returns only fresh, valid reports. Missing or stale files are omitted.
    """
    d = state_dir or IR_STATE_DIR
    reports: dict[str, dict[str, object]] = {}
    for role in IR_ROLES:
        data = read_ir_signal(d / f"{role}.json", max_age_seconds=max_age_seconds)
        if data is not None:
            reports[role] = data
    return reports
