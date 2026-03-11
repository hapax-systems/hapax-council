"""Health data collectors for the cockpit."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from shared.config import PROFILES_DIR


@dataclass
class HealthSnapshot:
    overall_status: str  # "healthy" | "degraded" | "failed"
    total_checks: int
    healthy: int
    degraded: int
    failed: int
    duration_ms: int
    failed_checks: list[str] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class HealthHistoryEntry:
    timestamp: str
    status: str
    healthy: int
    degraded: int
    failed: int
    duration_ms: int
    failed_checks: list[str] = field(default_factory=list)


@dataclass
class HealthHistory:
    entries: list[HealthHistoryEntry] = field(default_factory=list)
    uptime_pct: float = 0.0
    total_runs: int = 0


async def collect_live_health() -> HealthSnapshot:
    """Read the latest health check result from history.

    The health monitor runs on the host (with access to Docker, GPU,
    systemd, etc.) and writes results to health-history.jsonl.  The
    cockpit API runs inside Docker where most checks would fail, so
    we read the host-side results instead of running checks in-container.
    """
    path = PROFILES_DIR / "health-history.jsonl"
    try:
        # Read only the last line efficiently
        raw = path.read_bytes()
        last_line = raw.rstrip().rsplit(b"\n", 1)[-1]
        d = json.loads(last_line)
        failed_names = d.get("failed_checks", [])
        total = d.get("healthy", 0) + d.get("degraded", 0) + d.get("failed", 0)
        status = d.get("status", "unknown")
        return HealthSnapshot(
            overall_status=status,
            total_checks=total,
            healthy=d.get("healthy", 0),
            degraded=d.get("degraded", 0),
            failed=d.get("failed", 0),
            duration_ms=d.get("duration_ms", 0),
            failed_checks=failed_names,
            timestamp=d.get("timestamp", ""),
        )
    except Exception as e:
        return HealthSnapshot(
            overall_status="failed",
            total_checks=0,
            healthy=0,
            degraded=0,
            failed=0,
            duration_ms=0,
            failed_checks=[f"Could not read health history: {e}"],
        )


def collect_health_history(limit: int = 48) -> HealthHistory:
    """Read recent entries from health-history.jsonl."""
    path = PROFILES_DIR / "health-history.jsonl"
    if not path.exists():
        return HealthHistory()

    entries: list[HealthHistoryEntry] = []
    for line in path.read_text().splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            entries.append(
                HealthHistoryEntry(
                    timestamp=d.get("timestamp", ""),
                    status=d.get("status", "unknown"),
                    healthy=d.get("healthy", 0),
                    degraded=d.get("degraded", 0),
                    failed=d.get("failed", 0),
                    duration_ms=d.get("duration_ms", 0),
                    failed_checks=d.get("failed_checks", []),
                )
            )
        except (json.JSONDecodeError, KeyError):
            continue

    total = len(entries)
    healthy_runs = sum(1 for e in entries if e.status == "healthy")
    uptime_pct = round((healthy_runs / total) * 100, 1) if total > 0 else 0.0

    return HealthHistory(entries=entries, uptime_pct=uptime_pct, total_runs=total)
