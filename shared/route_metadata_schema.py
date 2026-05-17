"""Route metadata schema for quality-preserving capacity routing.

This module validates route metadata carried in request or cc-task
frontmatter. It is schema and audit plumbing only; it does not select or
launch routes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class QualityFloor(StrEnum):
    FRONTIER_REQUIRED = "frontier_required"
    FRONTIER_REVIEW_REQUIRED = "frontier_review_required"
    DETERMINISTIC_OK = "deterministic_ok"


class AuthorityLevel(StrEnum):
    AUTHORITATIVE = "authoritative"
    SUPPORT_NON_AUTHORITATIVE = "support_non_authoritative"
    EVIDENCE_RECEIPT = "evidence_receipt"
    RELAY_ONLY = "relay_only"


class MutationSurface(StrEnum):
    NONE = "none"
    VAULT_DOCS = "vault_docs"
    SOURCE = "source"
    RUNTIME = "runtime"
    PUBLIC = "public"
    PROVIDER_SPEND = "provider_spend"


class AuthorityClass(StrEnum):
    PLANNING = "planning"
    AUTHORITATIVE_DOCS = "authoritative_docs"
    SOURCE_MUTATION = "source_mutation"
    RUNTIME_MUTATION = "runtime_mutation"
    PUBLIC_CLAIM = "public_claim"
    PROVIDER_SPEND = "provider_spend"


class CodebaseLocality(StrEnum):
    NONE = "none"
    SINGLE_FILE = "single_file"
    MODULE = "module"
    CROSS_MODULE = "cross_module"
    CROSS_REPO = "cross_repo"


class ContextBreadth(StrEnum):
    NONE = "none"
    LOCAL_NOTE = "local_note"
    LOCAL_REPO = "local_repo"
    CROSS_REPO = "cross_repo"
    VAULT_PLUS_REPO = "vault_plus_repo"
    EXTERNAL_CURRENT = "external_current"


class SourceGroundingNeed(StrEnum):
    NONE = "none"
    LOCAL_DOCS = "local_docs"
    OFFICIAL_DOCS_CURRENT = "official_docs_current"
    WEB_CURRENT = "web_current"
    LITERATURE = "literature"
    MULTIMODAL = "multimodal"


class ToolAuthorityUse(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    VERIFY = "verify"


class ExecutionSurface(StrEnum):
    LOCAL_SHELL = "local_shell"
    BROWSER = "browser"
    ANDROID = "android"
    WEAROS = "wearos"
    GPU = "gpu"
    AUDIO = "audio"
    VIDEO = "video"
    DOCKER = "docker"
    SYSTEMD = "systemd"
    NETWORK = "network"


class Urgency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    P0 = "p0"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    CONTRADICTORY = "contradictory"
    UNPARSEABLE = "unparseable"
    MANUAL_ASSERTION = "manual_assertion"


class RouteMetadataStatus(StrEnum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    HOLD = "hold"
    MALFORMED = "malformed"


class _RouteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _coerce_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [] if not text or text in {"null", "None"} else [text]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


class RiskFlags(_RouteModel):
    governance_sensitive: bool = False
    privacy_or_secret_sensitive: bool = False
    public_claim_sensitive: bool = False
    aesthetic_theory_sensitive: bool = False
    audio_or_live_egress_sensitive: bool = False
    provider_billing_sensitive: bool = False


class ContextShape(_RouteModel):
    codebase_locality: CodebaseLocality = CodebaseLocality.NONE
    vault_context_required: bool = False
    external_docs_required: bool = False
    currentness_required: bool = False


class VerificationSurface(_RouteModel):
    deterministic_tests: list[str] = Field(default_factory=list)
    static_checks: list[str] = Field(default_factory=list)
    runtime_observation: list[str] = Field(default_factory=list)
    operator_only: bool = False

    @field_validator("deterministic_tests", "static_checks", "runtime_observation", mode="before")
    @classmethod
    def _lists_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_string_list(value)


class RequiredTool(_RouteModel):
    tool_id: str
    required: bool = True
    authority_use: ToolAuthorityUse = ToolAuthorityUse.READ


class ExecutionEnvironment(_RouteModel):
    required: bool = False
    surfaces: list[ExecutionSurface] = Field(default_factory=list)


class VerificationDemand(_RouteModel):
    deterministic_tests: list[str] = Field(default_factory=list)
    static_checks: list[str] = Field(default_factory=list)
    runtime_observation: list[str] = Field(default_factory=list)
    screenshot_or_media_required: bool = False
    operator_only: bool = False

    @field_validator("deterministic_tests", "static_checks", "runtime_observation", mode="before")
    @classmethod
    def _lists_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_string_list(value)


class TaskDemand(_RouteModel):
    authority_class: AuthorityClass
    grounding_criticality: int = Field(ge=0, le=5)
    governance_claim_risk: int = Field(ge=0, le=5)
    codebase_locality: CodebaseLocality = CodebaseLocality.NONE
    implementation_complexity: int = Field(ge=0, le=5)
    architectural_novelty: int = Field(ge=0, le=5)
    requirement_ambiguity: int = Field(ge=0, le=5)
    estimated_context_tokens: int = Field(ge=0)
    context_breadth: ContextBreadth = ContextBreadth.NONE
    source_grounding_need: SourceGroundingNeed = SourceGroundingNeed.NONE
    required_tools: list[RequiredTool] = Field(default_factory=list)
    execution_environment: ExecutionEnvironment = Field(default_factory=ExecutionEnvironment)
    verification_demand: VerificationDemand = Field(default_factory=VerificationDemand)
    security_privacy_sensitivity: int = Field(ge=0, le=5)
    release_publication_impact: int = Field(ge=0, le=5)
    coordination_load: int = Field(ge=0, le=5)
    branch_worktree_conflict_risk: int = Field(ge=0, le=5)
    operator_insight_dependency: int = Field(ge=0, le=5)
    failure_cost: int = Field(ge=0, le=5)


class PriorityContext(_RouteModel):
    value_braid_refs: list[str] = Field(default_factory=list)
    wsjf: float | None = None
    urgency: Urgency = Urgency.MEDIUM

    @field_validator("value_braid_refs", mode="before")
    @classmethod
    def _value_braid_refs_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_string_list(value)


class FreshnessRequirement(_RouteModel):
    source_id: str
    required_for: str
    stale_after: str
    fail_closed: bool = True


class DemandWorkItem(_RouteModel):
    task_id: str
    request_id: str | None = None
    authority_case: str
    authority_item: str | None = None
    note_path: str
    frontmatter_observed_at: datetime
    frontmatter_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class DemandSourceRef(_RouteModel):
    source_id: str
    artifact_path: str | None = None
    hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    freshness_state: FreshnessState
    message: str | None = None


class DemandVector(_RouteModel):
    demand_vector_schema: Literal[1] = 1
    routing_model_version: Literal["capacity-dimensional-v1"] = "capacity-dimensional-v1"
    work_item: DemandWorkItem
    quality_floor: QualityFloor
    authority_level: AuthorityLevel
    mutation_surface: MutationSurface
    mutation_scope_refs: list[str] = Field(default_factory=list)
    risk_flags: RiskFlags = Field(default_factory=RiskFlags)
    task_demand: TaskDemand
    priority_context: PriorityContext = Field(default_factory=PriorityContext)
    freshness_requirements: list[FreshnessRequirement] = Field(default_factory=list)
    source_refs: list[DemandSourceRef] = Field(default_factory=list)

    @field_validator("mutation_scope_refs", mode="before")
    @classmethod
    def _mutation_scope_refs_are_strings(cls, value: object) -> list[str]:
        return _coerce_string_list(value)


class DemandVectorFreshness(_RouteModel):
    freshness_state: FreshnessState
    stale_reasons: list[str] = Field(default_factory=list)
    source_refs: list[DemandSourceRef] = Field(default_factory=list)


class RouteConstraints(_RouteModel):
    preferred_platforms: list[str] = Field(default_factory=list)
    allowed_platforms: list[str] = Field(default_factory=list)
    prohibited_platforms: list[str] = Field(default_factory=list)
    required_mode: str | None = None
    required_profile: str | None = None

    @field_validator(
        "preferred_platforms", "allowed_platforms", "prohibited_platforms", mode="before"
    )
    @classmethod
    def _lists_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_string_list(value)


class ReviewRequirement(_RouteModel):
    support_artifact_allowed: bool = False
    independent_review_required: bool = False
    authoritative_acceptor_profile: str | None = None


class RouteMetadata(_RouteModel):
    route_metadata_schema: Literal[1] = 1
    quality_floor: QualityFloor
    authority_level: AuthorityLevel
    mutation_surface: MutationSurface
    mutation_scope_refs: list[str] = Field(default_factory=list)
    risk_flags: RiskFlags = Field(default_factory=RiskFlags)
    context_shape: ContextShape = Field(default_factory=ContextShape)
    verification_surface: VerificationSurface = Field(default_factory=VerificationSurface)
    route_constraints: RouteConstraints = Field(default_factory=RouteConstraints)
    review_requirement: ReviewRequirement = Field(default_factory=ReviewRequirement)

    @field_validator("mutation_scope_refs", mode="before")
    @classmethod
    def _mutation_scope_refs_are_strings(cls, value: object) -> list[str]:
        return _coerce_string_list(value)

    @model_validator(mode="after")
    def _support_outputs_need_review(self) -> Self:
        if self.quality_floor != QualityFloor.FRONTIER_REVIEW_REQUIRED:
            return self
        if self.authority_level == AuthorityLevel.AUTHORITATIVE:
            raise ValueError("frontier_review_required artifacts cannot be authoritative directly")
        if not self.review_requirement.support_artifact_allowed:
            raise ValueError("frontier_review_required requires support_artifact_allowed")
        if not self.review_requirement.independent_review_required:
            raise ValueError("frontier_review_required requires independent_review_required")
        if not self.review_requirement.authoritative_acceptor_profile:
            raise ValueError("frontier_review_required requires authoritative_acceptor_profile")
        return self


class RouteMetadataAssessment(_RouteModel):
    status: RouteMetadataStatus
    metadata: RouteMetadata | None = None
    hold_reasons: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    derived_fields: list[str] = Field(default_factory=list)

    @property
    def dispatchable(self) -> bool:
        return self.status in {RouteMetadataStatus.EXPLICIT, RouteMetadataStatus.DERIVED}

    def planning_status(self) -> dict[str, object]:
        metadata = self.metadata
        return {
            "status": self.status.value,
            "dispatchable": self.dispatchable,
            "quality_floor": metadata.quality_floor if metadata else None,
            "authority_level": metadata.authority_level if metadata else None,
            "mutation_surface": metadata.mutation_surface if metadata else None,
            "hold_reasons": self.hold_reasons,
            "missing_fields": self.missing_fields,
            "validation_errors": self.validation_errors,
            "derived_fields": self.derived_fields,
        }


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    VerificationSurface._lists_are_string_lists,
    VerificationDemand._lists_are_string_lists,
    PriorityContext._value_braid_refs_are_string_lists,
    DemandVector._mutation_scope_refs_are_strings,
    RouteConstraints._lists_are_string_lists,
    RouteMetadata._mutation_scope_refs_are_strings,
    RouteMetadata._support_outputs_need_review,
    RouteMetadataAssessment.planning_status,
)


ROUTE_METADATA_FIELDS = frozenset(
    {
        "route_metadata_schema",
        "quality_floor",
        "authority_level",
        "mutation_surface",
        "mutation_scope_refs",
        "risk_flags",
        "context_shape",
        "verification_surface",
        "route_constraints",
        "review_requirement",
    }
)


def route_metadata_payload_from_frontmatter(frontmatter: Mapping[str, Any]) -> dict[str, Any]:
    """Extract route metadata fields from canonical frontmatter data."""
    payload: dict[str, Any] = {}
    nested = frontmatter.get("route_metadata")
    if isinstance(nested, Mapping):
        payload.update(
            {key: value for key, value in nested.items() if not _is_empty_frontmatter_value(value)}
        )
    for field in ROUTE_METADATA_FIELDS:
        if field in frontmatter and not _is_empty_frontmatter_value(frontmatter[field]):
            payload[field] = frontmatter[field]
    return payload


def frontmatter_has_route_metadata(frontmatter: Mapping[str, Any]) -> bool:
    return bool(route_metadata_payload_from_frontmatter(frontmatter))


def validate_route_metadata(frontmatter: Mapping[str, Any]) -> RouteMetadata:
    return RouteMetadata.model_validate(route_metadata_payload_from_frontmatter(frontmatter))


def assess_route_metadata(frontmatter: Mapping[str, Any]) -> RouteMetadataAssessment:
    """Validate explicit metadata or derive a conservative route metadata row."""
    if frontmatter_has_route_metadata(frontmatter):
        return _assess_explicit_route_metadata(frontmatter)

    payload, derived_fields = derive_route_metadata_payload(frontmatter)
    missing = [field for field in ("quality_floor", "mutation_surface") if field not in payload]
    if missing:
        return RouteMetadataAssessment(
            status=RouteMetadataStatus.HOLD,
            hold_reasons=[f"missing_{field}" for field in missing],
            missing_fields=missing,
            derived_fields=derived_fields,
        )

    try:
        metadata = RouteMetadata.model_validate(payload)
    except ValidationError as exc:
        return RouteMetadataAssessment(
            status=RouteMetadataStatus.MALFORMED,
            validation_errors=_validation_error_messages(exc),
            derived_fields=derived_fields,
        )
    return RouteMetadataAssessment(
        status=RouteMetadataStatus.DERIVED,
        metadata=metadata,
        derived_fields=derived_fields,
    )


def stable_payload_hash(payload: Mapping[str, Any]) -> str:
    """Return a stable sha256 hash for frontmatter-like structured metadata."""

    normalized = json.dumps(
        _jsonable_mapping(
            {key: value for key, value in payload.items() if not key.startswith("__")}
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_demand_vector(
    frontmatter: Mapping[str, Any],
    *,
    note_path: Path | str | None = None,
    observed_at: datetime | None = None,
) -> DemandVector:
    """Build the typed dimensional demand vector for a dispatchable work item."""

    assessment = assess_route_metadata(frontmatter)
    if assessment.metadata is None:
        raise ValueError(
            "cannot build demand vector without valid route metadata: "
            + ", ".join(
                [
                    *assessment.hold_reasons,
                    *assessment.missing_fields,
                    *assessment.validation_errors,
                ]
            )
        )

    metadata = assessment.metadata
    checked_at = _coerce_utc(observed_at)
    resolved_note_path = _resolve_optional_path(
        note_path
        or frontmatter.get("__task_note_path")
        or frontmatter.get("note_path")
        or frontmatter.get("path")
    )
    note_path_text = str(resolved_note_path) if resolved_note_path else ""
    authority_case = _optional_frontmatter_string(frontmatter.get("authority_case"))
    request_id = _optional_frontmatter_string(
        frontmatter.get("request_id") or frontmatter.get("parent_request")
    )
    authority_item = _optional_frontmatter_string(
        frontmatter.get("authority_item") or frontmatter.get("slice_id")
    )
    task_id = _optional_frontmatter_string(frontmatter.get("task_id")) or "unknown-task"
    source_refs = _demand_source_refs(
        frontmatter,
        note_path=resolved_note_path,
        mutation_scope_refs=metadata.mutation_scope_refs,
    )

    return DemandVector(
        work_item=DemandWorkItem(
            task_id=task_id,
            request_id=request_id,
            authority_case=authority_case or "read-only-exempt",
            authority_item=authority_item,
            note_path=note_path_text,
            frontmatter_observed_at=checked_at,
            frontmatter_hash=stable_payload_hash(frontmatter),
        ),
        quality_floor=metadata.quality_floor,
        authority_level=metadata.authority_level,
        mutation_surface=metadata.mutation_surface,
        mutation_scope_refs=metadata.mutation_scope_refs,
        risk_flags=metadata.risk_flags,
        task_demand=_build_task_demand(frontmatter, metadata),
        priority_context=_build_priority_context(frontmatter),
        freshness_requirements=_build_freshness_requirements(frontmatter, source_refs),
        source_refs=source_refs,
    )


def check_demand_vector_freshness(
    demand_vector: DemandVector,
    current_frontmatter: Mapping[str, Any],
    *,
    note_path: Path | str | None = None,
) -> DemandVectorFreshness:
    """Return fail-closed freshness for a previously observed demand vector."""

    stale_reasons: list[str] = []
    current_frontmatter_hash = stable_payload_hash(current_frontmatter)
    if current_frontmatter_hash != demand_vector.work_item.frontmatter_hash:
        stale_reasons.append("frontmatter_hash_changed")

    current_source_refs = _demand_source_refs(
        current_frontmatter,
        note_path=_resolve_optional_path(note_path or demand_vector.work_item.note_path),
        mutation_scope_refs=demand_vector.mutation_scope_refs,
    )
    current_by_id = {ref.source_id: ref for ref in current_source_refs}
    checked_refs: list[DemandSourceRef] = []

    for original in demand_vector.source_refs:
        current = current_by_id.get(original.source_id)
        if current is None:
            stale_reasons.append(f"{original.source_id}:source_ref_missing")
            checked_refs.append(
                original.model_copy(
                    update={
                        "freshness_state": FreshnessState.MISSING,
                        "message": "source ref missing from current demand vector",
                    }
                )
            )
            continue
        if current.hash is None:
            stale_reasons.append(f"{original.source_id}:source_missing")
            checked_refs.append(current)
            continue
        if original.hash is not None and current.hash != original.hash:
            stale_reasons.append(f"{original.source_id}:hash_changed")
            checked_refs.append(
                current.model_copy(
                    update={
                        "freshness_state": FreshnessState.STALE,
                        "message": "source hash changed after demand vector observation",
                    }
                )
            )
            continue
        checked_refs.append(current)

    if any(ref.freshness_state is FreshnessState.MISSING for ref in checked_refs):
        state = FreshnessState.MISSING
    elif stale_reasons:
        state = FreshnessState.STALE
    else:
        state = FreshnessState.FRESH
    return DemandVectorFreshness(
        freshness_state=state,
        stale_reasons=stale_reasons,
        source_refs=checked_refs,
    )


def derive_route_metadata_payload(
    frontmatter: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Derive route metadata from existing request/task frontmatter, conservatively."""
    payload: dict[str, Any] = {"route_metadata_schema": 1}
    derived_fields: list[str] = ["route_metadata_schema"]
    quality_floor = _derive_quality_floor(frontmatter)
    mutation_surface = _derive_mutation_surface(frontmatter)

    if quality_floor is not None:
        payload["quality_floor"] = quality_floor
        derived_fields.append("quality_floor")
    if mutation_surface is not None:
        payload["mutation_surface"] = mutation_surface
        derived_fields.append("mutation_surface")

    authority_level = _derive_authority_level(frontmatter, quality_floor)
    payload["authority_level"] = authority_level
    derived_fields.append("authority_level")

    payload["mutation_scope_refs"] = _derive_mutation_scope_refs(frontmatter)
    derived_fields.append("mutation_scope_refs")
    payload["risk_flags"] = _derive_risk_flags(frontmatter)
    derived_fields.append("risk_flags")
    payload["context_shape"] = _derive_context_shape(frontmatter, mutation_surface)
    derived_fields.append("context_shape")
    payload["verification_surface"] = _derive_verification_surface(frontmatter)
    derived_fields.append("verification_surface")
    payload["route_constraints"] = {}
    derived_fields.append("route_constraints")
    payload["review_requirement"] = _derive_review_requirement(quality_floor)
    derived_fields.append("review_requirement")
    return payload, derived_fields


