"""Consultable standards and excellence evidence for segment prep.

The objects in this module are calibration surfaces. They help prep and review
judge a segment against role craft, examples, counterexamples, and quality
ranges. They do not grant script, layout, runtime, source, or public authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

SEGMENT_CONSULTATION_VERSION = 1

SEGMENTED_CONTENT_ROLES: tuple[str, ...] = (
    "tier_list",
    "top_10",
    "rant",
    "react",
    "iceberg",
    "interview",
    "lecture",
)

QUALITY_RANGE_REFS: tuple[str, ...] = (
    "quality_range:eligible_floor:v1",
    "quality_range:solid_candidate:v1",
    "quality_range:excellent_canary:v1",
)

AUTHORITY_BOUNDARY = "advisory_consultation_prior_not_script_or_runtime_authority"

FRAMEWORK_VOCABULARY_TERMS: tuple[str, ...] = (
    "eligibility gate",
    "excellence selection",
    "source consequence",
    "source-consequence",
    "detector-trigger theater",
    "detector trigger theater",
    "quality range receipt",
    "positive-excellence receipt",
    "consultation_manifest",
    "role_contract_refs",
    "non-anthropomorphic force",
)

SOURCE_CONSEQUENCE_MARKERS: tuple[str, ...] = (
    "because",
    "therefore",
    "which means",
    "changes",
    "consequence",
    "limits",
    "refuses",
    "rejects",
    "instead",
    "rather than",
    "so the",
    "so this",
    "the result",
)

NONSTERILE_FORCE_MARKERS: tuple[str, ...] = (
    "because",
    "therefore",
    "refuse",
    "reject",
    "rank",
    "place",
    "compare",
    "contrast",
    "consequence",
    "stakes",
    "claim",
    "evidence",
    "source",
    "limits",
    "changes",
)

ROLE_STANDARDS: dict[str, dict[str, Any]] = {
    "tier_list": {
        "standard_ref": "role_standard:tier_list:v1",
        "exemplar_refs": ("exemplar:tier_list:source-consequential-ranking:v1",),
        "counterexample_refs": ("counterexample:tier_list:preference-list-without-criteria:v1",),
        "quality_range_refs": QUALITY_RANGE_REFS,
        "excellent": (
            "Rankings use declared criteria, source-grounded consequences, and visible "
            "placements; a placement changes the chart, the argument, or the next contrast."
        ),
        "counterexample": (
            "A list of preferences, vibes, or trivia that could be reordered without "
            "changing the argument."
        ),
    },
    "top_10": {
        "standard_ref": "role_standard:top_10:v1",
        "exemplar_refs": ("exemplar:top_10:escalating-countdown-with-payoff:v1",),
        "counterexample_refs": ("counterexample:top_10:flat-numbered-summary:v1",),
        "quality_range_refs": QUALITY_RANGE_REFS,
        "excellent": "Each rank escalates a reason, with the top entry changing the frame.",
        "counterexample": "A numbered summary where #7 and #2 carry the same dramatic weight.",
    },
    "rant": {
        "standard_ref": "role_standard:rant:v1",
        "exemplar_refs": ("exemplar:rant:source-bound-refusal-with-pivot:v1",),
        "counterexample_refs": ("counterexample:rant:generic-complaint-without-warrant:v1",),
        "quality_range_refs": QUALITY_RANGE_REFS,
        "excellent": "Escalation is evidence-bound; the strongest refusal changes the stakes.",
        "counterexample": "Loud adjectives or complaint theater without source consequence.",
    },
    "react": {
        "standard_ref": "role_standard:react:v1",
        "exemplar_refs": ("exemplar:react:pause-specific-source-consequence:v1",),
        "counterexample_refs": ("counterexample:react:wow-reaction-without-analysis:v1",),
        "quality_range_refs": QUALITY_RANGE_REFS,
        "excellent": "Specific source moments alter a claim, question, pause, or contrast.",
        "counterexample": "A stream of approval or surprise without claim-level consequence.",
    },
    "iceberg": {
        "standard_ref": "role_standard:iceberg:v1",
        "exemplar_refs": ("exemplar:iceberg:layered-disclosure-with-abyss-payoff:v1",),
        "counterexample_refs": ("counterexample:iceberg:unordered-fact-pile:v1",),
        "quality_range_refs": QUALITY_RANGE_REFS,
        "excellent": "Each layer changes what the prior layer meant and earns the descent.",
        "counterexample": "Obscure facts stacked without a legible descent or final reversal.",
    },
    "interview": {
        "standard_ref": "role_standard:interview:v1",
        "exemplar_refs": ("exemplar:interview:question-ladder-with-evidence-turns:v1",),
        "counterexample_refs": ("counterexample:interview:generic-question-list:v1",),
        "quality_range_refs": QUALITY_RANGE_REFS,
        "excellent": "Questions form a ladder; each answer condition changes the next move.",
        "counterexample": "Reusable questions that could fit any subject.",
    },
    "lecture": {
        "standard_ref": "role_standard:lecture:v1",
        "exemplar_refs": ("exemplar:lecture:claim-map-with-demonstrable-turn:v1",),
        "counterexample_refs": ("counterexample:lecture:generic-explainer-with-name-drops:v1",),
        "quality_range_refs": QUALITY_RANGE_REFS,
        "excellent": "Explanation builds a live claim map with visible/doable checkpoints.",
        "counterexample": "A polished report that never becomes a live event.",
    },
}


def role_standard_for(role: str) -> dict[str, Any]:
    return dict(ROLE_STANDARDS.get(role, ROLE_STANDARDS["lecture"]))


def build_consultation_manifest(role: str) -> dict[str, Any]:
    standard = role_standard_for(role)
    return {
        "consultation_manifest_version": SEGMENT_CONSULTATION_VERSION,
        "role": role if role in ROLE_STANDARDS else "lecture",
        "role_standard_refs": [standard["standard_ref"]],
        "exemplar_refs": list(standard["exemplar_refs"]),
        "counterexample_refs": list(standard["counterexample_refs"]),
        "quality_range_refs": list(standard["quality_range_refs"]),
        "consultation_refs": [
            {
                "ref": standard["standard_ref"],
                "purpose": "role_standard",
                "advisory_only": True,
            },
            {
                "ref": standard["exemplar_refs"][0],
                "purpose": "exemplar",
                "advisory_only": True,
            },
            {
                "ref": standard["counterexample_refs"][0],
                "purpose": "counterexample",
                "advisory_only": True,
            },
            {
                "ref": "quality_range:excellent_canary:v1",
                "purpose": "quality_range",
                "advisory_only": True,
            },
        ],
        "standards_are_advisory": True,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "prompt_facing_vocabulary_allowed": False,
    }


def validate_consultation_manifest(value: Any, *, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"ok": False, "missing": ["consultation_manifest"]}

    missing: list[str] = []
    for key in (
        "consultation_manifest_version",
        "role_standard_refs",
        "exemplar_refs",
        "counterexample_refs",
        "quality_range_refs",
        "consultation_refs",
        "standards_are_advisory",
        "authority_boundary",
        "prompt_facing_vocabulary_allowed",
    ):
        if key not in value:
            missing.append(key)

    standard = role_standard_for(role)
    role_mismatch = bool(value.get("role") not in {role, standard.get("role"), None})
    role_standard_refs = _string_list(value.get("role_standard_refs"))
    exemplar_refs = _string_list(value.get("exemplar_refs"))
    counterexample_refs = _string_list(value.get("counterexample_refs"))
    quality_range_refs = _string_list(value.get("quality_range_refs"))
    consultation_refs = value.get("consultation_refs")
    refs_ok = (
        standard["standard_ref"] in role_standard_refs
        and bool(exemplar_refs)
        and bool(counterexample_refs)
        and "quality_range:excellent_canary:v1" in quality_range_refs
        and isinstance(consultation_refs, list)
        and all(
            isinstance(item, Mapping)
            and item.get("advisory_only") is True
            and isinstance(item.get("ref"), str)
            and item.get("ref")
            for item in consultation_refs
        )
    )
    advisory_ok = (
        value.get("standards_are_advisory") is True
        and value.get("authority_boundary") == AUTHORITY_BOUNDARY
        and value.get("prompt_facing_vocabulary_allowed") is False
    )
    return {
        "ok": not missing and not role_mismatch and refs_ok and advisory_ok,
        "missing": missing,
        "role": role,
        "role_mismatch": role_mismatch,
        "refs_ok": refs_ok,
        "advisory_ok": advisory_ok,
        "observed": {
            "role_standard_refs": role_standard_refs,
            "exemplar_refs": exemplar_refs,
            "counterexample_refs": counterexample_refs,
            "quality_range_refs": quality_range_refs,
        },
    }


def build_source_consequence_map(
    script: Sequence[str],
    beat_action_intents: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for beat_index, text in enumerate(script):
        if not _has_any(text, SOURCE_CONSEQUENCE_MARKERS):
            continue
        targets = _source_targets_for_beat(beat_action_intents, beat_index)
        if not targets and _has_sourceish_text(text):
            targets = [f"beat:{beat_index}:source_context"]
        for source_ref in targets:
            out.append(
                {
                    "beat_index": beat_index,
                    "source_ref": source_ref,
                    "evidence_ref": f"prepared_script[{beat_index}]",
                    "consequence": _consequence_kind(text),
                    "changed_dimensions": _changed_dimensions(text),
                    "advisory_only": True,
                }
            )
    return out


def validate_source_consequence_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        return {"ok": False, "reason": "missing_source_consequence_map"}
    invalid: list[int] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            invalid.append(index)
            continue
        if not (
            isinstance(item.get("source_ref"), str)
            and item.get("source_ref")
            and isinstance(item.get("evidence_ref"), str)
            and item.get("evidence_ref")
            and isinstance(item.get("consequence"), str)
            and item.get("consequence")
            and isinstance(item.get("changed_dimensions"), list)
            and item.get("changed_dimensions")
            and item.get("advisory_only") is True
        ):
            invalid.append(index)
    return {"ok": not invalid, "invalid_indices": invalid, "count": len(value)}


def build_live_event_viability(
    script: Sequence[str],
    *,
    actionability: Mapping[str, Any],
    layout: Mapping[str, Any],
    role: str,
) -> dict[str, Any]:
    action_kinds = sorted(
        {
            str(intent.get("kind"))
            for beat in actionability.get("beat_action_intents") or []
            if isinstance(beat, Mapping)
            for intent in beat.get("intents") or []
            if isinstance(intent, Mapping)
            and str(intent.get("kind")) not in {"spoken_argument", "source_citation"}
        }
    )
    layout_needs = sorted(
        {
            str(need)
            for beat in layout.get("beat_layout_intents") or []
            if isinstance(beat, Mapping)
            for need in beat.get("needs") or []
            if isinstance(need, str) and need not in {"unsupported_layout_need", "host_presence"}
        }
    )
    joined = " ".join(script)
    return {
        "live_event_viability_version": SEGMENT_CONSULTATION_VERSION,
        "role": role,
        "quality_range": "excellent_canary",
        "visible_or_doable_action_kinds": action_kinds,
        "layout_needs": layout_needs,
        "has_tension": _has_any(joined, ("but", "because", "stakes", "problem", "tension")),
        "has_payoff": _has_any(
            joined,
            ("so", "therefore", "which means", "consequence", "result", "changes", "next"),
        ),
        "nonsterile_force_markers": [
            marker for marker in NONSTERILE_FORCE_MARKERS if marker in joined.lower()
        ][:8],
        "advisory_only": True,
    }


def validate_live_event_viability(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"ok": False, "reason": "missing_live_event_viability"}
    action_kinds = value.get("visible_or_doable_action_kinds")
    layout_needs = value.get("layout_needs")
    force_markers = value.get("nonsterile_force_markers")
    ok = (
        value.get("live_event_viability_version") == SEGMENT_CONSULTATION_VERSION
        and value.get("quality_range") == "excellent_canary"
        and isinstance(action_kinds, list)
        and len(action_kinds) >= 2
        and isinstance(layout_needs, list)
        and bool(layout_needs)
        and value.get("has_tension") is True
        and value.get("has_payoff") is True
        and isinstance(force_markers, list)
        and bool(force_markers)
        and value.get("advisory_only") is True
    )
    return {
        "ok": ok,
        "visible_or_doable_action_kinds": action_kinds if isinstance(action_kinds, list) else [],
        "layout_needs": layout_needs if isinstance(layout_needs, list) else [],
        "nonsterile_force_markers": force_markers if isinstance(force_markers, list) else [],
    }


def build_readback_obligations(
    beat_layout_intents: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    obligations: list[dict[str, Any]] = []
    for beat in beat_layout_intents:
        if not isinstance(beat, Mapping):
            continue
        beat_index = beat.get("beat_index")
        for need in beat.get("needs") or []:
            if need in {"unsupported_layout_need", "host_presence"}:
                continue
            obligations.append(
                {
                    "beat_index": beat_index,
                    "layout_need": need,
                    "evidence_refs": _string_list(beat.get("evidence_refs")),
                    "source_affordances": _string_list(beat.get("source_affordances")),
                    "proposal_only": True,
                    "runtime_must_receipt": True,
                    "authority": "runtime_readback_required",
                    "success_claim_allowed_in_prep": False,
                }
            )
    return obligations


def validate_readback_obligations(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        return {"ok": False, "reason": "missing_readback_obligations"}
    invalid: list[int] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            invalid.append(index)
            continue
        if not (
            item.get("layout_need")
            and item.get("proposal_only") is True
            and item.get("runtime_must_receipt") is True
            and item.get("authority") == "runtime_readback_required"
            and item.get("success_claim_allowed_in_prep") is False
            and _string_list(item.get("evidence_refs"))
            and _string_list(item.get("source_affordances"))
        ):
            invalid.append(index)
    return {"ok": not invalid, "invalid_indices": invalid, "count": len(value)}


def framework_vocabulary_hits(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in FRAMEWORK_VOCABULARY_TERMS if term in lower]


def nonsterile_force_ok(
    script: Sequence[str], *, personage_violations: Sequence[Any]
) -> dict[str, Any]:
    joined = " ".join(script).lower()
    markers = [marker for marker in NONSTERILE_FORCE_MARKERS if marker in joined]
    return {
        "ok": not personage_violations and len(markers) >= 4,
        "markers": markers[:10],
        "personage_violation_count": len(personage_violations),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in phrases)


def _source_targets_for_beat(
    beat_action_intents: Sequence[Mapping[str, Any]] | None,
    beat_index: int,
) -> list[str]:
    if not beat_action_intents:
        return []
    for beat in beat_action_intents:
        if not isinstance(beat, Mapping) or beat.get("beat_index") != beat_index:
            continue
        targets = [
            str(intent.get("target"))
            for intent in beat.get("intents") or []
            if isinstance(intent, Mapping)
            and intent.get("kind") == "source_citation"
            and intent.get("target")
        ]
        return targets
    return []


def _has_sourceish_text(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:argues|writes|shows|documents|finds|study|report|source|archive|paper)\b",
            text,
            re.IGNORECASE,
        )
    )


def _consequence_kind(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in ("place", "rank", "tier", "#")):
        return "ranking_or_order_changed"
    if any(term in lower for term in ("visible", "layout", "chart", "show", "screen")):
        return "visible_or_layout_obligation_changed"
    if any(term in lower for term in ("refuse", "reject", "rather than", "instead")):
        return "scope_or_refusal_changed"
    return "claim_shape_changed"


def _changed_dimensions(text: str) -> list[str]:
    lower = text.lower()
    dims: list[str] = ["claim"]
    if any(term in lower for term in ("place", "rank", "tier", "#")):
        dims.append("ranking")
    if any(term in lower for term in ("visible", "layout", "chart", "screen", "show")):
        dims.append("layout_need")
    if any(term in lower for term in ("what do you think", "chat", "poll")):
        dims.append("audience_action")
    if any(term in lower for term in ("refuse", "reject", "instead", "rather than", "limits")):
        dims.append("scope")
    return sorted(set(dims))
