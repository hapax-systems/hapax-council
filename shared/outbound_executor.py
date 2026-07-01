from __future__ import annotations

import math
import uuid
from typing import Any, Final

from pydantic import Field, field_validator

from shared.resource_capability import (
    AccountFederationRegistry,
    AuthorityCeiling,
    StrictModel,
)

RECEIVE_ONLY_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        "buy_me_a_coffee",
        "buymeacoffee",
        "bmac",
        "github_sponsors",
        "githubsponsors",
        "ko_fi",
        "kofi",
        "liberapay",
        "mercury",
        "modern_treasury",
        "moderntreasury",
        "omg_lol_pay",
        "omglolpay",
        "open_collective",
        "opencollective",
        "patreon",
        "stripe_payment_link",
        "stripepaymentlink",
        "stripe",
        "treasury_prime",
        "treasuryprime",
    }
)


class OutboundExecutionRequest(StrictModel):
    scope: str
    venue: str
    amount: float
    use_default_token: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    public_gate_passed: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_is_finite_nonnegative(cls, value: Any) -> float:
        try:
            return _finite_nonnegative_float("amount", value)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class OutboundExecutionReceipt(StrictModel):
    receipt_id: str
    status: str  # "admitted" or "refused"
    request: OutboundExecutionRequest
    verdict: str
    refusal_reason: str | None = None
    notional_cap: float
    position_cap: float
    current_position_before: float
    current_position_after: float
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class OutboundExecutionRefusal(ValueError):
    """Raised when outbound execution is refused."""

    def __init__(self, receipt: OutboundExecutionReceipt) -> None:
        self.receipt = receipt
        super().__init__(f"Outbound execution refused: {receipt.verdict}")