def _assess_explicit_route_metadata(frontmatter: Mapping[str, Any]) -> RouteMetadataAssessment:
    try:
        metadata = validate_route_metadata(frontmatter)
    except ValidationError as exc:
        missing_fields = [
            str(error["loc"][0])
            for error in exc.errors()
            if error.get("type") == "missing" and error.get("loc")
        ]
        return RouteMetadataAssessment(
            status=RouteMetadataStatus.MALFORMED,
            validation_errors=_validation_error_messages(exc),
            missing_fields=missing_fields,
        )
    return RouteMetadataAssessment(status=RouteMetadataStatus.EXPLICIT, metadata=metadata)


def _derive_quality_floor(frontmatter: Mapping[str, Any]) -> QualityFloor | None:
    risk_tier = _lower_scalar(frontmatter.get("risk_tier") or frontmatter.get("tier"))
    tags = _lower_strings(frontmatter.get("tags"))
    kind = _lower_scalar(frontmatter.get("kind") or frontmatter.get("task_type"))
    authority_case = _lower_scalar(frontmatter.get("authority_case"))

    if risk_tier in {"t0", "t1"}:
        return QualityFloor.FRONTIER_REQUIRED
    if "frontier-required" in tags or "frontier_required" in tags:
        return QualityFloor.FRONTIER_REQUIRED
    if "frontier-review-required" in tags or "support-artifact" in tags:
        return QualityFloor.FRONTIER_REVIEW_REQUIRED
    if kind in {"support", "support_research", "inventory"}:
        return QualityFloor.FRONTIER_REVIEW_REQUIRED
    if "deterministic-ok" in tags or "deterministic_ok" in tags:
        return QualityFloor.DETERMINISTIC_OK
    if kind in {"mechanical", "maintenance", "test", "validation"} and authority_case:
        return QualityFloor.DETERMINISTIC_OK
    return None


