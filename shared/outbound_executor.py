from __future__ import annotations

import math
import threading
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, Literal

from pydantic import ConfigDict, Field, field_serializer, field_validator

from shared.license_request_price_class_router import ReceiveOnlyRail as LicenseReceiveOnlyRail
from shared.payment_aggregator_v2_support_normalizer import Rail as SupportRail
from shared.resource_capability import (
    FORBIDDEN_PROVIDER_WRITE_SCOPES,
    AccountFederationRegistry,
    AuthorityCeiling,
    StrictModel,
)


def _provider_keys(provider: str) -> frozenset[str]:
    normalized = provider.strip().casefold().replace("-", "_").replace(" ", "_").replace(".", "_")
    aliases = {normalized.strip("_")}
    if normalized.endswith("_receiver"):
        aliases.add(normalized.removesuffix("_receiver").strip("_"))
    return frozenset(
        alias
        for key in aliases
        if key
        for alias in (key, "".join(ch for ch in key if ch.isalnum()))
    )


def _provider_alias_keys(providers: frozenset[str]) -> frozenset[str]:
    return frozenset(key for provider in providers for key in _provider_keys(provider))


_PUBLIC_GATE_EVIDENCE_PREFIXES: Final[tuple[str, ...]] = (
    "public-gate:",
    "public_gate:",
    "receipt:public-gate:",
)
_MAX_EXACT_FLOAT_INT: Final[int] = 2**53
_SOURCE_RECEIVE_ONLY_PROVIDERS: Final[frozenset[str]] = frozenset(
    {rail.value for rail in SupportRail}
    | {rail.value for rail in LicenseReceiveOnlyRail if rail is not LicenseReceiveOnlyRail.NO_RAIL}
)
_PROCESSOR_RECEIVE_ONLY_PROVIDER_ALIASES: Final[frozenset[str]] = frozenset(
    {
        "base_usdc",
        "lightning",
        "nostr_zap",
        "usdc",
        "usdc_base",
        "x402",
        "x402_usdc_base",
    }
)
_LEGACY_RECEIVE_ONLY_PROVIDER_ALIASES: Final[frozenset[str]] = frozenset(
    {
        "buy_me_a_coffee",
        "bmac",
        "ko_fi",
        "mercury",
        "modern_treasury",
        "omg_lol_pay",
        "open_collective",
        "patreon",
        "stripe",
        "stripe_payment_link",
        "treasury_prime",
    }
)


RECEIVE_ONLY_PROVIDERS: Final[frozenset[str]] = frozenset(
    _provider_alias_keys(_SOURCE_RECEIVE_ONLY_PROVIDERS)
    | _provider_alias_keys(_PROCESSOR_RECEIVE_ONLY_PROVIDER_ALIASES)
    | _provider_alias_keys(_LEGACY_RECEIVE_ONLY_PROVIDER_ALIASES)
)


class OutboundExecutionRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: str
    venue: str
    amount: float
    use_default_token: bool = False
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_gate_passed: bool = False
    payload: Mapping[str, Any] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("scope", mode="before")
    @classmethod
    def _scope_is_nonblank_string(cls, value: Any) -> str:
        return _nonblank_string("scope", value)

    @field_validator("venue", mode="before")
    @classmethod
    def _venue_is_nonblank_string(cls, value: Any) -> str:
        return _nonblank_string("venue", value)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_is_finite_nonnegative(cls, value: Any) -> float:
        try:
            return _finite_nonnegative_float("amount", value)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("public_gate_passed", mode="before")
    @classmethod
    def _public_gate_passed_is_explicit_bool(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError(
                "public_gate_passed must be an explicit bool; next action: bind "
                "only a governed public gate receipt result"
            )
        return value

    @field_validator("use_default_token", mode="before")
    @classmethod
    def _use_default_token_is_explicit_bool(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError(
                "use_default_token must be an explicit bool; next action: bind "
                "a governed token decision without fallback coercion"
            )
        return value

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def _evidence_refs_are_nonblank_strings(cls, value: Any) -> Any:
        if value is None:
            raise ValueError(
                "evidence_refs must be a list or tuple of strings; next action: "
                "attach durable evidence reference strings"
            )
        if not isinstance(value, list | tuple):
            raise ValueError(
                "evidence_refs must be a list or tuple of strings; next action: "
                "attach durable evidence reference strings"
            )
        for ref in value:
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError(
                    "evidence_refs must contain only nonblank strings; next action: "
                    "attach durable evidence reference strings"
                )
        return tuple(value)

    @field_validator("payload", mode="before")
    @classmethod
    def _payload_is_string_key_mapping(cls, value: Any) -> Any:
        return _validate_mapping_shape("payload", value)

    @field_validator("payload", mode="after")
    @classmethod
    def _payload_is_immutable(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_mapping("payload", value)

    @field_serializer("payload")
    def _serialize_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _thaw_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class OutboundExecutionReceipt(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str
    status: Literal["admitted", "refused"]
    request: OutboundExecutionRequest
    verdict: str
    refusal_reason: str | None = None
    notional_cap: float
    position_cap: float
    current_position_before: float
    current_position_after: float
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    metadata: Mapping[str, Any] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_is_string_key_mapping(cls, value: Any) -> Any:
        return _validate_mapping_shape("metadata", value)

    @field_validator("metadata", mode="after")
    @classmethod
    def _metadata_is_immutable(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_mapping("metadata", value)

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _thaw_mapping(value)

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
        kill_switch: bool | None = None,
        public_gate_receipts: set[str] | frozenset[str] | None = None,
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
        if isinstance(venue_allowlist, str) or not isinstance(venue_allowlist, set | frozenset):
            raise TypeError(
                "venue_allowlist must be a set or frozenset of venue strings; "
                "next action: supply the governed venue allowlist for this route"
            )
        if not venue_allowlist:
            raise ValueError(
                "venue_allowlist must name at least one allowed venue; next action: "
                "supply the governed venue allowlist for this route"
            )
        if not all(isinstance(venue, str) for venue in venue_allowlist):
            raise TypeError(
                "venue_allowlist entries must be strings; next action: remove non-string venues"
            )
        if not all(venue.strip() for venue in venue_allowlist):
            raise ValueError(
                "venue_allowlist entries must be nonblank; next action: remove blank venues"
            )
        if not isinstance(kill_switch, bool):
            raise TypeError(
                "kill_switch must be an explicit bool; next action: bind the governed "
                "kill switch state before constructing the executor"
            )
        self.authority_ceiling = authority_ceiling
        self.venue_allowlist = frozenset(venue_allowlist)
        self.notional_cap = _finite_nonnegative_float("notional_cap", notional_cap)
        self.position_cap = _finite_nonnegative_float("position_cap", position_cap)
        self.current_position = _finite_nonnegative_float("current_position", current_position)
        self.kill_switch = kill_switch
        self.public_gate_receipts = _normalize_public_gate_receipts(public_gate_receipts)
        self.registry = registry
        self.send_scopes = _normalize_scope_collection(
            "registry.send_scopes",
            registry.send_scopes,
        )
        self.forbidden_actions = _normalize_scope_collection(
            "registry.forbidden_actions",
            registry.forbidden_actions,
        )
        self._position_lock = threading.RLock()

    def validate_request(self, request: OutboundExecutionRequest) -> OutboundExecutionReceipt:
        """Dry-run validate an execution request without mutating the position."""
        with self._position_lock:
            return self._validate_request_locked(request)

    def _validate_request_locked(
        self, request: OutboundExecutionRequest
    ) -> OutboundExecutionReceipt:
        """Validate a request while the position lock is held."""
        request = _snapshot_request(request)
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

        admission_metadata: dict[str, Any] = {}

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
        if request.scope not in self.send_scopes:
            return _refuse(
                "missing_scope",
                f"Outbound execution refused: scope {request.scope} is not in registry send_scopes",
                "add a governed send_scope to the registry or choose an already authorized scope",
            )

        # 4. Forbidden Action check
        if (
            request.scope in FORBIDDEN_PROVIDER_WRITE_SCOPES
            or request.scope in self.forbidden_actions
        ):
            return _refuse(
                "forbidden_action",
                f"Outbound execution refused: scope {request.scope} is a forbidden action",
                "remove the forbidden action or route through a new governed authority case",
            )

        # 5. Default token fallback check
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

        # 6. Venue Allowlist check
        if request.venue not in self.venue_allowlist:
            return _refuse(
                "venue_not_allowed",
                f"Outbound execution refused: venue {request.venue} is not allowed",
                "choose an allowlisted venue or update the route's governed venue allowlist",
            )

        # 7. Notional Cap check
        if _exceeds_cap(request.amount, self.notional_cap):
            return _refuse(
                "notional_cap_exceeded",
                f"Outbound execution refused: request amount {request.amount} exceeds notional cap {self.notional_cap}",
                "lower the requested amount or raise the notional cap through governance",
            )

        # 8. Position Cap check
        position_after_decimal = _position_after_decimal(self.current_position, request.amount)
        position_after = float(position_after_decimal)
        if _exceeds_decimal_cap(position_after_decimal, self.position_cap):
            return _refuse(
                "position_cap_exceeded",
                f"Outbound execution refused: position {position_after} exceeds cap {self.position_cap}",
                "reduce the request or reset/raise the position cap through governance",
            )
        if _decimal(position_after) != position_after_decimal:
            return _refuse(
                "position_precision_loss",
                f"Outbound execution refused: position {position_after_decimal} cannot be represented exactly",
                "lower the request amount or use a smaller current position before retrying",
            )

        # 9. Authority Ceiling check
        if self.authority_ceiling is AuthorityCeiling.INTERNAL_ONLY:
            if not (
                request.venue == "internal"
                or request.venue.startswith("internal:")
                # Legacy private runner prefix; still requires exact allowlist membership above.
                or request.venue.startswith("private_internal")
            ):
                return _refuse(
                    "authority_ceiling_exceeded",
                    f"Outbound execution refused: INTERNAL_ONLY ceiling blocks external venue {request.venue}",
                    "use an internal venue or raise the authority ceiling through governance",
                )
        elif self.authority_ceiling is AuthorityCeiling.EVIDENCE_BOUND:
            if not _has_durable_evidence(request.evidence_refs):
                return _refuse(
                    "authority_ceiling_exceeded",
                    "Outbound execution refused: EVIDENCE_BOUND ceiling requires evidence_refs",
                    "attach durable evidence_refs for the requested outbound action",
                )
        elif self.authority_ceiling is AuthorityCeiling.PUBLIC_GATE_REQUIRED:
            public_gate_evidence_ref = _bound_public_gate_evidence_ref(
                request.evidence_refs,
                self.public_gate_receipts,
            )
            if not request.public_gate_passed or public_gate_evidence_ref is None:
                return _refuse(
                    "authority_ceiling_exceeded",
                    "Outbound execution refused: PUBLIC_GATE_REQUIRED ceiling requires bound public gate evidence",
                    "complete the public gate, bind its durable receipt to the executor, "
                    "and attach that evidence_ref before retrying",
                )
            admission_metadata["public_gate_evidence_ref"] = public_gate_evidence_ref

        # Admitted!
        return OutboundExecutionReceipt(
            receipt_id=receipt_id,
            status="admitted",
            request=request,
            verdict="Outbound execution admitted under governed checks",
            notional_cap=self.notional_cap,
            position_cap=self.position_cap,
            current_position_before=self.current_position,
            current_position_after=position_after,
            evidence_refs=request.evidence_refs,
            metadata=admission_metadata,
        )

    def execute(self, request: OutboundExecutionRequest) -> OutboundExecutionReceipt:
        """Validate request and, if admitted, mutate executor's current position."""
        with self._position_lock:
            receipt = self._validate_request_locked(request)
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
    if isinstance(value, int) and abs(value) > _MAX_EXACT_FLOAT_INT:
        raise ValueError(
            f"{name} must fit exact float integer bounds; next action: supply a bounded "
            "non-negative number no larger than 2**53"
        )
    try:
        normalized = float(value)
    except OverflowError as exc:
        raise ValueError(
            f"{name} must be finite and >= 0; next action: supply a bounded non-negative number"
        ) from exc
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(
            f"{name} must be finite and >= 0; next action: supply a bounded non-negative number"
        )
    return normalized


def _nonblank_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} must be a nonblank string; next action: bind a governed nonblank value"
        )
    return value.strip()


def _normalize_scope_collection(name: str, values: Any) -> frozenset[str]:
    if isinstance(values, str) or not isinstance(values, list | tuple | set | frozenset):
        raise TypeError(
            f"{name} must be a list, tuple, or set of scope strings; next action: "
            "load a validated account federation registry"
        )
    return frozenset(_nonblank_string(f"{name} entries", value) for value in values)


def _snapshot_request(request: OutboundExecutionRequest) -> OutboundExecutionRequest:
    if not isinstance(request, OutboundExecutionRequest):
        raise TypeError(
            "request must be an OutboundExecutionRequest; next action: validate the "
            "outbound request before execution"
        )
    return OutboundExecutionRequest(
        scope=request.scope,
        venue=request.venue,
        amount=request.amount,
        use_default_token=request.use_default_token,
        evidence_refs=request.evidence_refs,
        public_gate_passed=request.public_gate_passed,
        payload=request.payload,
    )


def _validate_mapping_shape(name: str, value: Any) -> Any:
    if value is None:
        raise ValueError(
            f"{name} must be a mapping with string keys; next action: attach "
            "durable JSON-object evidence"
        )
    if not isinstance(value, Mapping):
        raise ValueError(
            f"{name} must be a mapping with string keys; next action: attach "
            "durable JSON-object evidence"
        )
    _validate_string_keys(name, value)
    return value


def _validate_string_keys(name: str, value: Mapping[Any, Any]) -> None:
    for key, nested_value in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(
                f"{name} keys must be nonblank strings; next action: attach "
                "durable JSON-object evidence"
            )
        if isinstance(nested_value, Mapping):
            _validate_string_keys(name, nested_value)


def _freeze_mapping(name: str, value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {key: _freeze_value(name, nested_value) for key, nested_value in value.items()}
    )


def _freeze_value(name: str, value: Any) -> Any:
    if isinstance(value, Mapping):
        _validate_string_keys(name, value)
        return _freeze_mapping(name, value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(name, nested_value) for nested_value in value)
    if isinstance(value, bool | str) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        raise ValueError(
            f"{name} values must be finite JSON-compatible scalars; next action: "
            "replace non-finite values with durable string, number, bool, or null evidence"
        )
    raise ValueError(
        f"{name} values must be JSON-compatible immutable evidence; next action: "
        "replace mutable or non-JSON values with durable string, number, bool, null, "
        "list, or object evidence"
    )


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _thaw_value(nested_value) for key, nested_value in value.items()}


def _thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _thaw_mapping(value)
    if isinstance(value, tuple):
        return [_thaw_value(nested_value) for nested_value in value]
    return value


def _exceeds_cap(value: float, cap: float) -> bool:
    return _exceeds_decimal_cap(_decimal(value), cap)


def _exceeds_decimal_cap(value: Decimal, cap: float) -> bool:
    return value > _decimal(cap)


def _position_after_decimal(current_position: float, amount: float) -> Decimal:
    return _decimal(current_position) + _decimal(amount)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _normalize_public_gate_receipts(
    public_gate_receipts: set[str] | frozenset[str] | None,
) -> frozenset[str]:
    if public_gate_receipts is None:
        return frozenset()
    if isinstance(public_gate_receipts, str) or not isinstance(
        public_gate_receipts, set | frozenset
    ):
        raise TypeError(
            "public_gate_receipts must be a set or frozenset of durable public-gate "
            "evidence refs; next action: bind receipts produced by the public gate"
        )
    if not all(isinstance(ref, str) for ref in public_gate_receipts):
        raise TypeError(
            "public_gate_receipts entries must be strings; next action: remove "
            "non-string public gate refs"
        )
    normalized = frozenset(ref.strip() for ref in public_gate_receipts)
    if not all(normalized):
        raise ValueError(
            "public_gate_receipts entries must be nonblank; next action: remove blank refs"
        )
    if not all(_is_public_gate_evidence_ref(ref) for ref in normalized):
        raise ValueError(
            "public_gate_receipts entries must use public-gate evidence refs; next action: "
            "bind refs with a public-gate receipt prefix"
        )
    return normalized


def _has_durable_evidence(evidence_refs: Sequence[str]) -> bool:
    return any(ref.strip() for ref in evidence_refs)


def _is_public_gate_evidence_ref(ref: str) -> bool:
    return ref.strip().casefold().startswith(_PUBLIC_GATE_EVIDENCE_PREFIXES)


def _bound_public_gate_evidence_ref(
    evidence_refs: Sequence[str],
    public_gate_receipts: frozenset[str],
) -> str | None:
    if not public_gate_receipts:
        return None
    for ref in evidence_refs:
        normalized = ref.strip()
        if normalized in public_gate_receipts and _is_public_gate_evidence_ref(normalized):
            return normalized
    return None


# This module is a governed contract for downstream lane adapters. Keep the
# dynamic entrypoints and Pydantic validators visible to the diff-only
# unused-callable gate until those adapters land.
_OUTBOUND_EXECUTOR_ENTRYPOINTS: Final = (
    OutboundExecutionRefusal,
    OutboundExecutionRequest._scope_is_nonblank_string,
    OutboundExecutionRequest._venue_is_nonblank_string,
    OutboundExecutionRequest._amount_is_finite_nonnegative,
    OutboundExecutionRequest._public_gate_passed_is_explicit_bool,
    OutboundExecutionRequest._use_default_token_is_explicit_bool,
    OutboundExecutionRequest._evidence_refs_are_nonblank_strings,
    OutboundExecutionRequest._payload_is_string_key_mapping,
    OutboundExecutionRequest._payload_is_immutable,
    OutboundExecutionRequest._serialize_payload,
    OutboundExecutionReceipt._metadata_is_string_key_mapping,
    OutboundExecutionReceipt._metadata_is_immutable,
    OutboundExecutionReceipt._serialize_metadata,
    OutboundExecutor,
    OutboundExecutor.validate_request,
    OutboundExecutor.require_execution,
    _normalize_public_gate_receipts,
    _is_public_gate_evidence_ref,
    _bound_public_gate_evidence_ref,
)