class OutboundExecutor:
    """Bounded-outbound executor governing send_scopes."""

    def __init__(
        self,
        *,
        authority_ceiling: AuthorityCeiling,
        venue_allowlist: set[str] | frozenset[str],
        notional_cap: float,
        position_cap: float,
        current_position: float = 0.0,
        kill_switch: bool = False,
        registry: AccountFederationRegistry,
    ) -> None:
        if not isinstance(authority_ceiling, AuthorityCeiling):
            raise TypeError(
                "authority_ceiling must be an AuthorityCeiling; next action: pass "
                "one of the governed AuthorityCeiling enum values"
            )
        if not isinstance(registry, AccountFederationRegistry):
            raise TypeError(
                "registry must be an AccountFederationRegistry; next action: load "
                "the account federation registry before constructing the executor"
            )
        if not venue_allowlist:
            raise ValueError(
                "venue_allowlist must name at least one allowed venue; next action: "
                "supply the governed venue allowlist for this route"
            )
        self.authority_ceiling = authority_ceiling
        self.venue_allowlist = frozenset(venue_allowlist)
        self.notional_cap = _finite_nonnegative_float("notional_cap", notional_cap)
        self.position_cap = _finite_nonnegative_float("position_cap", position_cap)
        self.current_position = _finite_nonnegative_float("current_position", current_position)
        self.kill_switch = kill_switch
        self.registry = registry

    def validate_request(self, request: OutboundExecutionRequest) -> OutboundExecutionReceipt:
        """Dry-run validate an execution request without mutating the position."""
        receipt_id = f"outbound-receipt-{uuid.uuid4()}"

        def _refuse(reason: str, verdict: str, next_action: str) -> OutboundExecutionReceipt:
            return OutboundExecutionReceipt(
                receipt_id=receipt_id,
                status="refused",
                request=request,
                verdict=f"{verdict}. Next action: {next_action}",
                refusal_reason=reason,
                notional_cap=self.notional_cap,
                position_cap=self.position_cap,
                current_position_before=self.current_position,
                current_position_after=self.current_position,
                evidence_refs=request.evidence_refs,
                metadata={"next_action": next_action},
            )

        # A no-claim ceiling refuses before route-specific checks can reveal state.
        if self.authority_ceiling is AuthorityCeiling.NO_CLAIM:
            return _refuse(
                "authority_ceiling_exceeded",
                "Outbound execution refused: authority ceiling is NO_CLAIM",
                "raise authority through the governed capability route before retrying",
            )

        # 1. Kill Switch
        if self.kill_switch:
            return _refuse(
                "kill_switch_active",
                "Outbound execution refused: kill switch is active",
                "clear or rotate the governed kill switch only after independent authorization",
            )

        # 2. Receive-only rail check
        provider_keys = _provider_keys(self.registry.provider)
        if provider_keys & RECEIVE_ONLY_PROVIDERS:
            return _refuse(
                "receive_only_rail",
                f"Outbound execution refused: provider {self.registry.provider} is a receive-only rail",
                "switch to a send-authorized registry entry; do not repurpose receive-only rails",
            )

        # 3. Missing scope check
        if request.scope not in self.registry.send_scopes:
            return _refuse(
                "missing_scope",
                f"Outbound execution refused: scope {request.scope} is not in registry send_scopes",
                "add a governed send_scope to the registry or choose an already authorized scope",
            )

        # 4. Default token fallback check
        if request.use_default_token:
            return _refuse(
                "default_token_fallback",
                "Outbound execution refused: default token fallback requested",
                "bind an explicit governed token reference and retry without default fallback",
            )
        if self.registry.no_fallback_to_default_token is not True:
            return _refuse(
                "default_token_fallback",
                "Outbound execution refused: registry does not enforce no_fallback_to_default_token",
                "set no_fallback_to_default_token to true before enabling outbound execution",
            )
        key_val = self.registry.pass_or_secret_key.strip()
        if not key_val or key_val.startswith("pass:placeholder") or key_val == "placeholder":
            return _refuse(
                "default_token_fallback",
                "Outbound execution refused: no fallback allowed and secret key is a placeholder or empty",
                "replace the placeholder with a governed pass or secret reference",
            )

        # 5. Forbidden Action check
        if request.scope in self.registry.forbidden_actions:
            return _refuse(
                "forbidden_action",
                f"Outbound execution refused: scope {request.scope} is a forbidden action",
                "remove the forbidden action or route through a new governed authority case",
            )

        # 6. Venue Allowlist check
        if request.venue not in self.venue_allowlist:
            return _refuse(
                "venue_not_allowed",
                f"Outbound execution refused: venue {request.venue} is not allowed",
                "choose an allowlisted venue or update the route's governed venue allowlist",
            )

        # 7. Notional Cap check
        if request.amount > self.notional_cap:
            return _refuse(
                "notional_cap_exceeded",
                f"Outbound execution refused: request amount {request.amount} exceeds notional cap {self.notional_cap}",
                "lower the requested amount or raise the notional cap through governance",
            )

        # 8. Position Cap check
        if self.current_position + request.amount > self.position_cap:
            return _refuse(
                "position_cap_exceeded",
                f"Outbound execution refused: position {self.current_position + request.amount} exceeds cap {self.position_cap}",
                "reduce the request or reset/raise the position cap through governance",
            )

        # 9. Authority Ceiling check
        if self.authority_ceiling is AuthorityCeiling.INTERNAL_ONLY:
            if not (
                request.venue == "internal"
                or request.venue.startswith("internal:")
                or request.venue.startswith("private_internal")
            ):
                return _refuse(
                    "authority_ceiling_exceeded",
                    f"Outbound execution refused: INTERNAL_ONLY ceiling blocks external venue {request.venue}",
                    "use an internal venue or raise the authority ceiling through governance",
                )
        elif self.authority_ceiling is AuthorityCeiling.EVIDENCE_BOUND:
            if not request.evidence_refs:
                return _refuse(
                    "authority_ceiling_exceeded",
                    "Outbound execution refused: EVIDENCE_BOUND ceiling requires evidence_refs",
                    "attach durable evidence_refs for the requested outbound action",
                )
        elif self.authority_ceiling is AuthorityCeiling.PUBLIC_GATE_REQUIRED:
            if not request.public_gate_passed:
                return _refuse(
                    "authority_ceiling_exceeded",
                    "Outbound execution refused: PUBLIC_GATE_REQUIRED ceiling requires public_gate_passed",
                    "complete the public gate and set public_gate_passed only from that receipt",
                )

        # Admitted!
        return OutboundExecutionReceipt(
            receipt_id=receipt_id,
            status="admitted",
            request=request,
            verdict="Outbound execution admitted under governed checks",
            notional_cap=self.notional_cap,
            position_cap=self.position_cap,
            current_position_before=self.current_position,
            current_position_after=self.current_position + request.amount,
            evidence_refs=request.evidence_refs,
        )

    def execute(self, request: OutboundExecutionRequest) -> OutboundExecutionReceipt:
        """Validate request and, if admitted, mutate executor's current position."""
        receipt = self.validate_request(request)
        if receipt.status == "admitted":
            self.current_position = receipt.current_position_after
        return receipt

    def require_execution(self, request: OutboundExecutionRequest) -> OutboundExecutionReceipt:
        """Execute request, raising OutboundExecutionRefusal if blocked."""
        receipt = self.execute(request)
        if receipt.status == "refused":
            raise OutboundExecutionRefusal(receipt)
        return receipt


def _finite_nonnegative_float(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(
            f"{name} must be a numeric cap; next action: supply a finite non-negative number"
        )
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(
            f"{name} must be finite and >= 0; next action: supply a bounded non-negative number"
        )
    return normalized


def _provider_keys(provider: str) -> frozenset[str]:
    normalized = provider.strip().casefold().replace("-", "_").replace(" ", "_").replace(".", "_")
    return frozenset({normalized.strip("_"), "".join(ch for ch in normalized if ch.isalnum())})


# This module is a governed contract for downstream lane adapters. Keep the
# dynamic entrypoints and Pydantic validators visible to the diff-only
# unused-callable gate until those adapters land.
_OUTBOUND_EXECUTOR_ENTRYPOINTS: Final = (
    OutboundExecutionRequest._amount_is_finite_nonnegative,
    OutboundExecutor,
    OutboundExecutor.require_execution,
)