def _derive_authority_level(
    frontmatter: Mapping[str, Any], quality_floor: QualityFloor | None
) -> AuthorityLevel:
    kind = _lower_scalar(frontmatter.get("kind") or frontmatter.get("task_type"))
    tags = _lower_strings(frontmatter.get("tags"))
    if kind in {"relay", "coordination"} or "relay-only" in tags:
        return AuthorityLevel.RELAY_ONLY
    if kind in {"evidence", "receipt", "audit"} or "evidence-receipt" in tags:
        return AuthorityLevel.EVIDENCE_RECEIPT
    if quality_floor == QualityFloor.FRONTIER_REVIEW_REQUIRED or "support-artifact" in tags:
        return AuthorityLevel.SUPPORT_NON_AUTHORITATIVE
    if _lower_scalar(frontmatter.get("authority_case")):
        return AuthorityLevel.AUTHORITATIVE
    return AuthorityLevel.SUPPORT_NON_AUTHORITATIVE


def _derive_mutation_surface(frontmatter: Mapping[str, Any]) -> MutationSurface | None:
    kind = _lower_scalar(frontmatter.get("kind") or frontmatter.get("task_type"))
    tags = _lower_strings(frontmatter.get("tags"))
    if "provider-spend" in tags or "provider_spend" in tags:
        return MutationSurface.PROVIDER_SPEND
    if "runtime" in tags:
        return MutationSurface.RUNTIME
    if "public" in tags or "public-surface" in tags:
        return MutationSurface.PUBLIC
    if kind in {"implementation", "source", "hotfix", "bugfix", "maintenance"}:
        return MutationSurface.SOURCE
    if kind in {"documentation", "docs", "planning", "research", "spec", "support"}:
        return MutationSurface.VAULT_DOCS
    if kind in {"relay", "coordination", "evidence", "receipt", "audit", "validation"}:
        return MutationSurface.NONE
    return None


