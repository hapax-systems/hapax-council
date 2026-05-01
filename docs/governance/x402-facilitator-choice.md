# x402 facilitator choice — Path A (refusal-as-data)

**Decision recorded:** 2026-05-01 by alpha (per autonomous overnight mandate)
**cc-task:** `x402-facilitator-config`
**Authoritative spec:** `docs/research/2026-05-01-x402-spec-current-research.md` (gamma, #1974)
**Hapax-side architecture:** `docs/research/2026-04-26-x402-receive-endpoint-architecture.md` (alpha, +supersession edits 2026-05-01)

## The choice

Per the `x402-spec-current-research` drop's A/B/C analysis:

- **A — refusal-as-data** *(this choice)*. The 402 response carries `accepts: []` (or an `extra` object listing operator's out-of-band rails); standard x402 clients fail closed; the refusal is published as data via the existing refusal-annex pattern. **No facilitator config needed.**
- B — add a Base-mainnet USDC receive wallet as a fourth listener-only rail. Custodial wallet + key management. Currently gated behind `wyoming-llc-dba-legal-entity-bootstrap` — the operator does not yet have a stablecoin-receive entity.
- C — defer x402 entirely until the stablecoin entity ships.

**Path A is selected** as the default starting state. Rationale (recapping from #1974):

1. **It is the recommended path in the source spec drop.** #1974 explicitly recommends A.
2. **Operator's deployed receive rails (Lightning, Liberapay, Nostr Zaps) are out-of-band relative to x402 v2.** Path A is honest about that gap; Paths B/C require new infrastructure (custodial wallet for B; deferral for C).
3. **No new attack surface.** A stablecoin custodial wallet (B) introduces new key-management and tax/legal posture; refusal-as-data introduces zero new attack surface.
4. **Reversible.** When `wyoming-llc-dba-legal-entity-bootstrap` lands and the operator decides to add a stablecoin rail, this choice can be flipped to B in a single PR (update this doc + flip the `HAPAX_X402_FACILITATOR_PATH` env var + ship the receiver per `x402-payment-rail-evm-stablecoin-receive` cc-task).

## Operational consequences

- **No `shared/x402_facilitator.py` module ships under Path A.** The receive-endpoint handler (`x402-receive-endpoint-handler` cc-task, currently unclaimed) returns 402 with `PAYMENT-REQUIRED` header containing `{accepts: [], extra: {out_of_band_rails: [...]}}` and never attempts to call `/verify` or `/settle`.
- **`x402-payment-rail-evm-stablecoin-receive` cc-task is N/A under Path A** and should be closed-as-superseded if and when Path A is locked in (currently kept open as a "ready to claim if operator flips to B" placeholder).
- **The license-class registry (`x402-license-class-registry` cc-task) still ships** — it documents the price metadata that future Path B implementation would consume. Under Path A it's vestigial-but-honest: the prices are real, the rail just isn't.

## Reversal procedure

If the operator decides to switch to Path B:

1. Update this doc — change "Path A is selected" to "Path B is selected" and record the operator's rationale.
2. Set `HAPAX_X402_FACILITATOR_PATH=B` (env var, exposed via `direnv`).
3. Set `HAPAX_X402_FACILITATOR_BASE_URL=<chosen>` (e.g. Coinbase's hosted facilitator URL).
4. Set `HAPAX_X402_FACILITATOR_TOKEN_PASS_PATH=<pass entry>` for any required auth.
5. Claim and implement `x402-payment-rail-evm-stablecoin-receive`.
6. Re-claim and finish `x402-receive-endpoint-handler` with the facilitator wired in.

## Test pin (deferred)

A `tests/x402/test_facilitator_path_a_refuses_outbound.py` would assert that under Path A, any code path that attempts to call a facilitator endpoint raises rather than silently calling out. Currently no such code path exists (no `shared/x402_facilitator.py`), so the test pin is N/A until either:
- Path A is reversed to B (then the test guards the off-flag) OR
- A speculative `shared/x402_facilitator.py` is added (then the test pins its A-mode refusal).

Filing this test pin as future work via a comment in this doc rather than a separate cc-task since the test only meaningfully exists once there's something to test.

## Cross-references

- Spec source: gamma's x402 v2 research drop `docs/research/2026-05-01-x402-spec-current-research.md`
- Architecture (with supersession): `docs/research/2026-04-26-x402-receive-endpoint-architecture.md`
- Sibling cc-tasks: `x402-pydantic-models` (epsilon, #1983 in flight), `x402-license-class-registry`, `x402-receive-endpoint-handler`, `x402-payment-rail-evm-stablecoin-receive`
- Refusal-as-data substrate: `agents/publication_bus/refusal_brief_publisher.py`
- Existing read-only payment rails: `agents/payment_processors/lightning_receiver.py`, `liberapay_receiver.py`, `nostr_zap_listener.py`

— alpha
