"""RDLC publication vehicle selector for publish-candidate receipts.

The selector is a pure planning layer between RDLC disposition and the publish
bus. It can recommend a publication vehicle and construct an in-memory draft
``PreprintArtifact``; it never writes to ``publish/inbox`` or authorizes public
egress.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.preprint_artifact import ApprovalState, PreprintArtifact
from shared.rdlc_experimental_disposition import (
    RdlcDispositionKind,
    RdlcDispositionReceipt,
    RdlcRiskLevel,
)


class RdlcPublicationVehicleError(ValueError):
    """Raised when selector output would bypass a publication gate."""


class RdlcPublicationAudienceFamily(StrEnum):
    """Reader families the selector can target."""

    RESEARCH_METHODS = "research_methods"
    SYSTEMS_ENGINEERING = "systems_engineering"
    GOVERNANCE_SAFETY = "governance_safety"
    DATASET_USERS = "dataset_users"
    ARTIFACT_INDEX = "artifact_index"
    PRODUCT_RESEARCH = "product_research"


class RdlcPublicationVehicle(StrEnum):
    """Supported RDLC publication vehicle classes."""

    METHOD_NOTE = "method_note"
    TECHNICAL_NOTE = "technical_note"
    GOVERNANCE_SAFETY_NOTE = "governance_safety_note"
    DATASET_CARD = "dataset_card"
    ARTIFACT_INDEX_ENTRY = "artifact_index_entry"
    PRODUCT_RESEARCH_UPDATE = "product_research_update"


class RdlcSurfaceRole(StrEnum):
    """Why a selected publication surface is present."""

    CANONICAL_HOME = "canonical_home"
    DOI_CITATION = "doi_citation"
    SOCIAL_SUMMARY = "social_summary"
    ARCHIVE = "archive"


class RdlcSurfaceBudgetProfile(StrEnum):
    """Small deterministic surface-budget vocabulary."""

    SCHOLARLY_COMPACT = "scholarly_compact"
    TECHNICAL_COMPACT = "technical_compact"
    SAFETY_RESTRAINED = "safety_restrained"
    DATASET_CITABLE = "dataset_citable"
    INDEX_ARCHIVAL = "index_archival"
    PRODUCT_BROAD = "product_broad"


class RdlcPublicationSelectorDecision(StrEnum):
    """Selector terminal decisions."""

    SELECTED = "selected"
    REFUSED = "refused"


class _FrozenSelectorModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _non_empty(value: str | None) -> bool:
    return bool(value and value.strip())


def _missing_tuple(value: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    return () if value and all(_non_empty(item) for item in value) else (field_name,)


class RdlcPublicationVehicleSelectorInput(_FrozenSelectorModel):
    """Immutable selector input extracted from an RDLC disposition receipt."""

    schema_version: Literal[1] = 1
    disposition_receipt_id: str = Field(min_length=1)
    disposition: RdlcDispositionKind
    claim_text: str | None = None
    claim_ceiling: str | None = None
    frozen_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_safe_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    audience_family: RdlcPublicationAudienceFamily
    risk_posture: RdlcRiskLevel
    freshness_ref: str | None = None
    currentness_ref: str | None = None

    @classmethod
    def from_disposition(
        cls,
        receipt: RdlcDispositionReceipt,
        *,
        audience_family: RdlcPublicationAudienceFamily | str,
        risk_posture: RdlcRiskLevel | str | None = None,
    ) -> RdlcPublicationVehicleSelectorInput:
        frozen_ruler_ref = _frozen_ruler_ref(receipt)
        frozen_refs = (frozen_ruler_ref,) if frozen_ruler_ref else ()
        return cls(
            disposition_receipt_id=receipt.receipt_id,
            disposition=receipt.disposition,
            claim_text=receipt.claim_text,
            claim_ceiling=receipt.claim_ceiling,
            frozen_evidence_refs=frozen_refs,
            public_safe_evidence_refs=receipt.public_safe_evidence_refs,
            audience_family=RdlcPublicationAudienceFamily(audience_family),
            risk_posture=RdlcRiskLevel(
                risk_posture
                or _highest_risk(receipt.observation.privacy_risk, receipt.observation.air_risk)
            ),
            freshness_ref=receipt.freshness_ref,
            currentness_ref=receipt.currentness_ref,
        )

    def missing_publication_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.disposition != RdlcDispositionKind.PUBLISH_CANDIDATE:
            missing.append(f"disposition:{self.disposition.value}")
        if not _non_empty(self.claim_text):
            missing.append("claim_text")
        if not _non_empty(self.claim_ceiling):
            missing.append("claim_ceiling")
        missing.extend(_missing_tuple(self.frozen_evidence_refs, "frozen_evidence_refs"))
        missing.extend(_missing_tuple(self.public_safe_evidence_refs, "public_safe_evidence_refs"))
        if not _non_empty(self.freshness_ref):
            missing.append("freshness_ref")
        if not _non_empty(self.currentness_ref):
            missing.append("currentness_ref")
        return tuple(missing)


class RdlcPublicationSurfaceSelection(_FrozenSelectorModel):
    """One selected surface plus its publication role."""

    role: RdlcSurfaceRole
    surface: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class RdlcPublicationVehicleSpec(_FrozenSelectorModel):
    """Static selector table row."""

    vehicle: RdlcPublicationVehicle
    budget_profile: RdlcSurfaceBudgetProfile
    allowed_audience_families: tuple[RdlcPublicationAudienceFamily, ...]
    surfaces: tuple[RdlcPublicationSurfaceSelection, ...]
    rationale: str


class RdlcPublicationVehicleSelectorReceipt(_FrozenSelectorModel):
    """Auditable selector receipt."""

    schema_version: Literal[1] = 1
    selector_receipt_id: str = Field(min_length=1)
    decision: RdlcPublicationSelectorDecision
    selector_input: RdlcPublicationVehicleSelectorInput
    recommended_vehicle: RdlcPublicationVehicle | None = None
    vehicle_rationale: str = Field(min_length=1)
    surface_budget_profile: RdlcSurfaceBudgetProfile | None = None
    selected_surfaces: tuple[RdlcPublicationSurfaceSelection, ...] = Field(default_factory=tuple)
    hardening_context: dict[str, object] = Field(default_factory=dict)
    public_abstract: str | None = None
    public_body_md: str | None = None
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)

    def selected_surface_slugs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(surface.surface for surface in self.selected_surfaces))


VEHICLE_SPECS: dict[RdlcPublicationVehicle, RdlcPublicationVehicleSpec] = {
    RdlcPublicationVehicle.METHOD_NOTE: RdlcPublicationVehicleSpec(
        vehicle=RdlcPublicationVehicle.METHOD_NOTE,
        budget_profile=RdlcSurfaceBudgetProfile.SCHOLARLY_COMPACT,
        allowed_audience_families=(
            RdlcPublicationAudienceFamily.RESEARCH_METHODS,
            RdlcPublicationAudienceFamily.SYSTEMS_ENGINEERING,
            RdlcPublicationAudienceFamily.GOVERNANCE_SAFETY,
        ),
        surfaces=(
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.CANONICAL_HOME,
                surface="omg-weblog",
                purpose="durable public home for the method note",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.DOI_CITATION,
                surface="osf-preprint",
                purpose="citable method-note record",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.SOCIAL_SUMMARY,
                surface="bluesky-post",
                purpose="short non-authoritative summary",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.ARCHIVE,
                surface="zenodo-doi",
                purpose="artifact archive and DOI-capable custody",
            ),
        ),
        rationale="method note preserves procedure, limits, and evidence custody",
    ),
    RdlcPublicationVehicle.TECHNICAL_NOTE: RdlcPublicationVehicleSpec(
        vehicle=RdlcPublicationVehicle.TECHNICAL_NOTE,
        budget_profile=RdlcSurfaceBudgetProfile.TECHNICAL_COMPACT,
        allowed_audience_families=(RdlcPublicationAudienceFamily.SYSTEMS_ENGINEERING,),
        surfaces=(
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.CANONICAL_HOME,
                surface="omg-weblog",
                purpose="canonical technical narrative",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.ARCHIVE,
                surface="zenodo-doi",
                purpose="durable technical artifact archive",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.SOCIAL_SUMMARY,
                surface="mastodon-post",
                purpose="short engineering-facing summary",
            ),
        ),
        rationale="technical note prioritizes implementation details and reproducible deltas",
    ),
    RdlcPublicationVehicle.GOVERNANCE_SAFETY_NOTE: RdlcPublicationVehicleSpec(
        vehicle=RdlcPublicationVehicle.GOVERNANCE_SAFETY_NOTE,
        budget_profile=RdlcSurfaceBudgetProfile.SAFETY_RESTRAINED,
        allowed_audience_families=(RdlcPublicationAudienceFamily.GOVERNANCE_SAFETY,),
        surfaces=(
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.CANONICAL_HOME,
                surface="omg-weblog",
                purpose="canonical restrained governance note",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.DOI_CITATION,
                surface="osf-preprint",
                purpose="reviewable safety/governance citation record",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.ARCHIVE,
                surface="zenodo-doi",
                purpose="durable governance evidence archive",
            ),
        ),
        rationale="governance safety note withholds broad social fanout for higher-risk claims",
    ),
    RdlcPublicationVehicle.DATASET_CARD: RdlcPublicationVehicleSpec(
        vehicle=RdlcPublicationVehicle.DATASET_CARD,
        budget_profile=RdlcSurfaceBudgetProfile.DATASET_CITABLE,
        allowed_audience_families=(RdlcPublicationAudienceFamily.DATASET_USERS,),
        surfaces=(
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.CANONICAL_HOME,
                surface="omg-weblog",
                purpose="human-readable dataset-card home",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.DOI_CITATION,
                surface="zenodo-doi",
                purpose="dataset citation and DOI",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.ARCHIVE,
                surface="zenodo-doi",
                purpose="dataset archive custody",
            ),
        ),
        rationale="dataset card foregrounds provenance, limits, and reuse conditions",
    ),
    RdlcPublicationVehicle.ARTIFACT_INDEX_ENTRY: RdlcPublicationVehicleSpec(
        vehicle=RdlcPublicationVehicle.ARTIFACT_INDEX_ENTRY,
        budget_profile=RdlcSurfaceBudgetProfile.INDEX_ARCHIVAL,
        allowed_audience_families=(RdlcPublicationAudienceFamily.ARTIFACT_INDEX,),
        surfaces=(
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.CANONICAL_HOME,
                surface="omg-weblog",
                purpose="canonical index entry",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.ARCHIVE,
                surface="zenodo-doi",
                purpose="archive pointer for indexed artifact",
            ),
        ),
        rationale="artifact index entry makes a durable pointer without over-reading the claim",
    ),
    RdlcPublicationVehicle.PRODUCT_RESEARCH_UPDATE: RdlcPublicationVehicleSpec(
        vehicle=RdlcPublicationVehicle.PRODUCT_RESEARCH_UPDATE,
        budget_profile=RdlcSurfaceBudgetProfile.PRODUCT_BROAD,
        allowed_audience_families=(RdlcPublicationAudienceFamily.PRODUCT_RESEARCH,),
        surfaces=(
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.CANONICAL_HOME,
                surface="omg-weblog",
                purpose="canonical product-research update",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.SOCIAL_SUMMARY,
                surface="bluesky-post",
                purpose="short product-research summary",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.SOCIAL_SUMMARY,
                surface="mastodon-post",
                purpose="short federated product-research summary",
            ),
            RdlcPublicationSurfaceSelection(
                role=RdlcSurfaceRole.ARCHIVE,
                surface="zenodo-doi",
                purpose="archival custody for the update",
            ),
        ),
        rationale="product research update reaches operational audiences after RDLC hardening",
    ),
}


def build_publication_vehicle_selector_receipt(
    disposition_receipt: RdlcDispositionReceipt,
    *,
    audience_family: RdlcPublicationAudienceFamily | str,
    risk_posture: RdlcRiskLevel | str | None = None,
    selector_receipt_id: str | None = None,
) -> RdlcPublicationVehicleSelectorReceipt:
    """Select a publication vehicle or emit a refusal receipt."""

    selector_input = RdlcPublicationVehicleSelectorInput.from_disposition(
        disposition_receipt,
        audience_family=audience_family,
        risk_posture=risk_posture,
    )
    missing = selector_input.missing_publication_fields()
    receipt_id = selector_receipt_id or f"rdlc-pubsel:{disposition_receipt.receipt_id}"
    if missing:
        return _refusal_receipt(
            receipt_id=receipt_id,
            selector_input=selector_input,
            reasons=tuple(f"missing_publication:{field}" for field in missing),
            rationale="publication vehicle selection refused before draft construction",
        )

    vehicle = _select_vehicle(selector_input)
    spec = VEHICLE_SPECS[vehicle]
    if selector_input.audience_family not in spec.allowed_audience_families:
        return _refusal_receipt(
            receipt_id=receipt_id,
            selector_input=selector_input,
            reasons=(
                f"vehicle_audience_mismatch:{vehicle.value}:{selector_input.audience_family.value}",
            ),
            rationale="publication vehicle selection refused by audience/vehicle policy",
        )

    abstract = _public_abstract(selector_input, vehicle)
    body_md = _public_body_md(selector_input, spec)
    hardening = _hardening_context(selector_input, spec)
    return RdlcPublicationVehicleSelectorReceipt(
        selector_receipt_id=receipt_id,
        decision=RdlcPublicationSelectorDecision.SELECTED,
        selector_input=selector_input,
        recommended_vehicle=vehicle,
        vehicle_rationale=spec.rationale,
        surface_budget_profile=spec.budget_profile,
        selected_surfaces=spec.surfaces,
        hardening_context=hardening,
        public_abstract=abstract,
        public_body_md=body_md,
    )


def build_preprint_draft_from_vehicle_selection(
    receipt: RdlcPublicationVehicleSelectorReceipt,
    *,
    slug: str,
    title: str | None = None,
) -> PreprintArtifact:
    """Construct an in-memory draft artifact from a selected vehicle receipt."""

    if receipt.decision != RdlcPublicationSelectorDecision.SELECTED:
        raise RdlcPublicationVehicleError(
            "cannot create PreprintArtifact for refused selector receipt; "
            "next action: provide a publish_candidate disposition with frozen public evidence "
            "and currentness refs before draft construction"
        )
    missing_publication_fields = receipt.selector_input.missing_publication_fields()
    if missing_publication_fields:
        missing = ", ".join(missing_publication_fields)
        raise RdlcPublicationVehicleError(
            f"selected receipt no longer satisfies publication gates: {missing}; "
            "next action: rebuild the selector receipt from a valid publish_candidate disposition"
        )
    if receipt.recommended_vehicle is None or receipt.public_body_md is None:
        raise RdlcPublicationVehicleError(
            "selected receipt missing vehicle/body sketch; "
            "next action: rebuild the selector receipt from a valid publish_candidate disposition"
        )
    expected_vehicle = _select_vehicle(receipt.selector_input)
    expected_spec = VEHICLE_SPECS[expected_vehicle]
    if receipt.selector_input.audience_family not in expected_spec.allowed_audience_families:
        raise RdlcPublicationVehicleError(
            "selected receipt audience does not match selected vehicle policy; "
            "next action: rebuild the selector receipt from a valid publish_candidate disposition"
        )
    if (
        receipt.recommended_vehicle != expected_vehicle
        or receipt.surface_budget_profile != expected_spec.budget_profile
        or receipt.selected_surfaces != expected_spec.surfaces
    ):
        raise RdlcPublicationVehicleError(
            "selected receipt vehicle/surface policy mismatch; "
            "next action: rebuild the selector receipt from a valid publish_candidate disposition"
        )
    expected_hardening_context = _hardening_context(receipt.selector_input, expected_spec)
    expected_abstract = _public_abstract(receipt.selector_input, expected_vehicle)
    expected_body = _public_body_md(receipt.selector_input, expected_spec)
    if (
        receipt.hardening_context != expected_hardening_context
        or receipt.public_abstract != expected_abstract
        or receipt.public_body_md != expected_body
    ):
        raise RdlcPublicationVehicleError(
            "selected receipt content/hardening policy mismatch; "
            "next action: rebuild the selector receipt from a valid publish_candidate disposition"
        )

    artifact_title = title or _title_from_vehicle(receipt.recommended_vehicle)
    context = {
        **expected_hardening_context,
        "rdlc_publication_vehicle_selector": receipt.model_dump(mode="json"),
        "egress_state": "draft_only_no_inbox_write",
        "publication_authorized": False,
    }
    return PreprintArtifact(
        slug=slug,
        title=artifact_title,
        abstract=expected_abstract,
        body_md=expected_body,
        surfaces_targeted=list(receipt.selected_surface_slugs()),
        approval=ApprovalState.DRAFT,
        publication_gate_context=context,
    )


def _select_vehicle(
    selector_input: RdlcPublicationVehicleSelectorInput,
) -> RdlcPublicationVehicle:
    if selector_input.risk_posture is RdlcRiskLevel.HIGH:
        return RdlcPublicationVehicle.GOVERNANCE_SAFETY_NOTE
    return {
        RdlcPublicationAudienceFamily.RESEARCH_METHODS: RdlcPublicationVehicle.METHOD_NOTE,
        RdlcPublicationAudienceFamily.SYSTEMS_ENGINEERING: RdlcPublicationVehicle.TECHNICAL_NOTE,
        RdlcPublicationAudienceFamily.GOVERNANCE_SAFETY: (
            RdlcPublicationVehicle.GOVERNANCE_SAFETY_NOTE
        ),
        RdlcPublicationAudienceFamily.DATASET_USERS: RdlcPublicationVehicle.DATASET_CARD,
        RdlcPublicationAudienceFamily.ARTIFACT_INDEX: RdlcPublicationVehicle.ARTIFACT_INDEX_ENTRY,
        RdlcPublicationAudienceFamily.PRODUCT_RESEARCH: (
            RdlcPublicationVehicle.PRODUCT_RESEARCH_UPDATE
        ),
    }[selector_input.audience_family]


def _refusal_receipt(
    *,
    receipt_id: str,
    selector_input: RdlcPublicationVehicleSelectorInput,
    reasons: tuple[str, ...],
    rationale: str,
) -> RdlcPublicationVehicleSelectorReceipt:
    return RdlcPublicationVehicleSelectorReceipt(
        selector_receipt_id=receipt_id,
        decision=RdlcPublicationSelectorDecision.REFUSED,
        selector_input=selector_input,
        vehicle_rationale=rationale,
        blocked_reasons=reasons,
        hardening_context={
            "rdlc_disposition_receipt_id": selector_input.disposition_receipt_id,
            "egress_state": "refused_before_draft_no_inbox_write",
            "publication_authorized": False,
        },
    )


def _frozen_ruler_ref(receipt: RdlcDispositionReceipt) -> str | None:
    if receipt.frozen_ruler_ref and receipt.frozen_ruler_version:
        return f"{receipt.frozen_ruler_ref}@{receipt.frozen_ruler_version}"
    return None


def _highest_risk(*levels: RdlcRiskLevel) -> RdlcRiskLevel:
    order = {
        RdlcRiskLevel.LOW: 0,
        RdlcRiskLevel.MODERATE: 1,
        RdlcRiskLevel.HIGH: 2,
    }
    return max(levels, key=lambda level: order[level])


def _hardening_context(
    selector_input: RdlcPublicationVehicleSelectorInput,
    spec: RdlcPublicationVehicleSpec,
) -> dict[str, object]:
    return {
        "rdlc_disposition_receipt_id": selector_input.disposition_receipt_id,
        "vehicle": spec.vehicle.value,
        "surface_budget_profile": spec.budget_profile.value,
        "claim_ceiling": selector_input.claim_ceiling,
        "frozen_evidence_refs": list(selector_input.frozen_evidence_refs),
        "public_safe_evidence_refs": list(selector_input.public_safe_evidence_refs),
        "currentness_evidence_refs": [
            ref for ref in (selector_input.currentness_ref, selector_input.freshness_ref) if ref
        ],
        "currentness_ref": selector_input.currentness_ref,
        "freshness_ref": selector_input.freshness_ref,
        "surface_roles": [selection.model_dump(mode="json") for selection in spec.surfaces],
        "publication_authorized": False,
        "egress_state": "draft_only_no_inbox_write",
    }


def _public_abstract(
    selector_input: RdlcPublicationVehicleSelectorInput,
    vehicle: RdlcPublicationVehicle,
) -> str:
    return (
        f"{vehicle.value.replace('_', ' ').title()} draft from an RDLC publish-candidate "
        f"receipt. Claim ceiling: {selector_input.claim_ceiling}."
    )


def _public_body_md(
    selector_input: RdlcPublicationVehicleSelectorInput,
    spec: RdlcPublicationVehicleSpec,
) -> str:
    evidence_lines = [f"- {ref}" for ref in selector_input.public_safe_evidence_refs]
    surface_lines = [
        f"- {selection.role.value}: {selection.surface} ({selection.purpose})"
        for selection in spec.surfaces
    ]
    return "\n".join(
        [
            f"# {_title_from_vehicle(spec.vehicle)}",
            "",
            f"Vehicle: {spec.vehicle.value}",
            f"Audience family: {selector_input.audience_family.value}",
            f"Claim: {selector_input.claim_text}",
            f"Claim ceiling: {selector_input.claim_ceiling}",
            f"Rationale: {spec.rationale}",
            f"Freshness: {selector_input.freshness_ref}",
            f"Currentness: {selector_input.currentness_ref}",
            "",
            "Public-safe evidence refs:",
            *evidence_lines,
            "",
            "Selected publication surfaces:",
            *surface_lines,
        ]
    )


def _title_from_vehicle(vehicle: RdlcPublicationVehicle) -> str:
    return vehicle.value.replace("_", " ").title()


__all__ = [
    "RdlcPublicationAudienceFamily",
    "RdlcPublicationSelectorDecision",
    "RdlcPublicationSurfaceSelection",
    "RdlcPublicationVehicle",
    "RdlcPublicationVehicleError",
    "RdlcPublicationVehicleSelectorInput",
    "RdlcPublicationVehicleSelectorReceipt",
    "RdlcSurfaceBudgetProfile",
    "RdlcSurfaceRole",
    "VEHICLE_SPECS",
    "build_preprint_draft_from_vehicle_selection",
    "build_publication_vehicle_selector_receipt",
]
