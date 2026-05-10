"""Fail-closed public-mode refusal harness for the content runner.

The content runner is still intentionally blocked behind WCS/readiness work.
This module gives tests and later runner wiring one deterministic predicate for
public-live and monetizable refusal behavior without activating public mode.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.content_programme_run_store import PrivacyState, PublicPrivateMode, RightsState

type ConsentPrivacyState = Literal["granted", "aggregate_only", "blocked", "unknown"]
type WcsWitnessState = Literal["verified", "missing", "stale", "unknown"]
type SourceFreshnessState = Literal["fresh", "stale", "unknown"]
type AudioEgressState = Literal["ready", "blocked", "private_only", "unknown"]
type PublicEventState = Literal["linked", "ready", "held", "missing", "unknown"]
type MonetizationEvidenceState = Literal["ready", "blocked", "not_requested", "unknown"]
type ClaimAuthorityCeiling = Literal["evidence_bound", "internal_only", "speculative", "expert"]
type RefusalArtifactKind = Literal["refusal", "correction"]
type RefusalDecisionStatus = Literal["allowed", "dry_run", "private", "refused"]
type BlockedReasonSeverity = Literal["block", "hold"]
type BlockedReasonCode = Literal[
    "missing_runner_mode_config",
    "default_public_mode_ignored",
    "public_mode_requires_explicit_request",
    "missing_grounding_question",
    "missing_claim_shape",
    "unsupported_public_claim",
    "missing_wcs_witness",
    "stale_source",
    "rights_hold",
    "consent_privacy_hold",
    "audio_egress_unknown",
    "public_event_hold",
    "monetization_hold",
]

PUBLIC_MODES: frozenset[PublicPrivateMode] = frozenset(
    {"public_live", "public_archive", "public_monetizable"}
)
PUBLIC_SAFE_RIGHTS: frozenset[RightsState] = frozenset(
    {"operator_original", "cleared", "platform_embed_only"}
)
PUBLIC_SAFE_PRIVACY: frozenset[PrivacyState] = frozenset({"public_safe", "aggregate_only"})
PUBLIC_SAFE_CONSENT: frozenset[ConsentPrivacyState] = frozenset({"granted", "aggregate_only"})
PUBLIC_READY_EVENT_STATES: frozenset[PublicEventState] = frozenset({"linked", "ready"})
PUBLIC_ARTIFACT_HARD_HOLDS: frozenset[BlockedReasonCode] = frozenset(
    {"rights_hold", "consent_privacy_hold"}
)


class RunnerPublicModeRefusalModel(BaseModel):
    """Strict immutable base for public-mode refusal harness records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RunnerPublicModeEvidence(RunnerPublicModeRefusalModel):
    """Evidence snapshot consumed before a content run may become public."""

    requested_mode: PublicPrivateMode | None = None
    configured_default_mode: PublicPrivateMode | None = None
    explicit_public_mode_request: bool = False
    grounding_question_present: bool = True
    claim_shape_declared: bool = True
    claim_authority_ceiling: ClaimAuthorityCeiling = "evidence_bound"
    unsupported_public_claim: bool = False
    wcs_witness_state: WcsWitnessState = "unknown"
    source_freshness_state: SourceFreshnessState = "unknown"
    rights_state: RightsState = "unknown"
    privacy_state: PrivacyState = "unknown"
    consent_state: ConsentPrivacyState = "unknown"
    audio_egress_state: AudioEgressState = "unknown"
    public_event_state: PublicEventState = "unknown"
    monetization_state: MonetizationEvidenceState = "not_requested"
    refusal_artifact_kind: RefusalArtifactKind = "refusal"
    refusal_artifact_public_safe: bool = True
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class RunnerBlockedReason(RunnerPublicModeRefusalModel):
    """One machine-readable blocked reason plus operator-facing text."""

    code: BlockedReasonCode
    severity: BlockedReasonSeverity = "block"
    dimension: str
    operator_message: str
    blocks_modes: tuple[PublicPrivateMode, ...]
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class RunnerRefusalArtifact(RunnerPublicModeRefusalModel):
    """Public-safe refusal/correction candidate emitted from a refused run."""

    artifact_type: Literal["refusal_artifact", "correction_artifact"]
    public_private_mode: Literal["public_archive"] = "public_archive"
    operator_summary: str
    machine_readable_blocked_reasons: tuple[BlockedReasonCode, ...]
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    validates_refused_claim: Literal[False] = False
    grants_public_run_authority: Literal[False] = False
    grants_monetization_authority: Literal[False] = False