def _derive_mutation_scope_refs(frontmatter: Mapping[str, Any]) -> list[str]:
    refs = []
    for field in ("parent_spec", "parent_plan", "parent_request"):
        value = str(frontmatter.get(field) or "").strip()
        if value and value not in {"null", "None"}:
            refs.append(value)
    return refs


def _derive_risk_flags(frontmatter: Mapping[str, Any]) -> dict[str, bool]:
    tags = _lower_strings(frontmatter.get("tags"))
    title = _lower_scalar(frontmatter.get("title"))
    combined = " ".join([title, *tags])
    return {
        "governance_sensitive": _contains_any(combined, ("governance", "authority", "policy")),
        "privacy_or_secret_sensitive": _contains_any(combined, ("privacy", "secret", "credential")),
        "public_claim_sensitive": _contains_any(combined, ("public", "publication", "claim")),
        "aesthetic_theory_sensitive": _contains_any(combined, ("aesthetic", "theory")),
        "audio_or_live_egress_sensitive": _contains_any(combined, ("audio", "egress", "live")),
        "provider_billing_sensitive": _contains_any(combined, ("provider", "billing", "spend")),
    }


def _derive_context_shape(
    frontmatter: Mapping[str, Any], mutation_surface: MutationSurface | None
) -> dict[str, object]:
    tags = _lower_strings(frontmatter.get("tags"))
    locality = CodebaseLocality.NONE
    if mutation_surface == MutationSurface.SOURCE:
        locality = CodebaseLocality.MODULE
    if "cross-repo" in tags or "cross_repo" in tags:
        locality = CodebaseLocality.CROSS_REPO
    elif "cross-module" in tags or "cross_module" in tags:
        locality = CodebaseLocality.CROSS_MODULE
    return {
        "codebase_locality": locality,
        "vault_context_required": bool(
            frontmatter.get("parent_spec") or frontmatter.get("parent_plan")
        ),
        "external_docs_required": "external-docs" in tags or "external_docs" in tags,
        "currentness_required": "currentness" in tags or "latest" in tags,
    }


