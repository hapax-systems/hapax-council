# x402 v2 spec research + architecture reconcile (2026-05-01)

**cc-task:** `x402-spec-current-research` (P2, WSJF 5.0)
**Author:** epsilon
**Predecessor:** `docs/research/2026-04-26-x402-receive-endpoint-architecture.md`
(alpha; deferred response-shape codification to a follow-on
research drop — this doc is that drop)

## Executive finding

The 2026-04-26 architecture doc's preliminary response design is
**fundamentally incompatible with the now-published x402 v2
transport spec**. Three divergences are load-bearing:

1. **Field naming + envelope.** Architecture uses snake_case under
   a `payment_required` wrapper. x402 v2 uses camelCase with
   top-level fields (`x402Version`, `accepts`, `payTo`,
   `maxTimeoutSeconds`).
2. **Header transport.** Architecture treats the JSON as the 402
   response *body*. x402 v2 requires the JSON to be **Base64-encoded
   and carried in a `PAYMENT-REQUIRED` HTTP header** (with reciprocal
   `PAYMENT-SIGNATURE` from client and `PAYMENT-RESPONSE` from
   server post-settlement).
3. **Rails support.** Architecture lists Hapax's existing rails —
   Lightning (Alby), Liberapay, Nostr Zaps — as accepted schemes.
   x402 v2's only documented scheme is **`exact`** over
   **`eip155:84532` (Base Sepolia testnet)** with SDK support for
   EVM, Solana (SVM), and Stellar. **None of the operator's
   currently-deployed rails are part of the x402 v2 protocol
   surface.**

The protocol-as-shipped is EVM-centric and stablecoin-centric (USDC
on Base/Polygon/Arbitrum/etc.). Lightning + Liberapay + Nostr Zaps
are out-of-band relative to x402 v2. Implementation cannot proceed
on the architecture doc as written without one of three explicit
operator decisions documented below.

## Authoritative spec — x402 v2 (canonical shape)

### Three headers

| Header | Direction | Purpose |
|---|---|---|
| `PAYMENT-REQUIRED` | Server → Client | Base64-encoded `PaymentRequired` object — the offer |
| `PAYMENT-SIGNATURE` | Client → Server | Base64-encoded `PaymentPayload` — the signed retry |
| `PAYMENT-RESPONSE` | Server → Client | Base64-encoded settlement outcome — success/failure |

### `PaymentRequired` object (decoded)

```json
{
  "x402Version": 2,
  "error": "descriptive error message",
  "resource": {
    "url": "https://hapax.example/api/protected",
    "description": "Premium endpoint",
    "mimeType": "application/json"
  },
  "accepts": [
    {
      "scheme": "exact",
      "network": "eip155:84532",
      "amount": "1000000",
      "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
      "payTo": "0xRecipientAddress…",
      "maxTimeoutSeconds": 60,
      "extra": {"name": "USDC", "version": "2"}
    }
  ]
}
```

### `PaymentPayload` (client retry)

```json
{
  "x402Version": 2,
  "resource": {"url": "...", "description": "...", "mimeType": "..."},
  "accepted": {"scheme": "exact", "network": "eip155:84532", "...": "..."},
  "payload": {
    "signature": "0x...",
    "authorization": {
      "from": "0xPayerAddress",
      "to": "0xRecipientAddress",
      "value": "1000000",
      "validAfter": "1714560000",
      "validBefore": "1714560060",
      "nonce": "0x..."
    }
  }
}
```

### Settlement response (in `PAYMENT-RESPONSE` header)

Success (HTTP 200):
```json
{
  "success": true,
  "transaction": "0xtxhash…",
  "network": "eip155:84532",
  "payer": "0xPayerAddress"
}
```

Failure (HTTP 402):
```json
{
  "success": false,
  "errorReason": "insufficient_funds",
  "transaction": "",
  "network": "eip155:84532",
  "payer": "0xPayerAddress"
}
```

### Status code mapping

