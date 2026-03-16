"""Nudge collector — surfaces prioritized open loops for the chat UI.

Fully deterministic, no LLM calls. Aggregates data from existing collectors
and returns a ranked list of suggested actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from cockpit.data.briefing import BriefingData, collect_briefing
from cockpit.data.drift import collect_drift
from cockpit.data.health import collect_health_history
from cockpit.data.scout import collect_scout

# Staleness thresholds in hours (duplicated from sidebar.py to avoid
# coupling cockpit.data → cockpit.widgets).
STALE_BRIEFING_H = 26  # briefing runs daily, stale after ~1 day
STALE_SCOUT_H = 192  # scout runs weekly, stale after ~8 days
STALE_DRIFT_H = 192  # drift runs weekly, stale after ~8 days

MAX_VISIBLE_NUDGES = 7  # attention budget cap — cognitive overload prevention
DISMISS_COOLDOWN_H = 48  # dismissed nudges suppressed for 48 hours


@dataclass
class Nudge:
    """A single actionable nudge for the operator."""

    category: str  # "health" | "briefing" | "readiness" | "profile" | "scout" | "drift" | "action" | "knowledge"
    priority_score: int  # numeric, higher = more urgent
    priority_label: str  # "critical" | "high" | "medium" | "low"
    title: str  # short line, e.g. "2 health checks failing"
    detail: str  # elaboration
    suggested_action: str
    command_hint: str = ""
    source_id: str = ""  # identity tracking for decision capture


def _age_hours(iso_ts: str) -> float | None:
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


# ── Priority mapping for action items ────────────────────────────────────────

_ACTION_ITEM_SCORES = {"high": 80, "medium": 50, "low": 25}
_ACTION_ITEM_LABELS = {"high": "high", "medium": "medium", "low": "low"}


def _collect_goal_nudges(nudges: list[Nudge]) -> None:
    """Check operator goals for staleness."""
    try:
        from cockpit.data.goals import collect_goals

        snapshot = collect_goals()
        for g in snapshot.goals:
            if not g.stale:
                continue
            score = 60 if g.category == "primary" else 35
            label = "medium" if g.category == "primary" else "low"
            if g.last_activity_h is not None:
                days = int(g.last_activity_h / 24)
                detail = f"No activity in {days} days"
            else:
                detail = "No recorded activity"
            nudges.append(
                Nudge(
                    category="goal",
                    priority_score=score,
                    priority_label=label,
                    title=f"Stale goal: {g.name}",
                    detail=detail,
                    suggested_action=f"Review progress on {g.name}",
                    source_id=f"goal:{g.id}",
                )
            )
    except Exception:
        pass


def _collect_action_item_nudges(
    nudges: list[Nudge],
    briefing: BriefingData | None,
) -> None:
    """Convert briefing action items into individual nudges."""
    if briefing is None or not briefing.action_items:
        return
    for item in briefing.action_items:
        nudges.append(
            Nudge(
                category="action",
                priority_score=_ACTION_ITEM_SCORES.get(item.priority, 25),
                priority_label=_ACTION_ITEM_LABELS.get(item.priority, "low"),
                title=item.action,
                detail=item.reason,
                suggested_action=item.action,
                command_hint=item.command,
                source_id=f"briefing-action:{item.action[:40]}",
            )
        )


# ── Per-source collectors ────────────────────────────────────────────────────


def _collect_health_nudges(nudges: list[Nudge]) -> None:
    """Generate per-check nudges weighted by service tier."""
    try:
        from shared.service_tiers import TIER_NUDGE_SCORES, tier_for_check

        history = collect_health_history(limit=1)
        if not history.entries:
            return
        last = history.entries[-1]
        if last.status not in ("failed", "degraded"):
            return

        failed_checks = getattr(last, "failed_checks", None) or []
        if not failed_checks:
            # Fallback: single blunt nudge if no per-check data
            nudges.append(
                Nudge(
                    category="health",
                    priority_score=100,
                    priority_label="critical",
                    title=f"{last.failed} health check{'s' if last.failed != 1 else ''} failing",
                    detail=f"Last check: {last.status}, {last.healthy} healthy / {last.failed} failed",
                    suggested_action="Auto-diagnose and attempt remediation of failing checks",
                    command_hint="uv run python -m agents.health_monitor --fix",
                    source_id="health:aggregate",
                )
            )
            return

        # Group failed checks by subsystem (first dotted segment) so
        # checks that map to the same --check command become one nudge.
        subsystem_checks: dict[str, list[tuple[str, int, str]]] = {}
        for check_name in failed_checks:
            subsystem = check_name.split(".")[0]
            tier = tier_for_check(check_name)
            score = TIER_NUDGE_SCORES.get(tier, 85)
            tier_label = f"Tier {tier.value} ({tier.name.lower()})"
            subsystem_checks.setdefault(subsystem, []).append((check_name, score, tier_label))

        for subsystem, checks in subsystem_checks.items():
            score = max(s for _, s, _ in checks)
            label = (
                "critical"
                if score >= 90
                else "high"
                if score >= 70
                else "medium"
                if score >= 40
                else "low"
            )
            if len(checks) == 1:
                check_name, _, tier_label = checks[0]
                title = f"{check_name} failing"
                detail = f"{tier_label} service check"
                source_id = f"health:{check_name}"
            else:
                names = [c[0] for c in checks]
                title = f"{len(checks)} {subsystem} checks failing"
                detail = ", ".join(names)
                source_id = f"health:{subsystem}"
            nudges.append(
                Nudge(
                    category="health",
                    priority_score=score,
                    priority_label=label,
                    title=title,
                    detail=detail,
                    suggested_action=f"Run targeted health check on {subsystem} and attempt fix",
                    command_hint=f"uv run python -m agents.health_monitor --check {subsystem} --fix",
                    source_id=source_id,
                )
            )
    except Exception:
        pass


def _collect_briefing_nudges(nudges: list[Nudge]) -> None:
    """Check briefing freshness and action items."""
    try:
        briefing = collect_briefing()
        if briefing is None:
            nudges.append(
                Nudge(
                    category="briefing",
                    priority_score=55,
                    priority_label="medium",
                    title="No briefing available",
                    detail="Briefing file missing or empty",
                    suggested_action="Generate today's briefing and save to profiles/",
                    command_hint="uv run python -m agents.briefing --save",
                    source_id="briefing:missing",
                )
            )
            return

        high_items = [a for a in briefing.action_items if a.priority == "high"]
        age = _age_hours(briefing.generated_at)
        stale = age is not None and age > STALE_BRIEFING_H

        if high_items:
            count = len(high_items)
            nudges.append(
                Nudge(
                    category="briefing",
                    priority_score=80,
                    priority_label="high",
                    title=f"{count} high-priority action item{'s' if count != 1 else ''}",
                    detail=high_items[0].action,
                    suggested_action="Review briefing action items",
                    source_id="briefing:high-actions",
                )
            )

        if stale and briefing.action_items:
            nudges.append(
                Nudge(
                    category="briefing",
                    priority_score=75,
                    priority_label="high",
                    title=f"Briefing {age:.0f}h stale with unresolved items",
                    detail=f"{len(briefing.action_items)} action items in stale briefing",
                    suggested_action="Generate fresh briefing (replaces stale one)",
                    command_hint="uv run python -m agents.briefing --save",
                    source_id="briefing:stale-with-items",
                )
            )
        elif stale:
            nudges.append(
                Nudge(
                    category="briefing",
                    priority_score=55,
                    priority_label="medium",
                    title=f"Briefing {age:.0f}h stale",
                    detail="No unresolved action items",
                    suggested_action="Generate fresh briefing (replaces stale one)",
                    command_hint="uv run python -m agents.briefing --save",
                    source_id="briefing:stale",
                )
            )
    except Exception:
        pass


def _collect_readiness_nudges(nudges: list[Nudge], *, analysis=None) -> None:
    """Check data readiness for interview, priorities, and neurocognitive gaps."""
    try:
        from cockpit.data.readiness import collect_readiness

        snap = collect_readiness(analysis=analysis)

        if not snap.interview_conducted:
            nudges.append(
                Nudge(
                    category="readiness",
                    priority_score=65,
                    priority_label="high",
                    title="No interview conducted yet",
                    detail=(
                        f"{snap.total_facts} facts from observation, zero from direct conversation"
                    ),
                    suggested_action="Start a profile interview to establish ground truth",
                    command_hint="",
                    source_id="readiness:no-interview",
                )
            )
            return  # Other readiness nudges are moot without an interview

        if not snap.priorities_known:
            nudges.append(
                Nudge(
                    category="readiness",
                    priority_score=55,
                    priority_label="medium",
                    title="Goals not validated through interview",
                    detail="Goals exist in operator.json but haven't been discussed",
                    suggested_action="Interview to validate and refine priorities",
                    command_hint="",
                    source_id="readiness:priorities-unvalidated",
                )
            )

        if not snap.neurocognitive_mapped:
            nudges.append(
                Nudge(
                    category="readiness",
                    priority_score=50,
                    priority_label="medium",
                    title="Neurocognitive profile undiscovered",
                    detail="Focus patterns, blockers, and energy cycles unknown",
                    suggested_action="Interview to explore cognitive patterns",
                    command_hint="",
                    source_id="readiness:neurocognitive-unmapped",
                )
            )
    except Exception:
        pass


def _collect_profile_nudges(nudges: list[Nudge], *, analysis=None) -> None:
    """Check profile completeness via analyze_profile()."""
    try:
        if analysis is None:
            from cockpit.interview import analyze_profile

            analysis = analyze_profile()

        missing = len(analysis.missing_dimensions)
        sparse = len(analysis.sparse_dimensions)
        total_dims = len(analysis.dimension_stats) + missing

        if missing >= 3:
            nudges.append(
                Nudge(
                    category="profile",
                    priority_score=60,
                    priority_label="medium",
                    title=f"Profile incomplete ({total_dims - missing}/{total_dims} dimensions)",
                    detail=f"{missing} missing dimensions: {', '.join(analysis.missing_dimensions[:3])}",
                    suggested_action="Start a profile interview",
                    command_hint="",
                    source_id="profile:incomplete-many",
                )
            )
        elif missing > 0:
            nudges.append(
                Nudge(
                    category="profile",
                    priority_score=50,
                    priority_label="medium",
                    title=f"Profile incomplete ({total_dims - missing}/{total_dims} dimensions)",
                    detail=f"{missing} missing: {', '.join(analysis.missing_dimensions)}",
                    suggested_action="Start a profile interview",
                    command_hint="",
                    source_id="profile:incomplete-few",
                )
            )
        elif sparse > 0:
            nudges.append(
                Nudge(
                    category="profile",
                    priority_score=40,
                    priority_label="medium",
                    title=f"{sparse} profile dimension{'s' if sparse != 1 else ''} sparse",
                    detail="Dimensions with fewer than 3 facts",
                    suggested_action="Deepen profile via interview",
                    command_hint="",
                    source_id="profile:sparse",
                )
            )
    except Exception:
        pass


def _collect_scout_nudges(nudges: list[Nudge]) -> None:
    """Check scout report for adopt/evaluate recommendations and staleness."""
    try:
        scout = collect_scout()
        if scout is None:
            return

        if scout.adopt_count > 0:
            nudges.append(
                Nudge(
                    category="scout",
                    priority_score=30,
                    priority_label="low",
                    title=f"{scout.adopt_count} component{'s' if scout.adopt_count != 1 else ''} recommended for adoption",
                    detail="Scout found components worth adopting",
                    suggested_action="Open Scout panel in sidebar to adopt, defer, or dismiss",
                    source_id="scout:adopt",
                )
            )
        elif scout.evaluate_count > 0:
            nudges.append(
                Nudge(
                    category="scout",
                    priority_score=20,
                    priority_label="low",
                    title=f"{scout.evaluate_count} component{'s' if scout.evaluate_count != 1 else ''} to evaluate",
                    detail="Scout found components worth evaluating",
                    suggested_action="Open Scout panel in sidebar to review recommendations",
                    source_id="scout:evaluate",
                )
            )

        age = _age_hours(scout.generated_at)
        if age is not None and age > STALE_SCOUT_H:
            nudges.append(
                Nudge(
                    category="scout",
                    priority_score=25,
                    priority_label="low",
                    title=f"Scout report {age:.0f}h stale",
                    detail="Weekly horizon scan overdue",
                    suggested_action="Re-run horizon scan to refresh recommendations",
                    command_hint="uv run python -m agents.scout",
                    source_id="scout:stale",
                )
            )
    except Exception:
        pass


def _collect_sufficiency_nudges(nudges: list[Nudge]) -> None:
    """Run sufficiency probes and generate nudges for failures."""
    try:
        from shared.sufficiency_probes import run_probes

        results = run_probes()
        failures = [r for r in results if not r.met]
        if not failures:
            return

        for r in failures:
            nudges.append(
                Nudge(
                    category="sufficiency",
                    priority_score=45,
                    priority_label="medium",
                    title=f"Sufficiency gap: {r.probe_id}",
                    detail=r.evidence,
                    suggested_action=f"Address sufficiency gap: {r.evidence}",
                    source_id=f"sufficiency:{r.probe_id}",
                )
            )
    except Exception:
        pass


def _collect_knowledge_sufficiency_nudges(nudges: list[Nudge]) -> None:
    """Generate nudges from knowledge sufficiency gaps across all domains."""
    try:
        from cockpit.data.knowledge_sufficiency import collect_all_domain_gaps, gaps_to_nudges

        reports = collect_all_domain_gaps()
        for domain_id, report in reports.items():
            nudges.extend(gaps_to_nudges(report.gaps, domain_id=domain_id))
    except Exception:
        pass


def _collect_precedent_nudges(nudges: list[Nudge]) -> None:
    """Generate nudges for agent precedents awaiting operator review."""
    try:
        from shared.axiom_precedents import PrecedentStore

        store = PrecedentStore()
        pending = store.get_pending_review()
        if not pending:
            return

        for p in pending:
            age = _age_hours(p.created)
            if age is not None and age > 21 * 24:
                score, label = 75, "high"
            elif age is not None and age > 7 * 24:
                score, label = 55, "medium"
            else:
                score, label = 30, "low"

            days_str = f" ({int(age / 24)}d old)" if age is not None else ""
            nudges.append(
                Nudge(
                    category="sufficiency",
                    priority_score=score,
                    priority_label=label,
                    title=f"Precedent awaiting review: {p.axiom_id}/{p.id}{days_str}",
                    detail=f"Tier {p.tier}, decision: {p.decision}. {p.situation[:80]}",
                    suggested_action="Review and confirm or reject this precedent",
                    command_hint="/axiom-review",
                    source_id=f"precedent:{p.id}",
                )
            )
    except Exception:
        pass


def _collect_rag_quality_nudges(nudges: list[Nudge]) -> None:
    """G3: Surface knowledge gaps from RAG zero-result queries."""
    try:
        from shared.langfuse_client import query_zero_result_spans

        zero_results = query_zero_result_spans(hours=24)
        if not zero_results:
            return

        # Group by collection
        by_collection: dict[str, list[str]] = {}
        for r in zero_results:
            col = r.get("collection") or "unknown"
            q = r.get("query", "")
            by_collection.setdefault(col, []).append(q)

        for col, queries in by_collection.items():
            if len(queries) < 3:
                continue
            sample = "; ".join(q for q in queries[:3] if q)
            nudges.append(
                Nudge(
                    category="knowledge",
                    priority_score=45,
                    priority_label="medium",
                    title=f"RAG knowledge gap in {col} ({len(queries)} zero-result queries)",
                    detail=f"Sample queries: {sample[:150]}",
                    suggested_action=f"Review and index content for '{col}' collection",
                    source_id=f"rag-quality:{col}",
                )
            )
    except Exception:
        pass


def _collect_emergence_nudges(nudges: list[Nudge]) -> None:
    """Generate nudges from emergence detection candidates."""
    try:
        from cockpit.data.emergence import collect_emergence

        snapshot = collect_emergence()
        for candidate in snapshot.candidates:
            nudges.append(
                Nudge(
                    category="emergence",
                    priority_score=55,
                    priority_label="medium",
                    title=f"Potential new domain: {candidate.label}",
                    detail=(
                        f"{candidate.event_count} activities over {candidate.week_span} weeks. "
                        f"Keywords: {', '.join(candidate.top_keywords[:3])}"
                    ),
                    suggested_action=f"/domain propose {candidate.candidate_id}",
                    command_hint="",
                    source_id=f"emergence:{candidate.candidate_id}",
                )
            )
    except Exception:
        pass


def _collect_drift_nudges(nudges: list[Nudge]) -> None:
    """Check drift report for items and staleness."""
    try:
        drift = collect_drift()
        if drift is None:
            return

        if drift.drift_count > 0:
            high_count = sum(1 for d in drift.items if d.severity == "high")
            score = 90 if high_count > 0 else 85
            label = "critical" if high_count > 0 else "high"
            nudges.append(
                Nudge(
                    category="drift",
                    priority_score=score,
                    priority_label=label,
                    title=f"{drift.drift_count} drift item{'s' if drift.drift_count != 1 else ''}"
                    + (f" ({high_count} high)" if high_count else ""),
                    detail=drift.summary or "Documentation out of sync with reality",
                    suggested_action="Scan docs vs reality, generate and apply corrections",
                    command_hint="uv run python -m agents.drift_detector --fix --apply",
                    source_id="drift:items",
                )
            )

        age = _age_hours(drift.latest_timestamp)
        if age is not None and age > STALE_DRIFT_H:
            nudges.append(
                Nudge(
                    category="drift",
                    priority_score=25,
                    priority_label="low",
                    title=f"Drift report {age:.0f}h stale",
                    detail="Weekly drift detection overdue",
                    suggested_action="Re-scan documentation against live infrastructure",
                    command_hint="uv run python -m agents.drift_detector",
                    source_id="drift:stale",
                )
            )
    except Exception:
        pass


def _collect_contradiction_nudges(nudges: list[Nudge]) -> None:
    """Surface cross-domain contradictions as nudges (DD-24)."""
    try:
        from agents.contradiction_detector import detect_contradictions

        contradictions = detect_contradictions()
        for c in contradictions:
            score = 80 if c.severity == "high" else 60 if c.severity == "medium" else 40
            nudges.append(
                Nudge(
                    category="knowledge",
                    priority_score=score,
                    priority_label=c.severity,
                    title=f"{c.domain_a} \u2194 {c.domain_b}: {c.assertion_a[:60]}",
                    detail=f"{c.assertion_a}\nvs: {c.assertion_b}",
                    suggested_action=c.suggestion,
                    source_id=c.source_id,
                )
            )
    except Exception:
        pass


# ── Main entry point ─────────────────────────────────────────────────────────


def collect_nudges(
    *,
    max_nudges: int = 5,
    briefing: BriefingData | None = None,
    accommodations: object | None = None,
) -> list[Nudge]:
    """Collect and rank nudges from all sources.

    Fully synchronous. Returns up to max_nudges sorted by priority (highest first).

    When *briefing* is passed, action items from it are converted to individual
    nudges (used by the dashboard). Otherwise briefing is fetched internally for
    staleness/missing checks only.
    """
    nudges: list[Nudge] = []
    _collect_health_nudges(nudges)

    # When briefing is provided, inject its action items as individual nudges
    if briefing is not None:
        _collect_action_item_nudges(nudges, briefing)
        _collect_briefing_nudges(nudges)
    else:
        _collect_briefing_nudges(nudges)

    # Single analyze_profile() call shared by readiness + profile collectors
    try:
        from cockpit.interview import analyze_profile

        analysis = analyze_profile()
    except Exception:
        analysis = None

    _collect_readiness_nudges(nudges, analysis=analysis)
    _collect_profile_nudges(nudges, analysis=analysis)
    _collect_scout_nudges(nudges)
    _collect_drift_nudges(nudges)
    _collect_goal_nudges(nudges)
    _collect_sufficiency_nudges(nudges)
    _collect_knowledge_sufficiency_nudges(nudges)
    _collect_precedent_nudges(nudges)
    _collect_rag_quality_nudges(nudges)
    _collect_emergence_nudges(nudges)
    _collect_contradiction_nudges(nudges)

    # Filter out recently dismissed nudges
    nudges = _filter_dismissed(nudges)

    # GAP-5: Watch biometrics → nudge priority adjustment
    _apply_watch_adjustments(nudges)

    # Apply accommodation adjustments
    if accommodations is not None:
        _apply_accommodation_adjustments(nudges, accommodations)

    nudges.sort(key=lambda n: (-n.priority_score, n.category))

    cap = min(max_nudges, MAX_VISIBLE_NUDGES)
    if len(nudges) > cap:
        overflow = len(nudges) - cap
        visible = nudges[:cap]
        visible.append(
            Nudge(
                category="meta",
                priority_score=0,
                priority_label="low",
                title=f"+ {overflow} more items",
                detail=f"{overflow} lower-priority items not shown",
                suggested_action="",
                source_id="meta:overflow",
            )
        )
        return visible

    return nudges[:max_nudges]


def _apply_watch_adjustments(nudges: list[Nudge]) -> None:
    """GAP-5: Adjust nudge priorities based on watch biometrics.

    - Poor sleep quality: reduce non-critical scores by 20%
    - Activity state "sleep" or "rest": suppress non-critical nudges entirely
    """
    import json
    from pathlib import Path

    watch_dir = Path.home() / "hapax-state" / "watch"

    # Read activity state
    activity_state = ""
    try:
        activity_file = watch_dir / "activity.json"
        if activity_file.exists():
            data = json.loads(activity_file.read_text())
            activity_state = data.get("state", "").upper()
    except (json.JSONDecodeError, OSError):
        pass

    # Read sleep quality
    sleep_quality = ""
    try:
        sleep_file = watch_dir / "sleep.json"
        if sleep_file.exists():
            data = json.loads(sleep_file.read_text())
            sleep_quality = data.get("quality", "").lower()
    except (json.JSONDecodeError, OSError):
        pass

    # Suppress non-critical nudges during sleep/rest
    if activity_state in ("STILL", "SLEEP"):
        for nudge in nudges:
            if nudge.priority_label not in ("critical",):
                nudge.priority_score = 0

    # Poor sleep: reduce non-critical scores by 20%
    if sleep_quality in ("poor", "restless", "bad"):
        for nudge in nudges:
            if nudge.priority_label not in ("critical", "high"):
                nudge.priority_score = max(1, int(nudge.priority_score * 0.8))


def _filter_dismissed(nudges: list[Nudge]) -> list[Nudge]:
    """Remove nudges that were dismissed within the cooldown window."""
    try:
        from cockpit.data.decisions import collect_decisions

        decisions = collect_decisions(hours=DISMISS_COOLDOWN_H)
        dismissed_titles = {d.nudge_title for d in decisions if d.action == "dismissed"}
        if not dismissed_titles:
            return nudges
        return [n for n in nudges if n.title not in dismissed_titles]
    except Exception:
        return nudges


def _apply_accommodation_adjustments(nudges: list[Nudge], accommodations) -> None:
    """Adjust nudge scores based on active accommodations."""
    if not getattr(accommodations, "energy_aware", False):
        return

    from datetime import datetime

    hour = datetime.now().hour
    low_hours = getattr(accommodations, "low_hours", [])
    if hour not in low_hours:
        return

    # During low-energy hours: reduce non-critical scores by 20%
    for nudge in nudges:
        if nudge.priority_label not in ("critical", "high"):
            nudge.priority_score = max(1, int(nudge.priority_score * 0.8))
