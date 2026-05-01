"""x402 v2 receive-endpoint handler — Path A (refusal-as-data).

Per `docs/governance/x402-facilitator-choice.md` (alpha, 2026-05-01):
the operator selected Path A as the default starting state for the
x402 endpoint. This handler returns HTTP 402 with `accepts: []` for
any license-gated route; standard x402 v2 clients (per
`docs/research/2026-05-01-x402-spec-current-research.md`) interpret
empty-accepts as a hard refusal and fail closed. The handler NEVER
calls a facilitator's `/verify` or `/settle` endpoints — Path A
explicitly forbids that code path, since no facilitator is wired
under refusal-as-data.

When the operator reverses Path A → Path B (per the §"Reversal
procedure" section of the facilitator-choice doc), the
`payment_required_response` helper will need to gain real `Accept`
entries (one per stablecoin rail / network) and a facilitator-call
follow-on endpoint must ship. Until then, this module is the
substrate-only refusal surface: it produces structurally-correct
x402 v2 responses that honestly say "we don't take your money via
this rail."

The receive-only invariant (mirrored from
`tests/payment_processors/test_read_only_contract.py`) is enforced
on this module by `tests/test_x402_route.py::TestReadOnlyContract`:
no forbidden outbound verbs (`send`, `initiate`, `payout`, etc.)
may be defined here.

References:
- Spec source: `docs/research/2026-05-01-x402-spec-current-research.md`
- Operator decision: `docs/governance/x402-facilitator-choice.md`
- Pydantic models (substrate): `agents/payment_processors/x402/models.py`
- Read-only contract: `tests/payment_processors/test_read_only_contract.py`
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from agents.payment_processors.x402.models import (
    PaymentRequired,
    ResourceRef,
    encode_payment_required,
)

router = APIRouter(prefix="/api/x402", tags=["x402"])

PAYMENT_REQUIRED_HEADER = "PAYMENT-REQUIRED"
"""Canonical header name carrying the Base64-encoded `PaymentRequired`.

Per the x402 v2 transport spec, the payment requirement rides in this
HTTP header rather than the response body. Body content is reserved
for the resource itself once payment settles (under Path B); under
Path A the body is empty.
"""


def payment_required_response(
    resource_url: str,
    *,
    description: str = "",
    mime_type: str = "application/octet-stream",
    error: str = "payment required",
) -> Response:
    """Build a Path-A 402 response for a license-gated resource.

    The `PAYMENT-REQUIRED` header carries a Base64-encoded
    `PaymentRequired` with empty `accepts` (refusal-as-data). The
    response body is empty. Any caller route that wants to gate behind
    x402 can return the result of this helper directly.

    Under Path A this helper never sets `Accept` entries; reversal to
    Path B will extend it (or supersede it) to advertise per-network
    receive rails. The `accepts: []` shape is structurally valid x402
    v2 — clients that follow the spec recognize the empty array as a
    hard refusal.
    """
    requirement = PaymentRequired(
        resource=ResourceRef(
            url=resource_url,
            description=description,
            mimeType=mime_type,
        ),
        accepts=[],
        error=error,
    )
    encoded = encode_payment_required(requirement)
    return Response(
        status_code=402,
        headers={PAYMENT_REQUIRED_HEADER: encoded},
    )


@router.get("/demo", status_code=402)
def demo_payment_required() -> Response:
    """Demo endpoint — always returns 402 (Path A refusal-as-data).

    Provided so x402 client implementations can verify the substrate
    end-to-end without operator intervention. The resource URL is a
    self-reference; the empty `accepts` array communicates the
    refusal posture.

    A canonical x402 v2 client receiving this response should treat
    the request as failed-with-no-retry-path (per the spec, an empty
    `accepts` array means "no payment option this server will
    accept"). This is the load-bearing semantic of Path A.
    """
    return payment_required_response(
        resource_url="/api/x402/demo",
        description="x402 v2 demo — Path A refusal-as-data (no payment rail accepted)",
        mime_type="application/json",
    )