def _derive_verification_surface(frontmatter: Mapping[str, Any]) -> dict[str, object]:
    tags = _lower_strings(frontmatter.get("tags"))
    deterministic_tests = []
    static_checks = []
    if "tests" in tags or "deterministic-ok" in tags or "deterministic_ok" in tags:
        deterministic_tests.append("task-specified-tests")
    if "lint" in tags or "static" in tags:
        static_checks.append("task-specified-static-checks")
    return {
        "deterministic_tests": deterministic_tests,
        "static_checks": static_checks,
        "runtime_observation": [],
        "operator_only": False,
    }


def _derive_review_requirement(quality_floor: QualityFloor | None) -> dict[str, object]:
    if quality_floor != QualityFloor.FRONTIER_REVIEW_REQUIRED:
        return {}
    return {
        "support_artifact_allowed": True,
        "independent_review_required": True,
        "authoritative_acceptor_profile": "frontier_full",
    }


def _build_task_demand(frontmatter: Mapping[str, Any], metadata: RouteMetadata) -> TaskDemand:
    explicit = frontmatter.get("task_demand")
    if isinstance(explicit, Mapping):
        payload = _derived_task_demand_payload(frontmatter, metadata)
        payload.update(dict(explicit))
        return TaskDemand.model_validate(payload)
    return TaskDemand.model_validate(_derived_task_demand_payload(frontmatter, metadata))


