"""Route metadata schema for quality-preserving capacity routing.

This module validates route metadata carried in request or cc-task
frontmatter. It is schema and audit plumbing only; it does not select or
launch routes.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
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


class HardeningIntensity(StrEnum):
    NONE = "none"
    LIGHT = "light"
    TARGETED = "targeted"
    STANDARD = "standard"
    DEEP = "deep"
    BREAK_GLASS = "break_glass"


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


def _coerce_strict_string_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a string or list of strings")
    if isinstance(value, (list, tuple, set, frozenset)):
        out: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                raise ValueError(f"{field_name} must be a string or list of strings")
            out.extend(_coerce_string_list(item))
        return out
    return _coerce_string_list(value)


def _coerce_verification_check_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [] if not text else [{"name": text, "command": text}]
    if isinstance(value, (list, tuple, set, frozenset)):
        out: list[object] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    out.append({"name": text, "command": text})
            elif isinstance(item, Mapping):
                out.append(dict(item))
            elif item is not None:
                text = str(item).strip()
                if text:
                    out.append({"name": text, "command": text})
        return out
    if isinstance(value, Mapping):
        return [dict(value)]
    return [{"name": str(value).strip(), "command": str(value).strip()}]


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


class VerificationCheck(_RouteModel):
    name: str
    command: str | None = None
    contexts: list[str] = Field(default_factory=list)
    blocking: bool | None = None
    touched_path_patterns: list[str] = Field(default_factory=list)

    @field_validator("contexts", mode="before")
    @classmethod
    def _contexts_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_strict_string_list(value, field_name="verification check contexts")

    @field_validator("touched_path_patterns", mode="before")
    @classmethod
    def _touched_path_patterns_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_strict_string_list(
            value, field_name="verification check touched_path_patterns"
        )

    @model_validator(mode="after")
    def _named_check_has_identifier(self) -> Self:
        if not self.name.strip():
            raise ValueError(
                "verification check requires name; add the CI context or command label"
            )
        return self


class BaselineWaiver(_RouteModel):
    waiver_id: str
    check_name: str
    witness: str
    observed_at: datetime
    expires_at: datetime
    tracking_ref: str
    affected_scope: list[str] = Field(default_factory=list)
    rationale: str

    @field_validator("affected_scope", mode="before")
    @classmethod
    def _affected_scope_is_string_list(cls, value: object) -> list[str]:
        return _coerce_strict_string_list(value, field_name="baseline waiver affected_scope")

    @model_validator(mode="after")
    def _waiver_is_auditable_and_expiring(self) -> Self:
        required = {
            "waiver_id": self.waiver_id,
            "check_name": self.check_name,
            "witness": self.witness,
            "tracking_ref": self.tracking_ref,
            "rationale": self.rationale,
        }
        missing = [field for field, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(
                "baseline waiver requires "
                + ",".join(sorted(missing))
                + "; add auditable waiver evidence before treating a failure as advisory"
            )
        if not self.affected_scope:
            raise ValueError(
                "baseline waiver requires affected_scope; add the known failing paths or globs"
            )
        if _coerce_utc(self.expires_at) <= _coerce_utc(self.observed_at):
            raise ValueError(
                "baseline waiver expires_at must be after observed_at; refresh the witness window"
            )
        return self


class VerificationAllocation(_RouteModel):
    request_hardening: HardeningIntensity = HardeningIntensity.LIGHT
    review_intensity: HardeningIntensity = HardeningIntensity.STANDARD
    verifier_intensity: HardeningIntensity = HardeningIntensity.TARGETED
    opportunity_cost: str | None = None
    rationale_refs: list[str] = Field(default_factory=list)

    @field_validator("rationale_refs", mode="before")
    @classmethod
    def _rationale_refs_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_string_list(value)


class VerificationSurface(_RouteModel):
    deterministic_tests: list[str] = Field(default_factory=list)
    static_checks: list[str] = Field(default_factory=list)
    runtime_observation: list[str] = Field(default_factory=list)
    operator_only: bool = False
    focused_checks: list[VerificationCheck] = Field(default_factory=list)
    touched_checks: list[VerificationCheck] = Field(default_factory=list)
    adjacent_checks: list[VerificationCheck] = Field(default_factory=list)
    required_ci_checks: list[VerificationCheck] = Field(default_factory=list)
    full_safety_net_checks: list[VerificationCheck] = Field(default_factory=list)
    baseline_waivers: list[BaselineWaiver] = Field(default_factory=list)
    allocation: VerificationAllocation = Field(default_factory=VerificationAllocation)

    @field_validator("deterministic_tests", "static_checks", "runtime_observation", mode="before")
    @classmethod
    def _lists_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_string_list(value)

    @field_validator(
        "focused_checks",
        "touched_checks",
        "adjacent_checks",
        "required_ci_checks",
        "full_safety_net_checks",
        mode="before",
    )
    @classmethod
    def _checks_are_check_lists(cls, value: object) -> list[object]:
        return _coerce_verification_check_list(value)


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


# The operator-steered execution-axis DEMANDS. The VALUE strings mirror the supply-side
# Effort / ContextMode StrEnums owned by shared.platform_capability_registry — but that module
# is HIGHER (it imports ToolAuthorityUse from here), so this lower module speaks the value strings
# and a drift-pin test binds these tuples to the registry enums (see test_route_metadata_schema).
_EFFORT_DEMAND_VALUES = ("none", "low", "medium", "high", "xhigh", "max")
_CONTEXT_MODE_DEMAND_VALUES = ("standard", "extended_1m", "not_applicable")


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
    # conditional execution-axis demands; None = undemanded (the non-perturbation default)
    effort_demand: str | None = None
    context_mode_demand: str | None = None

    @field_validator("effort_demand")
    @classmethod
    def _effort_demand_in_vocab(cls, value: str | None) -> str | None:
        if value is not None and value not in _EFFORT_DEMAND_VALUES:
            raise ValueError(
                f"effort_demand {value!r} is not a known effort; "
                f"use one of {_EFFORT_DEMAND_VALUES} or omit it"
            )
        return value

    @field_validator("context_mode_demand")
    @classmethod
    def _context_mode_demand_in_vocab(cls, value: str | None) -> str | None:
        if value is not None and value not in _CONTEXT_MODE_DEMAND_VALUES:
            raise ValueError(
                f"context_mode_demand {value!r} is not a known context mode; "
                f"use one of {_CONTEXT_MODE_DEMAND_VALUES} or omit it"
            )
        return value


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


class CloudBurst(_RouteModel):
    eligible: bool = False
    spike_reasons: list[str] = Field(default_factory=list)
    parallelism: int = Field(default=1, ge=1)
    agent_fanout: int = Field(default=1, ge=1)
    ci_matrix: bool = False
    release_or_ci_spend: bool = False
    costly_class: bool = False
    public_repo_only: bool = False
    read_mostly: bool = False
    no_secret_egress: bool = True
    provider_budget_ref: str | None = None

    @field_validator("spike_reasons", mode="before")
    @classmethod
    def _spike_reasons_are_string_lists(cls, value: object) -> list[str]:
        return _coerce_string_list(value)

    @model_validator(mode="after")
    def _eligible_requires_reasons_and_no_secret_egress(self) -> Self:
        if not self.eligible:
            return self
        if not self.spike_reasons:
            raise ValueError("cloud_burst eligibility requires spike_reasons")
        if not self.no_secret_egress:
            raise ValueError("cloud_burst eligibility requires no_secret_egress")
        return self


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
    cloud_burst: CloudBurst = Field(default_factory=CloudBurst)

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
    VerificationCheck._contexts_are_string_lists,
    VerificationCheck._touched_path_patterns_are_string_lists,
    VerificationCheck._named_check_has_identifier,
    BaselineWaiver._affected_scope_is_string_list,
    BaselineWaiver._waiver_is_auditable_and_expiring,
    VerificationAllocation._rationale_refs_are_string_lists,
    VerificationSurface._lists_are_string_lists,
    VerificationSurface._checks_are_check_lists,
    VerificationDemand._lists_are_string_lists,
    PriorityContext._value_braid_refs_are_string_lists,
    DemandVector._mutation_scope_refs_are_strings,
    RouteConstraints._lists_are_string_lists,
    RouteMetadata._mutation_scope_refs_are_strings,
    RouteMetadata._support_outputs_need_review,
    RouteMetadataAssessment.planning_status,
    CloudBurst._spike_reasons_are_string_lists,
    CloudBurst._eligible_requires_reasons_and_no_secret_egress,
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
        "cloud_burst",
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
    payload["cloud_burst"] = _derive_cloud_burst(frontmatter, payload["risk_flags"])
    derived_fields.append("cloud_burst")
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
        "audio_or_live_egress_sensitive": _contains_audio_or_live_egress_marker(combined),
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


VERIFICATION_CHECK_GROUPS = (
    "focused_checks",
    "touched_checks",
    "adjacent_checks",
    "required_ci_checks",
    "full_safety_net_checks",
)
SAFETY_NET_CHECK_GROUP = "full_safety_net_checks"


def verification_surface_from_frontmatter(frontmatter: Mapping[str, Any]) -> VerificationSurface:
    """Return the task verification contract, preserving legacy flat fields."""

    payload: dict[str, Any] = {}
    nested = frontmatter.get("route_metadata")
    if isinstance(nested, Mapping) and "verification_surface" in nested:
        nested_surface = nested.get("verification_surface")
        if isinstance(nested_surface, Mapping):
            payload.update(dict(nested_surface))
        elif nested_surface is not None:
            raise ValueError("route_metadata.verification_surface must be a mapping")
    surface = frontmatter.get("verification_surface")
    if isinstance(surface, Mapping):
        payload.update(dict(surface))
    elif "verification_surface" in frontmatter and surface is not None:
        raise ValueError("verification_surface must be a mapping")
    else:
        for key in ("deterministic_tests", "static_checks", "runtime_observation"):
            if key in frontmatter:
                payload[key] = frontmatter[key]
        if "operator_only" in frontmatter:
            payload["operator_only"] = frontmatter["operator_only"]
    if not payload:
        payload = _derive_verification_surface(frontmatter)
    return VerificationSurface.model_validate(payload)


def _verification_contract_error_messages(exc: ValidationError | ValueError) -> list[str]:
    if isinstance(exc, ValidationError):
        return _validation_error_messages(exc)
    return [str(exc)]


def verification_contract_structure_blockers(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    """Static malformed-contract blockers.

    Expiry is assessed only when a waiver is used for an observed safety-net
    failure; this structural check catches unauditable waiver shapes up front.
    """

    try:
        verification_surface_from_frontmatter(frontmatter)
    except (ValidationError, ValueError) as exc:
        return tuple(
            f"verification_contract_malformed:{msg}"
            for msg in _verification_contract_error_messages(exc)
        )
    return ()


def _verification_checks(surface: VerificationSurface) -> tuple[tuple[str, VerificationCheck], ...]:
    out: list[tuple[str, VerificationCheck]] = []
    for group in VERIFICATION_CHECK_GROUPS:
        out.extend((group, check) for check in getattr(surface, group))
    return tuple(out)


def _check_identifiers(check: VerificationCheck) -> frozenset[str]:
    identifiers = _coerce_string_list([check.name, check.command, *check.contexts])
    return frozenset(item.lower() for item in identifiers)


def _match_failed_check(
    failed_check: str, checks: tuple[tuple[str, VerificationCheck], ...]
) -> tuple[str, VerificationCheck] | None:
    needle = failed_check.strip().lower()
    for group, check in checks:
        if needle in _check_identifiers(check):
            return group, check
    return None


def _check_blocks_by_default(group: str, check: VerificationCheck) -> bool:
    if group != SAFETY_NET_CHECK_GROUP:
        return True
    if check.blocking is not None:
        return check.blocking
    return False


def _repo_relative_path(value: str) -> str:
    text = value.strip()
    worktree_match = re.search(r"/hapax-council(?:--[^/]+)?/", text)
    if worktree_match is not None:
        return text[worktree_match.end() :]
    if text.startswith("~/projects/hapax-council/"):
        return text.split("~/projects/hapax-council/", 1)[1]
    shorthand_match = re.match(r"~/projects/hapax-council--[^/]+/(.+)", text)
    if shorthand_match is not None:
        return shorthand_match.group(1)
    return text


def _path_pattern_matches(path: str, pattern: str) -> bool:
    candidates = {_repo_relative_path(path), path.strip()}
    patterns = {_repo_relative_path(pattern), pattern.strip()}
    for candidate in candidates:
        for pat in patterns:
            if not candidate or not pat:
                continue
            if pat in {".", "*", "**", "**/*"}:
                return True
            if pat.endswith("/**"):
                prefix = pat[:-3]
                if candidate == prefix or candidate.startswith(prefix + "/"):
                    return True
            if "**" in pat and _globstar_match(candidate, pat):
                return True
            if fnmatch.fnmatch(candidate, pat):
                return True
    return False


def _globstar_match(candidate: str, pattern: str) -> bool:
    regex = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern[index : index + 3] == "**/":
            # Recursive segment may match zero directories, e.g. agents/**/x -> agents/x.
            regex.append("(?:.*/)?")
            index += 3
        elif pattern[index : index + 2] == "**":
            regex.append(".*")
            index += 2
        elif char == "*":
            regex.append("[^/]*")
            index += 1
        elif char == "?":
            regex.append("[^/]")
            index += 1
        else:
            regex.append(re.escape(char))
            index += 1
    return re.fullmatch("".join(regex), candidate) is not None


def _scope_implicated(
    touched_paths: tuple[str, ...] | None, patterns: tuple[str, ...]
) -> bool | None:
    if touched_paths is None or not touched_paths:
        return None
    return any(
        _path_pattern_matches(path, pattern) for path in touched_paths for pattern in patterns
    )


def _current_matching_waivers(
    surface: VerificationSurface,
    check: VerificationCheck,
    *,
    now: datetime,
) -> tuple[tuple[BaselineWaiver, ...], str | None]:
    checked_at = _coerce_utc(now)
    matching = _matching_waivers(surface, check)
    if not matching:
        return (), "missing"
    future = [waiver for waiver in matching if _coerce_utc(waiver.observed_at) > checked_at]
    expired = [waiver for waiver in matching if _coerce_utc(waiver.expires_at) <= checked_at]
    current = [
        waiver
        for waiver in matching
        if _coerce_utc(waiver.observed_at) <= checked_at < _coerce_utc(waiver.expires_at)
    ]
    if current:
        return tuple(current), None
    if future:
        return (), "not_yet_observed:" + ",".join(waiver.waiver_id for waiver in future)
    return (), "expired:" + ",".join(waiver.waiver_id for waiver in expired)


def _matching_waivers(
    surface: VerificationSurface, check: VerificationCheck
) -> tuple[BaselineWaiver, ...]:
    identifiers = _check_identifiers(check)
    return tuple(
        waiver
        for waiver in surface.baseline_waivers
        if waiver.check_name.strip().lower() in identifiers
    )


def _implicated_stale_waiver_state(
    surface: VerificationSurface,
    check: VerificationCheck,
    *,
    touched_paths: tuple[str, ...] | None,
    now: datetime,
) -> str | None:
    checked_at = _coerce_utc(now)
    matching = _matching_waivers(surface, check)
    stale_groups = (
        (
            "not_yet_observed",
            tuple(waiver for waiver in matching if _coerce_utc(waiver.observed_at) > checked_at),
        ),
        (
            "expired",
            tuple(waiver for waiver in matching if _coerce_utc(waiver.expires_at) <= checked_at),
        ),
    )
    for state, waivers in stale_groups:
        implicated_ids = []
        for waiver in waivers:
            scope_patterns = tuple([*waiver.affected_scope, *check.touched_path_patterns])
            if _scope_implicated(touched_paths, scope_patterns):
                implicated_ids.append(waiver.waiver_id)
        if implicated_ids:
            return f"{state}:{','.join(implicated_ids)}"
    return None


def _verification_check_summary(group: str, check: VerificationCheck) -> dict[str, Any]:
    return {
        "name": check.name,
        "command": check.command,
        "contexts": check.contexts,
        "blocking": check.blocking,
        "effective_blocking": _check_blocks_by_default(group, check),
        "touched_path_patterns": check.touched_path_patterns,
    }


def verification_failure_blockers(
    frontmatter: Mapping[str, Any],
    *,
    failed_checks: list[str] | tuple[str, ...],
    touched_paths: list[str] | tuple[str, ...] | None = None,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Admission/closure blockers from observed failed verification checks.

    Unknown failed checks block. Declared full safety-net checks may be advisory
    only when a current baseline waiver proves an auditable, out-of-scope
    baseline failure.
    """

    failed = tuple(item for item in _coerce_string_list(failed_checks) if item)
    if not failed:
        return ()
    try:
        surface = verification_surface_from_frontmatter(frontmatter)
    except (ValidationError, ValueError) as exc:
        return tuple(
            f"verification_contract_malformed:{msg}"
            for msg in _verification_contract_error_messages(exc)
        )

    checks = _verification_checks(surface)
    changed = tuple(_coerce_string_list(touched_paths)) if touched_paths is not None else None
    checked_at = _coerce_utc(now)
    blockers: list[str] = []
    for failed_check in failed:
        matched = _match_failed_check(failed_check, checks)
        if matched is None:
            blockers.append(f"verification_failed_check:{failed_check}")
            continue
        group, check = matched
        if group != SAFETY_NET_CHECK_GROUP:
            if _check_blocks_by_default(group, check):
                blockers.append(f"verification_failed_check:{failed_check}")
            continue
        if _check_blocks_by_default(group, check):
            blockers.append(f"verification_safety_net_opted_in:{failed_check}")
            continue
        waivers, waiver_state = _current_matching_waivers(surface, check, now=checked_at)
        if not waivers:
            state = waiver_state or "missing"
            blockers.append(f"verification_safety_net_unwaived:{failed_check}:{state}")
            continue
        stale_waiver_state = _implicated_stale_waiver_state(
            surface,
            check,
            touched_paths=changed,
            now=checked_at,
        )
        if stale_waiver_state:
            blockers.append(f"verification_safety_net_unwaived:{failed_check}:{stale_waiver_state}")
            continue
        scope_unknown = False
        for waiver in waivers:
            scope_patterns = tuple([*waiver.affected_scope, *check.touched_path_patterns])
            implicated = _scope_implicated(changed, scope_patterns)
            if implicated is None:
                scope_unknown = True
                continue
            if implicated:
                blockers.append(
                    f"verification_safety_net_implicated:{failed_check}:{waiver.waiver_id}"
                )
                break
        else:
            if scope_unknown:
                blockers.append(f"verification_safety_net_scope_unknown:{failed_check}")
    return tuple(blockers)


