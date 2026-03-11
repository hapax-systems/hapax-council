"""Health history aggregation and retention.

Provides rollup (raw → hourly → daily) and trend analysis over health check
history. Raw data kept 7 days, hourly rollups 30 days, daily rollups 90 days.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.config import PROFILES_DIR


@dataclass
class HourlyRollup:
    hour: str  # ISO hour, e.g. "2026-03-03T14"
    total_runs: int = 0
    healthy_runs: int = 0
    degraded_runs: int = 0
    failed_runs: int = 0
    avg_duration_ms: int = 0
    failed_checks: list[str] = field(default_factory=list)  # unique check names

    def to_dict(self) -> dict:
        return {
            "hour": self.hour,
            "total_runs": self.total_runs,
            "healthy_runs": self.healthy_runs,
            "degraded_runs": self.degraded_runs,
            "failed_runs": self.failed_runs,
            "avg_duration_ms": self.avg_duration_ms,
            "failed_checks": self.failed_checks,
        }


@dataclass
class DailyRollup:
    date: str  # ISO date, e.g. "2026-03-03"
    total_runs: int = 0
    healthy_runs: int = 0
    degraded_runs: int = 0
    failed_runs: int = 0
    avg_duration_ms: int = 0
    uptime_pct: float = 0.0
    recurring_checks: list[str] = field(default_factory=list)  # failed in >50% of runs

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "total_runs": self.total_runs,
            "healthy_runs": self.healthy_runs,
            "degraded_runs": self.degraded_runs,
            "failed_runs": self.failed_runs,
            "avg_duration_ms": self.avg_duration_ms,
            "uptime_pct": self.uptime_pct,
            "recurring_checks": self.recurring_checks,
        }


def _parse_timestamp(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def aggregate_hourly(raw_entries: list[dict]) -> list[HourlyRollup]:
    """Aggregate raw health-history entries into hourly rollups."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for entry in raw_entries:
        dt = _parse_timestamp(entry.get("timestamp", ""))
        if not dt:
            continue
        hour_key = dt.strftime("%Y-%m-%dT%H")
        buckets[hour_key].append(entry)

    rollups = []
    for hour_key in sorted(buckets.keys()):
        entries = buckets[hour_key]
        total = len(entries)
        healthy = sum(1 for e in entries if e.get("status") == "healthy")
        degraded = sum(1 for e in entries if e.get("status") == "degraded")
        failed = sum(1 for e in entries if e.get("status") == "failed")
        avg_dur = int(sum(e.get("duration_ms", 0) for e in entries) / total) if total else 0
        all_failed = set()
        for e in entries:
            all_failed.update(e.get("failed_checks", []))
        rollups.append(HourlyRollup(
            hour=hour_key, total_runs=total,
            healthy_runs=healthy, degraded_runs=degraded, failed_runs=failed,
            avg_duration_ms=avg_dur, failed_checks=sorted(all_failed),
        ))
    return rollups