def _derived_task_demand_payload(
    frontmatter: Mapping[str, Any], metadata: RouteMetadata
) -> dict[str, Any]:
    risk = metadata.risk_flags
    context = metadata.context_shape
    verification = metadata.verification_surface
    mutation = metadata.mutation_surface
    locality = context.codebase_locality
    tags = _lower_strings(frontmatter.get("tags"))
    complexity = _context_complexity(locality)
    if mutation in {MutationSurface.RUNTIME, MutationSurface.PROVIDER_SPEND}:
        complexity = max(complexity, 4)
    if mutation == MutationSurface.SOURCE:
        complexity = max(complexity, 3)
    ambiguity = 3 if metadata.authority_level == AuthorityLevel.AUTHORITATIVE else 2
    if "ambiguous" in tags or "research" in tags:
        ambiguity = max(ambiguity, 4)

    return {
        "authority_class": _authority_class(metadata),
        "grounding_criticality": _risk_score(
            risk.governance_sensitive or risk.privacy_or_secret_sensitive
        ),
        "governance_claim_risk": _risk_score(risk.governance_sensitive),
        "codebase_locality": locality,
        "implementation_complexity": complexity,
        "architectural_novelty": 4
        if locality in {CodebaseLocality.CROSS_MODULE, CodebaseLocality.CROSS_REPO}
        else 2,
        "requirement_ambiguity": ambiguity,
        "estimated_context_tokens": _estimated_context_tokens(frontmatter, locality),
        "context_breadth": _context_breadth(metadata),
        "source_grounding_need": _source_grounding_need(metadata),
        "required_tools": _required_tools(frontmatter, metadata),
        "execution_environment": _execution_environment(frontmatter, metadata),
        "verification_demand": {
            "deterministic_tests": verification.deterministic_tests,
            "static_checks": verification.static_checks,
            "runtime_observation": verification.runtime_observation,
            "screenshot_or_media_required": bool(frontmatter.get("screenshot_or_media_required")),
            "operator_only": verification.operator_only,
        },
        "security_privacy_sensitivity": _risk_score(risk.privacy_or_secret_sensitive),
        "release_publication_impact": _risk_score(risk.public_claim_sensitive),
        "coordination_load": 4
        if locality == CodebaseLocality.CROSS_REPO
        else 3
        if locality == CodebaseLocality.CROSS_MODULE
        else 1,
        "branch_worktree_conflict_risk": 4 if mutation == MutationSurface.SOURCE else 1,
        "operator_insight_dependency": 4 if risk.aesthetic_theory_sensitive else 2,
        "failure_cost": 5
        if risk.audio_or_live_egress_sensitive or risk.provider_billing_sensitive
        else 4
        if risk.governance_sensitive
        else 2,
    }