def required_ci_check_contexts(
    frontmatter: Mapping[str, Any], *, default: tuple[str, ...] = ()
) -> tuple[str, ...]:
    try:
        surface = verification_surface_from_frontmatter(frontmatter)
    except (ValidationError, ValueError):
        return default
    contexts: list[str] = []
    for check in surface.required_ci_checks:
        contexts.extend(check.contexts or [check.name])
    return tuple(dict.fromkeys(contexts)) or default


def verification_contract_summary(frontmatter: Mapping[str, Any]) -> dict[str, Any]:
    try:
        surface = verification_surface_from_frontmatter(frontmatter)
    except (ValidationError, ValueError) as exc:
        return {
            "status": "malformed",
            "errors": _verification_contract_error_messages(exc),
        }
    return {
        "status": "valid",
        "focused_checks": [check.name for check in surface.focused_checks],
        "touched_checks": [check.name for check in surface.touched_checks],
        "adjacent_checks": [check.name for check in surface.adjacent_checks],
        "required_ci_checks": [check.name for check in surface.required_ci_checks],
        "full_safety_net_checks": [check.name for check in surface.full_safety_net_checks],
        "baseline_waivers": [
            {
                "waiver_id": waiver.waiver_id,
                "check_name": waiver.check_name,
                "witness": waiver.witness,
                "observed_at": _coerce_utc(waiver.observed_at).isoformat().replace("+00:00", "Z"),
                "expires_at": _coerce_utc(waiver.expires_at).isoformat().replace("+00:00", "Z"),
                "tracking_ref": waiver.tracking_ref,
                "affected_scope": waiver.affected_scope,
                "rationale": waiver.rationale,
            }
            for waiver in surface.baseline_waivers
        ],
        "check_details": {
            group: [_verification_check_summary(group, check) for check in getattr(surface, group)]
            for group in VERIFICATION_CHECK_GROUPS
        },
        "allocation": surface.allocation.model_dump(mode="json"),
    }


