# Research: x402 v2 spec — current shape (as of 2026-05-01)

**Authored:** 2026-05-01 by alpha
**cc-task:** `x402-spec-current-research` (WSJF 5.0)
**Supersedes the deferred-spec section of:** `docs/research/2026-04-26-x402-receive-endpoint-architecture.md`

## Sources fetched

- `https://x402.org` — landing page (general framing only)
- `https://github.com/coinbase/x402` — repo readme + SDK list
- `https://github.com/coinbase/x402/tree/main/specs` — directory listing
- `https://github.com/coinbase/x402/blob/main/specs/x402-specification-v2.md` — canonical v2 spec

## Spec version

The repo currently ships **two** specifications side-by-side:

- `specs/x402-specification-v1.md` — initial version
- `specs/x402-specification-v2.md` — updated version (this is the target shape)

x402 has shipped its v2 launch. The v2 spec is what new endpoints should target.

## HTTP transport

Client makes a regular request → server responds **HTTP 402 Payment Required** with:

| Header              | Direction | Payload                                                  |
|---------------------|-----------|----------------------------------------------------------|
| `PAYMENT-REQUIRED`  | server→client | base64-encoded `PaymentRequired` object                |
| `PAYMENT-SIGNATURE` | client→server | base64-encoded `PaymentPayload` (paid retry attempt)   |
| `PAYMENT-RESPONSE`  | server→client | base64-encoded `SettlementResponse` (post-settlement)  |

i.e. the structured fields ride in *headers*, not the response body. The response body is the resource itself once settlement succeeds.

## Canonical schemas (v2)

### `PaymentRequirements` (server-side, per-resource cost declaration)

```
{
  "scheme":             string,    // payment scheme id ("exact", etc.)
  "network":            string,    // CAIP-2: "eip155:8453", "solana:5eykt...", etc.
  "amount":             string,    // atomic token units (e.g. "100000" for 0.1 USDC)
  "asset":              string,    // token contract address or ISO 4217 code
  "payTo":              string,    // recipient wallet address or role constant
  "maxTimeoutSeconds":  number,    // max completion time
  "extra":              object?    // scheme-specific data, optional
}
```

### `PaymentPayload` (client-side, the paid retry)

```
{
  "x402Version":  number,                    // current = 2
  "accepted":     PaymentRequirements,       // echoes the requirement the client is paying
  "payload":      object,                    // scheme-specific authorization data
  "resource":     ResourceInfo?,             // optional resource description
  "extensions":   object?                    // optional
}
```

For the **`exact` EVM scheme**, `payload` contains:
```
{
  "signature":     string,                   // EIP-712 signature
  "authorization": {
    "from":          string,
    "to":            string,
    "value":         string,
    "validAfter":    number,                 // unix-ts
    "validBefore":   number,
    "nonce":         string
  }
}
```

This maps cleanly onto **EIP-3009** (`transferWithAuthorization`) — which is exactly how USDC on Base / Avalanche / etc. enables gasless authorization-based transfers.

### `VerifyResponse` (facilitator → server)

```
{
  "isValid":       boolean,
  "invalidReason": string?,
  "payer":         string?  // payer wallet address
}
```

### `SettlementResponse` (server → client, after on-chain settlement)

```
{
  "success":     boolean,
  "transaction": string,    // tx hash
  "network":     string,    // CAIP-2
  "payer":       string?,
  "errorReason": string?,
  "amount":      string?,   // atomic
  "extensions":  object?
}
```

## Facilitator endpoints

A **facilitator** is a third-party (or self-hosted) service that translates payment proofs into on-chain settlement. Spec endpoints:

| Method | Path                       | Purpose                                                |
|--------|----------------------------|--------------------------------------------------------|
| POST   | `/verify`                  | Validate `PaymentPayload` w/o on-chain execution       |
| POST   | `/settle`                  | Execute verified payment on-chain                      |
| GET    | `/supported`               | List supported schemes / networks / extensions         |
| GET    | `/discovery/resources`     | List discoverable x402 resources (filter by type, etc.) |

