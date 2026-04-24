"""Minimum-interval guard on pushes to the hapax-assets external repo.

Single-operator: there's no quota semantics here — just a "wait N seconds
between pushes" cushion so a burst of asset changes doesn't fire N git-pushes
in succession and churn the GitHub Actions queue. File-backed so state
survives daemon restarts.
"""

from __future__ import annotations

import time
from pathlib import Path


class PushThrottle:
    def __init__(self, state_file: Path, min_interval_sec: int) -> None:
        self.state_file = state_file
        self.min_interval_sec = min_interval_sec

    def _read_last(self) -> float:
        try:
            return float(self.state_file.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return 0.0

    def _write_last(self, when: float) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        tmp.write_text(f"{when:.3f}\n", encoding="utf-8")
        tmp.replace(self.state_file)

    def try_acquire(self) -> bool:
        now = time.time()
        last = self._read_last()
        if now - last < self.min_interval_sec:
            return False
        self._write_last(now)
        return True
