from __future__ import annotations

import math
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final, Literal

from pydantic import ConfigDict, Field, field_serializer, field_validator, model_validator

from shared.outbound_executor import (
    OutboundExecutionReceipt,
    OutboundExecutionRequest,
    OutboundExecutor,
)
from shared.resource_capability import (
    AccountFederationRegistry,
    AuthorityCeiling,
    StrictModel,
)

YOUTUBE_PUBLIC_UPLOAD_SCOPE: Final[str] = "youtube_video_insert"
YOUTUBE_PUBLIC_VENUE: Final[str] = "youtube:public-upload-template"
YOUTUBE_SCOPED_TOKEN_REF: Final[str] = "pass:google/token-youtube-streaming"

_GOVERNED_SECRET_REF_PREFIXES: Final[tuple[str, ...]] = ("pass:", "hapax-secrets:")

__all__ = (
    "YOUTUBE_PUBLIC_UPLOAD_SCOPE",
    "YOUTUBE_PUBLIC_VENUE",
    "YOUTUBE_SCOPED_TOKEN_REF",
    "BoundedOutboundLane",
    "OutboundLaneActReceipt",
    "OutboundLaneActRequest",
    "OutboundRateLimit",
    "ScopedOutboundToken",
    "build_youtube_public_upload_lane_template",
)


