"""Live-event quality gate for prepared livestream segments.

This layer checks whether a prepared script is actually structured as a
livestream bit: a source-bound public event with temporal movement, visible or
doable counterparts, audience job, and payoff. It is intentionally stricter than
script polish or metadata completeness.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from shared.segment_prep_contract import (
    framework_vocabulary_leaks,
    is_source_evidence_ref,
    validate_segment_prep_contract,
)
from shared.segment_quality_actionability import segment_personage_violations

LIVE_EVENT_RUBRIC_VERSION = 1
LIVE_EVENT_GOOD_FLOOR = 82

_CONCRETE_ACTION_KINDS = {
    "argument_posture_shift",
    "chat_poll",
    "comparison",
    "countdown",
    "iceberg_depth",
    "tier_chart",
}
_TRANSFORMING_ACTION_KINDS = {
    "chat_poll",
    "comparison",
    "countdown",
    "iceberg_depth",
    "tier_chart",
}
_TEMPORAL_TERMS_RE = re.compile(
    r"\b(?:now|first|next|then|later|return|back to|pivot|turn|opening|closing|"
    r"callback|before|after|because|therefore|so)\b",
    re.IGNORECASE,
)
_AUDIENCE_JOB_RE = re.compile(
    r"\b(?:chat|vote|judge|pick|challenge|compare|inspect|decide|rank|name the|"
    r"drop it in)\b",
    re.IGNORECASE,
)
_PAYOFF_RE = re.compile(
    r"\b(?:return|callback|closing|ending|resolve|land|therefore|so the|next move|"
    r"final decision|back to)\b",
    re.IGNORECASE,
)
_SOURCE_MECHANIC_RE = re.compile(
    r"\b(?:source|receipt|readback|trace|evidence|artifact|manifest|prompt hash|"
    r"claim|consequence|changes|shows|demonstrates|argues|documents)\b",
    re.IGNORECASE,
)
_STATIC_SUCCESS_RE = re.compile(
    r"\b(?:default|static|balanced|garage[-_ ]door).{0,40}\b(?:success|succeeds|works|"
    r"counts)\b",
    re.IGNORECASE,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _sha256_text(text)


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _all_intents(beat_action_intents: Any) -> list[Mapping[str, Any]]:
    return [
        intent
        for beat in _mapping_list(beat_action_intents)
        for intent in _mapping_list(beat.get("intents"))
    ]


def _all_layout_needs(beat_layout_intents: Any) -> list[Mapping[str, Any]]:
    needs: list[Mapping[str, Any]] = []
    for beat in _mapping_list(beat_layout_intents):
        need_objects = _mapping_list(beat.get("need_objects"))
        if need_objects:
            needs.extend(need_objects)
            continue
        for need in _string_list(beat.get("needs")):
            needs.append(
                {
                    "need_kind": need,
                    "source_packet_refs": _string_list(beat.get("evidence_refs")),
                    "source_affordances": _string_list(beat.get("source_affordances")),
                    "readback_required": True,
                }
            )
    return needs


def _layout_evidence_refs(beat_layout_intents: Any) -> list[str]:
    refs: list[str] = []
    for beat in _mapping_list(beat_layout_intents):
        refs.extend(_string_list(beat.get("evidence_refs")))
    return list(dict.fromkeys(refs))


def _contract_source_refs(segment_prep_contract: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(segment_prep_contract, Mapping):
        return []
    refs: list[str] = []
    for packet in _mapping_list(segment_prep_contract.get("source_packet_refs")):
        refs.extend(_string_list(packet.get("evidence_refs") or packet.get("source_ref")))
    for claim in _mapping_list(segment_prep_contract.get("claim_map")):
        refs.extend(_string_list(claim.get("grounds")))
    return list(dict.fromkeys(ref for ref in refs if is_source_evidence_ref(ref)))


def _role_required_actions(role: str) -> set[str]:
    return {
        "iceberg": {"iceberg_depth"},
        "react": {"argument_posture_shift", "source_citation"},
        "tier_list": {"tier_chart"},
        "top_10": {"countdown"},
    }.get(role, set())


def _band(score: int) -> str:
    if score >= 93:
        return "excellent"
    if score >= LIVE_EVENT_GOOD_FLOOR:
        return "good"
    if score >= 75:
        return "review_only"
    if score >= 50:
        return "thin"
    if score > 0:
        return "generic"
    return "invalid"


def _dimension(
    name: str, passed: bool, points: int, detail: str, **observed: Any
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "points": points if passed else 0,
        "detail": detail,
        "observed": observed,
    }


def evaluate_segment_live_event_quality(
    script: Sequence[str],
    segment_beats: Sequence[str],
    beat_action_intents: Sequence[Mapping[str, Any]],
    beat_layout_intents: Sequence[Mapping[str, Any]],
    *,
    role: str = "",
    segment_prep_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a blocking quality report for the live-event shape of a segment."""

    script_list = [str(item) for item in script]
    text = " ".join(script_list)
    intents = _all_intents(beat_action_intents)
    action_kinds = [str(intent.get("kind") or "") for intent in intents]
    concrete_action_kinds = sorted(
        set(kind for kind in action_kinds if kind in _CONCRETE_ACTION_KINDS)
    )
    transforming_action_kinds = sorted(
        set(kind for kind in action_kinds if kind in _TRANSFORMING_ACTION_KINDS)
    )
    source_refs = _contract_source_refs(segment_prep_contract)
    source_refs.extend(
        ref for ref in _layout_evidence_refs(beat_layout_intents) if is_source_evidence_ref(ref)
    )
    source_refs = list(dict.fromkeys(source_refs))
    layout_needs = _all_layout_needs(beat_layout_intents)
    role_required = _role_required_actions(role)
    contract_report = validate_segment_prep_contract(
        segment_prep_contract,
        prepared_script=script_list,
        segment_beats=segment_beats,
    )
    personage = segment_personage_violations(script_list)
    framework_leaks = framework_vocabulary_leaks(script_list)

    live_event_object = bool(transforming_action_kinds) and bool(source_refs)
    temporal_coupling = (
        len(script_list) >= 2
        and bool(_TEMPORAL_TERMS_RE.search(text))
        and len(concrete_action_kinds) >= 2
    )
    visible_transformation = bool(transforming_action_kinds) and bool(layout_needs)
    audience_job = "chat_poll" in action_kinds or bool(_AUDIENCE_JOB_RE.search(text))
    payoff = bool(script_list and _PAYOFF_RE.search(script_list[-1]))
    spoken_source_mechanic = bool(_SOURCE_MECHANIC_RE.search(text))
    source_as_mechanic = bool(source_refs) and spoken_source_mechanic
    role_standard_fit = not role_required or bool(role_required.intersection(action_kinds))
    repair_readback_legibility = bool(layout_needs) and any(
        "readback" in str(need).lower() or _string_list(need.get("source_packet_refs"))
        for need in layout_needs
    )
    perspective_clean = not personage and not framework_leaks

    dimensions = [
        _dimension(
            "live_event_object",
            live_event_object,
            12,
            "segment has a bounded public object tied to source evidence",
            source_ref_count=len(source_refs),
            transforming_action_kinds=transforming_action_kinds,
        ),
        _dimension(
            "temporal_coupling",
            temporal_coupling,
            12,
            "beats move in sequence rather than independent essays",
            concrete_action_kinds=concrete_action_kinds,
        ),
        _dimension(
            "visible_transformation",
            visible_transformation,
            14,
            "speech creates an inspectable visible or doable transformation",
            layout_need_count=len(layout_needs),
            transforming_action_kinds=transforming_action_kinds,
        ),
        _dimension(
            "audience_job",
            audience_job,
            10,
            "viewer or chat has a bounded job when participation matters",
            has_chat_poll="chat_poll" in action_kinds,
        ),
        _dimension(
            "payoff_resolution",
            payoff,
            10,
            "final beat resolves, reframes, or pays off the opening pressure",
            final_beat=script_list[-1] if script_list else "",
        ),
        _dimension(
            "source_as_mechanic",
            source_as_mechanic,
            16,
            "sources change scope, rank, confidence, contrast, or visible action",
            source_ref_count=len(source_refs),
            contract_ok=contract_report.get("ok"),
            spoken_source_mechanic=spoken_source_mechanic,
        ),
        _dimension(
            "role_standard_fit",
            role_standard_fit,
            10,
            "role-specific mechanics are present when the role implies them",
            role=role,
            required_action_kinds=sorted(role_required),
        ),
        _dimension(
            "repair_readback_legibility",
            repair_readback_legibility,
            8,
            "runtime readback/fallback has a legible object to inspect",
            layout_need_count=len(layout_needs),
        ),
        _dimension(
            "nonhuman_perspective_clean",
            perspective_clean,
            8,
            "script avoids anthropomorphic perspective and framework vocabulary leakage",
            personage_violations=personage,
            framework_vocabulary_leaks=framework_leaks,
        ),
    ]
    score = sum(item["points"] for item in dimensions)
    cap_reasons: list[dict[str, Any]] = []
    if _STATIC_SUCCESS_RE.search(text):
        score = 0
        cap_reasons.append({"reason": "static_default_layout_success_claim"})
    elif not live_event_object or not visible_transformation:
        score = min(score, 49)
        cap_reasons.append({"reason": "missing_live_event_object_or_visible_transformation"})
    elif not source_as_mechanic:
        score = min(score, 49)
        cap_reasons.append({"reason": "source_is_decorative_or_missing"})
    elif not temporal_coupling:
        score = min(score, 49)
        cap_reasons.append({"reason": "action_tokens_without_temporal_coupling"})
    elif not audience_job or not payoff:
        score = min(score, 74)
        cap_reasons.append({"reason": "missing_audience_job_or_payoff"})
    elif not perspective_clean:
        score = min(score, 49)
        cap_reasons.append({"reason": "perspective_or_framework_leak"})

    band = _band(score)
    violations = [
        {"reason": item["name"], "detail": item["detail"], "observed": item["observed"]}
        for item in dimensions
        if not item["passed"]
    ]
    violations.extend(cap_reasons)
    plan = {
        "live_event_object": transforming_action_kinds[0] if transforming_action_kinds else "",
        "source_refs": source_refs,
        "audience_job": "chat_poll_or_public_inspection" if audience_job else "",
        "payoff": script_list[-1][:320] if script_list else "",
        "role": role,
    }
    report = {
        "live_event_rubric_version": LIVE_EVENT_RUBRIC_VERSION,
        "ok": band in {"good", "excellent"},
        "score": score,
        "band": band,
        "dimensions": dimensions,
        "violations": violations,
        "plan": plan,
        "observed": {
            "action_kinds": sorted(set(action_kinds)),
            "concrete_action_kinds": concrete_action_kinds,
            "transforming_action_kinds": transforming_action_kinds,
            "source_ref_count": len(source_refs),
            "script_beat_count": len(script_list),
            "segment_beat_count": len(segment_beats),
        },
    }
    return report


