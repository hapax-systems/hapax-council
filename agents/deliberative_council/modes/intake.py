"""CCTV Intake mode — request hardening and quality gate.

Evaluates whether a request is specific enough to decompose into cc-tasks.
Produces accept/reject/harden verdicts with per-axis score data.

Spec: docs/superpowers/specs/2026-05-18-cctv-intake-gate-design.md
"""

from __future__ import annotations

import hashlib
import json
import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
)
from agents.deliberative_council.rubrics import IntakeHardeningRubric
from shared.frontmatter import parse_frontmatter

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
    receipt_ref: str = ""
    verdict: IntakeVerdict
    recommendation: IntakeRecommendation
    route_resource_admission: str = "missing"
    capability_receipt_refs: tuple[str, ...] = ()
    axis_results: tuple[AxisResult, ...] = ()
    composite_score: float = 0.0
    convergence_status: ConvergenceStatus = ConvergenceStatus.HUNG
    failing_axes: tuple[str, ...] = ()
    impediments: tuple[str, ...] = ()


class IntakeContractError(RuntimeError):
    """Raised when the panel output is not valid intake evidence."""


def derive_verdict(
    scores: dict[str, int | None],
    convergence: ConvergenceStatus,
    has_research_refs: bool = False,
) -> IntakeVerdict:
    # A REFUSED panel cannot certify readiness — fail CLOSED to NEEDS_HARDENING,
    # never READY_TO_PLAN, even if partial fold scores clear the floor. cc-task
    # cctv-council-perfect-health-faillloud-convergence.
    if convergence == ConvergenceStatus.REFUSED:
        return IntakeVerdict.NEEDS_HARDENING

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


def _complete_axis_scores(scores: dict[str, int | None]) -> dict[str, int] | None:
    axis_scores: dict[str, int] = {}
    for axis in AXIS_WEIGHTS:
        score = scores.get(axis)
        if isinstance(score, bool) or not isinstance(score, int):
            return None
        axis_scores[axis] = score
    return axis_scores


def _refusal_reason(receipt: dict[str, Any]) -> str:
    value = receipt.get("refusal_reason") or receipt.get("error") or ""
    return str(value).strip()


def build_receipt(
    request_id: str,
    request_path: str,
    scores: dict[str, int | None],
    convergence: ConvergenceStatus,
    has_research_refs: bool = False,
    impediments: tuple[str, ...] = (),
    council_receipt: dict[str, Any] | None = None,
) -> IntakeReceipt:
    verdict = derive_verdict(scores, convergence, has_research_refs)
    route_resource_admission = _route_resource_admission_from_council(council_receipt or {})
    capability_refs = _capability_receipt_refs_from_council(council_receipt or {})
    axis_results = tuple(
        AxisResult(
            name=axis,
            score=scores.get(axis),
            label=AXIS_LABELS.get(axis, ""),
            below_threshold=scores.get(axis, 5) is not None and scores.get(axis, 5) < 3,
        )
        for axis in AXIS_WEIGHTS
    )
    receipt_ref = _intake_receipt_ref(
        request_id=request_id,
        request_path=request_path,
        verdict=verdict,
        recommendation=derive_recommendation(verdict),
        route_resource_admission=route_resource_admission,
        scores=scores,
        capability_receipt_refs=capability_refs,
    )
    return IntakeReceipt(
        request_id=request_id,
        request_path=request_path,
        receipt_ref=receipt_ref,
        verdict=verdict,
        recommendation=derive_recommendation(verdict),
        route_resource_admission=route_resource_admission,
        capability_receipt_refs=capability_refs,
        axis_results=axis_results,
        composite_score=compute_composite(scores),
        convergence_status=convergence,
        failing_axes=identify_failing_axes(scores),
        impediments=impediments,
    )


def _route_resource_admission_from_council(receipt: dict[str, Any]) -> str:
    value = receipt.get("route_resource_admission")
    if isinstance(value, str) and value.strip():
        return value.strip()
    admissions = receipt.get("capability_admissions")
    if not isinstance(admissions, list) or not admissions:
        return "missing"
    admitted = 0
    refused = 0
    for item in admissions:
        if not isinstance(item, dict):
            continue
        if item.get("admitted") is True or item.get("admission_action") == "admitted":
            admitted += 1
        else:
            refused += 1
    if admitted and not refused:
        return "admitted"
    if admitted:
        return "partial_admitted"
    return "refused"