def _build_priority_context(frontmatter: Mapping[str, Any]) -> PriorityContext:
    urgency = _priority_to_urgency(frontmatter.get("priority"))
    wsjf = _float_or_none(frontmatter.get("wsjf"))
    return PriorityContext(
        value_braid_refs=_coerce_string_list(frontmatter.get("value_braid_refs")),
        wsjf=wsjf,
        urgency=urgency,
    )


def _build_freshness_requirements(
    frontmatter: Mapping[str, Any], source_refs: list[DemandSourceRef]
) -> list[FreshnessRequirement]:
    explicit = frontmatter.get("freshness_requirements")
    if isinstance(explicit, list):
        return [
            FreshnessRequirement.model_validate(item)
            for item in explicit
            if isinstance(item, Mapping)
        ]
    return [
        FreshnessRequirement(
            source_id=source_ref.source_id,
            required_for="demand_vector",
            stale_after="24h",
            fail_closed=True,
        )
        for source_ref in source_refs
    ]


def _demand_source_refs(
    frontmatter: Mapping[str, Any],
    *,
    note_path: Path | None,
    mutation_scope_refs: list[str],
) -> list[DemandSourceRef]:
    refs: list[DemandSourceRef] = []
    if note_path is not None:
        refs.append(_source_ref("task_note", note_path))

    for field in ("parent_spec", "parent_request"):
        path = _resolve_optional_path(frontmatter.get(field))
        if path is not None:
            refs.append(_source_ref(field, path))

    seen = {ref.artifact_path for ref in refs}
    for index, raw_ref in enumerate(mutation_scope_refs):
        path = _resolve_optional_path(raw_ref)
        if path is None:
            continue
        path_text = str(path)
        if path_text in seen:
            continue
        seen.add(path_text)
        refs.append(_source_ref(f"mutation_scope_ref_{index}", path))
    return refs


def _source_ref(source_id: str, path: Path) -> DemandSourceRef:
    if not path.exists():
        return DemandSourceRef(
            source_id=source_id,
            artifact_path=str(path),
            freshness_state=FreshnessState.MISSING,
            message="source artifact is missing",
        )
    if not path.is_file():
        return DemandSourceRef(
            source_id=source_id,
            artifact_path=str(path),
            freshness_state=FreshnessState.UNPARSEABLE,
            message="source artifact is not a file",
        )
    try:
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        return DemandSourceRef(
            source_id=source_id,
            artifact_path=str(path),
            freshness_state=FreshnessState.UNPARSEABLE,
            message=str(exc),
        )
    return DemandSourceRef(
        source_id=source_id,
        artifact_path=str(path),
        hash=digest,
        freshness_state=FreshnessState.FRESH,
    )


def _authority_class(metadata: RouteMetadata) -> AuthorityClass:
    if metadata.mutation_surface == MutationSurface.SOURCE:
        return AuthorityClass.SOURCE_MUTATION
    if metadata.mutation_surface == MutationSurface.RUNTIME:
        return AuthorityClass.RUNTIME_MUTATION
    if metadata.mutation_surface == MutationSurface.PUBLIC:
        return AuthorityClass.PUBLIC_CLAIM
    if metadata.mutation_surface == MutationSurface.PROVIDER_SPEND:
        return AuthorityClass.PROVIDER_SPEND
    if metadata.authority_level == AuthorityLevel.AUTHORITATIVE:
        return AuthorityClass.AUTHORITATIVE_DOCS
    return AuthorityClass.PLANNING


def _context_complexity(locality: CodebaseLocality) -> int:
    return {
        CodebaseLocality.NONE: 0,
        CodebaseLocality.SINGLE_FILE: 2,
        CodebaseLocality.MODULE: 3,
        CodebaseLocality.CROSS_MODULE: 4,
        CodebaseLocality.CROSS_REPO: 5,
    }[locality]


