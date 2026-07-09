"""Capability-agnostic availability receipts for routing.

The guarantor reads capability descriptors plus freshness checks and emits a
uniform availability receipt. Refresh is selected by ``auth_surface`` only; the
core evaluator does not branch on platform names or execute refresh side effects
unless a caller supplies an executable refresh strategy.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from shared.platform_capability_registry import (
    AuthSurface,
    CapacityPool,
    PlatformCapabilityRegistry,
    PlatformCapabilityRoute,
    RouteFreshnessCheck,
    RouteState,
    check_registry_freshness,
    normalize_route_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_SUBSCRIPTION_ADMISSION_ROUTE_ID = "claude.headless.full"
NEGATIVE_REF_TOKENS = {
    "absent",
    "blocked",
    "denied",
    "error",
    "exhausted",
    "expired",
    "failed",
    "failure",
    "false",
    "invalid",
    "missing",
    "negative",
    "not",
    "refused",
    "stale",
    "timeout",
    "unobservable",
    "unobserved",
    "zero",
}


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
    account_live_quota_attested: bool = True
    exec_auth_attested: bool = True

    @property
    def available(self) -> bool:
        return (
            self.admitted
            and self.auth_fresh
            and self.quota_headroom
            and self.not_degraded
            and self.mask_permitted
            and self.account_live_quota_attested
            and self.exec_auth_attested
        )


class RefreshOutcome(_AvailabilityModel):
    status: RefreshStatus
    strategy_id: str | None = None
    reason_codes: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())
    remediation_commands: tuple[str, ...] = Field(default=())


class RefreshCommandResult(_AvailabilityModel):
    returncode: int
    stdout: str = ""
    stderr: str = ""


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
    unsupported_routes: tuple[RouteFreshnessCheck, ...] = Field(default=())

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checked_at": self.checked_at.isoformat().replace("+00:00", "Z"),
            "route_count": self.route_count,
            "unsupported_routes": [route.to_dict() for route in self.unsupported_routes],
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
    ) -> RefreshOutcome:
        pass


class RefreshCommandRunner(Protocol):
    def __call__(
        self,
        command: tuple[str, ...],
        *,
        timeout_s: float,
    ) -> RefreshCommandResult:
        pass


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
    """Codex OAuth strategy: saved-login exec witness, no bearer-token daemon."""

    auth_surface = AuthSurface.OAUTH
    strategy_id = "codex-oauth-supported-refresh"

    def __init__(
        self,
        *,
        runner: RefreshCommandRunner | None = None,
        timeout_s: float = 30.0,
        execute: bool = False,
    ) -> None:
        self._runner = runner if runner is not None else (_run_refresh_command if execute else None)
        self._timeout_s = timeout_s

    def refresh(
        self,
        route: PlatformCapabilityRoute,
        freshness: RouteFreshnessCheck,
        *,
        now: datetime,
    ) -> RefreshOutcome:
        base_refs = (
            f"platform-capability-registry:{route.route_id}:auth_surface:oauth",
            (
                "script:scripts/hapax-platform-capability-receipts --platform codex "
                "--codex-exec-auth-probe --json"
            ),
            "policy:codex_saved_login_exec_auth_witness",
            "policy:not_codex_access_token_daemon",
            *freshness.evidence_refs,
        )
        refresh_command = (
            "scripts/hapax-platform-capability-receipts --platform codex "
            "--codex-exec-auth-probe --json"
        )
        freshness_command = (
            f"scripts/hapax-platform-capability-freshness --route {route.route_id} --json"
        )

        if self._runner is None:
            return RefreshOutcome(
                status=RefreshStatus.DEFERRED,
                strategy_id=self.strategy_id,
                reason_codes=(
                    "oauth_refresh_uses_codex_saved_login_exec_witness",
                    "refresh_execution_not_requested",
                    "availability_recheck_required_after_refresh",
                ),
                evidence_refs=base_refs,
                remediation_commands=(refresh_command, freshness_command),
            )

        command = (
            str(REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"),
            "--platform",
            "codex",
            "--codex-exec-auth-probe",
            "--json",
            "--now",
            _iso_z(now),
        )
        result = self._runner(command, timeout_s=self._timeout_s)
        receipt_item = _refresh_receipt_item(result.stdout, platform="codex")

        if result.returncode != 0:
            return RefreshOutcome(
                status=RefreshStatus.FAILED,
                strategy_id=self.strategy_id,
                reason_codes=(
                    "oauth_refresh_uses_codex_saved_login_exec_witness",
                    f"refresh_command_failed:{result.returncode}",
                ),
                evidence_refs=base_refs,
                remediation_commands=(refresh_command, freshness_command),
            )

        if receipt_item is None:
            return RefreshOutcome(
                status=RefreshStatus.FAILED,
                strategy_id=self.strategy_id,
                reason_codes=(
                    "oauth_refresh_uses_codex_saved_login_exec_witness",
                    "refresh_receipt_missing_from_command_output",
                ),
                evidence_refs=base_refs,
                remediation_commands=(refresh_command, freshness_command),
            )

        evidence_refs = [
            *base_refs,
            f"platform-capability-receipt:codex:{receipt_item.get('receipt_id')}",
        ]
        if receipt_item.get("path"):
            evidence_refs.append(f"platform-capability-receipt-file:{receipt_item['path']}")

        if not receipt_item.get("cli_available") or not receipt_item.get("wrapper_exists"):
            return RefreshOutcome(
                status=RefreshStatus.FAILED,
                strategy_id=self.strategy_id,
                reason_codes=(
                    "oauth_refresh_uses_codex_saved_login_exec_witness",
                    "refresh_receipt_observed_codex_unavailable",
                ),
                evidence_refs=tuple(dict.fromkeys(evidence_refs)),
                remediation_commands=(refresh_command, freshness_command),
            )

        surface_unavailable_reasons = _receipt_surface_unavailable_reasons(receipt_item)
        if surface_unavailable_reasons:
            return RefreshOutcome(
                status=RefreshStatus.FAILED,
                strategy_id=self.strategy_id,
                reason_codes=(
                    "oauth_refresh_uses_codex_saved_login_exec_witness",
                    "refresh_receipt_observed_codex_unavailable",
                    *surface_unavailable_reasons,
                ),
                evidence_refs=tuple(dict.fromkeys(evidence_refs)),
                remediation_commands=(refresh_command, freshness_command),
            )

        account_live_reasons = _receipt_account_live_unverified_reasons(receipt_item)
        if account_live_reasons:
            return RefreshOutcome(
                status=RefreshStatus.DEFERRED,
                strategy_id=self.strategy_id,
                reason_codes=(
                    "oauth_refresh_uses_codex_saved_login_exec_witness",
                    "refresh_receipt_account_live_unverified",
                    *account_live_reasons,
                    "availability_recheck_required_after_refresh",
                ),
                evidence_refs=tuple(dict.fromkeys(evidence_refs)),
                remediation_commands=(refresh_command, freshness_command),
            )

        return RefreshOutcome(
            status=RefreshStatus.REFRESHED,
            strategy_id=self.strategy_id,
            reason_codes=(
                "oauth_refresh_uses_codex_saved_login_exec_witness",
                "refresh_receipt_written",
                "availability_recheck_required_after_refresh",
            ),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            remediation_commands=(freshness_command,),
        )


class SubscriptionRefreshStrategy:
    """Explicit non-refreshable strategy for ``auth_surface=subscription`` routes.

    Subscription quota is NOT a programmatically refreshable credential like an OAuth token — no
    call mints headroom, and
    account-live subscription telemetry (OTel usage/cost) is not yet wired
    (CASE-CAPACITY-ROUTING-001 R2, "use receipts and manual refresh until observable"). Account-live
    quota for ``claude.headless.full`` is proven ONLY by a short-lived, sanitized admission receipt
    (``scripts/hapax-claude-subscription-quota-admission`` folded into the quota-spend ledger by
    ``scripts/hapax-quota-telemetry-writer``), NEVER inferred from a running lane's tmux/session
    presence. Other subscription routes must register their own provider/route-specific admission
    writer before this strategy can name an executable remediation.

    So this strategy is deliberately DEFERRED-only: it never executes a side effect and never
    attests on its own (attestation stays with ``_account_live_quota_attested`` reading the ledger's
    ``account-live-quota:observed`` evidence ref). Its whole job is to replace the bare
    ``refresh_strategy_absent:subscription`` with a typed, governed remediation naming the receipt
    path. Fail-closed: absent a fresh admission receipt the route stays degraded with these typed
    reasons rather than a missing-strategy hole.
    """

    auth_surface = AuthSurface.SUBSCRIPTION
    strategy_id = "subscription-account-live-quota-admission"

    def refresh(
        self,
        route: PlatformCapabilityRoute,
        freshness: RouteFreshnessCheck,
        *,
        now: datetime,
    ) -> RefreshOutcome:
        if route.route_id != CLAUDE_SUBSCRIPTION_ADMISSION_ROUTE_ID:
            return RefreshOutcome(
                status=RefreshStatus.DEFERRED,
                strategy_id=self.strategy_id,
                reason_codes=(
                    "subscription_quota_not_programmatically_refreshable",
                    "subscription_admission_writer_route_unsupported",
                    "provider_specific_subscription_admission_required",
                ),
                evidence_refs=tuple(
                    dict.fromkeys(
                        [
                            f"platform-capability-registry:{route.route_id}:auth_surface:subscription",
                            f"policy:subscription_admission_writer_route_unsupported:{route.platform.value}",
                            *freshness.evidence_refs,
                        ]
                    )
                ),
                remediation_commands=(
                    f"register subscription quota admission writer for {route.route_id}",
                    "scripts/hapax-quota-telemetry-writer --json",
                ),
            )

        admission_command = (
            "scripts/hapax-claude-subscription-quota-admission "
            "--evidence-ref claude-subscription-headroom-observed-$(date -u +%Y%m%dt%H%M%Sz) "
            "--json"
        )
        telemetry_command = "scripts/hapax-quota-telemetry-writer --json"
        return RefreshOutcome(
            status=RefreshStatus.DEFERRED,
            strategy_id=self.strategy_id,
            reason_codes=(
                "subscription_quota_not_programmatically_refreshable",
                "account_live_quota_requires_admission_receipt",
                "account_live_subscription_quota_not_lane_presence",
                "availability_recheck_required_after_admission_receipt",
            ),
            evidence_refs=tuple(
                dict.fromkeys(
                    [
                        f"platform-capability-registry:{route.route_id}:auth_surface:subscription",
                        "policy:account_live_subscription_quota_not_lane_presence",
                        f"script:{admission_command}",
                        *freshness.evidence_refs,
                    ]
                )
            ),
            remediation_commands=(admission_command, telemetry_command),
        )


def default_refresh_strategy_registry() -> RefreshStrategyRegistry:
    return RefreshStrategyRegistry((CodexOAuthRefreshStrategy(), SubscriptionRefreshStrategy()))


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
    unsupported = tuple(
        route_check for route_check in freshness.routes if not route_check.supported
    )
    return RegistryAvailabilityCheck(
        ok=freshness.ok and all(receipt.available for receipt in receipts),
        checked_at=checked_now,
        route_count=len(route_map),
        receipts=receipts,
        unsupported_routes=unsupported,
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
                *(
                    f"refresh_remediation:{command}"
                    for command in receipt.refresh_remediation_commands
                ),
            ]
        )
    )


def _availability_predicate(
    route: PlatformCapabilityRoute,
    freshness: RouteFreshnessCheck,
) -> AvailabilityPredicate:
    reason_text = "\n".join([*freshness.errors, *freshness.blocked_reasons]).lower()
    account_live_quota_attested = _account_live_quota_attested(route, freshness)
    exec_auth_attested = _exec_auth_attested(route, freshness)
    return AvailabilityPredicate(
        admitted=route.route_state is RouteState.ACTIVE and not route.blocked_reasons,
        auth_fresh=not _contains_reason_token(
            reason_text,
            ("auth", "credential", "oauth", "account_live"),
        )
        and account_live_quota_attested
        and exec_auth_attested,
        quota_headroom=not _contains_reason_token(reason_text, ("quota",))
        and account_live_quota_attested,
        not_degraded=freshness.ok,
        account_live_quota_attested=account_live_quota_attested,
        exec_auth_attested=exec_auth_attested,
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
    if not predicate.account_live_quota_attested:
        reasons.append("account_live_quota_evidence_absent")
    if not predicate.exec_auth_attested:
        reasons.append("codex_exec_auth_witness_absent")
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
            remediation_commands=(
                f"register refresh strategy for auth_surface={route.auth_surface.value}",
            ),
        )
    return strategy.refresh(route, freshness, now=now)


def _blocked_reason_refs(freshness: RouteFreshnessCheck) -> tuple[str, ...]:
    refs: list[str] = []
    for reason in freshness.blocked_reasons:
        refs.append(f"blocked_reason:{reason}")
    return tuple(refs)


def _account_live_quota_attested(
    route: PlatformCapabilityRoute,
    freshness: RouteFreshnessCheck,
) -> bool:
    if route.capacity_pool is not CapacityPool.SUBSCRIPTION_QUOTA:
        return True
    return any(
        _account_live_quota_observed_ref(ref, route_id=route.route_id)
        for ref in freshness.evidence_refs
    ) or _current_session_subscription_quota_attested(route, freshness)


def _account_live_quota_observed_ref(ref: str, *, route_id: str | None = None) -> bool:
    tokens = _ref_tokens(ref)
    if not tokens:
        return False
    if any(token in NEGATIVE_REF_TOKENS for token in tokens):
        return False
    allowed_suffixes = [("account", "live", "quota", "observed")]
    if normalize_route_id(route_id or "") != CLAUDE_SUBSCRIPTION_ADMISSION_ROUTE_ID:
        allowed_suffixes.append(("quota", "status", "observed"))
    return any(tokens[-len(suffix) :] == suffix for suffix in allowed_suffixes)


def _current_session_subscription_quota_attested(
    route: PlatformCapabilityRoute,
    freshness: RouteFreshnessCheck,
) -> bool:
    if route.auth_surface is not AuthSurface.OAUTH:
        return False
    platform = route.platform.value
    refs = tuple(_ref_tokens(ref) for ref in freshness.evidence_refs)
    return (
        any(_ref_startswith(ref, ("local", "current", platform, "session")) for ref in refs)
        and any(
            _ref_startswith(
                ref,
                ("local", "current", platform, "session", "filesystem", "shell", "browser"),
            )
            and "usable" in ref
            for ref in refs
        )
        and any(
            _ref_startswith(ref, ("local", platform, "quota", "probe", "unobservable"))
            for ref in refs
        )
        and any(
            _ref_startswith(ref, ("platform", "capability", "receipt", platform)) for ref in refs
        )
    )


def _exec_auth_attested(
    route: PlatformCapabilityRoute,
    freshness: RouteFreshnessCheck,
) -> bool:
    if route.platform.value != "codex" or route.auth_surface is not AuthSurface.OAUTH:
        return True
    refs = tuple(_ref_tokens(ref) for ref in freshness.evidence_refs)
    expected_hosts = _expected_exec_auth_hosts()
    return any(_exec_auth_ref_attested(ref, expected_hosts=expected_hosts) for ref in refs)


def _exec_auth_ref_attested(
    ref: tuple[str, ...],
    *,
    expected_hosts: frozenset[tuple[str, ...]],
) -> bool:
    if any(token in NEGATIVE_REF_TOKENS for token in ref):
        return False
    if not (
        len(ref) >= 8
        and ref[0] == "host"
        and ref[-6:] == ("codex", "exec", "auth", "saved", "login", "observed")
    ):
        return False
    return ref[1:-6] in expected_hosts


def _expected_exec_auth_hosts() -> frozenset[tuple[str, ...]]:
    dispatch_host = (
        os.environ.get("HAPAX_CODEX_EXEC_AUTH_HOST")
        or os.environ.get("HAPAX_DISPATCH_HOST")
        or os.environ.get("HAPAX_DEFAULT_DISPATCH_HOST")
        or ""
    ).strip()
    if dispatch_host:
        return _host_token_variants(dispatch_host)
    current = socket.gethostname().split(".", 1)[0]
    return (
        _host_token_variants("local")
        | _host_token_variants(current)
        | _host_token_variants("appendix")
    )


def _host_token_variants(host: str) -> frozenset[tuple[str, ...]]:
    tokens = _ref_tokens(host)
    variants = {tokens} if tokens else set()
    if len(tokens) == 1 and tokens[0] not in {"local", "localhost"}:
        variants.add(("hapax", tokens[0]))
    if len(tokens) == 2 and tokens[0] == "hapax":
        variants.add((tokens[1],))
    return frozenset(variants)


def _ref_tokens(ref: str) -> tuple[str, ...]:
    normalized = re.sub(r"[\s_:]+", "-", ref.strip().lower())
    if not normalized:
        return ()
    return tuple(token for token in normalized.split("-") if token)


def _ref_startswith(ref: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return ref[: len(prefix)] == prefix


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return _ensure_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_refresh_command(
    command: tuple[str, ...],
    *,
    timeout_s: float,
) -> RefreshCommandResult:
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            cwd=REPO_ROOT,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        return RefreshCommandResult(
            returncode=124,
            stdout=_string_output(exc.stdout),
            stderr=_string_output(exc.stderr) or f"timeout after {timeout_s}s",
        )
    except OSError as exc:
        return RefreshCommandResult(returncode=127, stderr=str(exc))
    return RefreshCommandResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _string_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _refresh_receipt_item(stdout: str, *, platform: str) -> dict[str, object] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    receipts = payload.get("receipts") if isinstance(payload, dict) else None
    if not isinstance(receipts, list):
        return None
    for item in receipts:
        if isinstance(item, dict) and item.get("platform") == platform:
            return item
    return None


def _receipt_account_live_unverified_reasons(receipt_item: dict[str, object]) -> tuple[str, ...]:
    reasons: list[str] = []
    quota_status = receipt_item.get("quota_status")
    if quota_status != "observed":
        reasons.append(f"refresh_receipt_quota_status:{quota_status or 'missing'}")
    quota_reason_codes = receipt_item.get("quota_reason_codes")
    if not isinstance(quota_reason_codes, list):
        reasons.append("refresh_receipt_quota_reason_codes_missing")
        return tuple(reasons)
    reasons.extend(f"refresh_receipt_quota_reason:{reason}" for reason in quota_reason_codes)
    return tuple(dict.fromkeys(reasons))


def _receipt_surface_unavailable_reasons(receipt_item: dict[str, object]) -> tuple[str, ...]:
    reasons: list[str] = []
    for surface in ("capability", "resource"):
        status = receipt_item.get(f"{surface}_status")
        if status is None:
            reasons.append(f"refresh_receipt_{surface}_status:missing")
            continue
        if status != "observed":
            reasons.append(f"refresh_receipt_{surface}_status:{status}")
        reason_codes = receipt_item.get(f"{surface}_reason_codes")
        if isinstance(reason_codes, list):
            reasons.extend(f"refresh_receipt_{surface}_reason:{reason}" for reason in reason_codes)
        elif status != "observed":
            reasons.append(f"refresh_receipt_{surface}_reason_codes_missing")
    return tuple(dict.fromkeys(reasons))


def _contains_reason_token(reason_text: str, tokens: tuple[str, ...]) -> bool:
    pattern = "|".join(re.escape(token) for token in tokens)
    return re.search(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])", reason_text) is not None


__all__ = [
    "AvailabilityPredicate",
    "AvailabilityStatus",
    "CapabilityAvailabilityReceipt",
    "CodexOAuthRefreshStrategy",
    "RefreshCommandResult",
    "RefreshCommandRunner",
    "RefreshOutcome",
    "RefreshStatus",
    "RefreshStrategy",
    "RefreshStrategyRegistry",
    "RegistryAvailabilityCheck",
    "SubscriptionRefreshStrategy",
    "availability_dispatch_reason_codes",
    "default_refresh_strategy_registry",
    "evaluate_registry_availability",
    "evaluate_route_availability",
]
