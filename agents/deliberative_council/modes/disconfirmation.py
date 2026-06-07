from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
)
from agents.deliberative_council.rubrics import DisconfirmationRubric

_log = logging.getLogger(__name__)

VERDICT_SURVIVED_FLOOR = 4
VERDICT_REFUTED_CEILING = 2

_NEGATIVE_MARKERS = ("contradicts", "missing", "not found", "inconsistent", "fails", "no evidence")
_POSITIVE_MARKERS = ("supports", "confirms", "consistent", "found", "exists")

__all__ = [
    "DisconfirmationReceipt",
    "DisconfirmationRecommendation",
    "DisconfirmationVerdict",
    "build_receipt",
    "derive_recommendation",
    "derive_verdict",
    "disconfirm",
]


class DisconfirmationVerdict(StrEnum):
    SURVIVED = "survived"
    CONTESTED = "contested"
    REFUTED = "refuted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DisconfirmationRecommendation(StrEnum):
    ACCEPT = "accept"
    NARROW = "narrow"
    REVISE = "revise"
    RETRACT = "retract"


class DisconfirmationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim: str
    source_refs: tuple[str, ...]
    verdict: DisconfirmationVerdict
    recommendation: DisconfirmationRecommendation
    evidence_for: tuple[str, ...] = ()
    evidence_against: tuple[str, ...] = ()
    counter_arguments: tuple[str, ...] = ()
    scores: dict[str, int | None] = Field(default_factory=dict)
    confidence_bands: dict[str, tuple[int, int]] = Field(default_factory=dict)
    attacks_attempted: tuple[str, ...] = ()
    attacks_survived: tuple[str, ...] = ()
    convergence_status: ConvergenceStatus = ConvergenceStatus.HUNG
    receipt: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_verdict_payload(self) -> Self:  # noqa: B018
        if self.verdict == DisconfirmationVerdict.SURVIVED:
            if not self.attacks_attempted or not self.attacks_survived:
                raise ValueError("SURVIVED receipts require attacks_attempted and attacks_survived")
        if self.verdict == DisconfirmationVerdict.REFUTED:
            if not self.evidence_against or not self.counter_arguments:
                raise ValueError("REFUTED receipts require evidence_against and counter_arguments")
        return self


_PYDANTIC_VALIDATORS = (DisconfirmationReceipt._validate_verdict_payload,)


def derive_verdict(verdict: CouncilVerdict) -> DisconfirmationVerdict:
    # A REFUSED panel (below quorum / family floor / all-failed) cannot be
    # trusted to survive OR refute a claim — fail CLOSED to INSUFFICIENT_EVIDENCE,
    # never a survival, even if some fold axes carry partial scores. cc-task
    # cctv-council-perfect-health-faillloud-convergence.
    if verdict.convergence_status in (ConvergenceStatus.REFUSED, ConvergenceStatus.HUNG):
        return DisconfirmationVerdict.INSUFFICIENT_EVIDENCE

    scores = [s for s in verdict.scores.values() if s is not None]
    if not scores:
        return DisconfirmationVerdict.INSUFFICIENT_EVIDENCE

    if any(s <= VERDICT_REFUTED_CEILING for s in scores):
        return DisconfirmationVerdict.REFUTED

    if all(s >= VERDICT_SURVIVED_FLOOR for s in scores):
        return DisconfirmationVerdict.SURVIVED

    return DisconfirmationVerdict.CONTESTED


def derive_recommendation(v: DisconfirmationVerdict) -> DisconfirmationRecommendation:
    return {
        DisconfirmationVerdict.SURVIVED: DisconfirmationRecommendation.ACCEPT,
        DisconfirmationVerdict.CONTESTED: DisconfirmationRecommendation.NARROW,
        DisconfirmationVerdict.REFUTED: DisconfirmationRecommendation.RETRACT,
        DisconfirmationVerdict.INSUFFICIENT_EVIDENCE: DisconfirmationRecommendation.REVISE,
    }[v]