class RunnerPublicModeDecision(RunnerPublicModeRefusalModel):
    """Fail-closed public-mode decision returned to runner tests/adapters."""

    schema_version: Literal[1] = 1
    requested_mode: PublicPrivateMode | None
    configured_default_mode: PublicPrivateMode | None
    effective_mode: PublicPrivateMode
    final_status: RefusalDecisionStatus
    public_live_allowed: bool
    public_archive_allowed: bool
    public_monetizable_allowed: bool
    public_claim_allowed: bool
    blocked_reasons: tuple[RunnerBlockedReason, ...] = Field(default_factory=tuple)
    operator_readable_blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    machine_readable_blocked_reasons: tuple[BlockedReasonCode, ...] = Field(default_factory=tuple)
    refusal_artifact: RunnerRefusalArtifact | None = None
    dry_run_cannot_be_promoted_by_default: Literal[True] = True
    no_expert_system_enforced: Literal[True] = True
    unsupported_public_claim_can_publish: Literal[False] = False


def evaluate_runner_public_mode_refusal(
    evidence: RunnerPublicModeEvidence,
) -> RunnerPublicModeDecision:
    """Decide whether the runner may enter a public mode, otherwise refuse safely."""

    intended_mode = _intended_mode(evidence)
    reasons = _blocked_reasons(evidence)
    public_intent = intended_mode in PUBLIC_MODES

    if not public_intent:
        effective_mode = intended_mode
        final_status: RefusalDecisionStatus = "private" if intended_mode == "private" else "dry_run"
        return _decision(
            evidence=evidence,
            effective_mode=effective_mode,
            final_status=final_status,
            reasons=reasons,
            refusal_artifact=None,
        )

    if reasons:
        effective_mode = "dry_run"
        final_status = "refused"
        artifact = _refusal_artifact(evidence, reasons)
        return _decision(
            evidence=evidence,
            effective_mode=effective_mode,
            final_status=final_status,
            reasons=reasons,
            refusal_artifact=artifact,
        )

    return _decision(
        evidence=evidence,
        effective_mode=intended_mode,
        final_status="allowed",
        reasons=(),
        refusal_artifact=None,
    )


def _intended_mode(evidence: RunnerPublicModeEvidence) -> PublicPrivateMode:
    if evidence.requested_mode is not None:
        return evidence.requested_mode
    if evidence.configured_default_mode in {"private", "dry_run"}:
        return evidence.configured_default_mode
    return "dry_run"


