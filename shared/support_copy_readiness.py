"""Support-copy readiness gate.

This contract sits between the support-surface registry, monetization readiness
ledger, and public copy renderers. It emits one machine-readable readiness state
for every public support/copy consumer and fails closed until registry,
monetization, public-event, aggregate-receipt, and no-perk evidence all line up.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.conversion_target_readiness import GateDimension, TargetFamilyId
from shared.monetization_readiness_ledger import MonetizationReadinessLedger
from shared.support_surface_registry import SupportSurfaceRegistry, public_prompt_allowed

type SupportCopyReadinessState = Literal[
    "unavailable",
    "bootstrap-needed",
    "registry-ready",
    "monetization-held",
    "public-safe",
    "refused",
]
type SupportCopyConsumer = Literal[
    "public_offer_page",
    "youtube_copy",
    "cross_surface_legibility_pack",
    "public_package_surface",
    "github_readme",
]

DEFAULT_SUPPORT_COPY_SURFACE_ID: Final[str] = "sponsor_support_copy"
DEFAULT_TARGET_FAMILY_ID: Final[TargetFamilyId] = "support_prompt"
SUPPORT_COPY_CONSUMERS: Final[tuple[SupportCopyConsumer, ...]] = (
    "public_offer_page",
    "youtube_copy",
    "cross_surface_legibility_pack",
    "public_package_surface",
    "github_readme",
)

PUBLIC_TRUTH_DIMENSIONS: Final[frozenset[GateDimension]] = frozenset(
    {
        "wcs",
        "programme",
        "public_event",
        "archive",
        "rights",
        "privacy",
        "provenance",
        "egress",
        "no_hidden_operator_labor",
    }
)

PROHIBITED_SUPPORT_COPY_SHAPES: Final[tuple[str, ...]] = (
    "payer_identity",
    "supporter_identity",
    "leaderboard",
    "supporter_list",
    "shoutout",
    "request_queue",
    "private_access",
    "priority",
    "guarantee",
    "subscriber_language",
    "subscriber_perk",
    "client_service",
    "customer_service",
    "licensing_negotiation",
    "issue_invitation",
)


class SupportCopyModel(BaseModel):
    """Frozen Pydantic base for gate models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SupportCopyConsumerReadiness(SupportCopyModel):
    """Readiness projection for one downstream public-copy consumer."""

    consumer: SupportCopyConsumer
    readiness_state: SupportCopyReadinessState
    public_copy_allowed: bool
    support_invitation_allowed: bool
    issue_invitation_allowed: bool = False
    licensing_negotiation_allowed: bool = False
    customer_service_expectation_allowed: bool = False
    reason_codes: tuple[str, ...] = Field(default=())

    @model_validator(mode="after")
    def validate_consumer_policy(self) -> SupportCopyConsumerReadiness:
        if self.readiness_state != "public-safe":
            forbidden = {
                "public_copy_allowed": self.public_copy_allowed,
                "support_invitation_allowed": self.support_invitation_allowed,
                "issue_invitation_allowed": self.issue_invitation_allowed,
                "licensing_negotiation_allowed": self.licensing_negotiation_allowed,
                "customer_service_expectation_allowed": (self.customer_service_expectation_allowed),
            }
            active = sorted(name for name, value in forbidden.items() if value)
            if active:
                msg = f"{self.consumer} allows public support copy before public-safe: {active!r}"
                raise ValueError(msg)

        if self.issue_invitation_allowed:
            raise ValueError("support-copy readiness never authorizes issue invitations")
        if self.licensing_negotiation_allowed:
            raise ValueError("support-copy readiness never authorizes licensing negotiation")
        if self.customer_service_expectation_allowed:
            raise ValueError("support-copy readiness never authorizes customer-service promises")
        return self


