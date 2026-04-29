"""Map content programme boundary events to ResearchVehiclePublicEvent records."""

from __future__ import annotations

import json
import re
from collections.abc import Hashable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    PrivacyState,
    PublicPrivateMode,
    RightsState,
    UnavailableReason,
    WitnessState,
)
from shared.research_vehicle_public_event import (
    EventType,
    FallbackAction,
    PrivacyClass,
    PublicEventChapterRef,
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    RightsClass,
    StateKind,
    Surface,
)

type BoundaryType = Literal[
    "programme.started",
    "criterion.declared",
    "evidence.observed",
    "claim.made",
    "rank.assigned",
    "comparison.resolved",
    "uncertainty.marked",
    "refusal.issued",
    "correction.made",
    "clip.candidate",
    "live_cuepoint.candidate",
    "chapter.boundary",
    "artifact.candidate",
    "programme.ended",
]
type GateState = Literal[
    "pass", "fail", "dry_run", "private_only", "refusal", "correction_required"
]
type ClaimKind = Literal[
    "observation",
    "classification",
    "ranking",
    "comparison",
    "explanation",
    "refusal",
    "correction",
    "metadata",
]
type AuthorityCeiling = Literal["evidence_bound", "speculative", "internal_only"]
type ConfidenceLabel = Literal["none", "low", "medium", "medium_high", "high"]
type BoundaryStatus = Literal["standard", "refusal", "correction"]
type AdaptationStatus = Literal["emitted", "refused"]

PRODUCER = "shared.format_public_event_adapter"
TASK_ANCHOR = "format-to-public-event-adapter"

_PUBLIC_MODES: frozenset[PublicPrivateMode] = frozenset(
    {"public_live", "public_archive", "public_monetizable"}
)
_PUBLIC_SAFE_RIGHTS: frozenset[RightsState] = frozenset(
    {"operator_original", "cleared", "platform_embed_only"}
)
_PUBLIC_SAFE_PRIVACY: frozenset[PrivacyState] = frozenset({"public_safe", "aggregate_only"})
_GLOBAL_BLOCK_REASONS: frozenset[UnavailableReason] = frozenset(
    {
        "private_mode",
        "dry_run_mode",
        "missing_evidence_ref",
        "missing_grounding_gate",
        "grounding_gate_failed",
        "unsupported_claim",
        "source_stale",
        "rights_blocked",
        "privacy_blocked",
        "egress_blocked",
        "audio_blocked",
        "monetization_blocked",
        "monetization_readiness_missing",
        "third_party_media_blocked",
        "owned_cleared_av_missing",
        "world_surface_blocked",
        "witness_missing",
    }
)


class FormatPublicEventModel(BaseModel):
    """Strict immutable base for adapter records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class BoundaryNoExpertSystemGate(FormatPublicEventModel):
    gate_ref: str | None
    gate_state: GateState
    claim_allowed: bool
    public_claim_allowed: bool
    infractions: tuple[str, ...] = Field(default_factory=tuple)


class BoundaryClaimShape(FormatPublicEventModel):
    claim_kind: ClaimKind
    authority_ceiling: AuthorityCeiling
    confidence_label: ConfidenceLabel
    uncertainty: str
    scope_limit: str


class BoundaryPublicEventMapping(FormatPublicEventModel):
    internal_only: bool
    research_vehicle_event_type: EventType | None
    state_kind: StateKind | None
    source_substrate_id: str | None
    allowed_surfaces: tuple[Surface, ...] = Field(default_factory=tuple)
    denied_surfaces: tuple[Surface, ...] = Field(default_factory=tuple)
    fallback_action: FallbackAction
    unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)


class BoundaryCuepointChapterPolicy(FormatPublicEventModel):
    live_ad_cuepoint_allowed: bool
    vod_chapter_allowed: bool
    live_cuepoint_distinct_from_vod_chapter: Literal[True] = True
    chapter_label: str | None
    timecode: str | None
    cuepoint_unavailable_reason: UnavailableReason | None


class ProgrammeBoundaryEvent(FormatPublicEventModel):
    schema_version: Literal[1] = 1
    boundary_id: str
    emitted_at: datetime
    programme_id: str
    run_id: str
    format_id: str
    sequence: int = Field(ge=0)
    boundary_type: BoundaryType
    public_private_mode: PublicPrivateMode
    grounding_question: str
    summary: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    no_expert_system_gate: BoundaryNoExpertSystemGate
    claim_shape: BoundaryClaimShape
    public_event_mapping: BoundaryPublicEventMapping
    cuepoint_chapter_policy: BoundaryCuepointChapterPolicy
    dry_run_unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)
    duplicate_key: str


class FormatPublicEventDecision(FormatPublicEventModel):
    """Adapter result that keeps refusals explicit instead of silently skipping."""

    schema_version: Literal[1] = 1
    decision_id: str
    idempotency_key: str
    status: AdaptationStatus
    run_id: str
    programme_id: str
    boundary_id: str
    boundary_type: BoundaryType
    public_event: ResearchVehiclePublicEvent | None
    unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)
    hard_unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)
    grounding_question: str
    claim_scope: str
    confidence_label: ConfidenceLabel
    uncertainty: str
    source_status: BoundaryStatus
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    substrate_refs: tuple[str, ...] = Field(default_factory=tuple)
    witness_statuses: tuple[WitnessState, ...] = Field(default_factory=tuple)
    wcs_unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)

    def to_json_line(self) -> str:
        """Serialize the decision for audit or hold queues."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