def _blocked_reasons(evidence: RunnerPublicModeEvidence) -> tuple[RunnerBlockedReason, ...]:
    reasons: list[RunnerBlockedReason] = []
    intended_mode = _intended_mode(evidence)
    public_intent = intended_mode in PUBLIC_MODES

    if evidence.requested_mode is None:
        reasons.append(
            _reason(
                "missing_runner_mode_config",
                evidence,
                detail="No explicit runner mode was supplied; the harness keeps the run dry.",
            )
        )

    if (
        evidence.configured_default_mode in PUBLIC_MODES
        and evidence.requested_mode not in PUBLIC_MODES
    ):
        reasons.append(
            _reason(
                "default_public_mode_ignored",
                evidence,
                detail=(
                    f"Configured default {evidence.configured_default_mode!r} is ignored "
                    "because public mode requires an explicit request."
                ),
            )
        )

    if not public_intent:
        return _dedupe_reasons(reasons)

    if not evidence.explicit_public_mode_request:
        reasons.append(
            _reason(
                "public_mode_requires_explicit_request",
                evidence,
                detail="Public mode was selected without an explicit public-mode request.",
            )
        )
    if not evidence.grounding_question_present:
        reasons.append(_reason("missing_grounding_question", evidence))
    if not evidence.claim_shape_declared:
        reasons.append(_reason("missing_claim_shape", evidence))
    if evidence.unsupported_public_claim or evidence.claim_authority_ceiling != "evidence_bound":
        reasons.append(_reason("unsupported_public_claim", evidence))
    if evidence.wcs_witness_state != "verified":
        reasons.append(_reason("missing_wcs_witness", evidence))
    if evidence.source_freshness_state != "fresh":
        reasons.append(_reason("stale_source", evidence))
    if evidence.rights_state not in PUBLIC_SAFE_RIGHTS:
        reasons.append(_reason("rights_hold", evidence))
    if (
        evidence.privacy_state not in PUBLIC_SAFE_PRIVACY
        or evidence.consent_state not in PUBLIC_SAFE_CONSENT
    ):
        reasons.append(_reason("consent_privacy_hold", evidence))
    if evidence.audio_egress_state != "ready":
        reasons.append(_reason("audio_egress_unknown", evidence))
    if evidence.public_event_state not in PUBLIC_READY_EVENT_STATES:
        reasons.append(_reason("public_event_hold", evidence))
    if intended_mode == "public_monetizable" and evidence.monetization_state != "ready":
        reasons.append(_reason("monetization_hold", evidence))

    return _dedupe_reasons(reasons)


def _decision(
    *,
    evidence: RunnerPublicModeEvidence,
    effective_mode: PublicPrivateMode,
    final_status: RefusalDecisionStatus,
    reasons: Iterable[RunnerBlockedReason],
    refusal_artifact: RunnerRefusalArtifact | None,
) -> RunnerPublicModeDecision:
    reason_tuple = tuple(reasons)
    blocked_codes = tuple(reason.code for reason in reason_tuple)
    public_allowed = final_status == "allowed" and effective_mode in PUBLIC_MODES
    return RunnerPublicModeDecision(
        requested_mode=evidence.requested_mode,
        configured_default_mode=evidence.configured_default_mode,
        effective_mode=effective_mode,
        final_status=final_status,
        public_live_allowed=public_allowed and effective_mode == "public_live",
        public_archive_allowed=public_allowed and effective_mode in PUBLIC_MODES,
        public_monetizable_allowed=public_allowed and effective_mode == "public_monetizable",
        public_claim_allowed=public_allowed,
        blocked_reasons=reason_tuple,
        operator_readable_blocked_reasons=tuple(reason.operator_message for reason in reason_tuple),
        machine_readable_blocked_reasons=blocked_codes,
        refusal_artifact=refusal_artifact,
    )


def _refusal_artifact(
    evidence: RunnerPublicModeEvidence,
    reasons: tuple[RunnerBlockedReason, ...],
) -> RunnerRefusalArtifact | None:
    codes = tuple(reason.code for reason in reasons)
    if not evidence.refusal_artifact_public_safe:
        return None
    if PUBLIC_ARTIFACT_HARD_HOLDS.intersection(codes):
        return None
    artifact_type: Literal["refusal_artifact", "correction_artifact"] = (
        "correction_artifact"
        if evidence.refusal_artifact_kind == "correction"
        else "refusal_artifact"
    )
    return RunnerRefusalArtifact(
        artifact_type=artifact_type,
        operator_summary=("Public run refused; only the blocked-reason artifact is public-safe."),
        machine_readable_blocked_reasons=codes,
        evidence_refs=evidence.evidence_refs,
    )


