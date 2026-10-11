"""Dedup and cadence state: seen content hashes and last-success epochs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

STATE_FILENAME = ".sensing-state.json"


@dataclass
class SensingState:
    seen: dict[str, str] = field(default_factory=dict)
    last_success: dict[str, int] = field(default_factory=dict)


def state_path(intake_dir: str | Path) -> Path:
    return Path(intake_dir) / STATE_FILENAME


def load_state(path: str | Path) -> SensingState:
    path = Path(path)
    if not path.exists():
        return SensingState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SensingState(
        seen={str(key): str(value) for key, value in raw.get("seen", {}).items()},
        last_success={str(key): int(value) for key, value in raw.get("last_success", {}).items()},
    )


def save_state(path: str | Path, state: SensingState) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"seen": state.seen, "last_success": state.last_success}, indent=1, sort_keys=True
    )
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    os.replace(tmp, path)