def adapt_format_boundary_to_public_event(
    run: ContentProgrammeRunEnvelope,
    boundary_event: ProgrammeBoundaryEvent | Mapping[str, Any],
    *,
    generated_at: datetime | str,
) -> FormatPublicEventDecision:
    """Return the public-event adapter decision for one run boundary.

    The adapter only accepts the canonical run envelope and full programme
    boundary event. It does not inspect legacy event files or reconstruct
    eligibility from partial state.
    """

    boundary = _coerce_boundary(boundary_event)
    generated = _normalise_timestamp(generated_at)
    event_id = format_public_event_id(
        run_id=run.run_id,
        boundary_id=boundary.boundary_id,
        duplicate_key=boundary.duplicate_key,
    )
    evidence_refs = _combined_evidence_refs(run, boundary)
    unavailable = _all_unavailable_reasons(run, boundary)
    hard_unavailable = _hard_unavailable_reasons(run, boundary, unavailable)
    public_event = None
    if not hard_unavailable:
        public_event = _build_public_event(
            run=run,
            boundary=boundary,
            event_id=event_id,
            generated_at=generated,
            evidence_refs=evidence_refs,
            unavailable_reasons=unavailable,
        )
    return FormatPublicEventDecision(
        decision_id=f"fped:{event_id}",
        idempotency_key=event_id,
        status="emitted" if public_event is not None else "refused",
        run_id=run.run_id,
        programme_id=run.programme_id,
        boundary_id=boundary.boundary_id,
        boundary_type=boundary.boundary_type,
        public_event=public_event,
        unavailable_reasons=unavailable,
        hard_unavailable_reasons=hard_unavailable,
        grounding_question=run.grounding_question,
        claim_scope=boundary.claim_shape.scope_limit,
        confidence_label=boundary.claim_shape.confidence_label,
        uncertainty=boundary.claim_shape.uncertainty,
        source_status=_boundary_status(boundary),
        evidence_refs=evidence_refs,
        evidence_envelope_refs=run.wcs.evidence_envelope_refs,
        substrate_refs=(*run.substrate_refs, *run.wcs.semantic_substrate_refs),
        witness_statuses=tuple(outcome.witness_state for outcome in run.witnessed_outcomes),
        wcs_unavailable_reasons=run.wcs.unavailable_reasons,
    )


def format_public_event_id(*, run_id: str, boundary_id: str, duplicate_key: str) -> str:
    """Stable idempotency key for a run-boundary public event projection."""

    return _sanitize_id(f"rvpe:format:{run_id}:{boundary_id}:{duplicate_key}")


