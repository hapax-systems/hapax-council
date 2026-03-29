"""Health perception backend — system health from health monitor JSONL.

Reads the last line of profiles/health-history.jsonl to determine
system health status and ratio. A failed system pauses voice operations.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior
from shared.config import PROFILES_DIR

log = logging.getLogger(__name__)

_HEALTH_HISTORY_PATH = PROFILES_DIR / "health-history.jsonl"


class HealthBackend:
    """PerceptionBackend that reads system health from health-history.jsonl.

    Provides:
      - system_health_status: str ("healthy", "degraded", "failed", "unknown")
      - system_health_ratio: float (0.0-1.0)
    """

    def __init__(self, history_path: Path | None = None) -> None:
        self._path = history_path or _HEALTH_HISTORY_PATH
        self._b_status: Behavior[str] = Behavior("unknown")
        self._b_ratio: Behavior[float] = Behavior(1.0)

    @property
    def name(self) -> str:
        return "health"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"system_health_status", "system_health_ratio"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        return True  # Graceful degradation

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        status, ratio = self._read_latest()
        self._b_status.update(status, now)
        self._b_ratio.update(ratio, now)
        behaviors["system_health_status"] = self._b_status
        behaviors["system_health_ratio"] = self._b_ratio

    def start(self) -> None:
        log.info("Health backend started (path=%s)", self._path)

    def stop(self) -> None:
        log.info("Health backend stopped")

    def _read_latest(self) -> tuple[str, float]:
        """Read the last line of the JSONL file.

        Returns (status, ratio) or defaults if unavailable.
        """
        if not self._path.exists():
            return "unknown", 1.0
        try:
            # Read last line efficiently
            with open(self._path, "rb") as f:
                f.seek(0, 2)  # End of file
                pos = f.tell()
                if pos == 0:
                    return "unknown", 1.0
                # Seek back to find last newline
                while pos > 0:
                    pos -= 1
                    f.seek(pos)
                    if f.read(1) == b"\n" and pos < f.seek(0, 2) - 1:
                        break
                if pos > 0:
                    f.seek(pos + 1)
                else:
                    f.seek(0)
                line = f.readline().decode("utf-8").strip()
            if not line:
                return "unknown", 1.0
            data = json.loads(line)
            healthy = data.get("healthy", 0)
            total = data.get("total", 0)
            if total == 0:
                return "unknown", 1.0
            ratio = healthy / total
            if ratio >= 0.9:
                status = "healthy"
            elif ratio > 0.0:
                status = "degraded"
            else:
                status = "failed"
            return status, ratio
        except (json.JSONDecodeError, OSError, KeyError):
            return "unknown", 1.0
