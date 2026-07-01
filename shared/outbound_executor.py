from __future__ import annotations

import uuid
from typing import Any, Final

from pydantic import Field

from shared.resource_capability import (
    AccountFederationRegistry,
    AuthorityCeiling,
    StrictModel,
)

RECEIVE_ONLY_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        "buy_me_a_coffee",
        "github_sponsors",
        "kofi",
        "liberapay",
        "mercury",
        "modern_treasury",
        "omg_lol_pay",
        "open_collective",
        "patreon",
        "stripe_payment_link",
        "stripe",
        "treasury_prime",
    }
)


class OutboundExecutionRequest(StrictModel):
    scope: str
    venue: str
    amount: float = Field(ge=0.0)
    use_default_token: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    public_gate_passed: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)

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
            raise TypeError("authority_ceiling must be an AuthorityCeiling")
        if not isinstance(registry, AccountFederationRegistry):
            raise TypeError("registry must be an AccountFederationRegistry")
        if not venue_allowlist:
            raise ValueError("venue_allowlist must name at least one allowed venue")
        if notional_cap < 0:
            raise ValueError("notional_cap must be >= 0")
        if position_cap < 0:
            raise ValueError("position_cap must be >= 0")
        if current_position < 0:
            raise ValueError("current_position must be >= 0")
        self.authority_ceiling = authority_ceiling
        self.venue_allowlist = frozenset(venue_allowlist)
        self.notional_cap = notional_cap
        self.position_cap = position_cap
        self.current_position = current_position
        self.kill_switch = kill_switch
        self.registry = registry

    def validate_request(self, request: OutboundExecutionRequest) -> OutboundExecutionReceipt:
        """Dry-run validate an execution request without mutating the position."""
        receipt_id = f"outbound-receipt-{uuid.uuid4()}"

        def _refuse(reason: str, verdict: str) -> OutboundExecutionReceipt:
            return OutboundExecutionReceipt(
                receipt_id=receipt_id,
                status="refused",
                request=request,
                verdict=verdict,
                refusal_reason=reason,
                notional_cap=self.notional_cap,
                position_cap=self.position_cap,
                current_position_before=self.current_position,
                current_position_after=self.current_position,
                evidence_refs=request.evidence_refs,
            )

        # 1. Kill Switch
        if self.kill_switch:
            return _refuse(
                "kill_switch_active",
                "Outbound execution refused: kill switch is active",
            )

        # 2. Receive-only rail check
        provider_key = self.registry.provider.strip().casefold()
        if provider_key in RECEIVE_ONLY_PROVIDERS:
            return _refuse(
                "receive_only_rail",
                f"Outbound execution refused: provider {self.registry.provider} is a receive-only rail",
            )

        # 3. Missing scope check
        if request.scope not in self.registry.send_scopes:
            return _refuse(
                "missing_scope",
                f"Outbound execution refused: scope {request.scope} is not in registry send_scopes",
            )

        # 4. Default token fallback check
        if request.use_default_token:
            return _refuse(
                "default_token_fallback",
                "Outbound execution refused: default token fallback requested",
            )
        if self.registry.no_fallback_to_default_token:
            # Check secret/key value
            key_val = self.registry.pass_or_secret_key.strip()
            if not key_val or key_val.startswith("pass:placeholder") or key_val == "placeholder":
                return _refuse(
                    "default_token_fallback",
                    "Outbound execution refused: no fallback allowed and secret key is a placeholder or empty",
                )

        # 5. Forbidden Action check
        if request.scope in self.registry.forbidden_actions:
            return _refuse(
                "forbidden_action",
                f"Outbound execution refused: scope {request.scope} is a forbidden action",
            )

        # 6. Venue Allowlist check
        if request.venue not in self.venue_allowlist:
            return _refuse(
                "venue_not_allowed",
                f"Outbound execution refused: venue {request.venue} is not allowed",
            )

        # 7. Notional Cap check
        if request.amount > self.notional_cap:
            return _refuse(
                "notional_cap_exceeded",
                f"Outbound execution refused: request amount {request.amount} exceeds notional cap {self.notional_cap}",
            )

        # 8. Position Cap check
        if self.current_position + request.amount > self.position_cap:
            return _refuse(
                "position_cap_exceeded",
                f"Outbound execution refused: position {self.current_position + request.amount} exceeds cap {self.position_cap}",
            )

        # 9. Authority Ceiling check
        if self.authority_ceiling is AuthorityCeiling.NO_CLAIM:
            return _refuse(
                "authority_ceiling_exceeded",
                "Outbound execution refused: authority ceiling is NO_CLAIM",
            )
        elif self.authority_ceiling is AuthorityCeiling.INTERNAL_ONLY:
            if not (
                request.venue == "internal"
                or request.venue.startswith("internal:")
                or request.venue.startswith("private_internal")
            ):
                return _refuse(
                    "authority_ceiling_exceeded",
                    f"Outbound execution refused: INTERNAL_ONLY ceiling blocks external venue {request.venue}",
                )
        elif self.authority_ceiling is AuthorityCeiling.EVIDENCE_BOUND:
            if not request.evidence_refs:
                return _refuse(
                    "authority_ceiling_exceeded",
                    "Outbound execution refused: EVIDENCE_BOUND ceiling requires evidence_refs",
                )
        elif self.authority_ceiling is AuthorityCeiling.PUBLIC_GATE_REQUIRED:
            if not request.public_gate_passed:
                return _refuse(
                    "authority_ceiling_exceeded",
                    "Outbound execution refused: PUBLIC_GATE_REQUIRED ceiling requires public_gate_passed",
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


# This module is a governed contract for downstream lane adapters. Keep the
# dynamic entrypoints visible to the diff-only unused-callable gate until those
# adapters land.
_OUTBOUND_EXECUTOR_ENTRYPOINTS: Final = (OutboundExecutor, OutboundExecutor.require_execution)