def _extract_evidence(
    council_verdict: CouncilVerdict,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    evidence_for: list[str] = []
    evidence_against: list[str] = []
    for finding in council_verdict.research_findings:
        lower = finding.lower()
        # Check negative markers first: "not found" must match before "found".
        if any(w in lower for w in _NEGATIVE_MARKERS):
            evidence_against.append(finding)
        elif any(w in lower for w in _POSITIVE_MARKERS):
            evidence_for.append(finding)
        else:
            evidence_for.append(finding)
    return tuple(evidence_for), tuple(evidence_against)


def _extract_attacks(
    council_verdict: CouncilVerdict,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    attempted: list[str] = []
    survived: list[str] = []
    for exchange in council_verdict.adversarial_exchanges:
        attempted.append(f"{exchange.axis}: {exchange.challenge_text[:200]}")
        if exchange.high_score >= VERDICT_SURVIVED_FLOOR:
            survived.append(f"{exchange.axis}: score held at {exchange.high_score}")
    return tuple(attempted), tuple(survived)


def _extract_counter_arguments(council_verdict: CouncilVerdict) -> tuple[str, ...]:
    counters: list[str] = []
    for exchange in council_verdict.adversarial_exchanges:
        counters.append(f"[{exchange.axis}] {exchange.response_text[:300]}")
    for entry in council_verdict.disagreement_log:
        counters.append(entry)
    return tuple(counters)


def _score_attacks(council_verdict: CouncilVerdict) -> tuple[str, ...]:
    return tuple(
        f"{axis}: adversarial rubric axis resolved at score {score}"
        for axis, score in council_verdict.scores.items()
        if score is not None
    )


def _score_survivals(council_verdict: CouncilVerdict) -> tuple[str, ...]:
    return tuple(
        f"{axis}: survived disconfirmation with score {score}"
        for axis, score in council_verdict.scores.items()
        if score is not None and score >= VERDICT_SURVIVED_FLOOR
    )


def _score_refutations(council_verdict: CouncilVerdict) -> tuple[str, ...]:
    return tuple(
        f"{axis}: score {score} is at or below refutation ceiling {VERDICT_REFUTED_CEILING}"
        for axis, score in council_verdict.scores.items()
        if score is not None and score <= VERDICT_REFUTED_CEILING
    )


def build_receipt(
    claim: str,
    source_refs: tuple[str, ...],
    council_verdict: CouncilVerdict,
) -> DisconfirmationReceipt:
    verdict = derive_verdict(council_verdict)
    recommendation = derive_recommendation(verdict)
    evidence_for, evidence_against = _extract_evidence(council_verdict)
    attacks_attempted, attacks_survived = _extract_attacks(council_verdict)
    counter_arguments = _extract_counter_arguments(council_verdict)

    if verdict == DisconfirmationVerdict.SURVIVED:
        if not attacks_attempted:
            attacks_attempted = _score_attacks(council_verdict) or (
                "claim survived, but no adversarial exchange transcript was recorded",
            )
        if not attacks_survived:
            attacks_survived = _score_survivals(council_verdict) or (
                "claim survived, but no per-axis survival detail was recorded",
            )

    if verdict == DisconfirmationVerdict.REFUTED:
        if not evidence_against:
            refuting = [
                f"[{e.axis}] score {e.low_score} (below ceiling {VERDICT_REFUTED_CEILING})"
                for e in council_verdict.adversarial_exchanges
                if e.low_score <= VERDICT_REFUTED_CEILING
            ]
            evidence_against = (
                tuple(refuting)
                or _score_refutations(council_verdict)
                or ("claim refuted, but no counter-evidence detail was extracted",)
            )
        if not counter_arguments:
            counter_arguments = (
                tuple(
                    f"[{e.axis}] {e.response_text[:300]}"
                    for e in council_verdict.adversarial_exchanges
                )
                or _score_refutations(council_verdict)
                or ("claim refuted, but no adversarial exchange transcript was recorded",)
            )

    return DisconfirmationReceipt(
        claim=claim,
        source_refs=source_refs,
        verdict=verdict,
        recommendation=recommendation,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        counter_arguments=counter_arguments,
        scores=council_verdict.scores,
        confidence_bands=council_verdict.confidence_bands,
        attacks_attempted=attacks_attempted,
        attacks_survived=attacks_survived,
        convergence_status=council_verdict.convergence_status,
        receipt=council_verdict.receipt,
    )


async def disconfirm(
    claim: str,
    source_refs: tuple[str, ...],
    config: CouncilConfig | None = None,
) -> DisconfirmationReceipt:
    from agents.deliberative_council.engine import deliberate

    inp = CouncilInput(
        text=claim,
        source_ref=source_refs[0] if source_refs else "inline-claim",
        metadata={"source_refs": list(source_refs), "mode": "disconfirmation"},
    )
    rubric = DisconfirmationRubric()
    council_verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)
    return build_receipt(claim, source_refs, council_verdict)
