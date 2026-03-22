"""Readiness assessment — measures data maturity for executive copilot functioning.

Deterministic, no LLM calls. Evaluates whether the copilot has enough operator
knowledge (interview data, validated priorities, neurocognitive mapping) to
function as an effective executive assistant.

Levels:
- bootstrapping: no interview conducted (regardless of other coverage)
- developing: interview done but gaps remain
- operational: interview done, dimensions covered, priorities validated
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logos.interview import ProfileAnalysis


@dataclass
class ReadinessSnapshot:
    """Data maturity assessment for copilot functioning."""

    level: str = "bootstrapping"  # "bootstrapping"|"developing"|"operational"
    interview_conducted: bool = False
    interview_fact_count: int = 0
    priorities_known: bool = False
    neurocognitive_mapped: bool = False
    profile_coverage_pct: float = 0.0
    total_facts: int = 0
    populated_dimensions: int = 0
    total_dimensions: int = 13
    missing_dimensions: list[str] = field(default_factory=list)
    sparse_dimensions: list[str] = field(default_factory=list)
    top_gap: str = ""
    gaps: list[str] = field(default_factory=list)


def collect_readiness(
    *,
    analysis: ProfileAnalysis | None = None,
) -> ReadinessSnapshot:
    """Assess data readiness for copilot functioning.

    Fully synchronous and deterministic. Reuses analyze_profile() for
    dimension gap analysis, adds interview and priority checks.

    If *analysis* is provided, it is used directly instead of calling
    analyze_profile() — useful to avoid redundant disk reads when the
    caller already has an analysis.
    """
    snap = ReadinessSnapshot()

    # Load profile analysis
    if analysis is None:
        try:
            from logos.interview import analyze_profile

            analysis = analyze_profile()
        except Exception:
            analysis = None

    if analysis is None:
        # No profile at all — everything is a gap
        snap.gaps = [
            "no interview conducted",
            "priorities not validated",
            "neurocognitive patterns undiscovered",
            "all profile dimensions missing",
        ]
        snap.top_gap = snap.gaps[0]
        return snap

    snap.total_facts = analysis.total_facts
    snap.neurocognitive_mapped = not analysis.neurocognitive_gap

    # Dimension coverage
    populated = len(analysis.dimension_stats)
    total = populated + len(analysis.missing_dimensions)
    snap.total_dimensions = total if total > 0 else 13
    snap.populated_dimensions = populated
    snap.profile_coverage_pct = (
        round(populated / snap.total_dimensions * 100, 1) if snap.total_dimensions > 0 else 0.0
    )
    snap.missing_dimensions = list(analysis.missing_dimensions)
    snap.sparse_dimensions = [s["dimension"] for s in analysis.sparse_dimensions]

    # Interview detection — scan fact sources for "interview"
    snap.interview_conducted, snap.interview_fact_count = _check_interview_facts()

    # Priorities validation — goals exist AND interview has been done
    snap.priorities_known = snap.interview_conducted and _check_priorities_validated(
        analysis,
    )

    # Compute gaps (ordered by impact on executive functioning)
    gaps: list[str] = []
    if not snap.interview_conducted:
        gaps.append("no interview conducted")
    if not snap.priorities_known:
        gaps.append("priorities not validated")
    if not snap.neurocognitive_mapped:
        gaps.append("neurocognitive patterns undiscovered")
    if snap.missing_dimensions:
        count = len(snap.missing_dimensions)
        dims = ", ".join(snap.missing_dimensions[:3])
        suffix = f" + {count - 3} more" if count > 3 else ""
        gaps.append(
            f"{count} profile dimension{'s' if count != 1 else ''} missing ({dims}{suffix})"
        )
    if snap.sparse_dimensions:
        count = len(snap.sparse_dimensions)
        gaps.append(f"{count} profile dimension{'s' if count != 1 else ''} sparse")

    snap.gaps = gaps
    snap.top_gap = gaps[0] if gaps else ""

    # Compute level
    snap.level = _compute_level(snap)

    return snap


def _check_interview_facts() -> tuple[bool, int]:
    """Check if any facts in the profile came from an interview.

    Returns (interview_conducted, interview_fact_count).
    """
    try:
        from agents.profiler import load_existing_profile

        profile = load_existing_profile()
        if profile is None:
            return False, 0

        count = 0
        for dim in profile.dimensions:
            for fact in dim.facts:
                if "interview" in fact.source.lower():
                    count += 1

        return count > 0, count
    except Exception:
        return False, 0


def _check_priorities_validated(analysis) -> bool:
    """Check if goals exist and have corresponding profile coverage."""
    try:
        from shared.operator import get_goals

        goals = get_goals()
        if not goals:
            return False
        # Goals exist and interview was done — priorities are at least acknowledged
        # Check that goal gaps aren't total (some goals have facts)
        return len(analysis.goal_gaps) < len(goals)
    except Exception:
        return False


def _compute_level(snap: ReadinessSnapshot) -> str:
    """Compute composite maturity level."""
    if not snap.interview_conducted:
        return "bootstrapping"

    if snap.missing_dimensions or not snap.neurocognitive_mapped or not snap.priorities_known:
        return "developing"

    return "operational"
