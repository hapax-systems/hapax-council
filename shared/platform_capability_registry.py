"""Typed platform capability registry and freshness checks.

The registry is inert metadata. It describes sanctioned platform routes and
their checked state; it does not grant task authority or choose dispatch
routes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.route_metadata_schema import ToolAuthorityUse

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_CAPABILITY_REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"

CAPACITY_INVARIANT = (
    "Default to maximum appropriate quality-preserving utilization. No quality "
    "degradation is permitted. Capacity may be reduced only by task-platform fit, "
    "quota state, resource contention, or explicit operator hold."
)

REQUIRED_ROUTE_IDS = frozenset(
    {
        "antigrav.interactive.full",
        "claude.headless.full",
        "claude.headless.opus",
        "claude.headless.sonnet",
        "codex.headless.full",
        "codex.headless.spark",
        "gemini.headless.flash",
        "gemini.headless.full",
        "gemini.headless.lite",
        "gemini.interactive.full",
        "vibe.headless.full",
    }
)

UNKNOWN_TELEMETRY_SOURCES = frozenset({"none", "unknown"})
UNKNOWN_PRIVACY_POSTURES = frozenset({"unknown", "provider_training_unknown", "public_risk"})
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
    LOCAL_TOOL = "local_tool"
    VIBE = "vibe"


class Mode(StrEnum):
    HEADLESS = "headless"
    INTERACTIVE = "interactive"
    LOCAL = "local"
    RECEIPT_ONLY = "receipt_only"


class Profile(StrEnum):
    API_FRONTIER = "api_frontier"
    DETERMINISTIC = "deterministic"
    FLASH = "flash"
    FULL = "full"
    JR = "jr"
    LITE = "lite"
    OPUS = "opus"
    SONNET = "sonnet"
    SPARK = "spark"


class RouteState(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


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


class Freshness(StrictModel):
    capability_checked_at: datetime | None
    capability_stale_after: str
    quota_checked_at: datetime | None
    quota_stale_after: str
    resource_checked_at: datetime | None
    resource_stale_after: str
    provider_docs_checked_at: datetime | None
    provider_docs_stale_after: str

    @model_validator(mode="after")
    def _duration_specs_are_valid(self) -> Self:
        for field_name in (
            "capability_stale_after",
            "quota_stale_after",
            "resource_stale_after",
            "provider_docs_stale_after",
        ):
            parse_duration_spec(getattr(self, field_name))
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


class PlatformCapabilityRoute(StrictModel):
    registry_schema: Literal[1] = 1
    route_id: str
    platform: Platform
    mode: Mode
    profile: Profile
    launcher: str
    summary: str
    notes: str
    route_state: RouteState
    blocked_reasons: list[str] = Field(default_factory=list)
    model_or_engine: str | None
    auth_surface: AuthSurface
    capacity_pool: CapacityPool
    mutability: Mutability
    authority_ceiling: AuthorityCeiling
    tool_access: ToolAccess
    privacy_posture: PrivacyPosture
    quality_envelope: QualityEnvelope
    capability_scores: CapabilityScores
    tool_state: list[ToolState] = Field(default_factory=list)
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

        if self.authority_ceiling is AuthorityCeiling.READ_ONLY:
            if self.mutability.any_mutation():
                raise ValueError("read-only routes cannot declare mutation surfaces")
            if self.tool_access.filesystem is FilesystemAccess.READ_WRITE:
                raise ValueError("read-only routes cannot declare read-write filesystem access")
            if self.tool_access.shell is ShellAccess.FULL:
                raise ValueError("read-only routes cannot declare full shell access")

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

        return self


class PlatformCapabilityRegistry(StrictModel):
    registry_schema: Literal[1] = 1
    registry_id: str
    schema_ref: Literal["schemas/platform-capability-registry.schema.json"]
    declared_at: datetime
    capacity_invariant: str
    generated_from: list[str] = Field(min_length=1)
    required_route_ids: list[str] = Field(min_length=1)
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

        if self.capacity_invariant != CAPACITY_INVARIANT:
            raise ValueError("capacity invariant drifted from governed dispatch invariant")

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
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "ok": self.ok,
            "supported": self.supported,
            "errors": list(self.errors),
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
    now: datetime,
) -> list[str]:
    if checked_at is None:
        return [f"{route_id}: {surface} freshness is unknown"]

    checked = ensure_utc(checked_at)
    ttl = parse_duration_spec(stale_after)
    if checked > now + timedelta(minutes=1):
        return [f"{route_id}: {surface} checked_at is in the future"]
    if now - checked > ttl:
        return [
            f"{route_id}: {surface} stale; checked_at={checked.isoformat()} "
            f"stale_after={stale_after}"
        ]
    return []


def check_route_freshness(
    route: PlatformCapabilityRoute,
    *,
    now: datetime | None = None,
) -> RouteFreshnessCheck:
    checked_now = ensure_utc(now or datetime.now(UTC))
    errors: list[str] = []
    freshness = route.freshness

    if route.route_state is RouteState.BLOCKED:
        errors.extend(f"{route.route_id}: blocked: {reason}" for reason in route.blocked_reasons)

    errors.extend(
        _timestamp_errors(
            route_id=route.route_id,
            surface="capability",
            checked_at=freshness.capability_checked_at,
            stale_after=freshness.capability_stale_after,
            now=checked_now,
        )
    )
    errors.extend(
        _timestamp_errors(
            route_id=route.route_id,
            surface="quota",
            checked_at=freshness.quota_checked_at,
            stale_after=freshness.quota_stale_after,
            now=checked_now,
        )
    )
    errors.extend(
        _timestamp_errors(
            route_id=route.route_id,
            surface="resource",
            checked_at=freshness.resource_checked_at,
            stale_after=freshness.resource_stale_after,
            now=checked_now,
        )
    )
    errors.extend(
        _timestamp_errors(
            route_id=route.route_id,
            surface="provider_docs",
            checked_at=freshness.provider_docs_checked_at,
            stale_after=freshness.provider_docs_stale_after,
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

    errors.extend(_capability_score_errors(route, now=checked_now))
    errors.extend(_tool_state_errors(route, now=checked_now))

    return RouteFreshnessCheck(
        route_id=route.route_id,
        ok=not errors,
        supported=True,
        errors=tuple(errors),
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
        freshness=SupplyFreshness(
            observed_at=ensure_utc(freshness_observed_at)
            if freshness_observed_at is not None
            else checked_now,
            stale_after=route.freshness.capability_stale_after,
            source_refs=[
                f"platform-capability-registry:{route.route_id}",
                *route.quality_envelope.explicit_equivalence_records,
            ],
        ),
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlatformCapabilityRegistryError(f"{path} did not contain a JSON object")
    return payload


def load_platform_capability_registry(
    path: Path = PLATFORM_CAPABILITY_REGISTRY,
) -> PlatformCapabilityRegistry:
    """Load the platform capability registry, failing closed on malformed data."""

    try:
        return PlatformCapabilityRegistry.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise PlatformCapabilityRegistryError(
            f"invalid platform capability registry at {path}: {exc}"
        ) from exc


_DYNAMIC_ENTRYPOINTS = (
    ScoreConfidence._score_evidence_is_freshness_typed,
    ToolState._tool_freshness_duration_is_valid,
    SupplyFreshness._freshness_duration_is_valid,
    Freshness._duration_specs_are_valid,
    PlatformCapabilityRoute._route_contract_fails_closed,
    PlatformCapabilityRegistry._route_set_matches_contract,
    build_supply_vector,
    check_registry_freshness,
    load_platform_capability_registry,
)
