"""Goal collector compatibility layer over vault-native goals.

The canonical goal model is the Obsidian vault ``type: goal`` frontmatter model
used by the orientation panel. This module keeps the older ``GoalSnapshot``
shape for API, MCP, nudges, voice context, and snapshot callers so they do not
silently diverge onto the legacy operator.json source.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from logos.data.vault_goals import (
    DEFAULT_VAULT_BASE,
    DEFAULT_VAULT_NAME,
    VaultGoal,
    collect_vault_goals,
)

# Staleness thresholds in days
STALE_ACTIVE_DAYS = 7
STALE_ONGOING_DAYS = 30
ACTIVE_GOAL_STATUSES = {"active", "ongoing", "blocked"}
TERMINAL_GOAL_STATUSES = {
    "done",
    "completed",
    "cancelled",
    "canceled",
    "withdrawn",
    "superseded",
    "skipped",
}
PRIMARY_PRIORITIES = {"P0", "P1"}

logger = logging.getLogger(__name__)


@dataclass
class GoalStatus:
    """Status of a single operator goal."""

    id: str
    name: str
    status: str  # "active" | "planned" | "ongoing"
    category: str  # "primary" | "secondary"
    last_activity_h: float | None
    stale: bool
    progress_summary: str
    description: str
    domain: str = ""
    priority: str = ""
    progress: float | None = None
    last_modified_at: str | None = None
    started_at: str | None = None
    target_date: str | None = None
    source_path: str = ""
    obsidian_uri: str = ""
    source: str = "vault"

    @property
    def title(self) -> str:
        """Compatibility alias for newer vault-native naming."""
        return self.name


@dataclass
class GoalSnapshot:
    """Aggregated goal state."""

    goals: list[GoalStatus] = field(default_factory=list)
    active_count: int = 0
    stale_count: int = 0
    primary_stale: list[str] = field(default_factory=list)
    total_count: int = 0
    source: str = "vault"
    source_model: str = "vault-native"
    source_path: str = str(DEFAULT_VAULT_BASE)
    source_detail: str = "Obsidian notes with type: goal frontmatter"

    def __post_init__(self) -> None:
        if self.total_count == 0 and self.goals:
            self.total_count = len(self.goals)

    def __iter__(self) -> Iterator[GoalStatus]:
        """Iterate over goals for older callers that treated snapshots as lists."""
        return iter(self.goals)

    def __len__(self) -> int:
        return len(self.goals)


def _activity_hours(iso_ts: str | None) -> float | None:
    """Parse an ISO timestamp and return hours since then, or None."""
    if not iso_ts:
        return None
    try:
        ts = iso_ts.replace("Z", "+00:00")
        if "+" not in ts and "-" not in ts[10:]:
            ts += "+00:00"
        dt = datetime.fromisoformat(ts)
        delta = datetime.now(UTC) - dt
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return None


def _is_stale(status: str, activity_h: float | None) -> bool:
    """Determine if a goal is stale based on its status and last activity."""
    if activity_h is None:
        # No activity recorded — stale if active, not stale if planned
        return status in ("active", "ongoing")
    threshold_h = (
        STALE_ACTIVE_DAYS * 24
        if status == "active"
        else STALE_ONGOING_DAYS * 24
        if status == "ongoing"
        else float("inf")  # planned goals are never stale
    )
    return activity_h > threshold_h


def _category_for_priority(priority: str) -> str:
    """Map vault priority to the legacy primary/secondary category."""
    return "primary" if priority.upper() in PRIMARY_PRIORITIES else "secondary"


def _last_activity_hours(goal: VaultGoal) -> float | None:
    if goal.last_modified is None:
        return None
    delta = datetime.now(UTC) - goal.last_modified
    return delta.total_seconds() / 3600


def _progress_summary(goal: VaultGoal) -> str:
    if goal.progress is None:
        return ""
    return f"{goal.progress:.0%} sprint measures complete"


def _vault_goal_to_status(goal: VaultGoal) -> GoalStatus:
    last_activity_h = _last_activity_hours(goal)
    last_modified_at = goal.last_modified.isoformat() if goal.last_modified else None
    source_path = str(goal.file_path) if goal.file_path else ""
    return GoalStatus(
        id=goal.id,
        name=goal.title,
        status=goal.status,
        category=_category_for_priority(goal.priority),
        last_activity_h=last_activity_h,
        stale=goal.stale,
        progress_summary=_progress_summary(goal),
        description="",
        domain=goal.domain,
        priority=goal.priority,
        progress=goal.progress,
        last_modified_at=last_modified_at,
        started_at=goal.started_at,
        target_date=goal.target_date,
        source_path=source_path,
        obsidian_uri=goal.obsidian_uri,
        source="vault",
    )


def empty_goal_snapshot(*, vault_base: Path | None = None) -> GoalSnapshot:
    """Return a non-null empty snapshot carrying source metadata."""
    base = vault_base or DEFAULT_VAULT_BASE
    return GoalSnapshot(source_path=str(base))


def _snapshot_from_vault_goals(
    vault_goals: list[VaultGoal],
    *,
    vault_base: Path | None = None,
) -> GoalSnapshot:
    base = vault_base or DEFAULT_VAULT_BASE
    non_terminal = [
        goal for goal in vault_goals if goal.status.lower() not in TERMINAL_GOAL_STATUSES
    ]
    active = [goal for goal in non_terminal if goal.status.lower() in ACTIVE_GOAL_STATUSES]
    goals = [_vault_goal_to_status(goal) for goal in active]
    stale_count = sum(1 for goal in goals if goal.stale)
    primary_stale = [goal.name for goal in goals if goal.stale and goal.category == "primary"]

    return GoalSnapshot(
        goals=goals,
        active_count=len(goals),
        stale_count=stale_count,
        primary_stale=primary_stale,
        total_count=len(non_terminal),
        source_path=str(base),
    )


def collect_goals(
    *,
    vault_base: Path | None = None,
    vault_name: str | None = None,
    sprint_measure_statuses: dict[str, str] | None = None,
) -> GoalSnapshot:
    """Collect active goals from Obsidian vault notes as a stable snapshot."""
    base = vault_base or DEFAULT_VAULT_BASE
    name = vault_name or DEFAULT_VAULT_NAME

    try:
        vault_goals = collect_vault_goals(
            vault_base=base,
            vault_name=name,
            sprint_measure_statuses=sprint_measure_statuses,
        )
    except Exception:
        logger.warning("Vault goal collection failed", exc_info=True)
        return empty_goal_snapshot(vault_base=base)

    return _snapshot_from_vault_goals(vault_goals, vault_base=base)
