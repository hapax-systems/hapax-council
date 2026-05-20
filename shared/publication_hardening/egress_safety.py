"""Runtime egress safety envelope for the publish orchestrator.

Three layers checked before any artifact is dispatched:
1. Kill switch — file-based emergency stop
2. Rate policy — sliding-window dispatch limit
3. Hold queue — artifacts gated by publication hardening move here

ISAP: docs/isaps/visibility-engine-egress-safety-gate-isap-2026-05-20.md
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)

_STATE_ROOT = Path(os.environ.get("HAPAX_STATE_ROOT", Path.home() / "hapax-state"))
_PUBLISH_ROOT = _STATE_ROOT / "publish"
_KILL_SWITCH_PATH = _PUBLISH_ROOT / "KILL_SWITCH"
_HELD_DIR = _PUBLISH_ROOT / "held"
_LOG_DIR = _PUBLISH_ROOT / "log"

DEFAULT_RATE_LIMIT = 20
DEFAULT_RATE_WINDOW_HOURS = 24


class EgressDecision(StrEnum):
    PROCEED = "proceed"
    KILL_SWITCHED = "kill_switched"
    RATE_LIMITED = "rate_limited"


class EgressCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: EgressDecision
    reason: str
    checked_at: str
    rate_window_count: int | None = None
    rate_limit: int | None = None


class EgressSafetyEnvelope:
    """Pre-dispatch safety check for the publish orchestrator."""

    def __init__(
        self,
        *,
        kill_switch_path: Path | None = None,
        log_dir: Path | None = None,
        held_dir: Path | None = None,
        rate_limit: int | None = None,
        rate_window_hours: float | None = None,
    ) -> None:
        self._kill_switch_path = kill_switch_path or _KILL_SWITCH_PATH
        self._log_dir = log_dir or _LOG_DIR
        self._held_dir = held_dir or _HELD_DIR
        self._rate_limit = rate_limit or _env_int("HAPAX_EGRESS_RATE_LIMIT", DEFAULT_RATE_LIMIT)
        self._rate_window_hours = rate_window_hours or _env_float(
            "HAPAX_EGRESS_RATE_WINDOW_HOURS", DEFAULT_RATE_WINDOW_HOURS
        )

    def check(self) -> EgressCheckResult:
        now = datetime.now(UTC)

        if self._kill_switch_path.exists():
            log.warning("Egress kill switch active: %s", self._kill_switch_path)
            return EgressCheckResult(
                decision=EgressDecision.KILL_SWITCHED,
                reason=f"kill switch file exists: {self._kill_switch_path}",
                checked_at=now.isoformat(),
            )

        window_count = self._count_recent_dispatches(now)
        if window_count >= self._rate_limit:
            log.warning(
                "Egress rate limit reached: %d/%d in last %.0fh",
                window_count,
                self._rate_limit,
                self._rate_window_hours,
            )
            return EgressCheckResult(
                decision=EgressDecision.RATE_LIMITED,
                reason=f"{window_count} dispatches in last {self._rate_window_hours}h (limit: {self._rate_limit})",
                checked_at=now.isoformat(),
                rate_window_count=window_count,
                rate_limit=self._rate_limit,
            )

        return EgressCheckResult(
            decision=EgressDecision.PROCEED,
            reason="all egress safety checks passed",
            checked_at=now.isoformat(),
            rate_window_count=window_count,
            rate_limit=self._rate_limit,
        )

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_path.exists()

    @property
    def held_dir(self) -> Path:
        return self._held_dir

    def _count_recent_dispatches(self, now: datetime) -> int:
        cutoff = now - timedelta(hours=self._rate_window_hours)
        count = 0
        if not self._log_dir.exists():
            return 0
        for log_file in self._log_dir.glob("*.json"):
            try:
                data = json.loads(log_file.read_text())
                result = data.get("result", "")
                ts_raw = data.get("dispatched_at") or data.get("generated_at", "")
                if result != "ok" or not ts_raw:
                    continue
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts >= cutoff:
                    count += 1
            except (json.JSONDecodeError, ValueError, OSError):
                continue
        return count


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid %s=%r; using %d", key, raw, default)
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid %s=%r; using %.1f", key, raw, default)
        return default


__all__ = [
    "DEFAULT_RATE_LIMIT",
    "DEFAULT_RATE_WINDOW_HOURS",
    "EgressCheckResult",
    "EgressDecision",
    "EgressSafetyEnvelope",
]