class SupportCopyReadinessDecision(SupportCopyModel):
    """Full support-copy readiness decision for all public support surfaces."""

    state: SupportCopyReadinessState
    target_family_id: TargetFamilyId
    surface_id: str
    public_copy_allowed: bool
    allowed_public_copy: tuple[str, ...] = Field(default=())
    no_perk_doctrine_summary: str = ""
    refusal_explanation: str | None = None
    refusal_brief_refs: tuple[str, ...] = Field(default=())
    buildable_conversion: str | None = None
    blockers: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())
    missing_gate_dimensions: tuple[GateDimension, ...] = Field(default=())
    missing_readiness_refs: tuple[str, ...] = Field(default=())
    prohibited_copy_shapes: tuple[str, ...] = PROHIBITED_SUPPORT_COPY_SHAPES
    aggregate_receipts_public_only: bool
    per_receipt_public_state_allowed: bool
    consumer_states: tuple[SupportCopyConsumerReadiness, ...]

    @model_validator(mode="after")
    def validate_decision(self) -> SupportCopyReadinessDecision:
        if self.public_copy_allowed != (self.state == "public-safe"):
            raise ValueError("public_copy_allowed must match public-safe state")
        if self.state == "public-safe":
            if self.blockers or self.missing_gate_dimensions or self.missing_readiness_refs:
                raise ValueError("public-safe decision cannot carry missing evidence")
            if not self.allowed_public_copy:
                raise ValueError("public-safe decision must carry allowed public copy")
        else:
            if self.allowed_public_copy:
                raise ValueError("non-public-safe decision cannot emit public support copy")
        return self

    def consumer_state(self, consumer: SupportCopyConsumer) -> SupportCopyConsumerReadiness:
        """Return one consumer projection, or raise if absent."""

        for state in self.consumer_states:
            if state.consumer == consumer:
                return state
        msg = f"no support-copy readiness for consumer {consumer!r}"
        raise KeyError(msg)


def support_copy_doctrine_summary(registry: SupportSurfaceRegistry) -> str:
    """Return the canonical no-perk support-copy summary."""

    return " ".join(registry.no_perk_support_doctrine.allowed_copy_clauses)


def evaluate_support_copy_readiness(
    registry: SupportSurfaceRegistry | None,
    ledger: MonetizationReadinessLedger | None,
    *,
    readiness_refs: Mapping[str, bool] | None = None,
    surface_id: str = DEFAULT_SUPPORT_COPY_SURFACE_ID,
    target_family_id: TargetFamilyId = DEFAULT_TARGET_FAMILY_ID,
) -> SupportCopyReadinessDecision:
    """Evaluate whether public support prompts/copy may render.

    ``readiness_refs`` are the support-surface registry's named readiness gates,
    such as ``support_surface_registry.no_perk_copy_valid`` or
    ``MonetizationReadiness.safe_to_publish_offer``. Missing refs fail closed.
    """

    refs = dict(readiness_refs or {})
    if registry is None:
        return _decision(
            state="unavailable",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=("support_surface_registry_missing",),
        )

    aggregate_policy = registry.aggregate_receipt_policy
    if not aggregate_policy.public_state_aggregate_only:
        return _decision(
            state="unavailable",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=("aggregate_receipt_policy_not_public_only",),
            registry=registry,
        )
    if aggregate_policy.per_receipt_public_state_allowed:
        return _decision(
            state="unavailable",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=("per_receipt_public_state_allowed",),
            registry=registry,
        )

    surfaces = registry.by_id()
    surface = surfaces.get(surface_id)
    if surface is None:
        return _decision(
            state="unavailable",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=(f"support_surface_missing:{surface_id}",),
            registry=registry,
        )

    if surface.decision == "refusal_conversion":
        return _decision(
            state="refused",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=("support_surface_refused",),
            refusal_explanation=surface.notes,
            refusal_brief_refs=surface.refusal_brief_refs,
            buildable_conversion=surface.buildable_conversion,
            registry=registry,
        )

    missing_surface_refs = tuple(gate for gate in surface.readiness_gates if not refs.get(gate))
    bootstrap_refs = tuple(
        gate for gate in missing_surface_refs if not gate.startswith("MonetizationReadiness.")
    )
    if bootstrap_refs:
        return _decision(
            state="bootstrap-needed",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=tuple(f"readiness_ref_missing:{gate}" for gate in bootstrap_refs),
            missing_readiness_refs=bootstrap_refs,
            registry=registry,
        )

    entry = None
    if ledger is not None:
        for candidate in ledger.entries:
            if candidate.target_family_id == target_family_id:
                entry = candidate
                break
    if entry is None:
        return _decision(
            state="monetization-held",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=("monetization_readiness_missing",),
            missing_readiness_refs=missing_surface_refs,
            registry=registry,
        )

    satisfied = frozenset(entry.satisfied_dimensions)
    missing_public_truth = tuple(sorted(PUBLIC_TRUTH_DIMENSIONS - satisfied))
    missing_monetization = "monetization" not in satisfied
    monetization_refs = tuple(
        gate for gate in missing_surface_refs if gate.startswith("MonetizationReadiness.")
    )
    if missing_public_truth:
        return _decision(
            state="registry-ready",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=tuple(f"public_truth_missing:{dim}" for dim in missing_public_truth),
            evidence_refs=entry.evidence_refs,
            missing_gate_dimensions=missing_public_truth,
            missing_readiness_refs=monetization_refs,
            registry=registry,
        )

    if missing_monetization or monetization_refs:
        blockers = []
        if missing_monetization:
            blockers.append("monetization_readiness_missing")
        blockers.extend(f"readiness_ref_missing:{gate}" for gate in monetization_refs)
        return _decision(
            state="monetization-held",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=tuple(blockers),
            evidence_refs=entry.evidence_refs,
            missing_gate_dimensions=("monetization",) if missing_monetization else (),
            missing_readiness_refs=monetization_refs,
            registry=registry,
        )

    if not entry.decision.allowed or entry.decision.effective_state != "public-monetizable":
        return _decision(
            state="monetization-held",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=(entry.decision.operator_visible_reason,),
            evidence_refs=entry.evidence_refs,
            missing_gate_dimensions=entry.decision.missing_gate_dimensions,
            registry=registry,
        )

    if not public_prompt_allowed(registry, surface_id, refs):
        return _decision(
            state="bootstrap-needed",
            target_family_id=target_family_id,
            surface_id=surface_id,
            blockers=("support_surface_public_prompt_gate_failed",),
            missing_readiness_refs=missing_surface_refs,
            registry=registry,
        )

    evidence_refs = tuple(dict.fromkeys((*registry.source_refs, *entry.evidence_refs)))
    return _decision(
        state="public-safe",
        target_family_id=target_family_id,
        surface_id=surface_id,
        allowed_public_copy=surface.allowed_public_copy,
        evidence_refs=evidence_refs,
        registry=registry,
    )


