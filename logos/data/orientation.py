"""Orientation collector — assembles per-domain state for the orientation panel.

Deterministic assembly phase (always runs) plus conditional narrative gating.
No LLM calls — narrative generation is deferred to the async route handler.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from logos.data.session_inference import SessionContext, infer_session
from logos.data.vault_goals import VaultGoal, collect_vault_goals

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "domains.yaml"

# Module-level narrative cache.
_last_narrative: str | None = None
_last_narrative_ts: float = 0.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GoalSummary:
    id: str
    title: str
    priority: str
    status: str
    progress: float | None
    stale: bool
    file_path: str
    obsidian_uri: str
    target_date: str | None = None


@dataclass
class SprintSummary:
    current_sprint: int = 0
    measures_completed: int = 0
    measures_total: int = 0
    blocking_gate: str | None = None
    next_measure: str | None = None
    next_measure_title: str | None = None
    models: dict[str, float] = field(default_factory=dict)


@dataclass
class DomainState:
    domain: str
    top_goal: GoalSummary | None = None
    goal_count: int = 0
    stale_count: int = 0
    recency_hours: float = float("inf")
    health: str = "dormant"  # "active" | "stale" | "dormant" | "blocked"
    sprint_progress: SprintSummary | None = None
    next_action: str | None = None
    next_action_link: str | None = None


@dataclass
class OrientationState:
    session: SessionContext
    domains: list[DomainState] = field(default_factory=list)
    briefing_headline: str | None = None
    briefing_generated_at: str | None = None
    system_health: str = "unknown"
    drift_high_count: int = 0
    narrative: str | None = None
    narrative_generated_at: str | None = None
    stimmung_stance: str = "nominal"


# ---------------------------------------------------------------------------
# Internal data readers
# ---------------------------------------------------------------------------


def _load_domain_registry() -> dict[str, dict]:
    """Read config/domains.yaml and return the domains mapping."""
    try:
        with open(CONFIG_PATH) as f:
            data = yaml.safe_load(f)
        return data.get("domains", {}) if data else {}
    except (OSError, yaml.YAMLError):
        logger.warning("Failed to load domain registry from %s", CONFIG_PATH)
        return {}


def _get_sprint_summary() -> SprintSummary | None:
    """Read sprint state from /dev/shm and return SprintSummary or None."""
    sprint_path = Path("/dev/shm/hapax-sprint/state.json")
    try:
        data = json.loads(sprint_path.read_text())
        return SprintSummary(
            current_sprint=data.get("current_sprint", 0),
            measures_completed=data.get("measures_completed", 0),
            measures_total=data.get("measures_total", 0),
            blocking_gate=data.get("blocking_gate"),
            next_measure=data.get("next_measure"),
            next_measure_title=data.get("next_measure_title"),
            models=data.get("models", {}),
        )
    except (OSError, json.JSONDecodeError):
        return None


def _sprint_measure_statuses() -> dict[str, str]:
    """Read sprint measure statuses from /dev/shm."""
    sprint_path = Path("/dev/shm/hapax-sprint/state.json")
    try:
        data = json.loads(sprint_path.read_text())
        return data.get("measure_statuses", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _get_stimmung_stance() -> str:
    """Read stimmung stance from /dev/shm."""
    stimmung_path = Path("/dev/shm/hapax-stimmung/state.json")
    try:
        data = json.loads(stimmung_path.read_text())
        return data.get("stance", "nominal")
    except (OSError, json.JSONDecodeError):
        return "nominal"


def _get_briefing() -> tuple[str | None, str | None]:
    """Lazy-load briefing collector and return (headline, generated_at)."""
    try:
        from logos.data.briefing import collect_briefing

        result = collect_briefing()
        return (result.get("headline"), result.get("generated_at"))
    except Exception:
        return (None, None)


def _get_health_summary() -> tuple[str, int]:
    """Lazy-load health + drift collectors and return (status, high_drift_count)."""
    try:
        from logos.data.drift import collect_drift
        from logos.data.health import collect_health

        health = collect_health()
        drift = collect_drift()
        status = health.get("status", "unknown") if isinstance(health, dict) else "unknown"
        high_count = (
            drift.get("high_count", 0)
            if isinstance(drift, dict)
            else len([d for d in drift if getattr(d, "severity", "") == "high"])
            if isinstance(drift, list)
            else 0
        )
        return (status, high_count)
    except Exception:
        return ("unknown", 0)


# ---------------------------------------------------------------------------
# Domain priority and health
# ---------------------------------------------------------------------------


def _domain_priority(ds: DomainState) -> tuple[int, float]:
    """Sort key: lower = higher priority. (tier, recency_hours)."""
    if ds.health == "blocked":
        return (0, ds.recency_hours)
    if ds.health == "stale" and ds.top_goal and ds.top_goal.priority == "P0":
        return (10, ds.recency_hours)
    if ds.health == "active":
        return (30, ds.recency_hours)
    if ds.health == "stale":
        return (50, ds.recency_hours)
    # dormant
    return (100, ds.recency_hours)


def _compute_health(
    goals: list[VaultGoal],
    sprint: SprintSummary | None,
    recency_hours: float,
) -> str:
    """Determine domain health: blocked > stale > active > dormant."""
    if sprint and sprint.blocking_gate:
        return "blocked"
    stale_goals = [g for g in goals if g.stale]
    if stale_goals:
        return "stale"
    if goals and recency_hours < 168.0:  # within a week
        return "active"
    return "dormant"


# ---------------------------------------------------------------------------
# Narrative gating
# ---------------------------------------------------------------------------


def _should_generate_narrative(
    session: SessionContext,
    stance: str,
    *,
    last_narrative_age_s: float,
) -> bool:
    """Decide whether to generate a fresh narrative.

    Rules (evaluated in order):
    - Suppressed if stance is degraded or critical.
    - Suppressed if last narrative < 30 min old.
    - Triggered on session boundary.
    - Triggered on morning return (absence >= 8h).
    - Otherwise suppressed (steady state).
    """
    if stance in ("degraded", "critical"):
        return False
    if last_narrative_age_s < 1800:
        return False
    if session.session_boundary:
        return True
    return session.absence_hours >= 8.0


# ---------------------------------------------------------------------------
# Main collector
# ---------------------------------------------------------------------------


def collect_orientation() -> OrientationState:
    """Assemble orientation state from all data sources.

    Deterministic — no LLM calls. Narrative field is populated from cache only;
    actual generation is deferred to the async API handler.
    """
    global _last_narrative, _last_narrative_ts

    registry = _load_domain_registry()
    session = infer_session(
        domains={name: {"telemetry": cfg.get("telemetry", {})} for name, cfg in registry.items()}
    )
    all_goals = collect_vault_goals(sprint_measure_statuses=_sprint_measure_statuses())
    sprint = _get_sprint_summary()
    stance = _get_stimmung_stance()
    briefing_headline, briefing_generated_at = _get_briefing()
    system_health, drift_high_count = _get_health_summary()

    # Build per-domain state.
    domain_states: list[DomainState] = []
    for domain_name in registry:
        domain_goals = [g for g in all_goals if g.domain == domain_name]
        stale_count = sum(1 for g in domain_goals if g.stale)
        recency = session.domain_recency.get(domain_name, float("inf"))

        # Top goal: first in priority-sorted list for this domain.
        top_goal_summary: GoalSummary | None = None
        if domain_goals:
            g = domain_goals[0]
            top_goal_summary = GoalSummary(
                id=g.id,
                title=g.title,
                priority=g.priority,
                status=g.status,
                progress=g.progress,
                stale=g.stale,
                file_path=str(g.file_path) if g.file_path else "",
                obsidian_uri=g.obsidian_uri,
                target_date=g.target_date,
            )

        # Sprint progress — research domain only per spec.
        has_sprint = "sprint" in (registry.get(domain_name, {}).get("apis") or {})
        domain_sprint = sprint if sprint and has_sprint else None

        health = _compute_health(domain_goals, domain_sprint, recency)

        # Next action.
        next_action: str | None = None
        next_action_link: str | None = None
        if domain_sprint and domain_sprint.blocking_gate:
            next_action = f"Resolve blocking gate: {domain_sprint.blocking_gate}"
        elif domain_sprint and domain_sprint.next_measure:
            title = domain_sprint.next_measure_title or domain_sprint.next_measure
            next_action = f"Next measure: {title}"
        elif top_goal_summary:
            next_action_link = top_goal_summary.obsidian_uri

        ds = DomainState(
            domain=domain_name,
            top_goal=top_goal_summary,
            goal_count=len(domain_goals),
            stale_count=stale_count,
            recency_hours=recency,
            health=health,
            sprint_progress=domain_sprint,
            next_action=next_action,
            next_action_link=next_action_link,
        )
        domain_states.append(ds)

    # Sort domains by priority.
    domain_states.sort(key=_domain_priority)

    # Narrative: use cached value only.
    narrative = _last_narrative
    narrative_generated_at: str | None = None
    if _last_narrative_ts > 0:
        from datetime import UTC, datetime

        narrative_generated_at = datetime.fromtimestamp(_last_narrative_ts, tz=UTC).isoformat()

    return OrientationState(
        session=session,
        domains=domain_states,
        briefing_headline=briefing_headline,
        briefing_generated_at=briefing_generated_at,
        system_health=system_health,
        drift_high_count=drift_high_count,
        narrative=narrative,
        narrative_generated_at=narrative_generated_at,
        stimmung_stance=stance,
    )
