"""Source-packet inquiry blackboard for segment prep.

The blackboard is a pre-planning control surface: it tells prep that source
packets and evaluated guidance are needed before drafting. It does not choose a
topic, script, layout, runtime action, or release outcome.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from shared.grounding_provider_router import REQUIRED_EVIDENCE_FIELDS
from shared.knowledge_recruitment_pressure import (
    AUTHORITY_BOUNDARIES as KNOWLEDGE_AUTHORITY_BOUNDARIES,
)
from shared.knowledge_recruitment_pressure import (
    FreshnessNeed,
    KnowledgeGapSignal,
    KnowledgeStakes,
    build_knowledge_recruitment_decision,
)

SOURCE_PACKET_INQUIRY_VERSION = 1
SOURCE_PACKET_INQUIRY_AUTHORITY = "advisory_source_packet_inquiry_prior"
SOURCE_PACKET_INQUIRY_DOCTRINE = "forms_are_generated_authority_is_gated"
SOURCE_PACKET_INQUIRY_REF_PREFIX = "source_packet_inquiry"


def build_source_packet_inquiry_blackboard(
    *,
    target_segments: int,
    existing_manifest_programmes: Sequence[str] = (),
    source_refs: Sequence[str] = (),
    budget_s: float | None = None,
) -> dict[str, Any]:
    """Build an advisory source-inquiry blackboard for the next planning call.

    The shape is deliberately not a role-specific expert system. It creates
    pressure to gather enough source packets, counterexamples, and actionability
    evidence, then leaves form/topic generation to the planner and model under
    existing provenance, pause, and Command-R residency gates.
    """

    cleaned_sources = tuple(_clean_refs(source_refs))
    cleaned_existing = tuple(_clean_refs(existing_manifest_programmes))
    signals = _knowledge_gap_signals(
        target_segments=target_segments,
        existing_manifest_programmes=cleaned_existing,
        source_refs=cleaned_sources,
    )
    decisions = [_decision_payload(signal) for signal in signals]
    blackboard: dict[str, Any] = {
        "source_packet_inquiry_version": SOURCE_PACKET_INQUIRY_VERSION,
        "authority": SOURCE_PACKET_INQUIRY_AUTHORITY,
        "doctrine": SOURCE_PACKET_INQUIRY_DOCTRINE,
        "target_segments": max(0, int(target_segments)),
        "budget_s": budget_s,
        "existing_manifest_programmes": list(cleaned_existing),
        "supplied_source_refs": list(cleaned_sources),
        "source_packet_requirements": _source_packet_requirements(),
        "knowledge_gap_signals": [signal.model_dump(mode="json") for signal in signals],
        "recruitment_decisions": decisions,
        "lead_policy": {
            "fixed_pass_count": False,
            "may_follow_leads_until": [
                "source_packet_sufficient",
                "budget_exhausted",
                "privacy_or_egress_blocked",
                "no_candidate_witness_required",
            ],
            "no_forced_segment_production": True,
            "thin_sources_prefer_no_candidate": True,
        },
        "authority_boundaries": [
            *KNOWLEDGE_AUTHORITY_BOUNDARIES,
            "blackboard_is_not_topic_authority",
            "blackboard_is_not_script_authority",
            "blackboard_is_not_layout_or_runtime_authority",
            "planner_may_use_it_only_as_source_inquiry_pressure",
        ],
    }
    blackboard["source_packet_inquiry_sha256"] = source_packet_inquiry_hash(blackboard)
    blackboard["source_packet_inquiry_ref"] = (
        f"{SOURCE_PACKET_INQUIRY_REF_PREFIX}:{blackboard['source_packet_inquiry_sha256']}"
    )
    return blackboard


def source_packet_inquiry_hash(blackboard: Mapping[str, Any]) -> str:
    """Return a stable hash for a source-packet inquiry blackboard."""

    payload = {
        key: value
        for key, value in blackboard.items()
        if key not in {"source_packet_inquiry_sha256", "source_packet_inquiry_ref"}
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_packet_inquiry_summary(blackboard: Mapping[str, Any]) -> dict[str, Any]:
    """Compact status payload for prep-status and manifests."""

    decisions = [
        item for item in blackboard.get("recruitment_decisions", []) if isinstance(item, Mapping)
    ]
    source_acquisition_required = any(
        item.get("source_acquisition_required") is True for item in decisions
    )
    blockers = sorted(
        {
            str(blocker)
            for item in decisions
            for blocker in item.get("blockers", []) or []
            if str(blocker).strip()
        }
    )
    return {
        "source_packet_inquiry_version": blackboard.get("source_packet_inquiry_version"),
        "authority": blackboard.get("authority"),
        "doctrine": blackboard.get("doctrine"),
        "source_packet_inquiry_sha256": blackboard.get("source_packet_inquiry_sha256"),
        "source_packet_inquiry_ref": blackboard.get("source_packet_inquiry_ref"),
        "knowledge_gap_count": len(blackboard.get("knowledge_gap_signals", []) or []),
        "recruitment_decision_count": len(decisions),
        "source_acquisition_required": source_acquisition_required,
        "blockers": blockers,
        "fixed_pass_count": bool((blackboard.get("lead_policy") or {}).get("fixed_pass_count")),
        "no_forced_segment_production": bool(
            (blackboard.get("lead_policy") or {}).get("no_forced_segment_production")
        ),
    }


def render_source_packet_inquiry_seed(blackboard: Mapping[str, Any] | None) -> str:
    """Render the blackboard into a compact seed addendum for Command-R."""

    if not blackboard:
        return ""
    signals = [
        item for item in blackboard.get("knowledge_gap_signals", []) if isinstance(item, Mapping)
    ]
    decisions = [
        item for item in blackboard.get("recruitment_decisions", []) if isinstance(item, Mapping)
    ]
    lines = [
        "SOURCE-PACKET INQUIRY BLACKBOARD:",
        "- Authority: advisory prior only; not topic, script, layout, cue, runtime, or release authority.",
        "- Doctrine: forms are generated; authority is gated.",
        "- Use: follow useful source leads until source packets are sufficient, budget/egress blocks, or a no-candidate witness is required.",
        "- Avoid: fixed pass counts, sticky examples, detector-trigger prose, prepared layout commands, and forced segment production.",
    ]
    ref = blackboard.get("source_packet_inquiry_ref")
    if ref:
        lines.append(f"- Inquiry ref: {ref}")
    if decisions:
        required = any(item.get("source_acquisition_required") is True for item in decisions)
        lines.append(f"- Source acquisition required before public claims: {required}.")
    for signal in signals[:4]:
        lines.append(
            "- Gap "
            f"{signal.get('gap_id', 'unknown')}: "
            f"{signal.get('uncertainty_summary', 'source uncertainty')} "
            f"(freshness={signal.get('freshness_need', 'unknown')}, "
            f"stakes={signal.get('stakes', 'unknown')})."
        )
    return "\n".join(lines)


def _source_packet_requirements() -> list[dict[str, Any]]:
    required_fields = sorted(REQUIRED_EVIDENCE_FIELDS)
    return [
        {
            "packet_kind": "public_claim_source_packet",
            "required_receipt_fields": required_fields,
            "purpose": "support concrete public claims and cite what would change if the source were absent",
            "authority_boundary": "evidence_pressure_not_claim_authority",
        },
        {
            "packet_kind": "live_actionability_source_packet",
            "required_receipt_fields": required_fields,
            "purpose": "identify visible or doable objects that can carry spoken claims",
            "authority_boundary": "proposal_only_until_runtime_readback",
        },
        {
            "packet_kind": "counterexample_or_counter_reference_packet",
            "required_receipt_fields": required_fields,
            "purpose": "calibrate quality ranges and prevent sticky examples from becoming topics",
            "authority_boundary": "calibration_surface_not_template",
        },
    ]


def _knowledge_gap_signals(
    *,
    target_segments: int,
    existing_manifest_programmes: Sequence[str],
    source_refs: Sequence[str],
) -> list[KnowledgeGapSignal]:
    common_refs = tuple(source_refs)
    return [
        KnowledgeGapSignal(
            gap_id="segment_source_packets_before_planning",
            domain="segment_prep",
            task_summary=(
                f"prepare source-packet candidates for {max(0, int(target_segments))} segment(s) "
                "before choosing topics or drafting"
            ),
            uncertainty_summary=(
                "internal topic/form memory is not enough for excellent livestream segments; "
                "public claims need source packets and consequences"
            ),
            internal_confidence=0.35,
            stakes=KnowledgeStakes.HIGH,
            freshness_need=FreshnessNeed.OPEN_WORLD,
            public_claim_intended=True,
            existing_evidence_refs=common_refs,
        ),
        KnowledgeGapSignal(
            gap_id="segment_actionability_sources_before_planning",
            domain="segment_prep",
            task_summary="find source-backed visible or doable objects before scripting beats",
            uncertainty_summary=(
                "script quality depends on each important claim mapping to something seen or done"
            ),
            internal_confidence=0.46,
            stakes=KnowledgeStakes.HIGH,
            freshness_need=FreshnessNeed.STABLE_BACKGROUND,
            public_claim_intended=True,
            existing_evidence_refs=common_refs,
        ),
        KnowledgeGapSignal(
            gap_id="segment_counterexamples_before_planning",
            domain="segment_prep",
            task_summary="gather references and counter-references for calibration, not imitation",
            uncertainty_summary=(
                "examples can contaminate topic choice unless treated as quality-range evidence"
            ),
            internal_confidence=0.58 if existing_manifest_programmes else 0.42,
            stakes=KnowledgeStakes.MEDIUM,
            freshness_need=FreshnessNeed.STABLE_BACKGROUND,
            public_claim_intended=False,
            existing_evidence_refs=common_refs,
        ),
    ]


def _decision_payload(signal: KnowledgeGapSignal) -> dict[str, Any]:
    try:
        return build_knowledge_recruitment_decision(signal).model_dump(mode="json")
    except Exception as exc:
        return {
            "schema_version": SOURCE_PACKET_INQUIRY_VERSION,
            "decision_id": f"source_packet_inquiry_blocked:{signal.gap_id}",
            "gap_id": signal.gap_id,
            "domain": signal.domain,
            "claim_type": "knowledge_recruitment_guidance_request",
            "should_recruit": True,
            "trigger_reasons": ["source_packet_inquiry_decision_build_failed"],
            "source_acquisition_required": True,
            "source_acquiring_provider_ids": [],
            "source_conditioned_provider_ids": [],
            "local_evaluator_provider_id": None,
            "egress_preflight_provider_ids": [],
            "required_receipt_fields": sorted(REQUIRED_EVIDENCE_FIELDS),
            "authority_boundaries": [
                *KNOWLEDGE_AUTHORITY_BOUNDARIES,
                "blackboard_is_not_script_layout_or_runtime_authority",
            ],
            "blockers": [f"{type(exc).__name__}: {exc}"],
        }


def _clean_refs(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned
