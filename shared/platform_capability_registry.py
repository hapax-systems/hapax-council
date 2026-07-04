"""Typed platform capability registry and freshness checks.

The registry is inert metadata. It describes sanctioned platform routes and
their checked state; it does not grant task authority or choose dispatch
routes.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.platform_capability_receipts import (
    DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR,
    PLATFORM_CAPABILITY_RECEIPT_DIR_ENV,
    EvidenceStatus,
    PlatformCapabilityReceipt,
    load_platform_capability_receipts,
    receipt_reference,
)
from shared.route_metadata_schema import (
    BenchmarkCoverage,
    FixedRouteOverhead,
    LocalCalibrationProvenance,
    ToolAuthorityUse,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_CAPABILITY_REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"

CAPACITY_INVARIANT = (
    "Default to maximum appropriate quality-preserving utilization. No quality "
    "degradation is permitted. Capacity may be reduced only by task-platform fit, "
    "quota state, resource contention, or explicit operator hold."
)

REQUIRED_ROUTE_IDS = frozenset(
    {
        "api.headless.api_frontier",
        "api.headless.provider_gateway",
        "claude.headless.full",
        "claude.headless.haiku",
        "claude.headless.opus",
        "claude.headless.sonnet",
        "claude.interactive.full",
        "codex.headless.full",
        "codex.headless.spark",
        "glmcp.review.direct",
        "local_tool.local.worker",
        "vibe.headless.full",
    }
)

UNKNOWN_TELEMETRY_SOURCES = frozenset({"none", "unknown"})
UNKNOWN_PRIVACY_POSTURES = frozenset({"unknown", "public_risk"})
_DURATION_RE = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>s|m|h|d)$")


class PlatformCapabilityRegistryError(ValueError):
    """Raised when the platform capability registry fails closed."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Platform(StrEnum):
    ANTIGRAV = "antigrav"
    API = "api"
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    GLMCP = "glmcp"
    LOCAL_TOOL = "local_tool"
    VIBE = "vibe"


class Mode(StrEnum):
    HEADLESS = "headless"
    INTERACTIVE = "interactive"
    LOCAL = "local"
    RECEIPT_ONLY = "receipt_only"
    REVIEW = "review"


class Profile(StrEnum):
    API_FRONTIER = "api_frontier"
    DETERMINISTIC = "deterministic"
    DIRECT = "direct"
    FLASH = "flash"
    FULL = "full"
    HAIKU = "haiku"
    JR = "jr"
    LITE = "lite"
    OPUS = "opus"
    PROVIDER_GATEWAY = "provider_gateway"
    SONNET = "sonnet"
    SPARK = "spark"
    WORKER = "worker"


class Effort(StrEnum):
    """Reasoning-effort axis (operator-steered; today smuggled into launchers/model strings)."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ContextMode(StrEnum):
    """Context-window mode: standard vs an extended (e.g. 1M) variant of the same model."""

    STANDARD = "standard"
    EXTENDED_1M = "extended_1m"
    NOT_APPLICABLE = "not_applicable"


class FastMode(StrEnum):
    """Opus faster-output mode (a client-side harness flag today)."""

    OFF = "off"
    FAST = "fast"
    NOT_APPLICABLE = "not_applicable"


class Quantization(StrEnum):
    """Local-inference quantization (EXL3 bits-per-weight); not_applicable for hosted models."""

    NONE = "none"
    EXL3_4_0BPW = "exl3_4_0bpw"
    EXL3_5_0BPW = "exl3_5_0bpw"
    NOT_APPLICABLE = "not_applicable"


class ModelId(StrEnum):
    """Closed catalog of dated, concrete model identities — the structured replacement for the
    coarse free-text ``model_or_engine``. A provider model swap is one enum edit here.
    ``UNKNOWN`` covers routes whose backing model is not a single dated identity (e.g. a
    receipt-only maintenance route)."""

    CLAUDE_OPUS_4_8 = "claude-opus-4-8"
    CLAUDE_SONNET_4_6 = "claude-sonnet-4-6"
    CLAUDE_SONNET_5 = "claude-sonnet-5"
    CLAUDE_HAIKU_4_5 = "claude-haiku-4-5"
    CLAUDE_FABLE_5 = "claude-fable-5"
    GPT_5_5 = "gpt-5.5"
    GPT_5_3_CODEX_SPARK = "gpt-5.3-codex-spark"
    COMMAND_R_08_2024 = "command-r-08-2024"
    QWEN3_5_9B = "qwen3.5-9b"
    MISTRAL_MEDIUM_3_5 = "mistral-medium-3.5"
    GEMINI_3_1_PRO_PREVIEW = "gemini-3.1-pro-preview"
    Z_AI_GLM_5 = "z_ai-glm-5"
    UNKNOWN = "unknown"


class RouteState(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class CapabilityShapeClass(StrEnum):
    MODEL_PROVIDER = "model_provider"
    LOCAL_COMPUTE = "local_compute"
    PUBLICATION_BUS = "publication_bus"
    MONEY_RAIL = "money_rail"
    MCP_CONNECTOR = "mcp_connector"
    ORCHESTRATOR = "orchestrator"
    SUBAGENT = "subagent"
    COCKPIT_COMMAND = "cockpit_command"
    CCTV_RUNNER = "cctv_runner"
    SELF_INLINE = "self_inline"


class CapabilityShapeState(StrEnum):
    EVIDENCE_ONLY = "evidence_only"
    INTAKE_REQUIRED = "intake_required"
    MEASUREMENT_PENDING = "measurement_pending"
    DEPRECATED = "deprecated"


class CapabilitySurfaceDeltaAction(StrEnum):
    KNOWN_HOLD_FOR_MEASUREMENT = "known_hold_for_measurement"
    MINT_INTAKE = "mint_intake"
    DEPRECATED_REFUSE = "deprecated_refuse"


class CapabilityShapeFreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    ASSERTED_ONLY = "asserted_only"
    CONTRADICTORY = "contradictory"


class AuthSurface(StrEnum):
    API_KEY = "api_key"
    LOCAL = "local"
    OPERATOR_SESSION = "operator_session"
    SUBSCRIPTION = "subscription"
    UNKNOWN = "unknown"
    VERTEX = "vertex"


class CapacityPool(StrEnum):
    API_PAID_SPEND = "api_paid_spend"
    BOOTSTRAP_BUDGET = "bootstrap_budget"
    LOCAL_COMPUTE = "local_compute"
    SUBSCRIPTION_QUOTA = "subscription_quota"


class AuthorityCeiling(StrEnum):
    AUTHORITATIVE = "authoritative"
    FRONTIER_REVIEW_REQUIRED = "frontier_review_required"
    READ_ONLY = "read_only"
    SUPPORT_ONLY = "support_only"


class FilesystemAccess(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


class ShellAccess(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"
    FULL = "full"


class PrivacyPosture(StrEnum):
    LOCAL_PRIVATE = "local_private"
    PROVIDER_PRIVATE = "provider_private"
    PROVIDER_TRAINING_UNKNOWN = "provider_training_unknown"
    PUBLIC_RISK = "public_risk"
    UNKNOWN = "unknown"


class QualityFloor(StrEnum):
    DETERMINISTIC_OK = "deterministic_ok"
    FRONTIER_REQUIRED = "frontier_required"
    FRONTIER_REVIEW_REQUIRED = "frontier_review_required"


class ContextClass(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VERY_LARGE = "very_large"
    UNKNOWN = "unknown"


class QuotaSource(StrEnum):
    CLI = "cli"
    CLOUD_MONITORING = "cloud_monitoring"
    LEDGER = "ledger"
    MANUAL = "manual"
    NONE = "none"
    OTEL = "otel"
    PROVIDER_CONSOLE = "provider_console"
    UNKNOWN = "unknown"


class CostSource(StrEnum):
    ESTIMATED = "estimated"
    LEDGER = "ledger"
    NONE = "none"
    OTEL = "otel"
    PROVIDER_USAGE = "provider_usage"
    UNKNOWN = "unknown"


class ResourceSource(StrEnum):
    INFRA_OBSERVATION_SPINE = "infra_observation_spine"
    LOCAL_PROBE = "local_probe"
    NONE = "none"
    UNKNOWN = "unknown"


class ApprovalPosture(StrEnum):
    AUTO_EDIT_POLICY_FIREWALLED = "auto_edit_policy_firewalled"
    DEFAULT_DENY_ENABLE_LATCH = "default_deny_enable_latch"
    IDE_TERMINAL_AUTO_APPROVE = "ide_terminal_auto_approve"
    NO_ASK_HOOKS_ENFORCED = "no_ask_hooks_enforced"
    PLAN_MODE_READ_ONLY = "plan_mode_read_only"
    PROGRAMMATIC_AUTO_APPROVE_TASK_SCOPED = "programmatic_auto_approve_task_scoped"
    UNKNOWN = "unknown"


class CapabilityTier(StrEnum):
    AUDITED_FULL_WORKER = "audited_full_worker"
    FRONTIER_FALLBACK = "frontier_fallback"
    FRONTIER_FULL = "frontier_full"
    JR_PLUS = "jr_plus"
    READ_ONLY_SUPPORT = "read_only_support"


class WorkerTier(StrEnum):
    AUDITED_FULL_WORKER = "audited_full_worker"
    BOUNDED_WORKER = "bounded_worker"
    FALLBACK_WORKER = "fallback_worker"
    FULL_WORKER = "full_worker"
    READ_ONLY_SIDECAR = "read_only_sidecar"


class Mutability(StrictModel):
    vault_docs: bool
    source: bool
    runtime: bool
    public: bool
    provider_spend: bool

    def any_mutation(self) -> bool:
        return self.vault_docs or self.source or self.runtime or self.public or self.provider_spend


class ToolAccess(StrictModel):
    filesystem: FilesystemAccess
    shell: ShellAccess
    browser: bool
    mcp: list[str] = Field(default_factory=list)


class ExecutionDescriptor(StrictModel):
    """The operator-steered execution axes a capability is selected on, beyond
    ``platform.mode.profile``. These were previously absent from the governed plane
    (effort/fast-mode/quantization) or coarse (a single ``max_context_class`` enum, a
    free-text ``model_or_engine``). Modeled here so a capability is the FULL descriptor;
    the 3-segment ``route_id`` stays the human key (no combinatorial blow-up)."""

    model_id: ModelId
    effort: Effort
    context_mode: ContextMode = ContextMode.STANDARD
    fast_mode: FastMode = FastMode.OFF
    quantization: Quantization = Quantization.NONE


class DescriptorVariant(StrictModel):
    """A materially-different (model, effort, context, …) leaf of a route, carried sparsely:
    a variant exists only where a knob change crosses an authority/quality/quota boundary or
    shifts a capability score. ``score_delta`` overrides specific scores; otherwise the leaf
    inherits the route scores with explicit ``scores_inherited_from`` provenance (never a
    fabricated per-knob number)."""

    variant_id: str
    knobs_override: dict[str, str] = Field(default_factory=dict)
    score_delta: dict[str, int] = Field(default_factory=dict)
    scores_inherited_from: str | None = None
    blocked_reasons: list[str] = Field(default_factory=list)


class CapabilityShapeDescriptor(StrictModel):
    """Evidence-only descriptor for an observed but not-yet-admitted capability surface.

    These records intentionally do not extend ``routes``. They let deterministic surface
    deltas create intake/remediation work without letting carrier labels such as
    "publication bus" or "OpenRouter" satisfy demand before measured supply leaves and
    receipts exist.
    """

    descriptor_schema: Literal[1] = 1
    shape_id: str
    shape_class: CapabilityShapeClass
    carrier_family: str
    summary: str
    harness_shape: str
    authority_ceiling: AuthorityCeiling
    shape_state: CapabilityShapeState
    demand_eligible: bool = False
    route_ids: list[str] = Field(default_factory=list)
    resource_semantics: list[str] = Field(min_length=1)
    spend_semantics: list[str] = Field(min_length=1)
    observability: list[str] = Field(min_length=1)
    failure_classes: list[str] = Field(min_length=1)
    measurement_plan_refs: list[str] = Field(min_length=1)
    remediation_refs: list[str] = Field(min_length=1)
    surface_delta_signal: str
    observed_at: datetime | None
    stale_after: str
    freshness_state: CapabilityShapeFreshnessState
    evidence_refs: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _omitted_shape_is_not_supply(self) -> Self:
        parse_duration_spec(self.stale_after)
        if self.demand_eligible:
            raise ValueError(
                "omitted capability shape descriptors cannot be demand_eligible; "
                "admit measured supply as a route leaf instead"
            )
        if self.route_ids:
            raise ValueError(
                "omitted capability shape descriptors cannot carry route_ids; link them "
                "through remediation/measurement refs until admitted supply exists"
            )
        if self.shape_state is CapabilityShapeState.DEPRECATED and not any(
            "deprecated" in reason or "retired" in reason for reason in self.blocked_reasons
        ):
            raise ValueError(
                "deprecated capability shapes must declare a deprecated/retired blocker"
            )
        if self.observed_at is None and not self.blocked_reasons:
            raise ValueError("unobserved capability shapes require blocked_reasons")
        if self.observed_at is not None and not self.evidence_refs:
            raise ValueError("observed capability shapes require evidence_refs")
        return self


class CapabilitySurfaceDelta(StrictModel):
    """Deterministic signal that a capability surface exists or materially changed."""

    surface_id: str
    shape_class: CapabilityShapeClass
    carrier_family: str
    observed_at: datetime
    evidence_refs: list[str] = Field(min_length=1)
    material_change: bool = True


class CapabilitySurfaceDisposition(StrictModel):
    surface_id: str
    action: CapabilitySurfaceDeltaAction
    demand_eligible: Literal[False] = False
    descriptor_id: str | None = None
    reason_codes: tuple[str, ...]
    remediation_refs: tuple[str, ...]


class QualityEnvelope(StrictModel):
    eligible_quality_floors: list[QualityFloor] = Field(min_length=1)
    explicit_equivalence_records: list[str] = Field(default_factory=list)
    excluded_task_classes: list[str] = Field(default_factory=list)


class ContextLimits(StrictModel):
    max_context_class: ContextClass


class Telemetry(StrictModel):
    quota_source: QuotaSource
    cost_source: CostSource
    resource_source: ResourceSource


FRESHNESS_SURFACES = ("capability", "quota", "resource", "provider_docs")


class FreshnessSurfaceEvidence(StrictModel):
    evidence_refs: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _has_evidence_or_blocker(self) -> Self:
        if not self.evidence_refs and not self.blocked_reasons:
            raise ValueError("freshness surface requires evidence_refs or blocked_reasons")
        return self


class FreshnessEvidence(StrictModel):
    capability: FreshnessSurfaceEvidence
    quota: FreshnessSurfaceEvidence
    resource: FreshnessSurfaceEvidence
    provider_docs: FreshnessSurfaceEvidence

    def surface(self, surface: str) -> FreshnessSurfaceEvidence:
        return getattr(self, surface)

    def all_evidence_refs(self) -> tuple[str, ...]:
        refs: list[str] = []
        for surface in FRESHNESS_SURFACES:
            refs.extend(self.surface(surface).evidence_refs)
        return tuple(dict.fromkeys(refs))

    def all_blocked_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for surface in FRESHNESS_SURFACES:
            reasons.extend(self.surface(surface).blocked_reasons)
        return tuple(dict.fromkeys(reasons))


class Freshness(StrictModel):
    capability_checked_at: datetime | None
    capability_stale_after: str
    quota_checked_at: datetime | None
    quota_stale_after: str
    resource_checked_at: datetime | None
    resource_stale_after: str
    provider_docs_checked_at: datetime | None
    provider_docs_stale_after: str
    evidence: FreshnessEvidence

    @model_validator(mode="after")
    def _duration_specs_are_valid(self) -> Self:
        for surface in FRESHNESS_SURFACES:
            parse_duration_spec(getattr(self, f"{surface}_stale_after"))
            checked_at = getattr(self, f"{surface}_checked_at")
            surface_evidence = self.evidence.surface(surface)
            if checked_at is None and not surface_evidence.blocked_reasons:
                raise ValueError(
                    f"{surface} freshness requires blocked_reasons when checked_at is null"
                )
            if checked_at is not None and not surface_evidence.evidence_refs:
                raise ValueError(
                    f"{surface} freshness requires evidence_refs when checked_at is set"
                )
        return self


class ScoreConfidence(StrictModel):
    score: int = Field(ge=0, le=5)
    confidence: int = Field(ge=0, le=5)
    evidence_refs: list[str] = Field(default_factory=list)
    observed_at: datetime | None
    stale_after: str

    @model_validator(mode="after")
    def _score_evidence_is_freshness_typed(self) -> Self:
        parse_duration_spec(self.stale_after)
        if self.confidence > 0 and not self.evidence_refs:
            raise ValueError("score confidence requires at least one evidence_ref")
        return self


class CapabilityScores(StrictModel):
    grounding: ScoreConfidence
    governance_reasoning: ScoreConfidence
    source_editing: ScoreConfidence
    architecture: ScoreConfidence
    ambiguity_resolution: ScoreConfidence
    long_context: ScoreConfidence
    current_docs_grounding: ScoreConfidence
    multimodal_verification: ScoreConfidence
    runtime_debugging: ScoreConfidence
    test_authoring: ScoreConfidence
    coordination_reliability: ScoreConfidence
    privacy_safety: ScoreConfidence
    public_claim_safety: ScoreConfidence
    local_calibration: ScoreConfidence


class ToolState(StrictModel):
    tool_id: str
    available: bool
    authority_use: list[ToolAuthorityUse] = Field(default_factory=list)
    observed_at: datetime | None
    stale_after: str
    evidence_ref: str

    @model_validator(mode="after")
    def _tool_freshness_duration_is_valid(self) -> Self:
        parse_duration_spec(self.stale_after)
        return self


class ExecutionAccess(StrictModel):
    local_shell: bool = False
    browser: bool = False
    android: bool = False
    wearos: bool = False
    gpu: bool = False
    audio: bool = False
    video: bool = False
    docker: bool = False
    systemd: bool = False
    network: bool = False


class VerificationCapacity(StrictModel):
    deterministic_tests: bool = False
    static_checks: bool = False
    runtime_observation: bool = False
    screenshot_or_media: bool = False
    operator_only_handoff: bool = False


class SupplyRoute(StrictModel):
    route_id: str
    platform: Platform
    lane_id: str | None = None
    mode: Mode
    profile: Profile
    model_fingerprint: str | None = None
    launcher_contract: str | None = None
    sanctioned_wrapper: str
    approval_posture: ApprovalPosture
    capability_tier: CapabilityTier
    worker_tier: WorkerTier


class SupplyAuthority(StrictModel):
    ceiling: str
    supported_quality_floors: list[QualityFloor] = Field(default_factory=list)
    supported_mutation_surfaces: list[str] = Field(default_factory=list)


class SupplyState(StrictModel):
    session_state: str = "unknown"
    worktree_state: str = "unknown"
    claim_state: str = "unknown"
    quota_state: str = "unknown"
    rate_limit_state: str = "unknown"
    resource_pressure: str = "unknown"
    model_version_state: str = "unknown"


class HistoricalPerformance(StrictModel):
    calibration_window: str = "unscored"
    evidence_refs: list[str] = Field(default_factory=list)
    class_posteriors: dict[str, ScoreConfidence] = Field(default_factory=dict)
    benchmark_coverage: BenchmarkCoverage = Field(default_factory=BenchmarkCoverage)
    fixed_route_overhead: FixedRouteOverhead = Field(default_factory=FixedRouteOverhead)
    local_calibration_provenance: LocalCalibrationProvenance = Field(
        default_factory=LocalCalibrationProvenance
    )


class OperatorConstraints(StrictModel):
    allowed: bool = True
    vetoes: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class SupplyFreshness(StrictModel):
    observed_at: datetime | None
    stale_after: str
    source_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _freshness_duration_is_valid(self) -> Self:
        parse_duration_spec(self.stale_after)
        return self


class SupplyDescriptor(StrictModel):
    """The execution-axis SUPPLY a route offers the dispatcher: its base descriptor plus the
    set of context-modes / efforts REACHABLE via the route's (non-blocked) descriptor variants.
    The ``*_to_variant`` maps point each reachable axis value at the variant_id that provides it
    (``None`` = the base descriptor already provides it), so the dispatcher can both SCORE
    satisfiability and RESOLVE the selected leaf without re-reading the route."""

    base_context_mode: str
    base_effort: str
    reachable_context_modes: tuple[str, ...]
    reachable_efforts: tuple[str, ...]
    context_mode_to_variant: dict[str, str | None]
    effort_to_variant: dict[str, str | None]


class SupplyVector(StrictModel):
    supply_vector_schema: Literal[1] = 1
    routing_model_version: Literal["capacity-dimensional-v1"] = "capacity-dimensional-v1"
    route: SupplyRoute
    authority: SupplyAuthority
    capability_scores: CapabilityScores
    tool_state: list[ToolState] = Field(default_factory=list)
    execution_access: ExecutionAccess = Field(default_factory=ExecutionAccess)
    verification_capacity: VerificationCapacity = Field(default_factory=VerificationCapacity)
    state: SupplyState = Field(default_factory=SupplyState)
    historical_performance: HistoricalPerformance = Field(default_factory=HistoricalPerformance)
    operator_constraints: OperatorConstraints = Field(default_factory=OperatorConstraints)
    freshness: SupplyFreshness
    # the operator-steered execution axes (optional: only build_supply_vector populates it;
    # direct constructors leave it None and the dispatcher fails closed on a None descriptor)
    supply_descriptor: SupplyDescriptor | None = None


class PlatformCapabilityRoute(StrictModel):
    registry_schema: Literal[1] = 1
    route_id: str
    platform: Platform
    mode: Mode
    profile: Profile
    launcher: str
    sanctioned_wrapper: str
    summary: str
    notes: str
    route_state: RouteState
    blocked_reasons: list[str] = Field(default_factory=list)
    model_or_engine: str | None
    execution_descriptor: ExecutionDescriptor
    descriptor_variants: list[DescriptorVariant] = Field(default_factory=list)
    paid_provider: str | None = None
    paid_profile: str | None = None
    approval_posture: ApprovalPosture
    capability_tier: CapabilityTier
    worker_tier: WorkerTier
    auth_surface: AuthSurface
    capacity_pool: CapacityPool
    mutability: Mutability
    authority_ceiling: AuthorityCeiling
    tool_access: ToolAccess
    privacy_posture: PrivacyPosture
    quality_envelope: QualityEnvelope
    capability_scores: CapabilityScores
    tool_state: list[ToolState] = Field(default_factory=list)
    historical_performance: HistoricalPerformance = Field(default_factory=HistoricalPerformance)
    context_limits: ContextLimits
    telemetry: Telemetry
    freshness: Freshness
    known_unknowns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _route_contract_fails_closed(self) -> Self:
        expected = f"{self.platform.value}.{self.mode.value}.{self.profile.value}"
        if self.route_id != expected:
            raise ValueError(f"route_id must equal platform.mode.profile: {expected}")

        if self.route_state is RouteState.BLOCKED and not self.blocked_reasons:
            raise ValueError("blocked routes must declare blocked_reasons")

        if self.route_state is RouteState.ACTIVE and self.blocked_reasons:
            raise ValueError("active routes cannot carry blocked_reasons")

        if self.route_state is RouteState.ACTIVE and self.freshness.evidence.all_blocked_reasons():
            raise ValueError("active routes cannot carry freshness blocked_reasons")

        if self.authority_ceiling is AuthorityCeiling.READ_ONLY:
            if self.mutability.any_mutation():
                raise ValueError("read-only routes cannot declare mutation surfaces")
            if self.tool_access.filesystem is FilesystemAccess.READ_WRITE:
                raise ValueError("read-only routes cannot declare read-write filesystem access")
            if self.tool_access.shell is ShellAccess.FULL:
                raise ValueError("read-only routes cannot declare full shell access")
            if self.worker_tier is not WorkerTier.READ_ONLY_SIDECAR:
                raise ValueError("read-only routes must declare read_only_sidecar worker_tier")

        if (
            self.approval_posture is ApprovalPosture.PLAN_MODE_READ_ONLY
            and self.authority_ceiling is not AuthorityCeiling.READ_ONLY
        ):
            raise ValueError("plan-mode read-only routes must have read_only authority ceiling")

        if (
            self.approval_posture
            in {
                ApprovalPosture.IDE_TERMINAL_AUTO_APPROVE,
                ApprovalPosture.PROGRAMMATIC_AUTO_APPROVE_TASK_SCOPED,
            }
            and self.authority_ceiling is AuthorityCeiling.AUTHORITATIVE
        ):
            raise ValueError("auto-approval posture cannot be unrestricted authoritative")

        if (
            self.mutability.source
            and self.tool_access.filesystem is not FilesystemAccess.READ_WRITE
        ):
            raise ValueError("source-mutable routes require read-write filesystem access")

        if self.mutability.source and self.tool_access.shell is not ShellAccess.FULL:
            raise ValueError("source-mutable routes require full shell access")

        if self.mutability.provider_spend and self.capacity_pool not in {
            CapacityPool.API_PAID_SPEND,
            CapacityPool.BOOTSTRAP_BUDGET,
        }:
            raise ValueError("provider-spend mutation requires a paid or bootstrap capacity pool")

        if (
            self.authority_ceiling is AuthorityCeiling.AUTHORITATIVE
            and QualityFloor.FRONTIER_REQUIRED not in self.quality_envelope.eligible_quality_floors
        ):
            raise ValueError("authoritative routes must declare frontier_required eligibility")

        if self.descriptor_variants:
            axes = set(ExecutionDescriptor.model_fields)
            scores = set(CapabilityScores.model_fields)
            seen: set[str] = set()
            for variant in self.descriptor_variants:
                if variant.variant_id in seen:
                    raise ValueError(
                        f"duplicate descriptor variant_id {variant.variant_id!r} on {self.route_id}; "
                        "give each variant a unique variant_id or remove the duplicate"
                    )
                seen.add(variant.variant_id)
                bad_knobs = set(variant.knobs_override) - axes
                if bad_knobs:
                    raise ValueError(
                        f"variant {variant.variant_id!r} overrides non-descriptor knobs {sorted(bad_knobs)}; "
                        f"knobs_override keys must be ExecutionDescriptor axes ({sorted(axes)})"
                    )
                bad_scores = set(variant.score_delta) - scores
                if bad_scores:
                    raise ValueError(
                        f"variant {variant.variant_id!r} score_delta targets unknown scores {sorted(bad_scores)}; "
                        "use CapabilityScores field names"
                    )
                if not variant.knobs_override and not variant.blocked_reasons:
                    raise ValueError(
                        f"variant {variant.variant_id!r} is inert; give it a knobs_override that changes an "
                        "axis or a blocked_reasons entry, or remove the variant"
                    )

        return self


class PlatformCapabilityRegistry(StrictModel):
    registry_schema: Literal[1] = 1
    registry_id: str
    schema_ref: Literal["schemas/platform-capability-registry.schema.json"]
    declared_at: datetime
    capacity_invariant: str
    generated_from: list[str] = Field(min_length=1)
    required_route_ids: list[str] = Field(min_length=1)
    omitted_capability_shapes: list[CapabilityShapeDescriptor] = Field(min_length=1)
    routes: list[PlatformCapabilityRoute] = Field(min_length=1)

    @model_validator(mode="after")
    def _route_set_matches_contract(self) -> Self:
        required = set(self.required_route_ids)
        if required != REQUIRED_ROUTE_IDS:
            missing = REQUIRED_ROUTE_IDS - required
            extra = required - REQUIRED_ROUTE_IDS
            raise ValueError(
                f"required platform route ids mismatch; missing={sorted(missing)}, "
                f"extra={sorted(extra)}"
            )

        route_ids = [route.route_id for route in self.routes]
        duplicates = sorted({route_id for route_id in route_ids if route_ids.count(route_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate platform route ids: {duplicates}")

        missing_routes = required - set(route_ids)
        if missing_routes:
            raise ValueError(f"missing required platform routes: {sorted(missing_routes)}")

        extra_routes = set(route_ids) - required
        if extra_routes:
            raise ValueError(f"routes not declared in required_route_ids: {sorted(extra_routes)}")

        if self.capacity_invariant != CAPACITY_INVARIANT:
            raise ValueError("capacity invariant drifted from governed dispatch invariant")

        shape_ids = [shape.shape_id for shape in self.omitted_capability_shapes]
        duplicate_shapes = sorted(
            {shape_id for shape_id in shape_ids if shape_ids.count(shape_id) > 1}
        )
        if duplicate_shapes:
            raise ValueError(f"duplicate omitted capability shape ids: {duplicate_shapes}")

        reserved_route_ids = set(route_ids)
        route_like_shapes = sorted(
            shape_id for shape_id in shape_ids if shape_id in reserved_route_ids
        )
        if route_like_shapes:
            raise ValueError(
                "omitted capability shape ids must not collide with admitted route ids: "
                f"{route_like_shapes}"
            )

        # descriptor variant provenance is a cross-route reference; only the registry can
        # verify it resolves (the per-route validator cannot see sibling routes).
        known_ids = set(route_ids)
        for route in self.routes:
            for variant in route.descriptor_variants:
                ref = variant.scores_inherited_from
                if ref is not None and ref not in known_ids:
                    raise ValueError(
                        f"variant {variant.variant_id!r} on {route.route_id} inherits scores from "
                        f"unknown route_id {ref!r}; scores_inherited_from must name a registry route "
                        "(or be null to inherit the variant's own route)"
                    )

        return self

    def route_map(self) -> dict[str, PlatformCapabilityRoute]:
        return {route.route_id: route for route in self.routes}

    def require(self, route_id: str) -> PlatformCapabilityRoute:
        return self.route_map()[normalize_route_id(route_id)]


@dataclass(frozen=True)
class RouteFreshnessCheck:
    route_id: str
    ok: bool
    supported: bool
    errors: tuple[str, ...]
    blocked_reasons: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "ok": self.ok,
            "supported": self.supported,
            "errors": list(self.errors),
            "blocked_reasons": list(self.blocked_reasons),
            "evidence_refs": list(self.evidence_refs),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class RegistryFreshnessCheck:
    ok: bool
    checked_at: datetime
    route_count: int
    routes: tuple[RouteFreshnessCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_at": self.checked_at.isoformat().replace("+00:00", "Z"),
            "route_count": self.route_count,
            "routes": [route.to_dict() for route in self.routes],
        }


def normalize_route_id(route_id: str) -> str:
    return route_id.strip().replace("/", ".")


def _normalize_surface_token(value: str) -> str:
    return value.strip().lower().replace("/", ".").replace(" ", "_")


def _surface_matches_shape(
    delta: CapabilitySurfaceDelta,
    shape: CapabilityShapeDescriptor,
) -> bool:
    surface = _normalize_surface_token(delta.surface_id)
    shape_id = _normalize_surface_token(shape.shape_id)
    return delta.shape_class is shape.shape_class and (
        surface == shape_id or surface.startswith(f"{shape_id}.")
    )


def disposition_for_capability_surface_delta(
    registry: PlatformCapabilityRegistry,
    delta: CapabilitySurfaceDelta,
) -> CapabilitySurfaceDisposition:
    """Classify a deterministic capability-surface delta without admitting supply.

    A known omitted shape still holds for measurement because the descriptor is evidence-only.
    An unknown surface mints intake. Deprecated shapes refuse as live supply while preserving
    provenance/remediation refs for Reins and operators.
    """

    matches = [
        shape
        for shape in registry.omitted_capability_shapes
        if _surface_matches_shape(delta, shape)
    ]
    if not matches:
        return CapabilitySurfaceDisposition(
            surface_id=delta.surface_id,
            action=CapabilitySurfaceDeltaAction.MINT_INTAKE,
            descriptor_id=None,
            reason_codes=(
                "capability_surface_delta_unknown_shape",
                "measured_supply_leaf_absent",
                "route_resource_governance_receipts_absent",
            ),
            remediation_refs=(
                "mint:cc-task:capability-surface-intake",
                "require:descriptor",
                "require:measurement_plan",
                "require:route_resource_governance_receipts",
            ),
        )

    shape = sorted(matches, key=lambda item: item.shape_id)[0]
    if shape.shape_state is CapabilityShapeState.DEPRECATED:
        return CapabilitySurfaceDisposition(
            surface_id=delta.surface_id,
            action=CapabilitySurfaceDeltaAction.DEPRECATED_REFUSE,
            descriptor_id=shape.shape_id,
            reason_codes=(
                "capability_shape_deprecated",
                "live_route_identity_refused",
                "measured_supply_leaf_absent",
            ),
            remediation_refs=tuple(shape.remediation_refs),
        )

    return CapabilitySurfaceDisposition(
        surface_id=delta.surface_id,
        action=CapabilitySurfaceDeltaAction.KNOWN_HOLD_FOR_MEASUREMENT,
        descriptor_id=shape.shape_id,
        reason_codes=(
            "known_omitted_capability_shape",
            "evidence_only_not_dispatch_supply",
            "measured_supply_leaf_absent",
        ),
        remediation_refs=tuple(shape.remediation_refs),
    )


def parse_duration_spec(spec: str) -> timedelta:
    match = _DURATION_RE.fullmatch(spec)
    if match is None:
        raise ValueError(f"invalid duration spec {spec!r}; use an integer plus s, m, h, or d")
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "s":
        return timedelta(seconds=count)
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    return timedelta(days=count)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp_errors(
    *,
    route_id: str,
    surface: str,
    checked_at: datetime | None,
    stale_after: str,
    surface_evidence: FreshnessSurfaceEvidence,
    now: datetime,
) -> list[str]:
    errors = [
        f"{route_id}: {surface} blocked: {reason}" for reason in surface_evidence.blocked_reasons
    ]

    if checked_at is None:
        if surface_evidence.blocked_reasons:
            return errors
        return [*errors, f"{route_id}: {surface} freshness is unknown"]

    if not surface_evidence.evidence_refs:
        errors.append(f"{route_id}: {surface} evidence refs missing")

    checked = ensure_utc(checked_at)
    ttl = parse_duration_spec(stale_after)
    if checked > now + timedelta(minutes=1):
        return [*errors, f"{route_id}: {surface} checked_at is in the future"]
    if now - checked > ttl:
        errors.append(
            f"{route_id}: {surface} stale; checked_at={checked.isoformat()} "
            f"stale_after={stale_after}"
        )
    return errors


def check_route_freshness(
    route: PlatformCapabilityRoute,
    *,
    now: datetime | None = None,
) -> RouteFreshnessCheck:
    checked_now = ensure_utc(now or datetime.now(UTC))
    errors: list[str] = []
    freshness = route.freshness
    blocked_reasons = [
        *route.blocked_reasons,
        *freshness.evidence.all_blocked_reasons(),
    ]
    evidence_refs = list(freshness.evidence.all_evidence_refs())

    if route.route_state is RouteState.BLOCKED:
        errors.extend(f"{route.route_id}: blocked: {reason}" for reason in route.blocked_reasons)

    for surface in FRESHNESS_SURFACES:
        errors.extend(
            _timestamp_errors(
                route_id=route.route_id,
                surface=surface,
                checked_at=getattr(freshness, f"{surface}_checked_at"),
                stale_after=getattr(freshness, f"{surface}_stale_after"),
                surface_evidence=freshness.evidence.surface(surface),
                now=checked_now,
            )
        )

    if route.privacy_posture.value in UNKNOWN_PRIVACY_POSTURES:
        errors.append(f"{route.route_id}: privacy posture is {route.privacy_posture.value}")

    if route.telemetry.quota_source.value in UNKNOWN_TELEMETRY_SOURCES:
        errors.append(f"{route.route_id}: quota telemetry source is {route.telemetry.quota_source}")

    if route.telemetry.resource_source.value in UNKNOWN_TELEMETRY_SOURCES:
        errors.append(
            f"{route.route_id}: resource telemetry source is {route.telemetry.resource_source}"
        )

    if not freshness.evidence.capability.blocked_reasons:
        errors.extend(_capability_score_errors(route, now=checked_now))
    if not freshness.evidence.resource.blocked_reasons:
        errors.extend(_tool_state_errors(route, now=checked_now))

    return RouteFreshnessCheck(
        route_id=route.route_id,
        ok=not errors,
        supported=True,
        errors=tuple(errors),
        blocked_reasons=tuple(dict.fromkeys(blocked_reasons)),
        evidence_refs=tuple(dict.fromkeys(evidence_refs)),
    )


def check_registry_freshness(
    registry: PlatformCapabilityRegistry,
    *,
    route_ids: Iterable[str] | None = None,
    now: datetime | None = None,
) -> RegistryFreshnessCheck:
    checked_now = ensure_utc(now or datetime.now(UTC))
    route_map = registry.route_map()
    checks: list[RouteFreshnessCheck] = []
    normalized_ids = [normalize_route_id(route_id) for route_id in route_ids] if route_ids else None

    for route_id in normalized_ids or sorted(route_map):
        route = route_map.get(route_id)
        if route is None:
            checks.append(
                RouteFreshnessCheck(
                    route_id=route_id,
                    ok=False,
                    supported=False,
                    errors=(f"unsupported route: {route_id}",),
                )
            )
            continue
        checks.append(check_route_freshness(route, now=checked_now))

    return RegistryFreshnessCheck(
        ok=all(check.ok for check in checks),
        checked_at=checked_now,
        route_count=len(route_map),
        routes=tuple(checks),
    )


def _capability_score_errors(route: PlatformCapabilityRoute, *, now: datetime) -> list[str]:
    errors: list[str] = []
    score_payload = route.capability_scores.model_dump()
    for dimension, payload in score_payload.items():
        observed_at = payload.get("observed_at")
        stale_after = str(payload.get("stale_after") or "")
        evidence_refs = payload.get("evidence_refs") or []
        if not evidence_refs:
            errors.append(f"{route.route_id}: capability_scores.{dimension} evidence missing")
        if observed_at is None:
            errors.append(f"{route.route_id}: capability_scores.{dimension} observed_at missing")
            continue
        errors.extend(
            _timestamp_errors(
                route_id=route.route_id,
                surface=f"capability_scores.{dimension}",
                checked_at=ensure_utc(observed_at)
                if isinstance(observed_at, datetime)
                else observed_at,
                stale_after=stale_after,
                surface_evidence=FreshnessSurfaceEvidence(
                    evidence_refs=list(evidence_refs),
                    blocked_reasons=[],
                ),
                now=now,
            )
        )
    return errors


def _tool_state_errors(route: PlatformCapabilityRoute, *, now: datetime) -> list[str]:
    errors: list[str] = []
    for tool in route.tool_state:
        if tool.observed_at is None:
            errors.append(f"{route.route_id}: tool_state.{tool.tool_id} observed_at missing")
            continue
        errors.extend(
            _timestamp_errors(
                route_id=route.route_id,
                surface=f"tool_state.{tool.tool_id}",
                checked_at=tool.observed_at,
                stale_after=tool.stale_after,
                surface_evidence=FreshnessSurfaceEvidence(
                    evidence_refs=[tool.evidence_ref],
                    blocked_reasons=[],
                ),
                now=now,
            )
        )
    return errors


def _supported_mutation_surfaces(mutability: Mutability) -> list[str]:
    surfaces = ["none"]
    for surface in ("vault_docs", "source", "runtime", "public", "provider_spend"):
        if getattr(mutability, surface):
            surfaces.append(surface)
    return surfaces


def _execution_access(route: PlatformCapabilityRoute) -> ExecutionAccess:
    return ExecutionAccess(
        local_shell=route.tool_access.shell is ShellAccess.FULL,
        browser=route.tool_access.browser,
        network=route.tool_access.browser or bool(route.tool_access.mcp),
    )


def _verification_capacity(
    route: PlatformCapabilityRoute, execution_access: ExecutionAccess
) -> VerificationCapacity:
    can_run_shell = route.tool_access.shell is ShellAccess.FULL
    can_read_shell = route.tool_access.shell in {ShellAccess.FULL, ShellAccess.READ_ONLY}
    return VerificationCapacity(
        deterministic_tests=can_run_shell,
        static_checks=can_run_shell,
        runtime_observation=can_read_shell,
        screenshot_or_media=execution_access.browser,
        operator_only_handoff=route.authority_ceiling
        in {
            AuthorityCeiling.FRONTIER_REVIEW_REQUIRED,
            AuthorityCeiling.READ_ONLY,
            AuthorityCeiling.SUPPORT_ONLY,
        },
    )


def _telemetry_state(source: str) -> str:
    return "unknown" if source in UNKNOWN_TELEMETRY_SOURCES else "available"


def _resource_pressure_state(source: str) -> str:
    return "unknown" if source in UNKNOWN_TELEMETRY_SOURCES else "green"


def _build_supply_descriptor(route: PlatformCapabilityRoute) -> SupplyDescriptor:
    """The route's reachable execution-axis surface: base descriptor + every non-blocked
    variant. First-writer-wins keeps the BASE as the provider when a value is reachable both
    ways (a ``None`` variant means "base already provides it"). Blocked variants are excluded
    (fail-closed) so a blocked variant can neither satisfy a demand nor be resolved as a leaf."""

    base = route.execution_descriptor
    context_mode_to_variant: dict[str, str | None] = {base.context_mode.value: None}
    effort_to_variant: dict[str, str | None] = {base.effort.value: None}
    for variant in route.descriptor_variants:
        if variant.blocked_reasons:
            continue
        leaf = materialize_variant_leaf(route, variant)
        context_mode_to_variant.setdefault(leaf.context_mode.value, variant.variant_id)
        effort_to_variant.setdefault(leaf.effort.value, variant.variant_id)
    return SupplyDescriptor(
        base_context_mode=base.context_mode.value,
        base_effort=base.effort.value,
        reachable_context_modes=tuple(context_mode_to_variant),
        reachable_efforts=tuple(effort_to_variant),
        context_mode_to_variant=context_mode_to_variant,
        effort_to_variant=effort_to_variant,
    )


def build_supply_vector(
    route: PlatformCapabilityRoute,
    *,
    lane_id: str | None = None,
    now: datetime | None = None,
) -> SupplyVector:
    """Project an inert registry route into the typed dimensional supply vector."""

    checked_now = ensure_utc(now or datetime.now(UTC))
    freshness_observed_at = route.freshness.capability_checked_at
    execution_access = _execution_access(route)
    return SupplyVector(
        route=SupplyRoute(
            route_id=route.route_id,
            platform=route.platform,
            lane_id=lane_id,
            mode=route.mode,
            profile=route.profile,
            model_fingerprint=route.model_or_engine,
            launcher_contract=route.launcher,
            sanctioned_wrapper=route.sanctioned_wrapper,
            approval_posture=route.approval_posture,
            capability_tier=route.capability_tier,
            worker_tier=route.worker_tier,
        ),
        authority=SupplyAuthority(
            ceiling=route.authority_ceiling.value,
            supported_quality_floors=route.quality_envelope.eligible_quality_floors,
            supported_mutation_surfaces=_supported_mutation_surfaces(route.mutability),
        ),
        capability_scores=route.capability_scores,
        tool_state=route.tool_state,
        execution_access=execution_access,
        verification_capacity=_verification_capacity(route, execution_access),
        state=SupplyState(
            session_state="unknown",
            worktree_state="unknown",
            claim_state="unknown",
            quota_state=_telemetry_state(route.telemetry.quota_source.value),
            rate_limit_state="unknown",
            resource_pressure=_resource_pressure_state(route.telemetry.resource_source.value),
            model_version_state="current"
            if route.freshness.provider_docs_checked_at is not None
            else "unknown",
        ),
        historical_performance=route.historical_performance,
        freshness=SupplyFreshness(
            observed_at=ensure_utc(freshness_observed_at)
            if freshness_observed_at is not None
            else checked_now,
            stale_after=route.freshness.capability_stale_after,
            source_refs=[
                f"platform-capability-registry:{route.route_id}",
                *route.freshness.evidence.all_evidence_refs(),
                *route.quality_envelope.explicit_equivalence_records,
            ],
        ),
        supply_descriptor=_build_supply_descriptor(route),
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlatformCapabilityRegistryError(f"{path} did not contain a JSON object")
    return payload


def load_platform_capability_registry(
    path: Path = PLATFORM_CAPABILITY_REGISTRY,
    *,
    receipt_dir: Path | None = None,
    now: datetime | None = None,
) -> PlatformCapabilityRegistry:
    """Load the platform capability registry, failing closed on malformed data."""

    try:
        registry = PlatformCapabilityRegistry.model_validate(_load_json_object(path))
        effective_receipt_dir = receipt_dir or _receipt_dir_from_env()
        if effective_receipt_dir is None:
            return registry
        return apply_platform_capability_receipts(
            registry,
            receipt_dir=effective_receipt_dir,
            now=now,
        )
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise PlatformCapabilityRegistryError(
            f"invalid platform capability registry at {path}: {exc}"
        ) from exc


def _receipt_dir_from_env() -> Path | None:
    configured = os.environ.get(PLATFORM_CAPABILITY_RECEIPT_DIR_ENV)
    if not configured:
        return None
    if configured.strip() in {"0", "none", "None", "false", "False"}:
        return None
    return Path(configured).expanduser()


def apply_platform_capability_receipts(
    registry: PlatformCapabilityRegistry,
    *,
    receipt_dir: Path = DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR,
    now: datetime | None = None,
) -> PlatformCapabilityRegistry:
    """Overlay fresh local receipts onto inert registry rows."""

    receipts = load_platform_capability_receipts(receipt_dir, now=now)
    if not receipts:
        return registry

    payload = registry.model_dump(mode="json")
    for route_payload in payload["routes"]:
        receipt = receipts.get(route_payload["platform"])
        if receipt is None:
            continue
        if route_payload["route_id"] not in receipt.routes:
            continue
        _apply_receipt_to_route_payload(route_payload, receipt)
    return PlatformCapabilityRegistry.model_validate(payload)


def _apply_receipt_to_route_payload(
    route_payload: dict[str, Any],
    receipt: PlatformCapabilityReceipt,
) -> None:
    receipt_ref = receipt_reference(receipt)
    freshness = route_payload["freshness"]
    observed_at = receipt.observed_at.isoformat().replace("+00:00", "Z")
    provider_docs_at = receipt.provider_docs.fetched_at.isoformat().replace("+00:00", "Z")
    top_blockers = list(route_payload.get("blocked_reasons") or [])
    quota_unobservable_nonblocking = _quota_unobservable_nonblocking(
        route_payload,
        receipt,
    )
    quota_reason_codes = [] if quota_unobservable_nonblocking else receipt.quota.reason_codes

    _apply_surface(
        freshness,
        "capability",
        checked_at=observed_at,
        stale_after=receipt.capability.stale_after,
        evidence_refs=[*receipt.capability.evidence_refs, receipt_ref],
        reason_codes=receipt.capability.reason_codes,
        removable_reasons=_capability_receipt_removable_reasons(route_payload),
    )
    _apply_surface(
        freshness,
        "resource",
        checked_at=observed_at,
        stale_after=receipt.resource.stale_after,
        evidence_refs=[*receipt.resource.evidence_refs, receipt_ref],
        reason_codes=receipt.resource.reason_codes,
        removable_reasons=_resource_receipt_removable_reasons(route_payload),
    )
    quota_stale_after = (
        receipt.stale_after if quota_unobservable_nonblocking else receipt.quota.stale_after
    )
    _apply_surface(
        freshness,
        "quota",
        checked_at=observed_at,
        stale_after=quota_stale_after,
        evidence_refs=[*receipt.quota.evidence_refs, receipt_ref],
        reason_codes=quota_reason_codes
        if receipt.quota.status is not EvidenceStatus.OBSERVED
        else [],
        removable_reasons=_quota_unobservable_removable_reasons(route_payload)
        if quota_unobservable_nonblocking
        else {"account_live_quota_receipt_absent", "quota_telemetry_unknown"},
    )
    _apply_surface(
        freshness,
        "provider_docs",
        checked_at=provider_docs_at,
        stale_after=receipt.provider_docs.stale_after,
        evidence_refs=[*receipt.provider_docs.refs, receipt_ref],
        reason_codes=[],
        removable_reasons={"provider_docs_evidence_absent"},
    )

    for tool in route_payload.get("tool_state", []):
        tool["observed_at"] = observed_at
        tool["evidence_ref"] = receipt_ref
    if receipt.capability.status is EvidenceStatus.OBSERVED:
        for score in route_payload.get("capability_scores", {}).values():
            score["observed_at"] = observed_at
            score["evidence_refs"] = list(
                dict.fromkeys([*score.get("evidence_refs", []), receipt_ref])
            )

    if receipt.capability.status is not EvidenceStatus.OBSERVED:
        top_blockers.extend(receipt.capability.reason_codes)
    if receipt.resource.status is not EvidenceStatus.OBSERVED:
        top_blockers.extend(receipt.resource.reason_codes)
    if receipt.quota.status is not EvidenceStatus.OBSERVED and not quota_unobservable_nonblocking:
        top_blockers.extend(receipt.quota.reason_codes)

    removable_top_blockers = {
        *_capability_receipt_removable_reasons(route_payload),
        *_resource_receipt_removable_reasons(route_payload),
        "provider_docs_evidence_absent",
    }
    if quota_unobservable_nonblocking:
        removable_top_blockers.update(_quota_unobservable_removable_reasons(route_payload))
    top_blockers = [reason for reason in top_blockers if reason not in removable_top_blockers]
    route_payload["blocked_reasons"] = list(dict.fromkeys(top_blockers))
    route_payload["route_state"] = "blocked" if route_payload["blocked_reasons"] else "active"


def _quota_unobservable_nonblocking(
    route_payload: dict[str, Any],
    receipt: PlatformCapabilityReceipt,
) -> bool:
    """Treat expected local quota unobservability as evidence, not a hold.

    Subscription products do not expose account-live quota through local CLI
    probes. Provider-gateway routes use the paid spend ledger for budget
    authority, so the local API receipt observes gateway surface/config health
    while the dispatcher policy enforces the paid budget. Keep every other
    quota reason fail-closed.
    """

    if receipt.quota.status is not EvidenceStatus.UNOBSERVABLE:
        return False
    if set(receipt.quota.reason_codes) - {
        "account_live_quota_receipt_absent",
        "quota_telemetry_unknown",
    }:
        return False
    if (
        receipt.capability.status is not EvidenceStatus.OBSERVED
        or receipt.resource.status is not EvidenceStatus.OBSERVED
    ):
        return False
    capacity_pool = route_payload.get("capacity_pool")
    if capacity_pool == CapacityPool.SUBSCRIPTION_QUOTA.value:
        return True
    return (
        capacity_pool
        in {
            CapacityPool.API_PAID_SPEND.value,
            CapacityPool.BOOTSTRAP_BUDGET.value,
        }
        and route_payload.get("telemetry", {}).get("quota_source") == QuotaSource.LEDGER.value
    )


def _capability_receipt_removable_reasons(route_payload: dict[str, Any]) -> set[str]:
    reasons = {"fresh_capability_evidence_absent"}
    if route_payload.get("route_id") == "api.headless.provider_gateway":
        reasons.add("provider_gateway_evidence_absent")
    return reasons


def _resource_receipt_removable_reasons(route_payload: dict[str, Any]) -> set[str]:
    reasons = {"fresh_resource_evidence_absent"}
    if route_payload.get("route_id") == "api.headless.provider_gateway":
        reasons.add("gateway_resource_receipt_absent")
    return reasons


def _quota_unobservable_removable_reasons(route_payload: dict[str, Any]) -> set[str]:
    reasons = {"account_live_quota_receipt_absent", "quota_telemetry_unknown"}
    if route_payload.get("capacity_pool") in {
        CapacityPool.API_PAID_SPEND.value,
        CapacityPool.BOOTSTRAP_BUDGET.value,
    }:
        reasons.add("provider_budget_receipt_absent")
    return reasons


def _apply_surface(
    freshness: dict[str, Any],
    surface: str,
    *,
    checked_at: str,
    stale_after: str,
    evidence_refs: list[str],
    reason_codes: list[str],
    removable_reasons: set[str],
) -> None:
    surface_payload = freshness["evidence"][surface]
    prior_reasons = [
        reason
        for reason in surface_payload.get("blocked_reasons", [])
        if reason not in removable_reasons
    ]
    surface_payload["blocked_reasons"] = list(dict.fromkeys([*prior_reasons, *reason_codes]))
    surface_payload["evidence_refs"] = list(
        dict.fromkeys([*surface_payload.get("evidence_refs", []), *evidence_refs])
    )
    freshness[f"{surface}_checked_at"] = checked_at
    freshness[f"{surface}_stale_after"] = stale_after


#: Effort tokens historically smuggled into ``model_or_engine`` (e.g. codex.headless.full's
#: ``gpt-5.5-xhigh``). ``derive_execution_descriptor`` splits them back into structured axes.
_SMUGGLED_EFFORT_SUFFIXES: dict[str, Effort] = {
    "-max": Effort.MAX,
    "-xhigh": Effort.XHIGH,
    "-high": Effort.HIGH,
    "-medium": Effort.MEDIUM,
    "-low": Effort.LOW,
}

#: Best-effort projection of legacy free-text ``model_or_engine`` strings onto the dated
#: :class:`ModelId` catalog (used by ``derive_execution_descriptor`` to GENERATE the
#: per-route backfill and to surface the smuggle). Unmapped strings project to ``UNKNOWN``.
_MODEL_OR_ENGINE_TO_MODEL_ID: dict[str, ModelId] = {
    "claude-code-default": ModelId.CLAUDE_OPUS_4_8,
    "claude-opus": ModelId.CLAUDE_OPUS_4_8,
    # NOTE (2026-07-02 registry-freshness): the bare "claude-sonnet" alias still projects to the
    # PRIOR Sonnet (4-6). Post-Sonnet-5-release the carrier's `--model sonnet` most likely serves
    # Sonnet 5, so any route declaring the bare "claude-sonnet" may be a CapabilityExecutionInvariant
    # DECLARE-layer drift (observed != declared). Repointing this alias is a production-routing
    # decision deferred to the operator; the explicit "claude-sonnet-5" identity below is additive.
    "claude-sonnet": ModelId.CLAUDE_SONNET_4_6,
    "claude-sonnet-5": ModelId.CLAUDE_SONNET_5,
    "claude-haiku": ModelId.CLAUDE_HAIKU_4_5,
    "gpt-5.5": ModelId.GPT_5_5,
    "gpt-5.3-codex-spark": ModelId.GPT_5_3_CODEX_SPARK,
    "mistral-vibe": ModelId.MISTRAL_MEDIUM_3_5,
    "google-antigravity-cli-agy": ModelId.GEMINI_3_1_PRO_PREVIEW,
    "z_ai-glm-coding-plan:glm-5": ModelId.Z_AI_GLM_5,
    "litellm.anthropic.claude-opus-4-cloud-burst": ModelId.CLAUDE_OPUS_4_8,
    "litellm.provider-gateway-maintenance": ModelId.GEMINI_3_1_PRO_PREVIEW,
}


def derive_execution_descriptor(route: PlatformCapabilityRoute) -> ExecutionDescriptor:
    """Project a route's implicit execution descriptor from its legacy ``model_or_engine``.

    Best-effort: it surfaces effort smuggled into the model string (``gpt-5.5-xhigh`` ->
    model_id ``gpt-5.5`` + effort ``XHIGH``) and maps the model onto the dated
    :class:`ModelId` catalog (unmapped -> ``ModelId.UNKNOWN``). effort that the data never
    carried is ``Effort.NONE``; context_mode/quantization stay at conservative defaults.
    Used to GENERATE the stored ``execution_descriptor`` backfill and demonstrate the
    smuggle-split; the stored field — not this projection — is the source of truth once set.
    """

    raw = (route.model_or_engine or "").strip()
    effort = Effort.NONE
    model_str = raw
    for suffix, eff in _SMUGGLED_EFFORT_SUFFIXES.items():
        if raw.endswith(suffix):
            effort = eff
            model_str = raw[: -len(suffix)]
            break
    model_id = _MODEL_OR_ENGINE_TO_MODEL_ID.get(model_str, ModelId.UNKNOWN)
    return ExecutionDescriptor(model_id=model_id, effort=effort)


def materialize_descriptors(
    registry: PlatformCapabilityRegistry,
) -> dict[str, ExecutionDescriptor]:
    """The stored execution descriptor for every route — the dispatch plane's capability
    *leaf set* made explicit. Reads the structured ``execution_descriptor`` field (the source
    of truth) rather than re-deriving from the legacy ``model_or_engine`` string."""

    return {route.route_id: route.execution_descriptor for route in registry.routes}


def materialize_variant_leaf(
    route: PlatformCapabilityRoute, variant: DescriptorVariant
) -> ExecutionDescriptor:
    """Resolve one sparse variant into its full ExecutionDescriptor by applying the
    variant's ``knobs_override`` onto the route's base descriptor. Fails closed: an
    override naming a non-descriptor knob raises (validated at load, re-checked here)."""

    knobs = route.execution_descriptor.model_dump()
    knobs.update(variant.knobs_override)
    return ExecutionDescriptor(**knobs)


def materialize_descriptor_leaves(
    registry: PlatformCapabilityRegistry,
) -> dict[str, ExecutionDescriptor]:
    """The FULL capability leaf set: every route's base descriptor plus each sparse
    variant as its own leaf keyed ``route_id#variant_id``. This is where a knob like
    ``context_mode=extended_1m`` becomes a distinct, materially-present capability —
    impossible to distinguish under the old bare ``max_context_class`` enum."""

    leaves: dict[str, ExecutionDescriptor] = {}
    for route in registry.routes:
        leaves[route.route_id] = route.execution_descriptor
        for variant in route.descriptor_variants:
            leaves[f"{route.route_id}#{variant.variant_id}"] = materialize_variant_leaf(
                route, variant
            )
    return leaves


_DYNAMIC_ENTRYPOINTS = (
    ScoreConfidence._score_evidence_is_freshness_typed,
    ToolState._tool_freshness_duration_is_valid,
    SupplyFreshness._freshness_duration_is_valid,
    FreshnessSurfaceEvidence._has_evidence_or_blocker,
    Freshness._duration_specs_are_valid,
    CapabilityShapeDescriptor._omitted_shape_is_not_supply,
    PlatformCapabilityRoute._route_contract_fails_closed,
    PlatformCapabilityRegistry._route_set_matches_contract,
    disposition_for_capability_surface_delta,
    build_supply_vector,
    check_registry_freshness,
    load_platform_capability_registry,
    derive_execution_descriptor,
    materialize_descriptors,
    materialize_variant_leaf,
    materialize_descriptor_leaves,
)