def compare_live_event_quality(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
    """Return 1 if left is stronger, -1 if right is stronger, 0 if equivalent."""
    left_score = int(left.get("score") or 0)
    right_score = int(right.get("score") or 0)
    if left_score != right_score:
        return 1 if left_score > right_score else -1
    left_band = str(left.get("band") or "")
    right_band = str(right.get("band") or "")
    order = {"invalid": 0, "generic": 1, "thin": 2, "review_only": 3, "good": 4, "excellent": 5}
    if order.get(left_band, -1) != order.get(right_band, -1):
        return 1 if order.get(left_band, -1) > order.get(right_band, -1) else -1
    return 0


def validate_live_event_report_matches_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Replay a stored live-event report and check hash/report freshness."""
    if artifact.get("segment_live_event_rubric_version") != LIVE_EVENT_RUBRIC_VERSION:
        return {
            "ok": False,
            "violations": [{"reason": "unsupported_live_event_rubric_version"}],
        }
    expected = evaluate_segment_live_event_quality(
        _string_list(artifact.get("prepared_script")),
        _string_list(artifact.get("segment_beats")),
        _mapping_list(artifact.get("beat_action_intents")),
        _mapping_list(artifact.get("beat_layout_intents")),
        role=str(artifact.get("role") or ""),
        segment_prep_contract=artifact.get("segment_prep_contract")
        if isinstance(artifact.get("segment_prep_contract"), Mapping)
        else None,
    )
    stored = artifact.get("segment_live_event_report")
    if stored != expected:
        return {
            "ok": False,
            "violations": [{"reason": "stale_live_event_report"}],
            "expected": expected,
        }
    stored_hash = artifact.get("segment_live_event_report_sha256")
    if not isinstance(stored_hash, str) or stored_hash != _sha256_json(expected):
        return {
            "ok": False,
            "violations": [{"reason": "live_event_report_hash_mismatch"}],
        }
    if expected["ok"] is not True:
        return {"ok": False, "violations": expected["violations"], "report": expected}
    return {"ok": True, "violations": [], "report": expected}
