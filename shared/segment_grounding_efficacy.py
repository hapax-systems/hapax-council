"""Axis-A grounding-efficacy ruler for segment-prep dual readout.

This is the source-only B1/G5 slice for LEG D (operator-Hapax livestream
dyad). It scores already-captured evidence; it does not call embeddings, run
segment prep, or write DV rows.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

AXIS_A_GROUNDING_EFFICACY_RULER_VERSION = 1
AXIS_A_GROUNDING_EFFICACY_RULER_NAME = "axis_a_grounding_efficacy_dyad"

AXIS_A_EXCELLENT_FLOOR = 90
AXIS_A_GOOD_FLOOR = 75
AXIS_A_REVIEW_ONLY_FLOOR = 60
AXIS_A_THIN_FLOOR = 40

_REQUIRED_DIMENSIONS = (
    "turn_pair_coherence",
    "dual_addressee_legibility",
    "peer_floor_share",
)
_DUAL_ADDRESSEE_SIGNALS = (
    "operator_grounded",
    "audience_context_cued",
    "shared_reference_public",
    "overhearer_readback_present",
)


def _unit_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number in [0.0, 1.0]")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise ValueError(f"{field} must be a number in [0.0, 1.0]")
    return number


def _non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _optional_unit(evidence: Mapping[str, Any], fields: Sequence[str]) -> tuple[str, float] | None:
    for field in fields:
        if field in evidence and evidence[field] is not None:
            return field, _unit_float(evidence[field], field=field)
    return None


def _bool_signal(evidence: Mapping[str, Any], field: str) -> bool | None:
    if field not in evidence or evidence[field] is None:
        return None
    if not isinstance(evidence[field], bool):
        raise ValueError(f"{field} must be a boolean when supplied")
    return bool(evidence[field])


def _band(score_0_100: int, *, coverage_ok: bool) -> str:
    if not coverage_ok:
        return "invalid"
    if score_0_100 >= AXIS_A_EXCELLENT_FLOOR:
        return "excellent"
    if score_0_100 >= AXIS_A_GOOD_FLOOR:
        return "good"
    if score_0_100 >= AXIS_A_REVIEW_ONLY_FLOOR:
        return "review_only"
    if score_0_100 >= AXIS_A_THIN_FLOOR:
        return "thin"
    return "invalid"


def _dimension(
    name: str,
    score: float | None,
    detail: str,
    *,
    capability: int | None = None,
    weight: float = 1.0,
    not_applicable: bool = False,
    required: bool = True,
    **observed: Any,
) -> dict[str, Any]:
    score_value = None if score is None else round(score, 3)
    points = None if score is None else round(score * weight * 100.0, 1)
    return {
        "name": name,
        "capability": capability,
        "required": required,
        "not_applicable": not_applicable,
        "score": score_value,
        "weight": weight,
        "points": points,
        "detail": detail,
        "observed": observed,
    }


def _missing_dimension(name: str, reason: str, *, capability: int | None = None) -> dict[str, Any]:
    return _dimension(
        name,
        0.0,
        f"Missing required evidence: {reason}.",
        capability=capability,
        missing=True,
    )


def _turn_pair_coherence(
    evidence: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    value = _optional_unit(evidence, ("turn_pair_coherence", "turn_pair_semantic_coherence"))
    if value is None:
        return _missing_dimension("turn_pair_coherence", "turn_pair_coherence"), [
            {
                "reason": "missing_turn_pair_coherence",
                "detail": "LEG D Axis-A needs the Cycle-2 continuity coherence signal.",
            }
        ]
    field, score = value
    return _dimension(
        "turn_pair_coherence",
        score,
        "Semantic continuity between the operator turn and Hapax response.",
        capability=None,
        source_field=field,
    ), []


def _dual_addressee_legibility(
    evidence: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    direct = _optional_unit(evidence, ("dual_addressee_legibility", "audience_design_legibility"))
    if direct is not None:
        field, score = direct
        return _dimension(
            "dual_addressee_legibility",
            score,
            "Grounding with the operator is legible to overhearers.",
            capability=1,
            source_field=field,
        ), []

    seen: dict[str, bool] = {}
    for field in _DUAL_ADDRESSEE_SIGNALS:
        value = _bool_signal(evidence, field)
        if value is not None:
            seen[field] = value

    if not seen:
        return _missing_dimension(
            "dual_addressee_legibility", "capability-1 signals", capability=1
        ), [
            {
                "reason": "missing_dual_addressee_legibility",
                "detail": "No direct score or capability-1 legibility signals were supplied.",
            }
        ]

    score = sum(1 for value in seen.values() if value) / len(_DUAL_ADDRESSEE_SIGNALS)
    return _dimension(
        "dual_addressee_legibility",
        score,
        "Capability 1 signal coverage across operator grounding and audience design.",
        capability=1,
        supplied_signal_count=len(seen),
        true_signal_count=sum(1 for value in seen.values() if value),
        signals=seen,
    ), []


def _peer_floor_share(evidence: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    value = _optional_unit(
        evidence,
        (
            "peer_floor_share_ratio",
            "hapax_floor_share_ratio",
            "assistant_floor_share_ratio",
        ),
    )
    if value is None:
        return _missing_dimension("peer_floor_share", "peer_floor_share_ratio", capability=2), [
            {
                "reason": "missing_peer_floor_share",
                "detail": "No Hapax floor-share ratio was supplied for capability 2.",
            }
        ]
    field, ratio = value
    distance_from_peer_center = abs(ratio - 0.5)
    if distance_from_peer_center <= 0.15:
        score = 1.0
    else:
        score = max(0.0, 1.0 - ((distance_from_peer_center - 0.15) / 0.35))
    return _dimension(
        "peer_floor_share",
        score,
        "Hapax shares the floor as a peer co-host rather than vanishing or dominating.",
        capability=2,
        source_field=field,
        ratio=round(ratio, 3),
        target_band=[0.35, 0.65],
    ), []


def _on_air_repair(evidence: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    direct = _optional_unit(evidence, ("on_air_repair_success_rate", "repair_success_rate"))
    if direct is not None:
        field, score = direct
        return _dimension(
            "on_air_repair",
            score,
            "Public repair attempts recovered grounding failures.",
            capability=3,
            required=False,
            source_field=field,
        ), []

    if "repair_opportunities" not in evidence or evidence["repair_opportunities"] is None:
        return _dimension(
            "on_air_repair",
            None,
            "No repair-opportunity evidence supplied; capability 3 is unscored for this row.",
            capability=3,
            not_applicable=True,
            required=False,
        ), []

    opportunities = _non_negative_int(
        evidence["repair_opportunities"], field="repair_opportunities"
    )
    if opportunities == 0:
        return _dimension(
            "on_air_repair",
            None,
            "No on-air repair opportunities occurred.",
            capability=3,
            not_applicable=True,
            required=False,
            repair_opportunities=0,
        ), []

    if "repair_successes" not in evidence or evidence["repair_successes"] is None:
        return _dimension(
            "on_air_repair",
            0.0,
            "Repair opportunities occurred, but successful repairs were not supplied.",
            capability=3,
            required=False,
            repair_opportunities=opportunities,
            missing=True,
        ), [
            {
                "reason": "missing_repair_successes",
                "detail": "repair_successes is required when repair_opportunities is positive.",
            }
        ]

    successes = _non_negative_int(evidence["repair_successes"], field="repair_successes")
    if successes > opportunities:
        raise ValueError("repair_successes cannot exceed repair_opportunities")
    return _dimension(
        "on_air_repair",
        successes / opportunities,
        "Public repair success rate for capability 3.",
        capability=3,
        required=False,
        repair_opportunities=opportunities,
        repair_successes=successes,
    ), []


def _score_1_5(score_0_100: int) -> float:
    return round(1.0 + (float(score_0_100) / 100.0) * 4.0, 2)


def evaluate_dyad_grounding_efficacy(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate LEG D Axis-A grounding efficacy from deterministic evidence.

    The first A0 slice requires three always-present dimensions: the historical
    turn-pair coherence continuity metric, capability 1 dual-addressee
    legibility, and capability 2 peer floor-share. Capability 3 on-air repair is
    scored when there were repair opportunities and marked not-applicable when
    no repair evidence was present for the row.
    """

    if not isinstance(evidence, Mapping):
        raise TypeError("evidence must be a mapping")

    dimensions: list[dict[str, Any]] = []
    violations: list[dict[str, str]] = []
    for scorer in (
        _turn_pair_coherence,
        _dual_addressee_legibility,
        _peer_floor_share,
        _on_air_repair,
    ):
        dimension, dimension_violations = scorer(evidence)
        dimensions.append(dimension)
        violations.extend(dimension_violations)

    required_missing = [
        dimension["name"]
        for dimension in dimensions
        if dimension["name"] in _REQUIRED_DIMENSIONS
        and (
            dimension["score"] is None
            or dimension["score"] <= 0.0
            and dimension["observed"].get("missing")
        )
    ]
    scored_dimensions = [
        dimension
        for dimension in dimensions
        if dimension["score"] is not None and not dimension["not_applicable"]
    ]
    not_applicable = [
        dimension["name"] for dimension in dimensions if bool(dimension["not_applicable"])
    ]
    weight_total = sum(float(dimension["weight"]) for dimension in scored_dimensions)
    if weight_total > 0:
        weighted_score = (
            sum(
                float(dimension["score"]) * float(dimension["weight"])
                for dimension in scored_dimensions
                if dimension["score"] is not None
            )
            / weight_total
        )
    else:
        weighted_score = 0.0
    score_0_100 = int(round(weighted_score * 100.0))
    coverage_ok = not required_missing and all(
        any(
            dimension["name"] == required_name and dimension["score"] is not None
            for dimension in dimensions
        )
        for required_name in _REQUIRED_DIMENSIONS
    )
    band = _band(score_0_100, coverage_ok=coverage_ok)

    return {
        "ruler": AXIS_A_GROUNDING_EFFICACY_RULER_NAME,
        "ruler_version": AXIS_A_GROUNDING_EFFICACY_RULER_VERSION,
        "axis": "grounding_efficacy",
        "axis_id": "A",
        "leg": "dyad",
        "score_0_100": score_0_100,
        "score_1_5": _score_1_5(score_0_100),
        "band": band,
        "ok": band in {"good", "excellent"},
        "coverage": {
            "required": len(_REQUIRED_DIMENSIONS),
            "scored": len(scored_dimensions),
            "required_scored": len(_REQUIRED_DIMENSIONS) - len(required_missing),
            "missing_required": required_missing,
            "not_applicable": not_applicable,
            "ok": coverage_ok,
        },
        "capability_scores": dimensions,
        "violations": violations,
    }


def compare_grounding_efficacy(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
    """Compare two grounding-efficacy reports by score, then coverage.

    Returns ``1`` when ``left`` is preferred, ``-1`` when ``right`` is preferred,
    and ``0`` for a tie.
    """

    left_score = int(left.get("score_0_100", 0))
    right_score = int(right.get("score_0_100", 0))
    if left_score != right_score:
        return 1 if left_score > right_score else -1
    left_coverage = bool((left.get("coverage") or {}).get("ok"))
    right_coverage = bool((right.get("coverage") or {}).get("ok"))
    if left_coverage != right_coverage:
        return 1 if left_coverage else -1
    return 0


__all__ = [
    "AXIS_A_GROUNDING_EFFICACY_RULER_NAME",
    "AXIS_A_GROUNDING_EFFICACY_RULER_VERSION",
    "compare_grounding_efficacy",
    "evaluate_dyad_grounding_efficacy",
]
