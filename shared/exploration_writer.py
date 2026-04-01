"""Atomic publication of ExplorationSignal to /dev/shm."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from shared.exploration import ExplorationSignal

log = logging.getLogger("exploration")

_DEFAULT_SHM = Path("/dev/shm")


def publish_exploration_signal(
    signal: ExplorationSignal,
    shm_root: Path = _DEFAULT_SHM,
) -> None:
    """Write ExplorationSignal atomically to /dev/shm/hapax-exploration/{component}.json."""
    directory = shm_root / "hapax-exploration"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{signal.component}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(signal.to_dict()), encoding="utf-8")
    tmp.rename(target)


class ExplorationReader:
    """Read ExplorationSignal JSON from /dev/shm."""

    def __init__(self, shm_root: Path = _DEFAULT_SHM) -> None:
        self._dir = shm_root / "hapax-exploration"

    def read(self, component: str) -> dict | None:
        path = self._dir / f"{component}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def read_all(self) -> dict[str, dict]:
        signals: dict[str, dict] = {}
        if not self._dir.exists():
            return signals
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                signals[path.stem] = data
            except (OSError, json.JSONDecodeError):
                continue
        return signals
