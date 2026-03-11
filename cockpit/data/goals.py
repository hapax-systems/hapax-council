"""Goal collector — reads operator goals and computes staleness.

Deterministic, no LLM calls. Reads from operator.json via shared.operator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# Staleness thresholds in days
STALE_ACTIVE_DAYS = 7
STALE_ONGOING_DAYS = 30


@dataclass
class GoalStatus:
    """Status of a single operator goal."""
    id: str
    name: str
    status: str           # "active" | "planned" | "ongoing"
    category: str         # "primary" | "secondary"
    last_activity_h: float | None
    stale: bool
    progress_summary: str
    description: str


@dataclass
class GoalSnapshot:
    """Aggregated goal state."""
    goals: list[GoalStatus] = field(default_factory=list)
    active_count: int = 0
    stale_count: int = 0
    primary_stale: list[str] = field(default_factory=list)


def _activity_hours(iso_ts: str | None) -> float | None:
    """Parse an ISO timestamp and return hours since then, or None."""
    if not iso_ts:
        return None
    try:
        ts = iso_ts.replace("Z", "+00:00")
        if "+" not in ts and "-" not in ts[10:]:
            ts += "+00:00"
        dt = datetime.fromisoformat(ts)
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return None


def _is_stale(status: str, activity_h: float | None) -> bool:
    """Determine if a goal is stale based on its status and last activity."""
    if activity_h is None:
        # No activity recorded — stale if active, not stale if planned
        return status in ("active", "ongoing")
    threshold_h = (
        STALE_ACTIVE_DAYS * 24 if status == "active"
        else STALE_ONGOING_DAYS * 24 if status == "ongoing"
        else float("inf")  # planned goals are never stale
    )
    return activity_h > threshold_h


def collect_goals() -> GoalSnapshot:
    """Read operator.json goals and compute staleness. Deterministic."""
    try:
        from shared.operator import _load_operator
    except Exception:
        return GoalSnapshot()

    try:
        data = _load_operator()
        goals_data = data.get("goals", {})
    except Exception:
        return GoalSnapshot()

    goals: list[GoalStatus] = []

    for category in ("primary", "secondary"):
        for g in goals_data.get(category, []):
            gid = g.get("id", "")
            name = g.get("name", gid)
            status = g.get("status", "planned")
            activity_h = _activity_hours(g.get("last_activity_at"))
            stale = _is_stale(status, activity_h)

            goals.append(GoalStatus(
                id=gid,
                name=name,
                status=status,
                category=category,
                last_activity_h=activity_h,
                stale=stale,
                progress_summary=g.get("progress", ""),
                description=g.get("description", ""),
            ))

    active_count = sum(1 for g in goals if g.status in ("active", "ongoing"))
    stale_count = sum(1 for g in goals if g.stale)
    primary_stale = [g.name for g in goals if g.stale and g.category == "primary"]

    return GoalSnapshot(
        goals=goals,
        active_count=active_count,
        stale_count=stale_count,
        primary_stale=primary_stale,
    )
