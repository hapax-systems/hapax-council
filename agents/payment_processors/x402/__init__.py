"""x402 v2 transport substrate.

Per cc-task ``x402-pydantic-models``. Typed models + Base64 helpers
for the x402 v2 HTTP transport spec
(`<https://github.com/coinbase/x402/blob/main/specs/transports-v2/http.md>`_).
The full spec extract + reconcile against the predecessor architecture
doc is in ``docs/research/2026-05-01-x402-spec-current-research.md``.

Substrate-only: no HTTP routing, no settlement logic, no facilitator
integration. The models are the wire format any of the three operator
decisions (A refusal-as-data, B EVM stablecoin onboarding, C defer)
will use.
"""

from agents.payment_processors.x402.models import (
    Accept,
    Authorization,
    PayloadInner,
    PaymentPayload,
    PaymentRequired,
    ResourceRef,
    SettlementResponse,
    decode_payment_required,
    encode_payment_required,
    validate_caip_network,
)

__all__ = [
    "Accept",
    "Authorization",
    "PaymentPayload",
    "PaymentRequired",
    "PayloadInner",
    "ResourceRef",
    "SettlementResponse",
    "decode_payment_required",
    "encode_payment_required",
    "validate_caip_network",
]