def _derive_review_requirement(quality_floor: QualityFloor | None) -> dict[str, object]:
    if quality_floor != QualityFloor.FRONTIER_REVIEW_REQUIRED:
        return {}
    return {
        "support_artifact_allowed": True,
        "independent_review_required": True,
        "authoritative_acceptor_profile": "frontier_full",
    }


HIGH_PARALLELISM_THRESHOLD = 8
MULTI_AGENT_FANOUT_THRESHOLD = 4


def _derive_cloud_burst(
    frontmatter: Mapping[str, Any],
    risk_flags: Mapping[str, bool],
) -> dict[str, object]:
    tags = _lower_strings(frontmatter.get("tags"))
    title = _lower_scalar(frontmatter.get("title"))
    combined = " ".join([title, *tags])
    parallelism = max(
        1,
        _int_or_none(
            frontmatter.get("parallelism")
            or frontmatter.get("estimated_parallel_jobs")
            or frontmatter.get("parallel_jobs")
        )
        or 1,
    )
    agent_fanout = max(
        1,
        _int_or_none(
            frontmatter.get("agent_fanout")
            or frontmatter.get("multi_agent_fanout")
            or frontmatter.get("fanout")
        )
        or 1,
    )
    ci_matrix = _boolish(frontmatter.get("ci_matrix")) or _contains_any(
        combined,
        ("matrix",),
    )
    release_or_ci_spend = _boolish(
        frontmatter.get("release_or_ci_spend") or frontmatter.get("release")
    ) or _contains_any(combined, ("release", "ci"))
    costly_class = _boolish(frontmatter.get("costly_class")) or _contains_any(
        combined,
        ("spike", "costly", "expensive", "fanout", "parallelism", "benchmark"),
    )

    spike_reasons: list[str] = []
    if parallelism >= HIGH_PARALLELISM_THRESHOLD:
        spike_reasons.append(f"high_parallelism:{parallelism}")
    if agent_fanout >= MULTI_AGENT_FANOUT_THRESHOLD:
        spike_reasons.append(f"multi_agent_fanout:{agent_fanout}")
    if ci_matrix:
        spike_reasons.append("ci_matrix")
    if release_or_ci_spend:
        spike_reasons.append("release_or_ci_spend")
    if costly_class:
        spike_reasons.append("costly_class")

    explicit = frontmatter.get("cloud_burst")
    if isinstance(explicit, Mapping):
        payload = dict(explicit)
        explicit_reasons = _coerce_string_list(payload.get("spike_reasons"))
        if explicit_reasons:
            spike_reasons = list(dict.fromkeys([*spike_reasons, *explicit_reasons]))
        parallelism = max(parallelism, _int_or_none(payload.get("parallelism")) or 1)
        agent_fanout = max(agent_fanout, _int_or_none(payload.get("agent_fanout")) or 1)
        ci_matrix = ci_matrix or _boolish(payload.get("ci_matrix"))
        release_or_ci_spend = release_or_ci_spend or _boolish(payload.get("release_or_ci_spend"))
        costly_class = costly_class or _boolish(payload.get("costly_class"))

    public_repo_only = _boolish(
        frontmatter.get("public_repo_only")
        or frontmatter.get("cloud_burst_public_repo_only")
        or ("public-repo" in tags)
        or ("public_repo" in tags)
    )
    read_mostly = _boolish(
        frontmatter.get("read_mostly")
        or frontmatter.get("cloud_burst_read_mostly")
        or ("read-mostly" in tags)
        or ("read_mostly" in tags)
    )
    no_secret_egress = not bool(risk_flags.get("privacy_or_secret_sensitive"))
    if "secret-egress" in tags or "secret_egress" in tags:
        no_secret_egress = False
    explicit_no_secret = frontmatter.get("no_secret_egress") or frontmatter.get(
        "cloud_burst_no_secret_egress"
    )
    if explicit_no_secret is not None:
        no_secret_egress = _boolish(explicit_no_secret)

    provider_budget_ref = _optional_frontmatter_string(
        frontmatter.get("cloud_burst_budget_ref")
        or frontmatter.get("provider_budget_ref")
        or frontmatter.get("budget_ref")
    )
    eligible = bool(spike_reasons)

    if isinstance(explicit, Mapping):
        if "eligible" in explicit:
            eligible = _boolish(explicit.get("eligible"))
        public_repo_only = _boolish(explicit.get("public_repo_only")) or public_repo_only
        read_mostly = _boolish(explicit.get("read_mostly")) or read_mostly
        if "no_secret_egress" in explicit:
            no_secret_egress = _boolish(explicit.get("no_secret_egress"))
        provider_budget_ref = (
            _optional_frontmatter_string(explicit.get("provider_budget_ref")) or provider_budget_ref
        )

    return {
        "eligible": eligible,
        "spike_reasons": spike_reasons,
        "parallelism": parallelism,
        "agent_fanout": agent_fanout,
        "ci_matrix": ci_matrix,
        "release_or_ci_spend": release_or_ci_spend,
        "costly_class": costly_class,
        "public_repo_only": public_repo_only,
        "read_mostly": read_mostly,
        "no_secret_egress": no_secret_egress,
        "provider_budget_ref": provider_budget_ref,
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


#: Alphanumeric token boundary for risk-flag keyword matching. Tokenizing
#: (rather than raw substring) prevents 'egress' matching inside 'regression'
#: or 'live' inside 'deliver' — false positives that wrongly mark routine
#: tasks audio/live/egress sensitive and veto their system auto-arm.
_RISK_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GO_LIVE_RE = re.compile(r"\bgo[-_\s]+live\b")


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    tokens = set(_RISK_TOKEN_RE.findall(value.lower()))
    return any(needle in tokens for needle in needles)


def _contains_audio_or_live_egress_marker(value: str) -> bool:
    # "go-live" is the SDLC/program milestone phrase, not evidence that the task
    # mutates a live public/audio egress surface.
    without_go_live = _GO_LIVE_RE.sub("golive", value.lower())
    return _contains_any(without_go_live, ("audio", "egress", "live"))


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


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


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