class ScopedOutboundToken(StrictModel):
    """Governed token reference plus the send scopes it may authorize."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    token_ref: str
    scopes: tuple[str, ...] = Field(min_length=1)

    @field_validator("token_ref", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _token_ref_is_governed(cls, value: Any) -> str:
        token_ref = _nonblank_string("token_ref", value)
        if not _is_governed_secret_ref(token_ref):
            raise ValueError(
                "token_ref must be a governed pass: or hapax-secrets: reference; "
                "next action: bind a scoped token reference, not a default token"
            )
        return token_ref

    @field_validator("scopes", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _scopes_are_nonblank_strings(cls, value: Any) -> tuple[str, ...]:
        return _nonblank_string_tuple("scopes", value)


class OutboundRateLimit(StrictModel):
    """Fixed-window limiter policy for a lane template."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_actions: int
    window_seconds: float

    @field_validator("max_actions", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _max_actions_is_positive_int(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "max_actions must be a positive integer; next action: bind "
                "a lane rate limit with at least one action per window"
            )
        if value <= 0:
            raise ValueError(
                "max_actions must be a positive integer; next action: bind "
                "a lane rate limit with at least one action per window"
            )
        return value

    @field_validator("window_seconds", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _window_seconds_is_positive_number(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(
                "window_seconds must be a positive finite number; next action: "
                "bind the duration of the governed rate-limit window"
            )
        normalized = float(value)
        if not math.isfinite(normalized) or normalized <= 0:
            raise ValueError(
                "window_seconds must be a positive finite number; next action: "
                "bind the duration of the governed rate-limit window"
            )
        return normalized


class OutboundLaneActRequest(StrictModel):
    """One bounded lane act. This is a template request, not provider execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    scope: str
    venue: str
    amount: float = 0.0
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_gate_passed: bool = False
    public_egress_requested: bool = False
    money_movement_requested: bool = False
    payload: Mapping[str, Any] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("action_id", "scope", "venue", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _string_fields_are_nonblank(cls, value: Any, info: Any) -> str:
        return _nonblank_string(info.field_name, value)

    @field_validator("amount", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _amount_is_finite_nonnegative(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(
                "amount must be a finite non-negative number; next action: "
                "use 0.0 for public-egress-only lanes"
            )
        normalized = float(value)
        if not math.isfinite(normalized) or normalized < 0:
            raise ValueError(
                "amount must be a finite non-negative number; next action: "
                "use 0.0 for public-egress-only lanes"
            )
        return normalized

    @field_validator(  # noqa: V105 - Pydantic reflection hook.
        "public_gate_passed",
        "public_egress_requested",
        "money_movement_requested",
        mode="before",
    )
    @classmethod
    def _bool_fields_are_explicit(cls, value: Any, info: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError(
                f"{info.field_name} must be an explicit bool; next action: "
                "bind the boolean authority decision without coercion"
            )
        return value

    @field_validator("evidence_refs", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _evidence_refs_are_nonblank_strings(cls, value: Any) -> tuple[str, ...]:
        return _nonblank_string_tuple("evidence_refs", value, allow_empty=True)

    @field_validator("payload", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _payload_is_mapping(cls, value: Any) -> Mapping[str, Any]:
        if value is None or not isinstance(value, Mapping):
            raise ValueError(
                "payload must be a mapping with string keys; next action: "
                "attach a durable JSON-object payload"
            )
        _validate_string_keys("payload", value)
        return value

    @field_validator("payload", mode="after")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _payload_is_immutable(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_mapping("payload", value)

    @field_serializer("payload")  # noqa: V105 - Pydantic reflection hook.
    def _serialize_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _thaw_mapping(value)


class OutboundLaneActReceipt(StrictModel):
    """Per-act receipt for the lane template wrapper."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_id: str
    lane_id: str
    action_id: str
    status: Literal["admitted", "refused"]
    refusal_reason: str | None = None
    scoped_token_ref: str
    rate_limit_remaining: int
    public_egress_authorized: bool
    money_movement_authorized: bool
    outbound_receipt: OutboundExecutionReceipt | None = None
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    metadata: Mapping[str, Any] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("receipt_id", "lane_id", "action_id", "scoped_token_ref", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _string_fields_are_nonblank(cls, value: Any, info: Any) -> str:
        return _nonblank_string(info.field_name, value)

    @field_validator("refusal_reason", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _refusal_reason_is_nonblank_when_present(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _nonblank_string("refusal_reason", value)

    @field_validator("rate_limit_remaining", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _rate_limit_remaining_is_nonnegative_int(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "rate_limit_remaining must be a non-negative integer; next action: "
                "bind the remaining lane quota as an integer count"
            )
        if value < 0:
            raise ValueError(
                "rate_limit_remaining must be a non-negative integer; next action: "
                "bind the remaining lane quota as an integer count"
            )
        return value

    @field_validator("metadata", mode="before")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _metadata_is_mapping(cls, value: Any) -> Mapping[str, Any]:
        if value is None or not isinstance(value, Mapping):
            raise ValueError(
                "metadata must be a mapping with string keys; next action: "
                "attach durable JSON-object receipt metadata"
            )
        _validate_string_keys("metadata", value)
        return value

    @field_validator("metadata", mode="after")  # noqa: V105 - Pydantic reflection hook.
    @classmethod
    def _metadata_is_immutable(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return _freeze_mapping("metadata", value)

    @field_serializer("metadata")  # noqa: V105 - Pydantic reflection hook.
    def _serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return _thaw_mapping(value)

    @model_validator(mode="after")  # noqa: V105 - Pydantic reflection hook.
    def _receipt_status_matches_reason(self) -> OutboundLaneActReceipt:
        if self.status == "refused" and self.refusal_reason is None:
            raise ValueError(
                "refusal_reason is required when status is refused; next action: "
                "record the fail-closed refusal reason"
            )
        if self.status == "admitted" and self.refusal_reason is not None:
            raise ValueError(
                "refusal_reason must be absent when status is admitted; next action: "
                "clear refusal_reason for admitted receipts"
            )
        return self


class BoundedOutboundLane:
    """Template wrapper requiring token, rate limit, receipt, and kill switch."""

    def __init__(
        self,
        *,
        lane_id: str,
        registry: AccountFederationRegistry,
        authority_ceiling: AuthorityCeiling,
        venue_allowlist: set[str] | frozenset[str],
        notional_cap: float,
        position_cap: float,
        scoped_token: ScopedOutboundToken,
        rate_limit: OutboundRateLimit,
        kill_switch: bool,
        public_egress_authorized: bool,
        money_movement_authorized: bool,
        public_gate_receipts: set[str] | frozenset[str] | None = None,
        current_position: float = 0.0,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._lane_id = _nonblank_string("lane_id", lane_id)
        if not isinstance(registry, AccountFederationRegistry):
            raise TypeError(
                "registry must be an AccountFederationRegistry; next action: load "
                "the route-specific account federation registry"
            )
        if not isinstance(scoped_token, ScopedOutboundToken):
            raise TypeError(
                "scoped_token must be a ScopedOutboundToken; next action: bind "
                "an explicit governed token reference"
            )
        if not isinstance(rate_limit, OutboundRateLimit):
            raise TypeError(
                "rate_limit must be an OutboundRateLimit; next action: bind "
                "the lane's fixed-window policy"
            )
        if not isinstance(kill_switch, bool):
            raise TypeError(
                "kill_switch must be an explicit bool; next action: bind "
                "the lane's governed kill-switch state"
            )
        if not isinstance(public_egress_authorized, bool):
            raise TypeError(
                "public_egress_authorized must be an explicit bool; next action: "
                "bind the public-egress authority decision without coercion"
            )
        if not isinstance(money_movement_authorized, bool):
            raise TypeError(
                "money_movement_authorized must be an explicit bool; next action: "
                "bind the money-movement authority decision without coercion"
            )
        registry_secret_ref = (
            registry.pass_or_secret_key.strip()
            if isinstance(registry.pass_or_secret_key, str)
            else ""
        )
        if registry_secret_ref != scoped_token.token_ref:
            raise ValueError(
                "scoped_token.token_ref must match registry.pass_or_secret_key; "
                "next action: load the route-specific scoped token registry"
            )
        if not set(scoped_token.scopes).issubset(set(registry.send_scopes)):
            raise ValueError(
                "scoped_token.scopes must be a subset of registry.send_scopes; "
                "next action: align token scope with the governed send scope"
            )

        self._scoped_token = scoped_token
        self._rate_limit = rate_limit
        self._public_egress_authorized = public_egress_authorized
        self._money_movement_authorized = money_movement_authorized
        self._now_fn = now_fn or time.monotonic
        self._window_started_at: float | None = None
        self._used_in_window = 0
        self._lock = threading.RLock()
        self._executor = OutboundExecutor(
            authority_ceiling=authority_ceiling,
            venue_allowlist=venue_allowlist,
            notional_cap=notional_cap,
            position_cap=position_cap,
            current_position=current_position,
            kill_switch=kill_switch,
            public_gate_receipts=public_gate_receipts,
            registry=registry,
        )

    @property
    def lane_id(self) -> str:
        return self._lane_id

    @property
    def scoped_token(self) -> ScopedOutboundToken:
        return self._scoped_token

    @property
    def rate_limit(self) -> OutboundRateLimit:
        return self._rate_limit

    @property
    def public_egress_authorized(self) -> bool:
        return self._public_egress_authorized

    @property
    def money_movement_authorized(self) -> bool:
        return self._money_movement_authorized

    @property
    def current_position(self) -> float:
        return self._executor.current_position

    def execute_act(self, request: OutboundLaneActRequest) -> OutboundLaneActReceipt:  # noqa: V105
        """Validate one lane act and return a durable per-act receipt shape."""
        if not isinstance(request, OutboundLaneActRequest):
            raise TypeError(
                "request must be an OutboundLaneActRequest; next action: validate "
                "the lane act before execution"
            )

        with self._lock:
            if request.scope not in self._scoped_token.scopes:
                return self._receipt(
                    request,
                    status="refused",
                    refusal_reason="token_scope_missing",
                    metadata={"next_action": "bind a scoped token that covers this send scope"},
                )

            public_egress_requires_authority = (
                self._executor.authority_ceiling is AuthorityCeiling.PUBLIC_GATE_REQUIRED
                or request.public_egress_requested
            )
            if public_egress_requires_authority and not self.public_egress_authorized:
                return self._receipt(
                    request,
                    status="refused",
                    refusal_reason="public_egress_not_authorized",
                    metadata={"next_action": "route public egress through a public gate authority"},
                )

            if (
                request.money_movement_requested or request.amount > 0
            ) and not self.money_movement_authorized:
                return self._receipt(
                    request,
                    status="refused",
                    refusal_reason="money_movement_not_authorized",
                    metadata={
                        "next_action": "route money movement through a distinct money authority"
                    },
                )

            outbound_request = OutboundExecutionRequest(
                scope=request.scope,
                venue=request.venue,
                amount=request.amount,
                evidence_refs=request.evidence_refs,
                public_gate_passed=request.public_gate_passed,
                payload=request.payload,
            )
            dry_run_receipt = self._executor.validate_request(outbound_request)
            if dry_run_receipt.status == "refused":
                return self._receipt(
                    request,
                    status="refused",
                    refusal_reason=dry_run_receipt.refusal_reason,
                    outbound_receipt=dry_run_receipt,
                    metadata={"next_action": dry_run_receipt.metadata.get("next_action")},
                )

            rate_limited = self._consume_rate_limit_slot()
            if rate_limited is not None:
                return self._receipt(
                    request,
                    status="refused",
                    refusal_reason="rate_limit_exceeded",
                    outbound_receipt=dry_run_receipt,
                    metadata=rate_limited
                    | {
                        "outbound_execute_reached": False,
                        "provider_execution_wired": False,
                    },
                )

            final_receipt = self._executor.execute(outbound_request)
            if final_receipt.status == "refused":
                return self._receipt(
                    request,
                    status="refused",
                    refusal_reason=final_receipt.refusal_reason,
                    outbound_receipt=final_receipt,
                    metadata={"next_action": final_receipt.metadata.get("next_action")},
                )
            return self._receipt(
                request,
                status="admitted",
                outbound_receipt=final_receipt,
                metadata={
                    "implementation_template": True,
                    "provider_execution_wired": False,
                },
            )

    def _reset_expired_window(self) -> None:
        now = self._now_fn()
        if (
            self._window_started_at is None
            or now - self._window_started_at >= self.rate_limit.window_seconds
        ):
            self._window_started_at = now
            self._used_in_window = 0

    def _consume_rate_limit_slot(self) -> dict[str, Any] | None:
        self._reset_expired_window()
        if self._used_in_window >= self.rate_limit.max_actions:
            return {
                "next_action": "wait for the lane rate-limit window or raise the limit through governance",
                "window_seconds": self.rate_limit.window_seconds,
                "max_actions": self.rate_limit.max_actions,
                "used_in_window": self._used_in_window,
            }
        self._used_in_window += 1
        return None

    def _rate_limit_remaining(self) -> int:
        if self._window_started_at is None:
            return self.rate_limit.max_actions
        if self._now_fn() - self._window_started_at >= self.rate_limit.window_seconds:
            return self.rate_limit.max_actions
        return max(0, self.rate_limit.max_actions - self._used_in_window)

    def _receipt(
        self,
        request: OutboundLaneActRequest,
        *,
        status: Literal["admitted", "refused"],
        refusal_reason: str | None = None,
        outbound_receipt: OutboundExecutionReceipt | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> OutboundLaneActReceipt:
        receipt_metadata = dict(metadata or {})
        receipt_metadata["provider_execution_wired"] = False
        return OutboundLaneActReceipt(
            receipt_id=f"outbound-lane-receipt-{uuid.uuid4()}",
            lane_id=self.lane_id,
            action_id=request.action_id,
            status=status,
            refusal_reason=refusal_reason,
            scoped_token_ref=self.scoped_token.token_ref,
            rate_limit_remaining=self._rate_limit_remaining(),
            public_egress_authorized=self.public_egress_authorized,
            money_movement_authorized=self.money_movement_authorized,
            outbound_receipt=outbound_receipt,
            evidence_refs=request.evidence_refs,
            metadata=receipt_metadata,
        )


def build_youtube_public_upload_lane_template(
    *,
    registry: AccountFederationRegistry,
    public_gate_receipts: set[str] | frozenset[str],
    max_actions: int,
    window_seconds: float,
    kill_switch: bool,
    now_fn: Callable[[], float] | None = None,
) -> BoundedOutboundLane:
    """Build the governed YouTube public-egress template, not a live uploader."""
    return BoundedOutboundLane(
        lane_id="template:youtube-public-upload",
        registry=registry,
        authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        venue_allowlist={YOUTUBE_PUBLIC_VENUE},
        notional_cap=0.0,
        position_cap=0.0,
        scoped_token=ScopedOutboundToken(
            token_ref=YOUTUBE_SCOPED_TOKEN_REF,
            scopes=(YOUTUBE_PUBLIC_UPLOAD_SCOPE,),
        ),
        rate_limit=OutboundRateLimit(
            max_actions=max_actions,
            window_seconds=window_seconds,
        ),
        kill_switch=kill_switch,
        public_gate_receipts=public_gate_receipts,
        public_egress_authorized=True,
        money_movement_authorized=False,
        now_fn=now_fn,
    )


def _nonblank_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} must be a nonblank string; next action: bind a stable governed identifier"
        )
    return value.strip()


def _nonblank_string_tuple(
    name: str,
    value: Any,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if value is None:
        if allow_empty:
            return ()
        raise ValueError(
            f"{name} must be a list or tuple of strings; next action: bind "
            "explicit governed scope/evidence strings"
        )
    if isinstance(value, str) or not isinstance(value, list | tuple | set | frozenset):
        raise ValueError(
            f"{name} must be a list or tuple of strings; next action: bind "
            "explicit governed scope/evidence strings"
        )
    normalized = tuple(_nonblank_string(f"{name} entries", item) for item in value)
    if not normalized and not allow_empty:
        raise ValueError(
            f"{name} must contain at least one scope; next action: bind the "
            "route-specific send scope"
        )
    return normalized


def _is_governed_secret_ref(ref: str) -> bool:
    normalized = ref.strip()
    if not normalized or normalized == "placeholder" or normalized.startswith("pass:placeholder"):
        return False
    return any(
        normalized.startswith(prefix) and bool(normalized.removeprefix(prefix).strip())
        for prefix in _GOVERNED_SECRET_REF_PREFIXES
    )


def _validate_string_keys(name: str, value: Mapping[Any, Any]) -> None:
    for key, nested_value in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(
                f"{name} keys must be nonblank strings; next action: "
                "replace blank or non-string keys with stable JSON object keys"
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
            "replace non-finite values with string, number, bool, null, list, or object evidence"
        )
    raise ValueError(
        f"{name} values must be JSON-compatible immutable evidence; next action: "
        "replace mutable or non-JSON values with string, number, bool, null, list, or object evidence"
    )


def _thaw_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _thaw_value(nested_value) for key, nested_value in value.items()}


def _thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _thaw_mapping(value)
    if isinstance(value, tuple):
        return [_thaw_value(nested_value) for nested_value in value]
    return value
