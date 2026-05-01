"""x402 v2 transport-spec Pydantic models + Base64 helpers.

Per ``docs/research/2026-05-01-x402-spec-current-research.md``. Models
match the ``x402Version: 2`` wire format documented at
`<https://github.com/coinbase/x402/blob/main/specs/transports-v2/http.md>`_.

Three primary headers carry these encoded objects:

- ``PAYMENT-REQUIRED`` (server → client): :class:`PaymentRequired`
- ``PAYMENT-SIGNATURE`` (client → server): :class:`PaymentPayload`
- ``PAYMENT-RESPONSE`` (server → client): :class:`SettlementResponse`

The HTTP layer Base64-encodes the JSON-serialized object into the
header value; helpers :func:`encode_payment_required` and
:func:`decode_payment_required` are the canonical conversion path.

Substrate-only: no HTTP routing, no settlement logic. Any of the
three operator decisions (A refusal-as-data, B EVM stablecoin
onboarding, C defer) consumes these models without modification.
"""

from __future__ import annotations

import base64
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

X402_VERSION: Literal[2] = 2
"""Pinned protocol version. Models reject any other value."""

CAIP_NETWORK_RE: re.Pattern[str] = re.compile(r"^eip155:\d+$")
"""CAIP-style EVM network identifier (e.g., ``eip155:8453`` for Base).

Solana (``solana:NNN``) and Stellar identifiers exist in the upstream
SDK matrix but the canonical spec excerpts and the operator's
Decision-A/B/C scope are EVM-only. Validator rejects non-EVM CAIP
strings until operator decision lands."""

VALID_SCHEMES: frozenset[str] = frozenset({"exact"})
"""Currently the only documented x402 scheme. ``upto`` is theoretical
future work; reject until shipped upstream."""

VALID_FAILURE_REASONS: frozenset[str] = frozenset(
    {"insufficient_funds", "expired", "invalid_signature", "verification_failed"}
)
"""Documented settlement-failure reasons. The set is permissive (the
spec allows facilitator-defined codes) but the canonical four are
the ones the upstream reference implementation emits."""


def validate_caip_network(value: str) -> str:
    """Reject non-``eip155:NNN`` CAIP network identifiers.

    Public helper so callers (e.g., the Accept-builder for license
    classes) can validate without instantiating a full model.
    Raises :class:`ValueError` on mismatch.
    """
    if not CAIP_NETWORK_RE.match(value):
        raise ValueError(
            f"network must match CAIP-eip155 form (e.g., 'eip155:8453'); got {value!r}"
        )
    return value


