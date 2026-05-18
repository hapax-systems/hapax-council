"""CCTV Intake mode — request hardening and quality gate.

Evaluates whether a request is specific enough to decompose into cc-tasks.
Produces accept/reject/harden verdicts with per-axis score data.

Spec: docs/superpowers/specs/2026-05-18-cctv-intake-gate-design.md
"""

from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from agents.deliberative_council.models import ConvergenceStatus

_log = logging.getLogger(__name__)

READY_FLOOR = 4
REJECT_CEILING = 2
COMPOSITE_THRESHOLD = 3.0

AXIS_WEIGHTS = {
    "outcome_concreteness": 0.20,
    "scope_boundedness": 0.15,
    "decomposability": 0.15,
    "artifact_specificity": 0.10,
    "verification_seed": 0.15,
    "singularity": 0.10,
}

AXIS_LABELS = {
    "outcome_concreteness": "testable state change",
    "scope_boundedness": "explicit in/out boundaries",
    "decomposability": "task derivability without research",
    "artifact_specificity": "named code paths or services",
    "verification_seed": "mechanizable pass/fail check",
    "singularity": "single atomic need",
}


class IntakeVerdict(StrEnum):
    READY_TO_PLAN = "ready_to_plan"
    NEEDS_HARDENING = "needs_hardening"
    REJECT = "reject"
    RESEARCH_NEEDED = "research_needed"


class IntakeRecommendation(StrEnum):
    ADVANCE = "advance"
    HARDEN = "harden"
    REJECT = "reject"
    RESEARCH_GATE = "research_gate"


class AxisResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    score: int | None = None
    label: str = ""
    below_threshold: bool = False


class IntakeReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    request_path: str
    verdict: IntakeVerdict
    recommendation: IntakeRecommendation
    axis_results: tuple[AxisResult, ...] = ()
    composite_score: float = 0.0
    convergence_status: ConvergenceStatus = ConvergenceStatus.HUNG
    failing_axes: tuple[str, ...] = ()
    impediments: tuple[str, ...] = ()


def derive_verdict(
    scores: dict[str, int | None],
    convergence: ConvergenceStatus,
    has_research_refs: bool = False,
) -> IntakeVerdict:
    valid = {k: v for k, v in scores.items() if v is not None}
    if not valid:
        return IntakeVerdict.NEEDS_HARDENING

    if any(v <= REJECT_CEILING for v in valid.values()):
        if has_research_refs and valid.get("decomposability", 5) <= REJECT_CEILING:
            return IntakeVerdict.RESEARCH_NEEDED
        if all(v <= REJECT_CEILING for v in valid.values()):
            return IntakeVerdict.REJECT
        return IntakeVerdict.NEEDS_HARDENING

    if convergence == ConvergenceStatus.HUNG:
        return IntakeVerdict.NEEDS_HARDENING

    if all(v >= READY_FLOOR for v in valid.values()):
        return IntakeVerdict.READY_TO_PLAN

    return IntakeVerdict.NEEDS_HARDENING


def derive_recommendation(verdict: IntakeVerdict) -> IntakeRecommendation:
    return {
        IntakeVerdict.READY_TO_PLAN: IntakeRecommendation.ADVANCE,
        IntakeVerdict.NEEDS_HARDENING: IntakeRecommendation.HARDEN,
        IntakeVerdict.REJECT: IntakeRecommendation.REJECT,
        IntakeVerdict.RESEARCH_NEEDED: IntakeRecommendation.RESEARCH_GATE,
    }[verdict]


def compute_composite(scores: dict[str, int | None]) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for axis, weight in AXIS_WEIGHTS.items():
        score = scores.get(axis)
        if score is not None:
            weighted_sum += score * weight
            total_weight += weight
    return weighted_sum / total_weight if total_weight > 0 else 0.0


def identify_failing_axes(scores: dict[str, int | None]) -> tuple[str, ...]:
    return tuple(
        f"{axis}={score} (needs: {AXIS_LABELS.get(axis, axis)})"
        for axis, score in scores.items()
        if score is not None and score < 3
    )


def build_receipt(
    request_id: str,
    request_path: str,
    scores: dict[str, int | None],
    convergence: ConvergenceStatus,
    has_research_refs: bool = False,
    impediments: tuple[str, ...] = (),
) -> IntakeReceipt:
    verdict = derive_verdict(scores, convergence, has_research_refs)
    axis_results = tuple(
        AxisResult(
            name=axis,
            score=scores.get(axis),
            label=AXIS_LABELS.get(axis, ""),
            below_threshold=scores.get(axis, 5) is not None and scores.get(axis, 5) < 3,
        )
        for axis in AXIS_WEIGHTS
    )
    return IntakeReceipt(
        request_id=request_id,
        request_path=request_path,
        verdict=verdict,
        recommendation=derive_recommendation(verdict),
        axis_results=axis_results,
        composite_score=compute_composite(scores),
        convergence_status=convergence,
        failing_axes=identify_failing_axes(scores),
        impediments=impediments,
    )
