"""State writer — persists `~/.cache/hapax/cc-hygiene-state.json`.

Writes atomically (tmp + rename) so downstream readers (waybar, Logos
panel, ntfy alert daemon) never see a half-written file.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import HygieneState

DEFAULT_STATE_PATH = Path.home() / ".cache" / "hapax" / "cc-hygiene-state.json"
"""Canonical state file path consumed by PR3-PR5 surfaces."""


def write_state(state: HygieneState, path: Path = DEFAULT_STATE_PATH) -> Path:
    """Atomically write the hygiene state JSON.

    Returns the destination path so callers can log it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump(mode="json")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path
