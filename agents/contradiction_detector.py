"""Cross-domain contradiction detection — carrier dynamics in practice.

Detects inconsistencies that no single agent can see because each agent
only knows its own domain. Uses the epistemic_contradiction_veto pattern
from DD-24 to check carrier facts against local knowledge.

Three detection strategies (simplest first):
1. Profile-data: stated preferences vs observed behavior
2. Calendar-temporal: scheduled events vs observed activity
3. Status-consistency: system state claims vs actual metrics

No LLM calls. Pure data extraction and rule-based comparison.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

PROFILES_DIR = Path.home() / "projects" / "hapax-council" / "profiles"
BRIEFING_PATH = PROFILES_DIR / "briefing.md"
DRIFT_REPORT = PROFILES_DIR / "drift-report.json"
HEALTH_HISTORY = PROFILES_DIR / "health-history.jsonl"
OPERATOR_PROFILE = PROFILES_DIR / "operator.json"


@dataclass(frozen=True)
class Contradiction:
    """A detected cross-domain inconsistency."""

    domain_a: str
    domain_b: str
    assertion_a: str
    assertion_b: str
    severity: str  # "high" | "medium" | "low"
    suggestion: str
    source_id: str  # for nudge dedup


def detect_contradictions() -> list[Contradiction]:
    """Run all contradiction detectors. Returns found contradictions."""
    results: list[Contradiction] = []
    results.extend(_check_briefing_vs_health())
    results.extend(_check_briefing_vs_drift())
    results.extend(_check_profile_vs_activity())
    return results


# ── Detector: Briefing claims vs actual health ───────────────────────


def _check_briefing_vs_health() -> list[Contradiction]:
    """Briefing headline says 'healthy' but health checks show failures."""
    if not BRIEFING_PATH.exists() or not HEALTH_HISTORY.exists():
        return []

    try:
        briefing = BRIEFING_PATH.read_text()
        headline = ""
        for line in briefing.splitlines():
            if line.startswith("## ") and not line.startswith("## Action"):
                headline = line[3:].strip().lower()
                break

        # Read latest health entry
        last_line = ""
        for line in HEALTH_HISTORY.read_text().splitlines():
            if line.strip():
                last_line = line
        if not last_line:
            return []

        health = json.loads(last_line)
        status = health.get("status", "unknown").lower()
        failed = health.get("failed", 0)
        degraded = health.get("degraded", 0)

        # Contradiction: briefing says healthy but health checks disagree
        if "healthy" in headline and (failed > 0 or degraded > 2):
            return [
                Contradiction(
                    domain_a="briefing",
                    domain_b="health_monitor",
                    assertion_a="Briefing says system is healthy",
                    assertion_b=f"Health monitor: {failed} failed, {degraded} degraded checks",
                    severity="high",
                    suggestion="Regenerate briefing or investigate health failures",
                    source_id="contradiction:briefing-health:stale",
                )
            ]

        # Contradiction: briefing says degraded but health is actually fine
        if "degraded" in headline and status == "healthy" and failed == 0:
            return [
                Contradiction(
                    domain_a="briefing",
                    domain_b="health_monitor",
                    assertion_a="Briefing says system is degraded",
                    assertion_b="Health monitor shows all checks passing",
                    severity="medium",
                    suggestion="Briefing may be stale — regenerate with /briefing",
                    source_id="contradiction:briefing-health:recovered",
                )
            ]

    except Exception:
        log.debug("Failed to check briefing vs health", exc_info=True)

    return []


# ── Detector: Briefing vs drift report ───────────────────────────────


def _check_briefing_vs_drift() -> list[Contradiction]:
    """Briefing omits or understates drift severity."""
    if not BRIEFING_PATH.exists() or not DRIFT_REPORT.exists():
        return []

    try:
        briefing = BRIEFING_PATH.read_text()

        drift = json.loads(DRIFT_REPORT.read_text())
        items = drift.get("drift_items", [])
        high_count = sum(1 for i in items if i.get("severity") == "high")

        if high_count == 0:
            return []

        # Check if briefing mentions drift at all
        briefing_lower = briefing.lower()
        mentions_drift = "drift" in briefing_lower

        if not mentions_drift and high_count >= 5:
            return [
                Contradiction(
                    domain_a="briefing",
                    domain_b="drift_monitor",
                    assertion_a="Briefing does not mention drift",
                    assertion_b=f"Drift report has {high_count} high-severity items",
                    severity="high",
                    suggestion="Regenerate briefing to include drift status",
                    source_id="contradiction:briefing-drift:omitted",
                )
            ]

        # Check if briefing understates
        if mentions_drift and high_count >= 10:
            # Extract drift count from briefing if present
            import re

            match = re.search(r"(\d+)\s*drift", briefing_lower)
            if match:
                briefing_drift = int(match.group(1))
                if briefing_drift < high_count:
                    return [
                        Contradiction(
                            domain_a="briefing",
                            domain_b="drift_monitor",
                            assertion_a=f"Briefing reports {briefing_drift} drift items",
                            assertion_b=f"Drift report has {len(items)} items ({high_count} high)",
                            severity="medium",
                            suggestion="Briefing drift count is stale",
                            source_id="contradiction:briefing-drift:understated",
                        )
                    ]

    except Exception:
        log.debug("Failed to check briefing vs drift", exc_info=True)

    return []


# ── Detector: Profile preferences vs observed behavior ───────────────


def _check_profile_vs_activity() -> list[Contradiction]:
    """Stated profile preferences contradict observed patterns."""
    if not OPERATOR_PROFILE.exists():
        return []

    contradictions: list[Contradiction] = []

    try:
        profile = json.loads(OPERATOR_PROFILE.read_text())

        # Check energy cycle claims vs actual patterns
        neuro = profile.get("neurocognitive", {})
        if isinstance(neuro, dict):
            energy_patterns = neuro.get("energy_cycles", [])
            

            # Check: profile claims morning peak but we know operator works late
            # (This is detected from Claude Code session history)
            from agents.context_restore import CC_HISTORY

            if CC_HISTORY.exists():
                try:
                    lines = CC_HISTORY.read_text().splitlines()
                    recent = lines[-100:] if len(lines) > 100 else lines
                    late_night_sessions = 0
                    morning_sessions = 0
                    for line in recent:
                        try:
                            entry = json.loads(line)
                            ts = entry.get("timestamp", 0)
                            if isinstance(ts, (int, float)) and ts > 1e12:
                                ts = ts / 1000
                            hour = datetime.fromtimestamp(ts, tz=UTC).hour
                            if 0 <= hour <= 4:
                                late_night_sessions += 1
                            elif 7 <= hour <= 10:
                                morning_sessions += 1
                        except (json.JSONDecodeError, ValueError, OSError):
                            continue

                    # If mostly late-night sessions and profile mentions "morning"
                    if late_night_sessions > morning_sessions * 2 and late_night_sessions > 10:
                        for pattern in energy_patterns:
                            if isinstance(pattern, str) and "morning" in pattern.lower():
                                contradictions.append(
                                    Contradiction(
                                        domain_a="operator_profile",
                                        domain_b="session_activity",
                                        assertion_a=f"Profile: {pattern}",
                                        assertion_b=(
                                            f"Last 100 sessions: {late_night_sessions} late-night "
                                            f"vs {morning_sessions} morning"
                                        ),
                                        severity="medium",
                                        suggestion="Profile energy patterns may need updating",
                                        source_id="contradiction:profile-activity:energy",
                                    )
                                )
                                break
                except Exception:
                    pass

    except Exception:
        log.debug("Failed to check profile vs activity", exc_info=True)

    return contradictions


if __name__ == "__main__":
    results = detect_contradictions()
    if not results:
        print("No contradictions detected.")
    else:
        for c in results:
            print(f"[{c.severity}] {c.domain_a} ↔ {c.domain_b}")
            print(f"  A: {c.assertion_a}")
            print(f"  B: {c.assertion_b}")
            print(f"  → {c.suggestion}")
            print()
