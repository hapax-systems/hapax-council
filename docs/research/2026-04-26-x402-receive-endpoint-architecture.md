# Architecture: x402 receive-endpoint

**Authored:** 2026-04-26 by alpha
**cc-task:** `leverage-vector-x402-receive-endpoint` (WSJF 5.0)
**Source:** `docs/research/2026-04-25-leverage-strategy.md`

## Context

x402 is an emerging HTTP protocol for agent-mediated payments triggered by HTTP `402 Payment Required` responses. First-mover position: very few deployed x402 endpoints exist as of 2026-04. The protocol's core mechanic is that a server returns `HTTP 402` with structured payment-requirements metadata in the response body; the requesting agent's payment client extracts the metadata and routes payment via a supported rail (Lightning, on-chain crypto, or fiat-via-card-tokenisation).

Hapax-side use: agent-to-agent commercial-license rail. When another agent (Claude Code, GPT, etc.) attempts to consume Hapax's licensed resources (paid models, premium endpoints, derivative-work licenses), the endpoint returns 402 with payment-rail metadata pointing at the operator's existing receive rails (Alby Lightning, Liberapay, Nostr Zaps).

## Existing Hapax payment infrastructure

| Component | Path | Direction |
|---|---|---|
| Lightning receive (Alby polling) | `agents/payment_processors/lightning_receiver.py` | inbound, READ-ONLY contract |
| Liberapay receive (basic-auth polling) | `agents/payment_processors/liberapay_receiver.py` | inbound, READ-ONLY contract |
| Nostr Zap listener | `agents/payment_processors/nostr_zap_listener.py` | inbound, READ-ONLY contract |
| Monetization aggregator | `agents/payment_processors/monetization_aggregator.py` | event-bus consumer |
| Refusal annex (rejected payments) | `agents/payment_processors/refusal_annex.py` | refusal-as-data |

All three rails are listener-only — they poll their respective providers and emit `PaymentEvent` instances onto the canonical event bus. There is no outbound `send`/`payout`/`transfer` path (enforced by `tests/payment_processors/test_read_only_contract.py`). x402 fits cleanly: it advertises receive-rails to inbound requesters; it does not initiate outbound payments.

## Spec landscape (as of 2026-04)

**Authoritative source needed:** the x402 protocol does not yet have a stable RFC-style spec. Several discovery surfaces:

- Coinbase's x402 launch (Q1 2026) — primary launch surface; spec under `https://x402.org` or similar
- Lightning Network's existing `LNURL-pay` flow — adjacent prior art for advertising Lightning payment options via HTTP
- BOLT 11 invoice format — what a Lightning payment requirement looks like under the hood

**Action required before endpoint ships:** dispatch a research agent to fetch the current x402 response-shape spec (header names, JSON keys, accepted networks, etc.) from authoritative sources. This architecture doc deliberately defers the response-shape codification to that research drop so the Pydantic model is grounded.

## Hapax-specific response design (preliminary; pending spec confirmation)

The 402 response should carry, at minimum:

```json
{
  "payment_required": {
    "resource": "<URI of the resource being requested>",
    "amount_options": [
      {
        "rail": "lightning",
        "currency": "BTC",
        "amount_msat": <int>,
        "invoice": "<BOLT 11 invoice OR LNURL-pay endpoint>",
        "ttl_s": <int>
      },
      {
        "rail": "liberapay",
        "currency": "USD",
        "amount_cents": <int>,
        "tip_url": "https://liberapay.com/<operator>/tip",
        "ttl_s": null
      },
      {
        "rail": "nostr_zap",
        "currency": "BTC",
        "amount_msat": <int>,
        "lnurl": "<LNURL-pay endpoint resolved from operator's nip-05>",
        "ttl_s": <int>
      }
    ],
    "license_class": "<commercial | research | review>",
    "refusal_brief_on_decline": "marketing-refusal-annex-x402-declined-<resource-slug>"
  }
}
```

`license_class` distinguishes the requested use case so the operator's existing `repo-pres-license-policy` matrix maps to per-class amounts (commercial > research > review).

## Components needed (separate PRs)

