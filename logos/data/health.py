"""Health data collectors for the logos."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import JSONDecodeError

from logos._config import PROFILES_DIR


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
    source_status: str = "ok"  # "ok" | "missing" | "empty" | "invalid" | "unreadable"
    source_message: str = ""
    summary: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary:
            self.summary = {
                "healthy": self.healthy,
                "degraded": self.degraded,
                "failed": self.failed,
                "total": self.total_checks,
            }


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
    source_status: str = "ok"
    source_message: str = ""


def _source_unavailable(status: str, message: str) -> HealthSnapshot:
    return HealthSnapshot(
        overall_status="degraded",
        total_checks=0,
        healthy=0,
        degraded=0,
        failed=0,
        duration_ms=0,
        failed_checks=[],
        source_status=status,
        source_message=message,
    )


async def collect_live_health() -> HealthSnapshot:
    """Read the latest health check result from history.

    The health monitor runs on the host (with access to Docker, GPU,
    systemd, etc.) and writes results to health-history.jsonl.  The
    logos API runs inside Docker where most checks would fail, so
    we read the host-side results instead of running checks in-container.
    """
    path = PROFILES_DIR / "health-history.jsonl"
    if not path.exists():
        return _source_unavailable(
            "missing",
            "health history unavailable: no host-side health-history.jsonl has been written",
        )

    try:
        # Read only the last line efficiently
        raw = path.read_bytes()
    except OSError as e:
        return _source_unavailable(
            "unreadable",
            f"health history unavailable: latest entry could not be read ({type(e).__name__})",
        )

    raw = raw.strip()
    if not raw:
        return _source_unavailable(
            "empty",
            "health history unavailable: host-side health-history.jsonl is empty",
        )

    try:
        last_line = raw.rsplit(b"\n", 1)[-1]
        d = json.loads(last_line)
        if not isinstance(d, dict):
            raise ValueError("latest entry is not a JSON object")
        failed_names = d.get("failed_checks", [])
        if not isinstance(failed_names, list):
            failed_names = []
        total = d.get("healthy", 0) + d.get("degraded", 0) + d.get("failed", 0)
        status = d.get("status", "unknown")
        if status not in {"healthy", "degraded", "failed"}:
            status = "degraded"
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
    except (JSONDecodeError, TypeError, ValueError):
        return _source_unavailable(
            "invalid",
            "health history unavailable: latest health-history.jsonl entry is invalid",
        )


def collect_health_history(limit: int = 48) -> HealthHistory:
    """Read recent entries from health-history.jsonl."""
    path = PROFILES_DIR / "health-history.jsonl"
    if not path.exists():
        return HealthHistory(
            source_status="missing",
            source_message="health history unavailable: no host-side health-history.jsonl has been written",
        )

    try:
        raw_text = path.read_text()
    except OSError as e:
        return HealthHistory(
            source_status="unreadable",
            source_message=f"health history unavailable: entries could not be read ({type(e).__name__})",
        )

    if not raw_text.strip():
        return HealthHistory(
            source_status="empty",
            source_message="health history unavailable: host-side health-history.jsonl is empty",
        )

    entries: list[HealthHistoryEntry] = []
    for line in raw_text.splitlines()[-limit:]:
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

    source_status = "ok" if total else "invalid"
    source_message = "" if source_status == "ok" else "no valid health-history entries found"
    return HealthHistory(
        entries=entries,
        uptime_pct=uptime_pct,
        total_runs=total,
        source_status=source_status,
        source_message=source_message,
    )
