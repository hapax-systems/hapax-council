"""RDLC disposition adapter for continuously emitted SDLC observations.

The adapter is deliberately pure: it classifies candidate observations and can
construct a draft ``PreprintArtifact`` for a publishable claim, but it never
writes to the publish inbox and never invokes a publisher or provider.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.preprint_artifact import ApprovalState, PreprintArtifact


class RdlcDispositionError(ValueError):
    """Raised when a disposition would bypass an RDLC gate."""


class RdlcDispositionKind(StrEnum):
    """Disposition outcomes before the publication bus becomes relevant."""

    SUPPORT_NON_AUTHORITATIVE = "support_non_authoritative"
    PUBLISH_CANDIDATE = "publish_candidate"
    BLOCKED = "blocked"
    CONVERT_TO_TASK = "convert_to_task"


class RdlcRiskLevel(StrEnum):
    """Small shared risk vocabulary for candidate observation triage."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class _FrozenRdlcModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _non_empty(value: str | None) -> bool:
    return bool(value and value.strip())


def _missing_tuple(value: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    return () if value else (field_name,)


class RdlcExperimentalObservation(_FrozenRdlcModel):
    """Candidate experimental context emitted by SDLC-adjacent systems."""

    schema_version: Literal[1] = 1
    observation_id: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    authority_case: str | None = None
    parent_spec: str | None = None
    observation_kind: str = Field(min_length=1)
    intervention: str | None = None
    outcome: str | None = None
    claim_ceiling: str | None = None
    privacy_risk: RdlcRiskLevel = RdlcRiskLevel.MODERATE
    air_risk: RdlcRiskLevel = RdlcRiskLevel.MODERATE
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    def missing_custody_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        missing.extend(_missing_tuple(self.source_refs, "source_refs"))
        missing.extend(_missing_tuple(self.evidence_refs, "evidence_refs"))
        if not _non_empty(self.authority_case):
            missing.append("authority_case")
        if not _non_empty(self.parent_spec):
            missing.append("parent_spec")
        return tuple(missing)

    def has_custody(self) -> bool:
        return not self.missing_custody_fields()


class RdlcTaskConversion(_FrozenRdlcModel):
    """Structured detail carried when an observation should become a cc-task."""

    title: str = Field(min_length=1)
    mutation_scope_refs: tuple[str, ...] = Field(default_factory=tuple)
    acceptance_refs: tuple[str, ...] = Field(default_factory=tuple)
    rationale: str = Field(min_length=1)


class RdlcDispositionReceipt(_FrozenRdlcModel):
    """RDLC disposition receipt for one candidate SDLC observation."""

    schema_version: Literal[1] = 1
    receipt_id: str = Field(min_length=1)
    observation: RdlcExperimentalObservation
    disposition: RdlcDispositionKind
    rationale: str = Field(min_length=1)
    claim_text: str | None = None
    claim_ceiling: str | None = None
    frozen_ruler_ref: str | None = None
    frozen_ruler_version: str | None = None
    public_safe_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    freshness_ref: str | None = None
    currentness_ref: str | None = None
    task_conversion: RdlcTaskConversion | None = None
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        if self.disposition != RdlcDispositionKind.BLOCKED and not self.observation.has_custody():
            missing = ", ".join(self.observation.missing_custody_fields())
            raise RdlcDispositionError(f"non-blocked disposition requires custody: {missing}")

        if self.disposition == RdlcDispositionKind.PUBLISH_CANDIDATE:
            missing = self.missing_publish_fields()
            if missing:
                raise RdlcDispositionError(
                    "publish_candidate requires assay/freeze inputs: " + ", ".join(missing)
                )

        if self.disposition == RdlcDispositionKind.CONVERT_TO_TASK and self.task_conversion is None:
            raise RdlcDispositionError("convert_to_task requires task_conversion detail")

    def missing_publish_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not _non_empty(self.claim_text):
            missing.append("claim_text")
        if not _non_empty(self.claim_ceiling):
            missing.append("claim_ceiling")
        if not _non_empty(self.frozen_ruler_ref):
            missing.append("frozen_ruler_ref")
        if not _non_empty(self.frozen_ruler_version):
            missing.append("frozen_ruler_version")
        if not self.public_safe_evidence_refs:
            missing.append("public_safe_evidence_refs")
        if not _non_empty(self.freshness_ref):
            missing.append("freshness_ref")
        if not _non_empty(self.currentness_ref):
            missing.append("currentness_ref")
        return tuple(missing)


def build_disposition_receipt(
    observation: RdlcExperimentalObservation,
    *,
    disposition: RdlcDispositionKind | str,
    rationale: str,
    receipt_id: str | None = None,
    claim_text: str | None = None,
    claim_ceiling: str | None = None,
    frozen_ruler_ref: str | None = None,
    frozen_ruler_version: str | None = None,
    public_safe_evidence_refs: tuple[str, ...] = (),
    freshness_ref: str | None = None,
    currentness_ref: str | None = None,
    task_conversion: RdlcTaskConversion | None = None,
) -> RdlcDispositionReceipt:
    """Build a receipt, coercing missing-gate cases to ``blocked``.

    Direct ``RdlcDispositionReceipt`` construction remains strict; this helper is
    the adapter surface that turns absent custody/freeze into explicit blocked
    receipts instead of letting callers accidentally create publication artifacts.
    """

    kind = RdlcDispositionKind(disposition)
    effective_claim_ceiling = claim_ceiling or observation.claim_ceiling
    reasons: list[str] = []

    if kind != RdlcDispositionKind.BLOCKED:
        reasons.extend(f"missing_custody:{field}" for field in observation.missing_custody_fields())

    if kind == RdlcDispositionKind.PUBLISH_CANDIDATE:
        probe = RdlcDispositionReceipt.model_construct(
            schema_version=1,
            receipt_id=receipt_id or f"rdlc-disp:{observation.observation_id}",
            observation=observation,
            disposition=kind,
            rationale=rationale,
            claim_text=claim_text,
            claim_ceiling=effective_claim_ceiling,
            frozen_ruler_ref=frozen_ruler_ref,
            frozen_ruler_version=frozen_ruler_version,
            public_safe_evidence_refs=public_safe_evidence_refs,
            freshness_ref=freshness_ref,
            currentness_ref=currentness_ref,
            task_conversion=task_conversion,
            blocked_reasons=(),
        )
        reasons.extend(f"missing_publish:{field}" for field in probe.missing_publish_fields())

    if kind == RdlcDispositionKind.CONVERT_TO_TASK and task_conversion is None:
        reasons.append("missing_task_conversion")

    if reasons:
        return RdlcDispositionReceipt(
            receipt_id=receipt_id or f"rdlc-disp:{observation.observation_id}:blocked",
            observation=observation,
            disposition=RdlcDispositionKind.BLOCKED,
            rationale=rationale,
            claim_text=claim_text,
            claim_ceiling=effective_claim_ceiling,
            frozen_ruler_ref=frozen_ruler_ref,
            frozen_ruler_version=frozen_ruler_version,
            public_safe_evidence_refs=public_safe_evidence_refs,
            freshness_ref=freshness_ref,
            currentness_ref=currentness_ref,
            task_conversion=task_conversion,
            blocked_reasons=tuple(reasons),
        )

    return RdlcDispositionReceipt(
        receipt_id=receipt_id or f"rdlc-disp:{observation.observation_id}:{kind.value}",
        observation=observation,
        disposition=kind,
        rationale=rationale,
        claim_text=claim_text,
        claim_ceiling=effective_claim_ceiling,
        frozen_ruler_ref=frozen_ruler_ref,
        frozen_ruler_version=frozen_ruler_version,
        public_safe_evidence_refs=public_safe_evidence_refs,
        freshness_ref=freshness_ref,
        currentness_ref=currentness_ref,
        task_conversion=task_conversion,
    )


def build_preprint_draft_from_disposition(
    receipt: RdlcDispositionReceipt,
    *,
    slug: str,
    title: str,
    abstract: str = "",
    surfaces_targeted: tuple[str, ...] = (),
) -> PreprintArtifact:
    """Create a draft-only ``PreprintArtifact`` from a publish candidate."""

    if receipt.disposition != RdlcDispositionKind.PUBLISH_CANDIDATE:
        raise RdlcDispositionError(
            f"cannot create PreprintArtifact for disposition {receipt.disposition.value}"
        )

    body_md = "\n".join(
        [
            f"# {title}",
            "",
            f"Claim: {receipt.claim_text}",
            f"Claim ceiling: {receipt.claim_ceiling}",
            f"Observation: {receipt.observation.observation_id}",
            f"AuthorityCase: {receipt.observation.authority_case}",
            f"Parent spec: {receipt.observation.parent_spec}",
            f"Frozen ruler: {receipt.frozen_ruler_ref}@{receipt.frozen_ruler_version}",
            "Public-safe evidence refs:",
            *[f"- {ref}" for ref in receipt.public_safe_evidence_refs],
        ]
    )

    return PreprintArtifact(
        slug=slug,
        title=title,
        abstract=abstract,
        body_md=body_md,
        surfaces_targeted=list(surfaces_targeted),
        approval=ApprovalState.DRAFT,
        publication_gate_context={
            "rdlc_disposition": receipt.model_dump(mode="json"),
            "publication_bus_owner": "publish_orchestrator",
            "egress_state": "draft_only_no_inbox_write",
        },
    )


__all__ = [
    "RdlcDispositionError",
    "RdlcDispositionKind",
    "RdlcDispositionReceipt",
    "RdlcExperimentalObservation",
    "RdlcRiskLevel",
    "RdlcTaskConversion",
    "build_disposition_receipt",
    "build_preprint_draft_from_disposition",
]