def _coerce_boundary(
    boundary_event: ProgrammeBoundaryEvent | Mapping[str, Any],
) -> ProgrammeBoundaryEvent:
    if isinstance(boundary_event, ProgrammeBoundaryEvent):
        return boundary_event
    return ProgrammeBoundaryEvent.model_validate(boundary_event)


def _all_unavailable_reasons(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> tuple[UnavailableReason, ...]:
    reasons: list[UnavailableReason] = []
    reasons.extend(_identity_reasons(run, boundary))
    reasons.extend(_mode_reasons(run, boundary))
    reasons.extend(_evidence_reasons(run, boundary))
    reasons.extend(_rights_privacy_reasons(run))
    reasons.extend(_wcs_reasons(run))
    reasons.extend(_gate_reasons(run, boundary))
    reasons.extend(_mapping_reasons(boundary))
    reasons.extend(run.rights_privacy_public_mode.unavailable_reasons)
    reasons.extend(run.wcs.unavailable_reasons)
    reasons.extend(boundary.public_event_mapping.unavailable_reasons)
    reasons.extend(boundary.dry_run_unavailable_reasons)
    if boundary.cuepoint_chapter_policy.cuepoint_unavailable_reason is not None:
        reasons.append(boundary.cuepoint_chapter_policy.cuepoint_unavailable_reason)
    return _dedupe(reasons)


def _hard_unavailable_reasons(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
    unavailable: Iterable[UnavailableReason],
) -> tuple[UnavailableReason, ...]:
    hard: list[UnavailableReason] = [
        reason for reason in unavailable if reason in _GLOBAL_BLOCK_REASONS
    ]
    mapping = boundary.public_event_mapping
    if mapping.research_vehicle_event_type == "cuepoint.candidate":
        hard.extend(
            reason
            for reason in unavailable
            if reason
            in {
                "archive_missing",
                "video_id_missing",
                "cuepoint_smoke_missing",
                "cuepoint_api_rejected",
                "rate_limited",
                "live_provider_smoke_missing",
            }
        )
    if (
        mapping.research_vehicle_event_type == "shorts.candidate"
        and "owned_cleared_av_missing" in unavailable
    ):
        hard.append("owned_cleared_av_missing")
    if run.public_private_mode == "public_monetizable" and (
        "monetization" in mapping.allowed_surfaces
        or run.rights_privacy_public_mode.monetization_state != "ready"
    ):
        if run.rights_privacy_public_mode.monetization_state != "ready":
            hard.append("monetization_readiness_missing")
    return _dedupe(hard)


def _identity_reasons(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> tuple[UnavailableReason, ...]:
    if (
        boundary.run_id == run.run_id
        and boundary.programme_id == run.programme_id
        and boundary.format_id == run.format_id
    ):
        return ()
    return ("unsupported_claim",)


def _mode_reasons(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> tuple[UnavailableReason, ...]:
    reasons: list[UnavailableReason] = []
    for mode in (run.public_private_mode, boundary.public_private_mode):
        if mode == "private":
            reasons.append("private_mode")
        elif mode == "dry_run":
            reasons.append("dry_run_mode")
    return _dedupe(reasons)


def _evidence_reasons(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> tuple[UnavailableReason, ...]:
    reasons: list[UnavailableReason] = []
    if not boundary.evidence_refs:
        reasons.append("missing_evidence_ref")
    if not run.wcs.evidence_envelope_refs:
        reasons.append("missing_evidence_ref")
    if not run.gate_refs.grounding_gate_refs or boundary.no_expert_system_gate.gate_ref is None:
        reasons.append("missing_grounding_gate")
    if not _has_verified_witness(run):
        reasons.append("witness_missing")
    return _dedupe(reasons)


def _rights_privacy_reasons(run: ContentProgrammeRunEnvelope) -> tuple[UnavailableReason, ...]:
    posture = run.rights_privacy_public_mode
    reasons: list[UnavailableReason] = []
    if posture.rights_state not in _PUBLIC_SAFE_RIGHTS:
        reasons.append("rights_blocked")
    if posture.privacy_state not in _PUBLIC_SAFE_PRIVACY:
        reasons.append("privacy_blocked")
    return tuple(reasons)


def _wcs_reasons(run: ContentProgrammeRunEnvelope) -> tuple[UnavailableReason, ...]:
    health = run.wcs.health_state
    if health in {"blocked", "unsafe"}:
        return ("world_surface_blocked",)
    if health == "stale":
        return ("source_stale",)
    if health == "missing":
        return ("missing_evidence_ref",)
    if health == "private_only":
        return ("private_mode",)
    if health in {"dry_run", "candidate"}:
        return ("dry_run_mode",)
    return ()


def _gate_reasons(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> tuple[UnavailableReason, ...]:
    gate = boundary.no_expert_system_gate
    public_safe_artifact = _is_public_safe_refusal_or_correction(run, boundary)
    if public_safe_artifact:
        return ()
    reasons: list[UnavailableReason] = []
    if gate.gate_state in {"fail", "dry_run", "private_only"} or gate.infractions:
        reasons.append("grounding_gate_failed")
    if not gate.claim_allowed:
        reasons.append("unsupported_claim")
    if not gate.public_claim_allowed:
        reasons.append("unsupported_claim")
    if boundary.claim_shape.authority_ceiling == "internal_only":
        reasons.append("unsupported_claim")
    return _dedupe(reasons)


def _mapping_reasons(boundary: ProgrammeBoundaryEvent) -> tuple[UnavailableReason, ...]:
    mapping = boundary.public_event_mapping
    if (
        mapping.internal_only
        or mapping.research_vehicle_event_type is None
        or mapping.state_kind is None
        or mapping.source_substrate_id is None
        or not mapping.allowed_surfaces
    ):
        return ("unsupported_claim",)
    return ()


def _build_public_event(
    *,
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
    event_id: str,
    generated_at: str,
    evidence_refs: tuple[str, ...],
    unavailable_reasons: tuple[UnavailableReason, ...],
) -> ResearchVehiclePublicEvent:
    mapping = boundary.public_event_mapping
    event_type = cast("EventType", mapping.research_vehicle_event_type)
    state_kind = cast("StateKind", mapping.state_kind)
    return ResearchVehiclePublicEvent(
        schema_version=1,
        event_id=event_id,
        event_type=event_type,
        occurred_at=_normalise_timestamp(boundary.emitted_at),
        broadcast_id=_first_ref(run.broadcast_refs),
        programme_id=run.programme_id,
        condition_id=run.condition_id,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id=cast("str", mapping.source_substrate_id),
            task_anchor=TASK_ANCHOR,
            evidence_ref=f"ContentProgrammeRun:{run.run_id}#ProgrammeBoundaryEvent:{boundary.boundary_id}",
            freshness_ref="programme_boundary.emitted_at",
        ),
        salience=_salience(boundary),
        state_kind=state_kind,
        rights_class=_rights_class(run.rights_privacy_public_mode.rights_state),
        privacy_class=_privacy_class(run.rights_privacy_public_mode.privacy_state),
        provenance=PublicEventProvenance(
            token=f"format_public_event:{event_id}",
            generated_at=generated_at,
            producer=PRODUCER,
            evidence_refs=list(
                _dedupe(
                    (
                        *evidence_refs,
                        *(f"unavailable:{reason}" for reason in unavailable_reasons),
                    )
                )
            ),
            rights_basis=_rights_basis(run.rights_privacy_public_mode.rights_state),
            citation_refs=list(_citation_refs(boundary.evidence_refs)),
        ),
        public_url=_public_url(run),
        frame_ref=None,
        chapter_ref=_chapter_ref(boundary, event_id),
        attribution_refs=list(_citation_refs(boundary.evidence_refs)),
        surface_policy=_surface_policy(run, boundary),
    )


def _surface_policy(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> PublicEventSurfacePolicy:
    mapping = boundary.public_event_mapping
    event_type = cast("EventType", mapping.research_vehicle_event_type)
    state_kind = cast("StateKind", mapping.state_kind)
    return PublicEventSurfacePolicy(
        allowed_surfaces=list(mapping.allowed_surfaces),
        denied_surfaces=list(mapping.denied_surfaces),
        claim_live=_claim_live(run, boundary),
        claim_archive=_claim_archive(run, boundary),
        claim_monetizable=_claim_monetizable(run, mapping.allowed_surfaces),
        requires_egress_public_claim=run.requested_public_private_mode == "public_live"
        or _claim_live(run, boundary),
        requires_audio_safe=_requires_audio_safe(mapping.allowed_surfaces),
        requires_provenance=True,
        requires_human_review=mapping.fallback_action == "operator_review",
        rate_limit_key=f"{event_type}:{state_kind}",
        redaction_policy="aggregate_only"
        if run.rights_privacy_public_mode.privacy_state == "aggregate_only"
        else "none",
        fallback_action=mapping.fallback_action,
        dry_run_reason=None,
    )


def _claim_live(run: ContentProgrammeRunEnvelope, boundary: ProgrammeBoundaryEvent) -> bool:
    mapping = boundary.public_event_mapping
    return (
        run.public_private_mode in {"public_live", "public_monetizable"}
        and boundary.no_expert_system_gate.public_claim_allowed
        and (
            "youtube_cuepoints" in mapping.allowed_surfaces
            or "youtube_description" in mapping.allowed_surfaces
            or "omg_statuslog" in mapping.allowed_surfaces
        )
    )


def _claim_archive(run: ContentProgrammeRunEnvelope, boundary: ProgrammeBoundaryEvent) -> bool:
    return run.public_private_mode in _PUBLIC_MODES and (
        bool(run.archive_refs)
        or boundary.cuepoint_chapter_policy.vod_chapter_allowed
        or "archive" in boundary.public_event_mapping.allowed_surfaces
    )


def _claim_monetizable(
    run: ContentProgrammeRunEnvelope,
    allowed_surfaces: tuple[Surface, ...],
) -> bool:
    return (
        run.public_private_mode == "public_monetizable"
        and run.rights_privacy_public_mode.monetization_state == "ready"
        and "monetization" in allowed_surfaces
    )


def _requires_audio_safe(allowed_surfaces: tuple[Surface, ...]) -> bool:
    return bool({"youtube_cuepoints", "youtube_shorts", "monetization"} & set(allowed_surfaces))


def _chapter_ref(
    boundary: ProgrammeBoundaryEvent,
    event_id: str,
) -> PublicEventChapterRef | None:
    policy = boundary.cuepoint_chapter_policy
    if not policy.chapter_label or not policy.timecode:
        return None
    if boundary.boundary_type == "live_cuepoint.candidate":
        kind = "cuepoint"
    elif boundary.boundary_type == "chapter.boundary":
        kind = "chapter"
    elif policy.vod_chapter_allowed:
        kind = "programme_boundary"
    else:
        return None
    return PublicEventChapterRef(
        kind=kind,
        label=policy.chapter_label,
        timecode=policy.timecode,
        source_event_id=event_id,
    )


def _is_public_safe_refusal_or_correction(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> bool:
    status = _boundary_status(boundary)
    if status == "standard":
        return False
    expected_claim_kind = "refusal" if status == "refusal" else "correction"
    return (
        run.public_private_mode in _PUBLIC_MODES
        and run.rights_privacy_public_mode.rights_state in _PUBLIC_SAFE_RIGHTS
        and run.rights_privacy_public_mode.privacy_state in _PUBLIC_SAFE_PRIVACY
        and boundary.claim_shape.claim_kind == expected_claim_kind
        and not boundary.public_event_mapping.internal_only
        and boundary.public_event_mapping.research_vehicle_event_type
        in {"publication.artifact", "metadata.update", "programme.boundary"}
    )


def _combined_evidence_refs(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> tuple[str, ...]:
    return _dedupe(
        (
            f"ContentProgrammeRun:{run.run_id}",
            f"ContentProgrammeRun.opportunity_decision_id:{run.opportunity_decision_id}",
            f"ProgrammeBoundaryEvent:{boundary.boundary_id}",
            f"ProgrammeBoundaryEvent.duplicate_key:{boundary.duplicate_key}",
            f"ProgrammeBoundaryEvent.grounding_question:{boundary.grounding_question}",
            f"ClaimShape.scope_limit:{boundary.claim_shape.scope_limit}",
            f"ClaimShape.confidence:{boundary.claim_shape.confidence_label}",
            f"ClaimShape.uncertainty:{boundary.claim_shape.uncertainty}",
            *boundary.evidence_refs,
            *_combined_claim_evidence_refs(run),
            *run.wcs.evidence_envelope_refs,
            *run.wcs.semantic_substrate_refs,
            *run.wcs.capability_outcome_refs,
            *(
                f"witness:{outcome.outcome_id}:{outcome.witness_state}"
                for outcome in run.witnessed_outcomes
            ),
            *(f"refusal:{refusal.state_id}" for refusal in run.refusals),
            *(f"correction:{correction.state_id}" for correction in run.corrections),
        )
    )


def _combined_claim_evidence_refs(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    refs: list[str] = []
    for claim in run.claims:
        refs.extend(claim.evidence_refs)
        refs.extend(claim.evidence_envelope_refs)
    return _dedupe(refs)


def _has_verified_witness(run: ContentProgrammeRunEnvelope) -> bool:
    return any(
        outcome.witness_state == "witness_verified" and outcome.evidence_envelope_refs
        for outcome in run.witnessed_outcomes
    )


def _boundary_status(boundary: ProgrammeBoundaryEvent) -> BoundaryStatus:
    if boundary.boundary_type == "refusal.issued":
        return "refusal"
    if boundary.boundary_type == "correction.made":
        return "correction"
    return "standard"


def _salience(boundary: ProgrammeBoundaryEvent) -> float:
    confidence_salience = {
        "none": 0.25,
        "low": 0.4,
        "medium": 0.6,
        "medium_high": 0.74,
        "high": 0.86,
    }[boundary.claim_shape.confidence_label]
    if _boundary_status(boundary) in {"refusal", "correction"}:
        return max(confidence_salience, 0.68)
    return confidence_salience


def _rights_class(state: RightsState) -> RightsClass:
    return {
        "operator_original": "operator_original",
        "cleared": "operator_controlled",
        "platform_embed_only": "platform_embedded",
        "blocked": "third_party_uncleared",
        "unknown": "unknown",
    }[state]


def _privacy_class(state: PrivacyState) -> PrivacyClass:
    return {
        "operator_private": "operator_private",
        "public_safe": "public_safe",
        "aggregate_only": "aggregate_only",
        "blocked": "consent_required",
        "unknown": "unknown",
    }[state]


def _rights_basis(state: RightsState) -> str:
    return {
        "operator_original": "operator generated content programme evidence",
        "cleared": "cleared content programme evidence",
        "platform_embed_only": "platform embedded content programme evidence",
        "blocked": "blocked rights posture",
        "unknown": "unknown rights posture",
    }[state]


def _public_url(run: ContentProgrammeRunEnvelope) -> str | None:
    for ref in (*run.archive_refs, *run.broadcast_refs):
        if ref.startswith(("http://", "https://")):
            return ref
    return None


def _citation_refs(refs: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        ref for ref in refs if ref.startswith(("citation:", "license:", "attribution:", "source:"))
    )


def _first_ref(refs: tuple[str, ...]) -> str | None:
    return refs[0] if refs else None


def _normalise_timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dedupe[T: Hashable](values: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(values))


def _sanitize_id(raw: str) -> str:
    lowered = raw.lower().replace("+00:00", "z")
    cleaned = re.sub(r"[^a-z0-9_:-]+", "_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_:")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"rvpe:{cleaned}"
    return cleaned


__all__ = [
    "AdaptationStatus",
    "AuthorityCeiling",
    "BoundaryClaimShape",
    "BoundaryCuepointChapterPolicy",
    "BoundaryNoExpertSystemGate",
    "BoundaryPublicEventMapping",
    "BoundaryStatus",
    "BoundaryType",
    "ClaimKind",
    "ConfidenceLabel",
    "FormatPublicEventDecision",
    "GateState",
    "ProgrammeBoundaryEvent",
    "adapt_format_boundary_to_public_event",
    "format_public_event_id",
]