| Status | Meaning |
|---|---|
| 402 | Payment required (initial denial) OR payment verification failure |
| 400 | Malformed `PAYMENT-SIGNATURE` payload |
| 500 | Server processing error during verification/settlement |
| 200 | Verified + settled; resource returned |

## Network + scheme support landscape

- **Documented scheme:** `exact` (specific-amount transfer). An `upto`
  scheme is mentioned as theoretical future work, not implemented.
- **Network identifiers:** CAIP-style `eip155:NNN` for EVM. Examples
  observed: `eip155:84532` (Base Sepolia testnet, used in the
  reference docs). EVM mainnets supported by SDK; Solana (SVM) and
  Stellar SDK packages also exist but the published spec excerpts
  are EVM-centric.
- **Token contracts:** the protocol is "token and currency agnostic"
  per the upstream README. In practice, the deployed examples use
  USDC on Base; production deployments are expected to specify the
  exact token contract per accept entry.
- **Facilitator services:** the spec allows facilitators (third
  parties that verify + settle on the server's behalf) but no
  specific facilitator services are named in the upstream
  documentation. The Coinbase-hosted Cloudflare-announced launch
  positions the x402 Foundation as the standards body.

## SDKs available (2026-05)

- **TypeScript** (50.5% of upstream codebase): multiple integration
  packages.
- **Python** (29.3%): pip-installable `x402` package.
- **Go** (19.1%).

For Hapax (Python-first stack), the Python SDK is the natural
candidate. **Recommendation:** vet `x402` Python SDK for
license-compatibility (the cc-task acceptance requires this) before
adding a runtime dependency.

## Reconcile against `2026-04-26-x402-receive-endpoint-architecture.md`

The predecessor architecture doc's "Hapax-specific response design"
section is **superseded by this drop**. Specifically:

| Architecture doc field | x402 v2 reality | Action |
|---|---|---|
| `payment_required` wrapper | Top-level `PaymentRequired` object inside Base64'd `PAYMENT-REQUIRED` header | Replace |
| `amount_options[]` | `accepts[]` | Rename |
| `rail: "lightning"` / `"liberapay"` / `"nostr_zap"` | `scheme: "exact"` over EVM/SVM/Stellar | **Architectural mismatch, see decisions below** |
| `currency: "BTC"` / `"USD"` | Network-specific token (USDC contract on Base, etc.) | Mismatch |
| `amount_msat` / `amount_cents` | `amount` as numeric string in token base units | Reformat |
| `invoice: "<BOLT 11>"` / `tip_url` | `payTo: "<address>"` + `asset: "<token-contract>"` | Different model |
| `ttl_s` | `maxTimeoutSeconds: <int>` | Rename + relocate |
| `license_class: "commercial \| research \| review"` | `extra: {...}` (free-form per-accept metadata) | Embed in `extra` |
| `refusal_brief_on_decline: "<slug>"` | Not in x402 v2 spec | Out-of-band; not in 402 response |

The `license_class` and `refusal_brief_on_decline` Hapax-specific
metadata **may** ride in the per-accept `extra` field, but x402
clients are not required to interpret them. They are advisory at
best.

## The rails problem (load-bearing decision)

The operator's deployed inbound rails are Lightning (via Alby
polling), Liberapay (basic-auth polling), and Nostr Zaps (event
listener). **None of these are x402 v2 schemes.** x402 v2 settles
on-chain via signed token transfers (exact scheme); a Lightning
invoice is not an x402 settlement object.

Three operator decisions resolve this:

### Decision A — "x402 endpoint exists but no x402-compatible rails"
The endpoint returns a 402 with `accepts: []` (or with a single
accept whose `extra` describes the out-of-band rails Hapax actually
uses). Standard x402 clients receiving an empty `accepts` array
will fail closed (no actionable payment options). This is
**refusal-as-data at the protocol layer** — Hapax declares the
protocol surface is acknowledged but no compliant rails are wired,
and points the requester at omg.lol/refusal for the operator's
non-engagement clause.

Pros: zero new infrastructure. Honest. Aligns with the
"full-automation-or-no-engagement" directive.
Cons: x402 clients get no actionable payment path.

