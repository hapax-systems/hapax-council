"""Capability-agnostic availability receipts for routing.

The guarantor reads capability descriptors plus freshness checks and emits a
uniform availability receipt. Refresh is selected by ``auth_surface`` only; the
core evaluator does not branch on platform names.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from shared.platform_capability_registry import (
    AuthSurface,
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    RouteFreshnessCheck,
    RouteState,
    check_registry_freshness,
    normalize_route_id,
)


class _AvailabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"


class RefreshStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    NO_STRATEGY = "no_strategy"
    REFRESHED = "refreshed"
    DEFERRED = "deferred"
    FAILED = "failed"


class AvailabilityPredicate(_AvailabilityModel):
    admitted: bool
    auth_fresh: bool
    quota_headroom: bool
    not_degraded: bool
    mask_permitted: bool = True

    @property
    def available(self) -> bool:
        return (
            self.admitted
            and self.auth_fresh
            and self.quota_headroom
            and self.not_degraded
            and self.mask_permitted
        )


class RefreshOutcome(_AvailabilityModel):
    status: RefreshStatus
    strategy_id: str | None = None
    reason_codes: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())
    remediation_commands: tuple[str, ...] = Field(default=())


class CapabilityAvailabilityReceipt(_AvailabilityModel):
    availability_receipt_schema: Literal[1] = 1
    receipt_id: str
    route_id: str
    checked_at: datetime
    auth_surface: str
    capacity_pool: str
    status: AvailabilityStatus
    predicate: AvailabilityPredicate
    reason_codes: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())
    refresh_status: RefreshStatus = RefreshStatus.NOT_REQUIRED
    refresh_strategy_id: str | None = None
    refresh_reason_codes: tuple[str, ...] = Field(default=())
    refresh_evidence_refs: tuple[str, ...] = Field(default=())
    refresh_remediation_commands: tuple[str, ...] = Field(default=())
    recomposition_required: bool = False

    @property
    def available(self) -> bool:
        return self.status is AvailabilityStatus.AVAILABLE

    @property
    def reference(self) -> str:
        return f"capability-availability-receipt:{self.route_id}:{self.receipt_id}"


class RegistryAvailabilityCheck(_AvailabilityModel):
    ok: bool
    checked_at: datetime
    route_count: int
    receipts: tuple[CapabilityAvailabilityReceipt, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checked_at": self.checked_at.isoformat().replace("+00:00", "Z"),
            "route_count": self.route_count,
            "receipts": [
                {
                    **receipt.model_dump(mode="json"),
                    "receipt_ref": receipt.reference,
                }
                for receipt in self.receipts
            ],
        }


class RefreshStrategy(Protocol):
    auth_surface: AuthSurface
    strategy_id: str

    def refresh(
        self,
        route: PlatformCapabilityRoute,
        freshness: RouteFreshnessCheck,
        *,
        now: datetime,
    ) -> RefreshOutcome: ...


class RefreshStrategyRegistry:
    def __init__(self, strategies: Iterable[RefreshStrategy] = ()) -> None:
        self._strategies: dict[AuthSurface, RefreshStrategy] = {}
        for strategy in strategies:
            self.register(strategy)

    def register(self, strategy: RefreshStrategy) -> None:
        self._strategies[strategy.auth_surface] = strategy

    def strategy_for(self, auth_surface: AuthSurface) -> RefreshStrategy | None:
        return self._strategies.get(auth_surface)


class CodexOAuthRefreshStrategy:
    """First OAuth strategy: supported Codex refresh boundary, no bearer-token daemon."""

    auth_surface = AuthSurface.OAUTH
    strategy_id = "codex-oauth-supported-refresh"

    def refresh(
        self,
        route: PlatformCapabilityRoute,
        freshness: RouteFreshnessCheck,
        *,
        now: datetime,
    ) -> RefreshOutcome:
        return RefreshOutcome(
            status=RefreshStatus.DEFERRED,
            strategy_id=self.strategy_id,
            reason_codes=(
                "oauth_refresh_uses_supported_codex_auth_path",
                "availability_recheck_required_after_refresh",
            ),
            evidence_refs=(
                f"platform-capability-registry:{route.route_id}:auth_surface:oauth",
                "script:scripts/hapax-platform-capability-receipts --platform codex",
                "policy:not_codex_access_token_daemon",
                *freshness.evidence_refs,
            ),
            remediation_commands=(
                "scripts/hapax-platform-capability-receipts --platform codex",
                "scripts/hapax-platform-capability-freshness --route codex.headless.full --json",
            ),
        )


def default_refresh_strategy_registry() -> RefreshStrategyRegistry:
    return RefreshStrategyRegistry((CodexOAuthRefreshStrategy(),))


def evaluate_registry_availability(
    registry: PlatformCapabilityRegistry,
    *,
    route_ids: Iterable[str] | None = None,
    refresh_strategies: RefreshStrategyRegistry | None = None,
    now: datetime | None = None,
) -> RegistryAvailabilityCheck:
    checked_now = _ensure_utc(now or datetime.now(UTC))
    freshness = check_registry_freshness(registry, route_ids=route_ids, now=checked_now)
    route_map = registry.route_map()
    receipts = tuple(
        evaluate_route_availability(
            route_map[normalize_route_id(route_check.route_id)],
            route_check,
            refresh_strategies=refresh_strategies,
            now=checked_now,
        )
        for route_check in freshness.routes
        if route_check.supported
    )
    return RegistryAvailabilityCheck(
        ok=all(receipt.available for receipt in receipts),
        checked_at=checked_now,
        route_count=len(route_map),
        receipts=receipts,
    )


def evaluate_route_availability(
    route: PlatformCapabilityRoute,
    freshness: RouteFreshnessCheck,
    *,
    refresh_strategies: RefreshStrategyRegistry | None = None,
    now: datetime | None = None,
) -> CapabilityAvailabilityReceipt:
    checked_now = _ensure_utc(now or datetime.now(UTC))
    strategies = refresh_strategies or default_refresh_strategy_registry()
    predicate = _availability_predicate(route, freshness)
    reason_codes = _availability_reason_codes(route, freshness, predicate)
    refresh = _refresh_outcome(route, freshness, predicate, strategies, now=checked_now)
    status = AvailabilityStatus.AVAILABLE if predicate.available else AvailabilityStatus.DEGRADED
    if refresh.status is RefreshStatus.REFRESHED and status is AvailabilityStatus.DEGRADED:
        reason_codes = tuple(
            dict.fromkeys([*reason_codes, "availability_recheck_required_after_refresh"])
        )
    receipt_id = (
        f"availability-{normalize_route_id(route.route_id).replace('.', '-')}-"
        f"{checked_now.strftime('%Y%m%dT%H%M%SZ')}"
    )
    return CapabilityAvailabilityReceipt(
        receipt_id=receipt_id,
        route_id=route.route_id,
        checked_at=checked_now,
        auth_surface=route.auth_surface.value,
        capacity_pool=route.capacity_pool.value,
        status=status,
        predicate=predicate,
        reason_codes=reason_codes,
        evidence_refs=tuple(
            dict.fromkeys(
                [
                    f"platform-capability-registry:{route.route_id}",
                    *freshness.evidence_refs,
                ]
            )
        ),
        refresh_status=refresh.status,
        refresh_strategy_id=refresh.strategy_id,
        refresh_reason_codes=refresh.reason_codes,
        refresh_evidence_refs=refresh.evidence_refs,
        refresh_remediation_commands=refresh.remediation_commands,
        recomposition_required=status is AvailabilityStatus.DEGRADED,
    )


def availability_dispatch_reason_codes(
    receipt: CapabilityAvailabilityReceipt,
) -> tuple[str, ...]:
    if receipt.available:
        return ()
    return tuple(
        dict.fromkeys(
            [
                "capability_availability_degraded",
                f"availability_receipt:{receipt.receipt_id}",
                f"auth_surface:{receipt.auth_surface}",
                f"capacity_pool:{receipt.capacity_pool}",
                *receipt.reason_codes,
                f"refresh_status:{receipt.refresh_status.value}",
                *receipt.refresh_reason_codes,
            ]
        )
    )


def _availability_predicate(
    route: PlatformCapabilityRoute,
    freshness: RouteFreshnessCheck,
) -> AvailabilityPredicate:
    reason_text = "\n".join([*freshness.errors, *freshness.blocked_reasons]).lower()
    return AvailabilityPredicate(
        admitted=route.route_state is RouteState.ACTIVE and not route.blocked_reasons,
        auth_fresh=not any(
            token in reason_text
            for token in ("auth", "credential", "oauth", "account_live", "capability")
        ),
        quota_headroom="quota" not in reason_text,
        not_degraded=freshness.ok,
    )


def _availability_reason_codes(
    route: PlatformCapabilityRoute,
    freshness: RouteFreshnessCheck,
    predicate: AvailabilityPredicate,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not predicate.admitted:
        reasons.append("route_not_admitted")
        reasons.extend(f"route_blocked:{reason}" for reason in route.blocked_reasons)
    if not predicate.auth_fresh:
        reasons.append("auth_surface_not_fresh")
    if not predicate.quota_headroom:
        reasons.append("capacity_pool_headroom_not_fresh")
    if not predicate.not_degraded:
        reasons.append("capability_degraded")
    reasons.extend(_blocked_reason_refs(freshness))
    return tuple(dict.fromkeys(reasons))


def _refresh_outcome(
    route: PlatformCapabilityRoute,
    freshness: RouteFreshnessCheck,
    predicate: AvailabilityPredicate,
    strategies: RefreshStrategyRegistry,
    *,
    now: datetime,
) -> RefreshOutcome:
    if predicate.available:
        return RefreshOutcome(status=RefreshStatus.NOT_REQUIRED)
    strategy = strategies.strategy_for(route.auth_surface)
    if strategy is None:
        return RefreshOutcome(
            status=RefreshStatus.NO_STRATEGY,
            reason_codes=(f"refresh_strategy_absent:{route.auth_surface.value}",),
        )
    return strategy.refresh(route, freshness, now=now)


def _blocked_reason_refs(freshness: RouteFreshnessCheck) -> tuple[str, ...]:
    refs: list[str] = []
    for reason in freshness.blocked_reasons:
        refs.append(f"blocked_reason:{reason}")
    return tuple(refs)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "AvailabilityPredicate",
    "AvailabilityStatus",
    "CapabilityAvailabilityReceipt",
    "CodexOAuthRefreshStrategy",
    "RefreshOutcome",
    "RefreshStatus",
    "RefreshStrategy",
    "RefreshStrategyRegistry",
    "RegistryAvailabilityCheck",
    "availability_dispatch_reason_codes",
    "default_refresh_strategy_registry",
    "evaluate_registry_availability",
    "evaluate_route_availability",
]