A receive-only endpoint (Hapax's posture) needs to call `/verify` + `/settle` against a chosen facilitator (Coinbase hosts one; self-hosting is possible).

## Supported networks (v2 examples)

**EVM (CAIP-2):**
- `eip155:8453` — Base mainnet
- `eip155:84532` — Base Sepolia (test)
- `eip155:43114` — Avalanche mainnet
- `eip155:43113` — Avalanche Fuji (test)

**Solana (SVM):**
- `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp` — mainnet
- `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` — devnet

**Stellar** — supported in spec, network identifiers TBD per scheme docs.

## SDKs

- `@x402/evm` — EVM client/server
- `@x402/svm` — Solana
- `@x402/stellar` — Stellar

(JS only at present — no Python SDK; Hapax must talk the protocol over plain HTTP / pydantic models.)

## Spec divergence from `2026-04-26-x402-receive-endpoint-architecture.md`

The April arch doc speculatively put structured fields in the **response body** under a `payment_required` JSON key with a Lightning-first orientation. The actual v2 spec:

1. **Fields live in HEADERS, not the body.** `PAYMENT-REQUIRED` header carries the base64'd `PaymentRequirements`.
2. **Stablecoin-first, not Lightning-first.** No Lightning scheme is in v2; the `exact` EVM/SVM schemes target stablecoin transfers via EIP-3009 (EVM) and SPL token transfers (SVM).
3. **CAIP-2 network IDs**, not free-text `"rail": "lightning"`.
4. **Facilitator pattern** for verify/settle — third-party service is the recommended verifier, not in-process logic.

## Implication for Hapax

Hapax's existing receive rails (Lightning, Liberapay, Nostr Zaps) are **none of them x402-native**. To ship an x402 receive endpoint, Hapax needs either:

- **A. Add a stablecoin receive wallet** on a v2-supported network (Base mainnet is the canonical example; Hapax operator's choice). This becomes the `payTo` address in `PaymentRequirements`.
- **B. Use an x402 *adapter* facilitator** that can accept x402 payments and settle into Hapax's existing rails (e.g. accept USDC-on-Base, convert to BTC Lightning, settle to Alby). No such adapter is publicly listed; this is a build-it-yourself path.

**Recommended:** (A) — add a Base-mainnet USDC receive address as a fourth listener-only rail in `agents/payment_processors/`. The wallet address is operator-provided and read-only on the Hapax side (Hapax never holds the key; it just observes incoming USDC at the address via the facilitator's settlement webhook).

## Implementation tasks to file as follow-ups

1. **`x402-payment-rail-evm-stablecoin-receive`** — Add `agents/payment_processors/evm_stablecoin_receiver.py` modeled on `lightning_receiver.py`. Listener-only, polls a chosen facilitator's `/discovery` or webhook for settlements at the operator-configured `payTo` address. Emits `PaymentEvent` onto the event bus per existing contract.

2. **`x402-receive-endpoint-handler`** — Implement the actual HTTP 402 response in a FastAPI dependency / middleware. On unauthenticated requests to license-gated routes, return 402 + `PAYMENT-REQUIRED` header with base64'd `PaymentRequirements`. On retry with `PAYMENT-SIGNATURE` header, call facilitator `/verify` then `/settle`, then serve the resource if successful.

3. **`x402-pydantic-models`** — `shared/x402_models.py` with Pydantic models for: `PaymentRequirements`, `PaymentPayload`, `VerifyResponse`, `SettlementResponse`. Pure data-class concerns; no IO.

4. **`x402-license-class-registry`** — `shared/x402_license_classes.yaml` mapping route patterns / capability tiers to `PaymentRequirements` (amount, asset, network). Operator-curated, read at boot.

5. **`x402-facilitator-config`** — Operator-config for which facilitator to use (Coinbase's hosted, self-hosted, etc.). Includes facilitator base URL + any required API keys via `pass`.

## Out of scope (do not implement)

Per existing arch doc and operator constraint: **no outbound payment behavior**. Hapax's payment posture is receive-only. The x402 protocol itself supports send/receive; we implement *only* the server side. The read-only contract pin in `tests/payment_processors/test_read_only_contract.py` should be extended to cover `evm_stablecoin_receiver.py` once filed.

## Status

The architecture doc at `docs/research/2026-04-26-x402-receive-endpoint-architecture.md` should be **updated with a pointer to this research doc** as the authoritative spec reference. The five follow-up cc-tasks above should be filed; only after they are claimed-and-implemented should code touch the receive endpoint surface.