### Decision B — "Onboard a stablecoin rail just for x402"
The operator wires up a Base/USDC receive address (operator-owned
EVM wallet) and adds a `payment_processors/usdc_receiver.py` to
the existing inbound-only payment_processors family. The x402
endpoint advertises `eip155:8453` (Base mainnet) USDC `accepts`
entries. Existing rails (Lightning, Liberapay, Nostr Zaps) remain
the primary surfaces; x402 is the agent-to-agent path.

Pros: x402 clients can actually settle. First-mover x402 endpoint.
Cons: introduces a new rail (custodial wallet, key management,
on-chain attestation), violates the "no new rails" hygiene of the
existing payment_processors. Requires legal entity for
USDC-receive (already blocked by `wyoming-llc-dba-legal-entity-bootstrap`
per the parent monetization-rails task).

### Decision C — "Defer x402 entirely until stablecoin rail is wired"
Don't ship the x402 endpoint until decision B (or its equivalent)
is independently approved. Mark the architecture as superseded;
mark the implementation cc-task `x402-receive-endpoint-implementation`
as blocked on a `stablecoin-receive-rail-bootstrap` follow-on task.

Pros: most honest. No half-shipped surface.
Cons: pushes the first-mover x402 timing.

**Recommendation:** Decision A is the lowest-risk, highest-honesty
move. It ships the x402 endpoint as a refusal-as-data surface that
acknowledges the protocol exists, advertises Hapax's existing
rails through `extra` for advisory consumers, and adds no new
custodial infrastructure. Decision B becomes a separate
operator-physical work item that runs in parallel with the legal
entity bootstrap.

## Acceptance status (this research drop)

- [x] Research the current authoritative x402 specification and
  record source links, response headers, JSON schema, network/rail
  support, and verification flow → §"Authoritative spec — x402 v2",
  §"Network + scheme support landscape", §"SDKs available".
- [x] Update or supersede the existing architecture document where
  it diverges from the current spec → §"Reconcile against
  2026-04-26-x402-receive-endpoint-architecture.md" — every
  divergence enumerated; doc explicitly supersedes the
  predecessor's "Hapax-specific response design" section.
- [x] Document operator decision required before implementation →
  §"The rails problem (load-bearing decision)" — three options A/B/C
  with recommendation.
- [x] Capture concrete pointers downstream implementation can use
  → schema blocks above; SDK candidates listed; CAIP network
  identifiers documented.

## Sources

- [x402 HTTP transport-v2 spec (canonical)](https://github.com/coinbase/x402/blob/main/specs/transports-v2/http.md)
- [x402 documentation: HTTP 402 core concept](https://docs.x402.org/core-concepts/http-402)
- [x402 main repository (SDK matrix + scope)](https://github.com/coinbase/x402)
- [Cloudflare announcement — x402 Foundation launch](https://blog.cloudflare.com/x402/)
- [QuickNode explainer (developer-facing summary)](https://blog.quicknode.com/x402-protocol-explained-inside-the-https-native-payment-layer/)
- [Avalanche Builder Hub — x402 technical architecture](https://build.avax.network/academy/blockchain/x402-payment-infrastructure/03-technical-architecture/02-http-payment-required)
- [PayStabl AgentPay — x402 headers reference](https://agentpay-docs.replit.app/reference/x402_headers)
- [MDN — HTTP 402 Payment Required](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/402)

## Pointers

- Predecessor architecture: `docs/research/2026-04-26-x402-receive-endpoint-architecture.md` (this doc supersedes its "Hapax-specific response design" section)
- Hapax payment receivers (existing rails, READ-ONLY contract):
  - `agents/payment_processors/lightning_receiver.py`
  - `agents/payment_processors/liberapay_receiver.py`
  - `agents/payment_processors/nostr_zap_listener.py`
- Read-only contract test: `tests/payment_processors/test_read_only_contract.py`
- Implementation cc-task (blocked on this drop): `x402-receive-endpoint-implementation` (vault active/, blocked on operator decision A/B/C)
- Parent monetization-rails task (blocked on legal entity): `publication-bus-monetization-rails-surfaces`