class ResourceRef(BaseModel):
    """The resource a 402 payment unlocks. Same shape on both server +
    client sides of the exchange.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(description="Canonical resource URL")
    description: str = Field(default="", description="Human-readable hint")
    mimeType: str = Field(default="application/octet-stream", description="MIME type")


class Accept(BaseModel):
    """One payment option in a :class:`PaymentRequired` ``accepts`` array.

    The server may advertise multiple ``Accept`` entries (e.g., USDC on
    Base + USDC on Polygon); the client picks one and signs against it.
    """

    model_config = ConfigDict(extra="forbid")

    scheme: str = Field(description='Payment scheme; only "exact" is currently documented')
    network: str = Field(description="CAIP network identifier (e.g., 'eip155:8453')")
    amount: str = Field(description="Numeric string in token base units; never a float")
    asset: str = Field(description="Token contract address or canonical asset id")
    payTo: str = Field(description="Recipient address")
    maxTimeoutSeconds: int = Field(default=60, ge=1, description="Server-side payment timeout")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form per-accept metadata (e.g., {'name': 'USDC', 'version': '2'} or {'hapax_license_class': 'commercial'})",
    )

    @field_validator("scheme")
    @classmethod
    def _scheme_supported(cls, v: str) -> str:
        if v not in VALID_SCHEMES:
            raise ValueError(f"scheme {v!r} not in supported set {sorted(VALID_SCHEMES)}")
        return v

    @field_validator("network")
    @classmethod
    def _network_caip_eip155(cls, v: str) -> str:
        return validate_caip_network(v)

    @field_validator("amount")
    @classmethod
    def _amount_is_numeric_string(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError(
                f"amount must be a non-negative integer string in base units; got {v!r}"
            )
        return v


class PaymentRequired(BaseModel):
    """The 402 response object. Server → client, Base64'd into the
    ``PAYMENT-REQUIRED`` header.
    """

    model_config = ConfigDict(extra="forbid")

    x402Version: Literal[2] = Field(default=X402_VERSION, description="Pinned to 2")
    error: str = Field(default="payment required", description="Human-readable error message")
    resource: ResourceRef = Field(description="The resource that requires payment")
    accepts: list[Accept] = Field(
        default_factory=list,
        description="Accepted payment options. Empty array = refusal-as-data (Decision A)",
    )


class Authorization(BaseModel):
    """The signed payment authorization the client submits."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    # Note: x402 v2 uses `from` as a key, which is reserved in Python.
    # Pydantic's alias machinery routes JSON `from` → field
    # `from_address` so callers can use either path.
    from_address: str = Field(alias="from", description="Payer address")
    to: str = Field(description="Recipient address; must match the Accept.payTo")
    value: str = Field(description="Numeric string in base units; must match Accept.amount")
    validAfter: str = Field(description="UNIX timestamp string; payment valid after this time")
    validBefore: str = Field(description="UNIX timestamp string; payment expires after this time")
    nonce: str = Field(description="Hex-encoded nonce; replay protection")


class PayloadInner(BaseModel):
    """The signature + authorization bundle inside a :class:`PaymentPayload`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signature: str = Field(description="Hex-encoded signature over the authorization")
    authorization: Authorization


class PaymentPayload(BaseModel):
    """The client retry object. Client → server, Base64'd into the
    ``PAYMENT-SIGNATURE`` header.
    """

    model_config = ConfigDict(extra="forbid")

    x402Version: Literal[2] = Field(default=X402_VERSION)
    resource: ResourceRef
    accepted: Accept = Field(description="The accept entry the client chose to fulfill")
    payload: PayloadInner


class SettlementResponse(BaseModel):
    """The settlement outcome. Server → client, Base64'd into the
    ``PAYMENT-RESPONSE`` header. ``success=True`` carries
    ``transaction``; ``success=False`` carries ``errorReason`` and an
    empty ``transaction`` per the spec.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(description="True if verified + settled; False otherwise")
    transaction: str = Field(default="", description="Tx hash on success; empty string on failure")
    network: str = Field(description="CAIP network identifier of the settlement attempt")
    payer: str = Field(description="Payer address from the submitted Authorization")
    errorReason: str | None = Field(
        default=None,
        description="Human-readable failure reason; required when success=False",
    )

    @field_validator("network")
    @classmethod
    def _network_caip_eip155(cls, v: str) -> str:
        return validate_caip_network(v)


# ── Base64 transport helpers ─────────────────────────────────────────


def encode_payment_required(req: PaymentRequired) -> str:
    """Serialize a :class:`PaymentRequired` to the Base64 string the
    ``PAYMENT-REQUIRED`` HTTP header carries. Round-trips with
    :func:`decode_payment_required` losslessly.
    """
    return base64.b64encode(req.model_dump_json(by_alias=True).encode("utf-8")).decode("ascii")


def decode_payment_required(b64: str) -> PaymentRequired:
    """Inverse of :func:`encode_payment_required`. Validates the
    decoded JSON against the model schema; raises Pydantic
    ``ValidationError`` on shape mismatch.
    """
    raw = base64.b64decode(b64.encode("ascii")).decode("utf-8")
    return PaymentRequired.model_validate_json(raw)
