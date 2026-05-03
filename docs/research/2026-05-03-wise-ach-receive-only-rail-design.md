# Wise + ACH Receive-Only Rail — Design Spike

**cc-task:** `jr-wise-ach-receive-only-rail-spike`
**Status:** Spike (design only — no implementation in this task)
**Date:** 2026-05-03
**Sources:** jr-packets `20260502T214501Z-jr-currentness-scout-wise-ach-payment-rails-2026-05-02.md` and `20260503T045511Z-jr-currentness-scout-wisetech-receive-2026.md`
**Sibling rails:** Mercury (#2313), Modern Treasury (#2315), Treasury Prime (#2317), Stripe Payment Link (#2294, hardened #2322)

## Intent

Add **Wise** as the 11th receive-only payment rail in the V5 publication-bus family. Wise is the operator's preferred international rail and complements the existing three USD-only bank rails (Mercury, Modern Treasury, Treasury Prime) with multi-currency support for international grant payments and cross-border income.

This document is the design spike. Implementation lands as a separate cc-task once the spike is reviewed.

## Decision summary

- **YES, Wise as 11th rail.** Multi-currency value justifies the asymmetric-signature complexity.
- **NO, do not add Stripe ACH as a separate rail.** Stripe Payment Link (#2294) already covers ACH at the platform layer; adding a parallel Stripe ACH receiver would double the signature-verification surface. Operators wanting ACH receive should use Mercury / Modern Treasury / Treasury Prime (already shipped) for direct bank rails or Stripe Payment Link for the platform-mediated path.
- **NO Wise SDK import.** Receive-only invariant requires stdlib-only verification. Asymmetric signature verification uses `cryptography` (already a transitive dep via `pydantic` → no new dep required) — see § Signature mechanism.

## Wise wire shape

### Event types

The receiver will accept three Wise webhook event kinds (all on schema v4.0.0):

| Wise event | Canonical kind |
|---|---|
| `account-details-payment#state-change` | `account_details_payment_state_change` (primary; incoming ACH credit to virtual USD account) |
| `balances#credit` | `balances_credit` (broader notification — any balance increase, multi-currency) |
| `transfers#state-change` | **REJECTED** — outgoing transfer state, violates receive-only |

Unaccepted-but-known event types (e.g. `profiles#change`, `transfers#refund`) raise `ReceiveOnlyRailError` per the family convention. Unknown strings raise the same error with a "malformed" reason.

### Payload shape (v4.0.0)

```json
{
  "data": {
    "resource": {
      "type": "account-details-payment",
      "id": 12345678901234567,                  // 64-bit integer; see § Precision
      "profile_id": 98765432109876543,
      "account_id": 11122233344455566
    },
    "current_state": "RECEIVED",
    "previous_state": "PENDING",
    "occurred_at": "2026-05-03T07:30:00.123Z",  // millisecond precision
    "amount": {
      "value": 1234.56,                          // canonical decimal — DO NOT use float
      "currency": "USD"
    },
    "sender_reference": "ABCDEF1234567890"       // opaque sender identifier
  },
  "subscription_id": 88899900011122233,
  "event_type": "account-details-payment#state-change",
  "schema_version": "4.0.0",
  "sent_at": "2026-05-03T07:30:01.456Z"
}
```

### Precision (CRITICAL)

Wise schema v4.0.0 enforces **64-bit integer IDs**. Standard JavaScript `Number` types (and Python `json.loads` defaults are fine — Python `int` is arbitrary-precision) lose precision past 2^53. The receiver MUST:

1. Use Python's stdlib `json.loads` (already arbitrary-precision-safe — Python `int` handles 64-bit cleanly).
2. Preserve the raw bytes for signature verification — re-serializing with `json.dumps` could quantize the integer to a different representation. The rail's existing `raw_body=` kwarg pattern (already used by all 10 sibling rails post-#2280) is the right shape.
3. Money amounts (`data.resource.amount.value`) are **decimals, not cents**. The receiver MUST convert to integer minor units (`amount_currency_cents`) at the boundary — never store the float.

### Money normalization

Wise emits `amount.value` as a JSON number (e.g. `1234.56` USD). The receiver normalizes to integer minor units:

```python
def _to_currency_cents(value: float | int | Decimal, currency: str) -> int:
    """Convert a Wise amount.value to integer minor units in source currency.

    Uses Decimal arithmetic — float multiplication has precision drift
    ($0.10 * 100 == 10.000000000000002, but $0.10 * 100 should be 1000 cents
    via Decimal). Zero-decimal currencies (JPY, KRW) pass through; standard
    2-decimal currencies multiply by 100; 3-decimal currencies (BHD, KWD)
    multiply by 1000.
    """
    minor_units = MINOR_UNIT_MULTIPLIER[currency]  # ISO 4217 lookup
    decimal_value = Decimal(str(value))
    cents = decimal_value * minor_units
    if cents != cents.to_integral_value():
        raise ReceiveOnlyRailError(
            f"amount.value {value} {currency} does not multiply to integer "
            f"minor units (got {cents}); fractional minor units rejected"
        )
    return int(cents)
```

Same fail-closed semantics as #2325 (GH Sponsors cents-int normalization): fractional minor units (e.g. $1.234 USD) raise `ReceiveOnlyRailError` rather than rounding silently.

## Signature mechanism

### Source disagreement

The two jr-packets disagree on the asymmetric algorithm:

| jr-packet | Algorithm | Header |
|---|---|---|
| `20260502T214501Z` | RSA-SHA256 | `X-Signature-SHA256` |
| `20260503T045511Z` | Ed25519 | `X-Wise-Signature` |

**Resolution:** verify against authoritative Wise docs (`https://api-docs.wise.com/changelog`) at implementation time. **Do not commit to one signature path until a live Wise webhook delivery is captured and verified.** The implementation cc-task must include a fixture from a real Wise sandbox webhook before merging.

### Public-key fetch (architectural concern)

Wise uses asymmetric verification — the receiver must hold the Wise public key to verify signatures. Two paths:

**A. Pre-cached static artifact (recommended)**

- Operator runs `scripts/fetch-wise-public-key.sh` once at credential bootstrap.
- Key persists to `~/hapax-state/wise/public-key.pem`.
- Rail reads from disk on startup; no runtime outbound call.
- Key rotation handled out-of-band via the same script (cron or operator-action).
- **Receive-only invariant preserved.** Rail makes zero outbound calls.

**B. Runtime fetch with cache (REJECTED)**

- Receiver fetches `GET https://api.wise.com/v1/webhooks/public-key` on first delivery.
- Caches in-memory + on disk.
- **VIOLATES receive-only invariant** — adds an outbound HTTP call from the rail boundary. The rail's promise to upstream consumers is "no outbound, no SDK"; runtime fetch breaks that promise even if cached.

Use path A. The bootstrap script is a separate cc-task (`wise-public-key-bootstrap-script`) that produces the artifact the rail reads.

### Verification path (Path A, RSA-SHA256 hypothesis)

```python
def _verify_signature(payload_bytes: bytes, signature_b64: str, public_key_pem: bytes) -> None:
    """Fail-closed RSA-SHA256 verification against pre-cached Wise public key.

    If Wise actually uses Ed25519 (per packet 2), swap the verifier for
    cryptography.hazmat.primitives.asymmetric.ed25519.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature

    public_key = serialization.load_pem_public_key(public_key_pem)
    signature = base64.b64decode(signature_b64)
    try:
        public_key.verify(
            signature,
            payload_bytes,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise ReceiveOnlyRailError("Wise RSA-SHA256 signature mismatch") from exc
```

`cryptography` is a transitive dependency via `pydantic` and already locked. No new Pyproject dependency.

## Receive-only invariants

The rail must satisfy the same invariants as the existing 10 rails:

1. **No outbound calls** — public-key bootstrap is out-of-band (Path A above).
2. **No SDK import** — `wise-python-client` (or similar) is forbidden. Stdlib + `cryptography` only.
3. **No PII persisted** — `sender_reference` is the opaque Wise identifier; never extract sender email, name, address, free-text reference, or sender bank-account details. Only `sender_reference` + `amount_currency_cents` + `currency` + `event_kind` + `occurred_at` + `raw_payload_sha256` flow to the publisher.
4. **Fail-closed** — `ReceiveOnlyRailError` on signature failure, schema-version mismatch, fractional-minor-unit, missing fields, or unaccepted event kinds.
5. **`raw_body=` kwarg** — all 10 sibling rails already accept raw bytes for HMAC verification (signed bytes are the wire bytes, not the canonical re-encoding). Wise's asymmetric verification has the same constraint.
6. **Idempotency** — Wise emits a unique `subscription_id` per delivery; the rail SHOULD use the sqlite `IdempotencyStore` pattern shipped in #2322 (Stripe Payment Link rail) keyed on `subscription_id`. **Strongly recommended for Wise** because Wise enforces `2xx` within 5 seconds and has known retry-storm behavior on partial-acceptance.

## OAuth scope posture (RECEIVE-ONLY ENFORCEMENT)

Wise enforces receive-only via OAuth scopes, not a separate account type. The operator's API token MUST be issued with **only**:

- `profiles:read`
- `balances:read`
- `transfers:read`
- `statements:read`

And MUST NOT carry:

- `transfers:create` (forbidden — would allow outbound transfers)
- `transfers:manage` (forbidden — would allow modifying outbound transfers)
- `balances:manage` (forbidden — would allow moving funds between balances)

**Architectural constraint:** the rail itself never sees the OAuth token (it only verifies inbound webhook signatures). The token is held by the bootstrap script + `pass`-managed credentials. The receive-only-invariant proof at the rail boundary is "no outbound HTTP", not "limited OAuth scopes" — the OAuth scopes are a defense-in-depth at the credential layer.

## Comparison to USD-only ACH alternatives

| Option | Multi-currency | Signature | Already shipped? | New rail needed? |
|---|---|---|---|---|
| Mercury | USD only (limited multi) | HMAC-SHA256 | YES (#2313) | NO |
| Modern Treasury | USD only | HMAC-SHA256 | YES (#2315) | NO |
| Treasury Prime | USD only | HMAC-SHA256 | YES (#2317) | NO |
| Stripe ACH (via Stripe Payment Link) | USD primarily, FX via Stripe | HMAC-SHA256 (#2322 hardened) | YES (#2294, #2322) | NO |
| Stripe ACH (direct, via Plaid) | USD only | HMAC + JWT (Plaid) | NO | **REJECTED** — doubles security surface (HMAC + ES256 JWT) for one rail |
| Wise | **YES (native multi-currency)** | RSA-SHA256 or Ed25519 (asymmetric) | NO | **YES — this design** |

**Operator income mix consideration:** Wise unblocks international grants (UK, EU, AU, CA grant programs commonly disburse in GBP/EUR/AUD/CAD). The existing 4 USD rails cover US-domiciled grant programs and creator-platform support but cannot receive non-USD without manual conversion friction.

## Implementation skeleton (for the follow-up cc-task)

```python
# shared/wise_receive_only_rail.py

WISE_WEBHOOK_PUBLIC_KEY_PATH_ENV = "WISE_WEBHOOK_PUBLIC_KEY_PATH"

class WiseEventKind(StrEnum):
    ACCOUNT_DETAILS_PAYMENT_STATE_CHANGE = "account_details_payment_state_change"
    BALANCES_CREDIT = "balances_credit"

class WisePaymentEvent(_RailModel):
    sender_reference: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)  # ISO 4217
    event_kind: WiseEventKind
    occurred_at: datetime
    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

class WiseRailReceiver:
    def __init__(
        self,
        *,
        public_key_path_env: str = WISE_WEBHOOK_PUBLIC_KEY_PATH_ENV,
        idempotency_store: IdempotencyStore | None = None,  # reuse Stripe's pattern
        accepted_schema_versions: frozenset[str] = frozenset({"4.0.0"}),
    ) -> None: ...

    def ingest_webhook(
        self,
        payload: dict[str, Any],
        signature: str | None,
        *,
        raw_body: bytes | None = None,
    ) -> WisePaymentEvent | None: ...
```

Publisher follows the same pattern as the 10 existing rails — uses `agents.publication_bus._rail_publisher_helpers` (shipped in #2320).

## Open questions for senior review

1. **Signature algorithm — RSA-SHA256 or Ed25519?** Resolve before implementation. Capture a real Wise sandbox webhook and verify which algorithm validates.
2. **mTLS requirement.** Packet 2 mentions "mandatory mTLS for production partner integrations in 2026." This is a TLS-layer concern (reverse proxy / Caddy / nginx), not a rail-internal concern, but the operator's `logos-api` deployment must support mTLS termination before Wise will deliver to the endpoint. Spike a separate cc-task for `wise-mtls-termination-config` if mTLS is mandatory.
3. **Schema version drift.** Wise has shipped v3 → v4 since 2024. The receiver should accept only `4.0.0` initially; future versions raise `ReceiveOnlyRailError` until the operator opts in. Pin `accepted_schema_versions` in the receiver's `__init__`.
4. **Idempotency key choice.** `subscription_id` is the natural key per delivery, but Wise may emit the same `subscription_id` for distinct events on the same subscription. Re-evaluate after capturing real deliveries; may need composite `(subscription_id, occurred_at_ns)`.
5. **Direct Debit (active reception) — out of scope?** Packet 2 mentions Wise's 2026 Direct Debit API for pull payments. Pull payments are arguably outbound-initiated even though they collect funds; flagging as REFUSED tier per receive-only stance, mirroring how Stripe Payment Link rail rejects `customer.subscription.deleted` initiation. Confirm with operator.

## Acceptance criteria status

- [x] Existing 10-rail pattern read and characterized.
- [x] Wise webhook event types enumerated; receive-only filter spec'd.
- [x] Signature mechanism characterized with explicit uncertainty (RSA vs Ed25519 — must resolve at impl).
- [x] Pydantic model spec'd with `amount_currency_cents: int` per family convention.
- [x] Receive-only invariant preserved — no Wise SDK, no outbound, public-key fetch out-of-band.
- [x] PII rejection spec'd — `sender_reference` only.
- [x] ACH alternatives compared — Mercury / Modern Treasury / Treasury Prime cover USD-only ACH; Wise adds the multi-currency surface.
- [x] Spike doc only — implementation deferred to follow-up cc-task `wise-receive-only-rail-implement`.

## Follow-up cc-tasks (suggested)

- `wise-receive-only-rail-implement` — implementation per this spec (mirror #2313/#2315/#2317 shape; reuse `IdempotencyStore` from #2322).
- `wise-public-key-bootstrap-script` — `scripts/fetch-wise-public-key.sh` + systemd timer for rotation.
- `wise-mtls-termination-config` — Caddy/nginx mTLS terminator if Wise mandates.
- `direct-debit-active-reception-refusal-brief` — REFUSED-tier publisher recording the active-collection refusal.

## Continuity

This spike completes the WSJF-6 design step. The implementation cc-task is **independent** of the Wyoming LLC bootstrap (`wyoming-llc-dba-legal-entity-bootstrap`, WSJF 14.5) — Wise account creation does require a legal entity, but the *rail receiver* is testable against Wise sandbox webhooks without a real Wise Business account.