def aggregate_daily(hourly_entries: list[dict]) -> list[DailyRollup]:
    """Aggregate hourly rollup entries into daily rollups."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for entry in hourly_entries:
        hour = entry.get("hour", "")
        if len(hour) >= 10:
            date_key = hour[:10]
            buckets[date_key].append(entry)

    rollups = []
    for date_key in sorted(buckets.keys()):
        entries = buckets[date_key]
        total = sum(e.get("total_runs", 0) for e in entries)
        healthy = sum(e.get("healthy_runs", 0) for e in entries)
        degraded = sum(e.get("degraded_runs", 0) for e in entries)
        failed = sum(e.get("failed_runs", 0) for e in entries)
        avg_dur = (
            int(sum(e.get("avg_duration_ms", 0) * e.get("total_runs", 0) for e in entries) / total)
            if total else 0
        )
        uptime = round((healthy / total) * 100, 1) if total else 0.0

        # Recurring: checks that failed in >50% of hourly windows
        check_counts: Counter[str] = Counter()
        for e in entries:
            for c in e.get("failed_checks", []):
                check_counts[c] += 1
        threshold = len(entries) * 0.5
        recurring = sorted(c for c, n in check_counts.items() if n > threshold)

        rollups.append(DailyRollup(
            date=date_key, total_runs=total,
            healthy_runs=healthy, degraded_runs=degraded, failed_runs=failed,
            avg_duration_ms=avg_dur, uptime_pct=uptime, recurring_checks=recurring,
        ))
    return rollups


def rotate_with_rollup(
    raw_path: Path | None = None,
    hourly_path: Path | None = None,
    daily_path: Path | None = None,
    raw_days: int = 7,
    hourly_days: int = 30,
    daily_days: int = 90,
) -> dict[str, int]:
    """Rotate raw history into hourly/daily rollups with retention policy.

    Returns counts: {"raw_kept", "hourly_kept", "daily_kept"}.
    """
    raw_path = raw_path or PROFILES_DIR / "health-history.jsonl"
    hourly_path = hourly_path or PROFILES_DIR / "health-hourly.jsonl"
    daily_path = daily_path or PROFILES_DIR / "health-daily.jsonl"

    now = datetime.now(timezone.utc)
    raw_cutoff = now - timedelta(days=raw_days)
    hourly_cutoff = now - timedelta(days=hourly_days)
    daily_cutoff = now - timedelta(days=daily_days)

    # Read raw entries
    raw_entries = _read_jsonl(raw_path)
    recent_raw = []
    old_raw = []
    for entry in raw_entries:
        dt = _parse_timestamp(entry.get("timestamp", ""))
        if dt and dt >= raw_cutoff:
            recent_raw.append(entry)
        elif dt:
            old_raw.append(entry)

    # Aggregate old raw → hourly
    new_hourly = aggregate_hourly(old_raw)

    # Read existing hourly, merge, and trim
    existing_hourly = _read_jsonl(hourly_path)
    seen_hours = {e.get("hour") for e in existing_hourly}
    for r in new_hourly:
        if r.hour not in seen_hours:
            existing_hourly.append(r.to_dict())
    hourly_kept = [
        e for e in existing_hourly
        if _parse_timestamp(e.get("hour", "") + ":00:00+00:00") is None
        or _parse_timestamp(e.get("hour", "") + ":00:00+00:00") >= hourly_cutoff
    ]

    # Aggregate expired hourly → daily
    expired_hourly = [
        e for e in existing_hourly if e not in hourly_kept
    ]
    new_daily = aggregate_daily(expired_hourly)

    # Read existing daily, merge, and trim
    existing_daily = _read_jsonl(daily_path)
    seen_dates = {e.get("date") for e in existing_daily}
    for r in new_daily:
        if r.date not in seen_dates:
            existing_daily.append(r.to_dict())
    daily_kept = [
        e for e in existing_daily
        if _parse_timestamp(e.get("date", "") + "T00:00:00+00:00") is None
        or _parse_timestamp(e.get("date", "") + "T00:00:00+00:00") >= daily_cutoff
    ]

    # Write back
    raw_path.write_text("\n".join(json.dumps(e) for e in recent_raw) + "\n" if recent_raw else "")
    hourly_path.write_text("\n".join(json.dumps(e) for e in hourly_kept) + "\n" if hourly_kept else "")
    daily_path.write_text("\n".join(json.dumps(e) for e in daily_kept) + "\n" if daily_kept else "")

    return {
        "raw_kept": len(recent_raw),
        "hourly_kept": len(hourly_kept),
        "daily_kept": len(daily_kept),
    }


def get_recurring_issues(days: int = 7) -> list[tuple[str, int]]:
    """Return check names that recur across multiple health runs, with counts.

    Checks raw history for the last `days` days.
    """
    raw_path = PROFILES_DIR / "health-history.jsonl"
    entries = _read_jsonl(raw_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    check_counts: Counter[str] = Counter()
    total_runs = 0
    for entry in entries:
        dt = _parse_timestamp(entry.get("timestamp", ""))
        if not dt or dt < cutoff:
            continue
        total_runs += 1
        for c in entry.get("failed_checks", []):
            check_counts[c] += 1

    # Return checks that failed in at least 3 runs
    return sorted(
        [(c, n) for c, n in check_counts.items() if n >= 3],
        key=lambda x: -x[1],
    )


def get_uptime_trend(days: int = 7) -> list[tuple[str, float]]:
    """Return daily uptime percentages for the last `days` days.

    Uses raw history if available, falls back to daily rollups.
    """
    raw_path = PROFILES_DIR / "health-history.jsonl"
    entries = _read_jsonl(raw_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    daily_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "healthy": 0})
    for entry in entries:
        dt = _parse_timestamp(entry.get("timestamp", ""))
        if not dt or dt < cutoff:
            continue
        date_key = dt.strftime("%Y-%m-%d")
        daily_stats[date_key]["total"] += 1
        if entry.get("status") == "healthy":
            daily_stats[date_key]["healthy"] += 1

    return [
        (date, round((s["healthy"] / s["total"]) * 100, 1) if s["total"] else 0.0)
        for date, s in sorted(daily_stats.items())
    ]