def _estimated_context_tokens(frontmatter: Mapping[str, Any], locality: CodebaseLocality) -> int:
    explicit = _int_or_none(frontmatter.get("estimated_context_tokens"))
    if explicit is not None:
        return max(explicit, 0)
    return {
        CodebaseLocality.NONE: 4_000,
        CodebaseLocality.SINGLE_FILE: 8_000,
        CodebaseLocality.MODULE: 24_000,
        CodebaseLocality.CROSS_MODULE: 80_000,
        CodebaseLocality.CROSS_REPO: 160_000,
    }[locality]


def _context_breadth(metadata: RouteMetadata) -> ContextBreadth:
    context = metadata.context_shape
    if context.currentness_required or context.external_docs_required:
        return ContextBreadth.EXTERNAL_CURRENT
    if context.vault_context_required and context.codebase_locality != CodebaseLocality.NONE:
        return ContextBreadth.VAULT_PLUS_REPO
    if context.codebase_locality == CodebaseLocality.CROSS_REPO:
        return ContextBreadth.CROSS_REPO
    if context.codebase_locality != CodebaseLocality.NONE:
        return ContextBreadth.LOCAL_REPO
    if context.vault_context_required:
        return ContextBreadth.LOCAL_NOTE
    return ContextBreadth.NONE


def _source_grounding_need(metadata: RouteMetadata) -> SourceGroundingNeed:
    context = metadata.context_shape
    if context.currentness_required:
        return SourceGroundingNeed.WEB_CURRENT
    if context.external_docs_required:
        return SourceGroundingNeed.OFFICIAL_DOCS_CURRENT
    if context.codebase_locality != CodebaseLocality.NONE:
        return SourceGroundingNeed.LOCAL_DOCS
    return SourceGroundingNeed.NONE


def _required_tools(
    frontmatter: Mapping[str, Any], metadata: RouteMetadata
) -> list[dict[str, Any]]:
    explicit = frontmatter.get("required_tools")
    if isinstance(explicit, list):
        tools: list[dict[str, Any]] = []
        for item in explicit:
            if isinstance(item, Mapping):
                tools.append(dict(item))
            else:
                tools.append({"tool_id": str(item), "required": True, "authority_use": "read"})
        return tools

    tools = []
    if metadata.mutation_surface == MutationSurface.SOURCE:
        tools.extend(
            [
                {"tool_id": "filesystem", "required": True, "authority_use": "write"},
                {"tool_id": "local_shell", "required": True, "authority_use": "execute"},
            ]
        )
    if metadata.context_shape.external_docs_required or metadata.context_shape.currentness_required:
        tools.append({"tool_id": "context7", "required": True, "authority_use": "read"})
    return tools


def _execution_environment(
    frontmatter: Mapping[str, Any], metadata: RouteMetadata
) -> dict[str, Any]:
    explicit = frontmatter.get("execution_environment")
    if isinstance(explicit, Mapping):
        return dict(explicit)
    surfaces: list[str] = []
    if metadata.mutation_surface == MutationSurface.SOURCE:
        surfaces.append(ExecutionSurface.LOCAL_SHELL.value)
    if metadata.context_shape.external_docs_required or metadata.context_shape.currentness_required:
        surfaces.append(ExecutionSurface.NETWORK.value)
    return {"required": bool(surfaces), "surfaces": surfaces}


def _risk_score(flag: bool) -> int:
    return 5 if flag else 1


def _priority_to_urgency(value: object) -> Urgency:
    priority = _lower_scalar(value)
    if priority == "p0":
        return Urgency.P0
    if priority in {"p1", "high"}:
        return Urgency.HIGH
    if priority in {"p2", "medium"}:
        return Urgency.MEDIUM
    if priority in {"p3", "low"}:
        return Urgency.LOW
    return Urgency.MEDIUM


def _validation_error_messages(exc: ValidationError) -> list[str]:
    messages = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ())) or "route_metadata"
        messages.append(f"{loc}: {error.get('msg', 'invalid route metadata')}")
    return messages


def _lower_scalar(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _lower_strings(value: object) -> set[str]:
    return {item.lower() for item in _coerce_string_list(value)}


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _optional_frontmatter_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "~"}:
        return None
    return text


def _resolve_optional_path(value: object) -> Path | None:
    text = _optional_frontmatter_string(value)
    if text is None:
        return None
    if not _looks_like_path(text):
        return None
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / path


def _looks_like_path(value: str) -> bool:
    if value.startswith(("/", "~", ".")):
        return True
    return "/" in value and not value.startswith(("http://", "https://", "isap:"))


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC, microsecond=0)
    return value.astimezone(UTC).replace(microsecond=0)


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _jsonable_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _jsonable(item) for key, item in value.items()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _jsonable_mapping(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    return value


def _is_empty_frontmatter_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "null", "None"}
    return False


_DEMAND_VECTOR_DYNAMIC_ENTRYPOINTS = (
    build_demand_vector,
    check_demand_vector_freshness,
    stable_payload_hash,
)
