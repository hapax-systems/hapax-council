"""Route metadata schema for quality-preserving capacity routing.

This module validates route metadata carried in request or cc-task
frontmatter. It is schema and audit plumbing only; it does not select or
launch routes.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
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


class CodebaseLocality(StrEnum):
    NONE = "none"
    SINGLE_FILE = "single_file"
    MODULE = "module"
    CROSS_MODULE = "cross_module"
    CROSS_REPO = "cross_repo"


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


def _is_empty_frontmatter_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "null", "None"}
    return False