def _decision(
    *,
    state: SupportCopyReadinessState,
    target_family_id: TargetFamilyId,
    surface_id: str,
    blockers: tuple[str, ...] = (),
    allowed_public_copy: tuple[str, ...] = (),
    refusal_explanation: str | None = None,
    refusal_brief_refs: tuple[str, ...] = (),
    buildable_conversion: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    missing_gate_dimensions: tuple[GateDimension, ...] = (),
    missing_readiness_refs: tuple[str, ...] = (),
    registry: SupportSurfaceRegistry | None = None,
) -> SupportCopyReadinessDecision:
    public_safe = state == "public-safe"
    reason_codes = blockers or (state,)
    return SupportCopyReadinessDecision(
        state=state,
        target_family_id=target_family_id,
        surface_id=surface_id,
        public_copy_allowed=public_safe,
        allowed_public_copy=allowed_public_copy if public_safe else (),
        no_perk_doctrine_summary=(
            support_copy_doctrine_summary(registry) if registry is not None else ""
        ),
        refusal_explanation=refusal_explanation,
        refusal_brief_refs=refusal_brief_refs,
        buildable_conversion=buildable_conversion,
        blockers=blockers,
        evidence_refs=evidence_refs,
        missing_gate_dimensions=missing_gate_dimensions,
        missing_readiness_refs=missing_readiness_refs,
        aggregate_receipts_public_only=(
            registry.aggregate_receipt_policy.public_state_aggregate_only
            if registry is not None
            else False
        ),
        per_receipt_public_state_allowed=(
            registry.aggregate_receipt_policy.per_receipt_public_state_allowed
            if registry is not None
            else False
        ),
        consumer_states=tuple(
            _consumer_state(consumer, state=state, reason_codes=reason_codes)
            for consumer in SUPPORT_COPY_CONSUMERS
        ),
    )


def _consumer_state(
    consumer: SupportCopyConsumer,
    *,
    state: SupportCopyReadinessState,
    reason_codes: tuple[str, ...],
) -> SupportCopyConsumerReadiness:
    public_safe = state == "public-safe"
    return SupportCopyConsumerReadiness(
        consumer=consumer,
        readiness_state=state,
        public_copy_allowed=public_safe,
        support_invitation_allowed=public_safe,
        issue_invitation_allowed=False,
        licensing_negotiation_allowed=False,
        customer_service_expectation_allowed=False,
        reason_codes=reason_codes,
    )