| # | Component | Path | Effort | Dep | Status |
|---|---|---|---|---|---|
| 0 | This architecture doc | `docs/research/2026-04-26-x402-receive-endpoint-architecture.md` | shipped here | none | **SHIPPED** PR #1681 |
| 1 | x402 spec research drop | `docs/research/2026-04-30-x402-v2-spec-current.md` | 1h research-agent dispatch | none | **SHIPPED** PR #1974 (Path A operator decision per `docs/governance/x402-facilitator-choice.md` PR #1987) |
| 2 | Pydantic response model | `agents/payment_processors/x402/models.py` | 30 min | #1 | **SHIPPED** PR #1983 (`Accept` + `SettlementResponse` + `encode_payment_required` / `decode_payment_required` helpers) |
| 3 | License-class registry | `shared/x402_license_classes.yaml` + reader | 1-2h | #2 | **SHIPPED** PR #1989 |
| 4 | Endpoint composer (pure) | `agents/payment_processors/x402/...` | 1-2h | #2, #3 | **SHIPPED** PR #1990 (Path A composer = `payment_required_response()` helper in `logos/api/routes/x402.py`; pure-helper extraction is implicit per Path A's stateless refusal shape) |
| 5 | FastAPI route | `logos/api/routes/x402.py` | 1h | #4 | **SHIPPED** PR #1990 (`APIRouter` at `/api/x402` with `GET /api/x402/demo` substrate self-test) |
| 6 | Integration tests | `tests/test_x402_route.py` | 1-2h | #5 | **SHIPPED** PR #1990 (16 tests across `TestDemoRoute` / `TestPaymentRequiredResponseHelper` / `TestReadOnlyContract` — last includes a no-outbound-HTTP lexical pin so future regressions can't accidentally adopt Path B) |

**Status (2026-05-02 reconcile by beta per cc-task `x402-receive-endpoint-implementation`):** all 7 components shipped. Total cycle time was ~5 days (2026-04-26 architecture → 2026-05-01 receive-endpoint handler). The original ~6-8h estimate was tight; actual was ~12h spread across 4 sessions (alpha + epsilon + gamma + alpha).

## Path A semantics and reversal

Per `docs/governance/x402-facilitator-choice.md` (PR #1987, alpha — operator decision): Hapax's x402 endpoint operates under **Path A (refusal-as-data)**. Every `payment_required_response()` returns HTTP 402 with `accepts: []`; standard x402 v2 clients interpret empty-accepts as a hard refusal and fail closed. The handler **NEVER** calls a facilitator's `/verify` or `/settle` endpoints. This invariant is lexically pinned by `tests/test_x402_route.py:TestReadOnlyContract.test_no_facilitator_call_imports`.

**Reversal procedure (Path A → Path B):** documented in `docs/governance/x402-facilitator-choice.md` § "Reversal procedure". Three deliberate steps gate the reversal:

1. `payment_required_response` extends to advertise per-network `Accept` entries (USDC on Base / Polygon / etc.).
2. Facilitator-call follow-on endpoint ships under `x402-payment-rail-evm-stablecoin-receive` cc-task (NOT yet filed).
3. `TestReadOnlyContract.test_no_facilitator_call_imports` will fail and must be updated to exempt the chosen HTTP client — the exemption update signals deliberately that Path B is being adopted.

The cc-task `x402-receive-endpoint-implementation` closes here as **DONE under Path A**. Future Path B work files a new cc-task per the reversal procedure above.

## Constitutional posture

- `feedback_full_automation_or_no_engagement` — entire flow is daemon-tractable; no operator intervention per request.
- `single_user` — Hapax serves; each requesting agent is its own operator's agent. Multi-tenancy is bounded by the HTTP 402 response (not by Hapax-side identity tracking).
- `interpersonal_transparency` — no persistent state about the requesting agent's principal; the 402 response is stateless from Hapax's view.
- Refusal-as-data — any 402-handler refusal (decline, missing-rail-credentials, license-class-not-offered) emits a refusal brief with a stable slug for citation-graph cross-reference.
- READ-ONLY contract preserved — x402 advertises receive rails; it never initiates outbound payments.

## Cross-references

- Source synthesis: `docs/research/2026-04-25-leverage-strategy.md` drop-leverage
- Lightning receive contract: `agents/payment_processors/lightning_receiver.py` + `tests/payment_processors/test_read_only_contract.py`
- License-class matrix (parent): `docs/repo-pres/repo-registry.yaml` (PR #1679)
- Refusal-as-data substrate: `agents/publication_bus/refusal_brief_publisher.py`

— alpha