def _capability_receipt_refs_from_council(receipt: dict[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    direct_refs = receipt.get("capability_receipt_refs")
    if isinstance(direct_refs, list | tuple):
        refs.extend(str(ref) for ref in direct_refs if str(ref).strip())
    admissions = receipt.get("capability_admissions")
    if isinstance(admissions, list):
        for item in admissions:
            if not isinstance(item, dict):
                continue
            item_refs = item.get("receipt_refs")
            if isinstance(item_refs, list | tuple):
                refs.extend(str(ref) for ref in item_refs if str(ref).strip())
            elif isinstance(item.get("receipt_ref"), str):
                refs.append(str(item["receipt_ref"]))
    return tuple(dict.fromkeys(refs))


def _intake_receipt_ref(
    *,
    request_id: str,
    request_path: str,
    verdict: IntakeVerdict,
    recommendation: IntakeRecommendation,
    route_resource_admission: str,
    scores: dict[str, int | None],
    capability_receipt_refs: tuple[str, ...],
) -> str:
    payload = {
        "request_id": request_id,
        "request_path": request_path,
        "verdict": verdict.value,
        "recommendation": recommendation.value,
        "route_resource_admission": route_resource_admission,
        "scores": scores,
        "capability_receipt_refs": list(capability_receipt_refs),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return f"cctv-intake-receipt:{request_id}:{digest}"


def _intake_axes_frontmatter(receipt: IntakeReceipt) -> dict[str, dict[str, Any]]:
    return {
        axis.name: {
            "score": axis.score,
            "label": axis.label,
            "below_threshold": axis.below_threshold,
        }
        for axis in receipt.axis_results
    }


def intake_axis_score_map(receipt: IntakeReceipt) -> dict[str, int]:
    scores = {axis.name: axis.score for axis in receipt.axis_results}
    complete = _complete_axis_scores(scores)
    if complete is None:
        raise IntakeContractError("COUNCIL_REFUSED invalid_axis_scores")
    return complete


def _render_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{body}"


def _timeout_failures(receipt: dict[str, Any]) -> list[str]:
    failures = receipt.get("failed_members")
    if not isinstance(failures, list):
        return []

    timed_out = []
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        reason = str(failure.get("reason") or "")
        if "TimeoutError" in reason:
            alias = str(failure.get("model_alias") or "unknown")
            timed_out.append(alias)
    return timed_out


def _has_research_refs(frontmatter: dict[str, Any], body: str) -> bool:
    nullish = {"", "null", "none", "unassigned"}

    def is_real_ref(item: Any) -> bool:
        return item is not None and not (isinstance(item, str) and item.strip().lower() in nullish)

    for key in (
        "research_refs",
        "research_ref",
        "research_documents",
        "research_docs",
        "source_refs",
        "source_ref",
        "sources",
        "references",
    ):
        value = frontmatter.get(key)
        if isinstance(value, str):
            if value.strip().lower() not in nullish:
                return True
        elif isinstance(value, list | tuple | set):
            if any(is_real_ref(item) for item in value):
                return True
        elif isinstance(value, dict):
            if any(is_real_ref(item) for item in value.values()):
                return True
        elif value is not None:
            return True

    body_lower = body.lower()
    return any(
        marker in body_lower
        for marker in (
            "research refs:",
            "research references:",
            "source refs:",
            "docs/superpowers/research/",
            "arxiv",
            "doi:",
        )
    )


def _assert_intake_output_contract(
    scores: dict[str, int | None],
    convergence: ConvergenceStatus,
    receipt: dict[str, Any],
    request_id: str,
) -> dict[str, int]:
    reason = _refusal_reason(receipt)
    if convergence == ConvergenceStatus.REFUSED:
        raise IntakeContractError(f"COUNCIL_REFUSED {reason or 'refused'} request={request_id}")
    if reason == "all_models_failed":
        raise IntakeContractError(f"COUNCIL_REFUSED all_models_failed request={request_id}")

    complete = _complete_axis_scores(scores)
    if complete is None:
        non_null = sum(1 for score in scores.values() if score is not None)
        reason = "no_axis_scores" if non_null == 0 else "partial_axis_scores"
        raise IntakeContractError(f"COUNCIL_REFUSED {reason} request={request_id}")
    return complete


async def run_intake(
    request_path: str | Path,
    config: CouncilConfig | None = None,
    write_back: bool = True,
) -> IntakeReceipt:
    path = Path(request_path)
    frontmatter, body = parse_frontmatter(path)
    request_id = str(frontmatter.get("request_id") or path.stem)
    cfg = config if config is not None else CouncilConfig()

    inp = CouncilInput(
        text=body,
        source_ref=str(path),
        metadata=dict(frontmatter),
    )
    from agents.deliberative_council.engine import deliberate

    try:
        council_verdict = await deliberate(inp, CouncilMode.INTAKE, IntakeHardeningRubric(), cfg)
    except TimeoutError as exc:
        raise RuntimeError(f"intake council member timeout for {request_id}") from exc
    timed_out = _timeout_failures(council_verdict.receipt)
    if timed_out:
        aliases = ", ".join(timed_out)
        raise RuntimeError(f"intake council member timeout for {request_id}: {aliases}")
    scores = _assert_intake_output_contract(
        council_verdict.scores,
        council_verdict.convergence_status,
        council_verdict.receipt,
        request_id,
    )

    receipt = build_receipt(
        request_id=request_id,
        request_path=str(path),
        scores=scores,
        convergence=council_verdict.convergence_status,
        has_research_refs=_has_research_refs(frontmatter, body),
        impediments=tuple(council_verdict.disagreement_log),
        council_receipt=council_verdict.receipt,
    )

    if write_back:
        frontmatter["status"] = (
            "accepted_for_planning"
            if receipt.verdict == IntakeVerdict.READY_TO_PLAN
            else "captured"
        )
        frontmatter["cctv_intake_receipt"] = receipt.receipt_ref
        frontmatter["cctv_intake_verdict"] = receipt.verdict.value
        frontmatter["cctv_route_resource_admission"] = receipt.route_resource_admission
        frontmatter["cctv_capability_receipts"] = list(receipt.capability_receipt_refs)
        frontmatter["recommendation"] = receipt.recommendation.value
        frontmatter["composite"] = receipt.composite_score
        frontmatter["axes"] = _intake_axes_frontmatter(receipt)
        frontmatter["failing_axes"] = list(receipt.failing_axes)
        path.write_text(_render_frontmatter(frontmatter, body), encoding="utf-8")

    return receipt
