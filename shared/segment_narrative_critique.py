"""Segment narrative quality critique via deliberative council.

Runs the council in NARRATIVE mode on composed segment scripts,
producing structured verdicts with revision directives. Integrates
as Pass 4 in the segment prep pipeline (after disconfirmation).

The narrative quality rubric evaluates structural properties that make
segments work as broadcast speech: information gaps, escalation,
source consequence, focalization integrity, evaluation sufficiency,
promise-delivery ratio, and authentic uncertainty. Each axis reinforces
non-anthropomorphism through scoring.
"""

from __future__ import annotations

import asyncio
import logging

from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
    NarrativeVerdict,
    NarrativeVerdictStatus,
)
from agents.deliberative_council.rubrics import NarrativeQualityRubric

_log = logging.getLogger(__name__)


def run_narrative_critique(
    script_text: str,
    programme_id: str,
    *,
    config: CouncilConfig | None = None,
) -> NarrativeVerdict:
    """Run the narrative quality council on a composed segment script.

    Returns a NarrativeVerdict with scores, verdict status, and
    revision directives. Fail-open: returns BROADCAST_READY if
    the council is unavailable.
    """
    if not script_text or len(script_text.strip()) < 100:
        return _empty_verdict("script_too_short")

    try:
        return asyncio.run(_run_narrative_critique_async(script_text, programme_id, config))
    except Exception as e:
        _log.warning("Narrative critique failed for %s: %s", programme_id, e)
        return _empty_verdict(f"council_unavailable: {e}")


async def _run_narrative_critique_async(
    script_text: str,
    programme_id: str,
    config: CouncilConfig | None,
) -> NarrativeVerdict:
    from agents.deliberative_council.engine import deliberate

    rubric = NarrativeQualityRubric()
    if config is None:
        config = CouncilConfig(max_models=3, phase3_rounds=1)

    council_input = CouncilInput(
        text=script_text[:6000],
        source_ref=f"narrative_critique:{programme_id}",
        metadata={"check_type": "narrative_quality", "programme_id": programme_id},
    )

    verdict = await deliberate(council_input, CouncilMode.NARRATIVE, rubric, config)
    return _convert_to_narrative_verdict(verdict, programme_id)


def _convert_to_narrative_verdict(
    verdict: CouncilVerdict,
    programme_id: str,
) -> NarrativeVerdict:
    """Convert a generic CouncilVerdict to a NarrativeVerdict with status and directives."""
    scores = verdict.scores
    mean_score = sum(s for s in scores.values() if s is not None) / max(1, len(scores))

    focalization = scores.get("focalization_integrity")
    opening = scores.get("information_gap_integrity")
    escalation = scores.get("escalation_architecture")

    if focalization is not None and focalization <= 2:
        status = NarrativeVerdictStatus.GENERIC_DETECTED
    elif (opening is not None and opening <= 2) or (escalation is not None and escalation <= 2):
        status = NarrativeVerdictStatus.STRUCTURAL_REWORK
    elif mean_score < 3.0:
        status = NarrativeVerdictStatus.REVISE_AND_RESUBMIT
    else:
        status = NarrativeVerdictStatus.BROADCAST_READY

    directives = _build_revision_directives(scores, verdict.disagreement_log)

    return NarrativeVerdict(
        scores=scores,
        confidence_bands=verdict.confidence_bands,
        convergence_status=verdict.convergence_status,
        verdict_status=status,
        alternative_framings=[],
        audience_breaks=[],
        disagreement_log=verdict.disagreement_log,
        revision_directives=directives,
        receipt={
            "programme_id": programme_id,
            "mean_score": round(mean_score, 2),
            "verdict_status": status.value,
        },
    )


def _build_revision_directives(
    scores: dict[str, int | None],
    disagreement_log: list[str],
) -> list[str]:
    """Generate actionable revision directives from low scores."""
    directives: list[str] = []

    axis_directives = {
        "information_gap_integrity": (
            "Opening lacks genuine cognitive tension. Rewrite beat 0 to surface "
            "a specific contradiction, unknown, or tension the segment will resolve."
        ),
        "escalation_architecture": (
            "Beats do not build on each other. Restructure so each beat creates "
            "preconditions for the next. The argument should get more specific "
            "as it progresses."
        ),
        "source_consequence_density": (
            "Sources are decorative, not consequential. Each source must change, "
            "narrow, or refute a specific claim. Remove 'According to X' boilerplate."
        ),
        "focalization_integrity": (
            "Voice drifts into anthropomorphic performance. Remove claims of "
            "interior states, fake enthusiasm, and performed curiosity. Report "
            "processing and observations as genuine system outputs."
        ),
        "evaluation_sufficiency": (
            "Segment does not demonstrate why its content matters. Add structural "
            "evaluation: contrast with prior state, quantified change, or "
            "demonstrated consequence."
        ),
        "promise_delivery_ratio": (
            "Closing does not resolve the opening's tension. Rewrite the final "
            "beat to answer the specific question beat 0 posed."
        ),
        "authentic_uncertainty": (
            "Uncertainty is either absent or generic. Name specific unknowns "
            "with specific evidence gaps. Quantify where possible."
        ),
    }

    for axis, score in scores.items():
        if score is not None and score <= 2 and axis in axis_directives:
            directives.append(axis_directives[axis])

    return directives


def format_narrative_verdict_for_composer(verdict: NarrativeVerdict) -> str:
    """Format a NarrativeVerdict as feedback for the segment composer."""
    lines = [
        f"## Narrative Quality Council Verdict: {verdict.verdict_status.value}",
        f"Mean score: {verdict.receipt.get('mean_score', '?')}",
        "",
        "### Scores:",
    ]
    for axis, score in verdict.scores.items():
        lines.append(f"  - {axis}: {score}")

    if verdict.revision_directives:
        lines.append("\n### Revision Directives:")
        for d in verdict.revision_directives:
            lines.append(f"  - {d}")

    if verdict.disagreement_log:
        lines.append("\n### Council Notes:")
        for note in verdict.disagreement_log[:3]:
            lines.append(f"  - {note[:200]}")

    return "\n".join(lines)


def _empty_verdict(reason: str) -> NarrativeVerdict:
    return NarrativeVerdict(
        scores={},
        confidence_bands={},
        convergence_status=ConvergenceStatus.HUNG,
        verdict_status=NarrativeVerdictStatus.BROADCAST_READY,
        disagreement_log=[f"Council unavailable: {reason}"],
        receipt={"council_unavailable": True, "reason": reason},
    )