def _dedupe_reasons(reasons: Iterable[RunnerBlockedReason]) -> tuple[RunnerBlockedReason, ...]:
    seen: set[BlockedReasonCode] = set()
    deduped: list[RunnerBlockedReason] = []
    for reason in reasons:
        if reason.code in seen:
            continue
        seen.add(reason.code)
        deduped.append(reason)
    return tuple(deduped)


def _reason(
    code: BlockedReasonCode,
    evidence: RunnerPublicModeEvidence,
    *,
    detail: str | None = None,
) -> RunnerBlockedReason:
    dimension, message, modes = _REASON_TEXT[code]
    return RunnerBlockedReason(
        code=code,
        dimension=dimension,
        operator_message=detail or message,
        blocks_modes=modes,
        evidence_refs=evidence.evidence_refs,
    )


_ALL_PUBLIC_MODES: tuple[PublicPrivateMode, ...] = (
    "public_live",
    "public_archive",
    "public_monetizable",
)
_PUBLIC_LIVE_AND_MONEY: tuple[PublicPrivateMode, ...] = (
    "public_live",
    "public_monetizable",
)
_PUBLIC_MONEY: tuple[PublicPrivateMode, ...] = ("public_monetizable",)

_REASON_TEXT: dict[
    BlockedReasonCode,
    tuple[str, str, tuple[PublicPrivateMode, ...]],
] = {
    "missing_runner_mode_config": (
        "mode_config",
        "No explicit runner mode was supplied; defaulting to dry-run.",
        _ALL_PUBLIC_MODES,
    ),
    "default_public_mode_ignored": (
        "mode_config",
        "A public default cannot promote a private or dry-run request.",
        _ALL_PUBLIC_MODES,
    ),
    "public_mode_requires_explicit_request": (
        "mode_config",
        "Public mode requires an explicit public-mode request.",
        _ALL_PUBLIC_MODES,
    ),
    "missing_grounding_question": (
        "grounding",
        "Public runs require a grounding question before any claim can emit.",
        _ALL_PUBLIC_MODES,
    ),
    "missing_claim_shape": (
        "claim_shape",
        "Public runs require a permitted claim shape.",
        _ALL_PUBLIC_MODES,
    ),
    "unsupported_public_claim": (
        "claim_shape",
        "Unsupported or expert-style claims cannot publish.",
        _ALL_PUBLIC_MODES,
    ),
    "missing_wcs_witness": (
        "wcs",
        "Missing or non-verified WCS witness blocks public mode.",
        _ALL_PUBLIC_MODES,
    ),
    "stale_source": (
        "source_freshness",
        "Stale or unknown source freshness blocks public mode.",
        _ALL_PUBLIC_MODES,
    ),
    "rights_hold": (
        "rights",
        "Rights are not cleared for public output.",
        _ALL_PUBLIC_MODES,
    ),
    "consent_privacy_hold": (
        "privacy_consent",
        "Consent or privacy posture is not public-safe.",
        _ALL_PUBLIC_MODES,
    ),
    "audio_egress_unknown": (
        "audio_egress",
        "Audio or egress state is unknown, blocked, or private-only.",
        _PUBLIC_LIVE_AND_MONEY,
    ),
    "public_event_hold": (
        "public_event",
        "Public-event readiness is missing or held.",
        _ALL_PUBLIC_MODES,
    ),
    "monetization_hold": (
        "monetization",
        "Monetization readiness evidence is missing or blocked.",
        _PUBLIC_MONEY,
    ),
}


__all__ = [
    "AudioEgressState",
    "BlockedReasonCode",
    "ConsentPrivacyState",
    "MonetizationEvidenceState",
    "PUBLIC_MODES",
    "PublicEventState",
    "RunnerBlockedReason",
    "RunnerPublicModeDecision",
    "RunnerPublicModeEvidence",
    "RunnerRefusalArtifact",
    "SourceFreshnessState",
    "WcsWitnessState",
    "evaluate_runner_public_mode_refusal",
]
