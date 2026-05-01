# TemporalConsent interval-boundary contract design

beta, 2026-05-01

cc-task: `temporal-consent-contract-interval-boundary-design`
Train: `pipeline-ingress-recovery-audit-2026-04-28`
Source: PR #1658 deferral; R-7 audit note that TemporalConsent remains
"related but orthogonal" to the context-restore wire-in.

## Question

What is the explicit contract for time-bounded consent decisions, and
which existing governance consumers should adopt it?

## Status quo (verified 2026-05-01)

The module exists at `shared/governance/temporal.py` (and a sibling
mirror at `agents/_governance/temporal.py`). Public API:

- **`ConsentInterval`** — frozen dataclass with `start: float` (epoch
  seconds) and `end: float | None` (None means indefinite). Supports
  `active_at(t)`, `expired_at(t)`, `remaining_at(t)`, `near_expiry(grace_s, t)`,
  `extend(s)`, `renew(duration_s, from_time)`, `intersect(other)`,
  `contains(other)`, `before(other)`, `overlaps(other)`, plus the
  `indefinite()` and `fixed(duration_s)` static constructors.
  Half-open `[start, end)` semantics throughout.
- **`TemporalConsent`** — frozen dataclass wrapping `contract_id: str`,
  `interval: ConsentInterval`, and an optional `person_id: str`. Exposes
  `valid_at(t)` and `needs_renewal(grace_s, t)`.

Library coverage: `tests/test_temporal_bounds.py` (30 tests).
Production consumers: **none.** Existing tests are the only call sites.

## Contract semantics

The interval-boundary contract is the binding answer to two governance
questions that the existing `ConsentContract` cannot answer:

1. **When does this consent decision take effect?** `created_at` answers
   "when the operator made the decision," not "when the consent window
   opens." Most contracts open immediately, but pre-authorised
   recurring sessions (a recording-consent ladder, a time-limited
   livestream window) need an explicit `start`.
2. **When does this consent decision expire?** `revoked_at` answers
   "when the operator manually withdrew the decision," not "when
   the operator's prior authorisation runs out." Time-limited consent
   without manual revocation is currently not expressible.

`ConsentInterval` is the answer in both directions; `TemporalConsent`
binds it to a contract id + optional principal.

### Half-open invariant

`active_at(t) ⇔ start ≤ t < end` (or `end = None`). The
half-open shape means concatenation works without overlap: the
interval `[t₀, t₁)` followed by `[t₁, t₂)` covers `[t₀, t₂)` exactly
once, which matters for ledger-style consent renewal where one
interval's `end` is the next interval's `start`.

### Allen's algebra subset

`before` and `overlaps` are exposed today. The full algebra (`meets`,
`during`, `starts`, `finishes`, `equals`) is **out of scope** for this
contract — the half-open semantics + `intersect` give us enough for
the gate-side reasoning we need; full Allen relations are a research
artefact, not a consumer requirement.

## Interaction with existing governance gates

| Gate / consumer                          | Current state                | Should it adopt TemporalConsent? | Notes |
|------------------------------------------|------------------------------|----------------------------------|-------|
| `shared/governance/consent.py` (`ConsentContract`) | `created_at` + `revoked_at` only | **Yes — at the boundary.** The contract should optionally carry an `interval: ConsentInterval | None`. Existing consumers default to `None` (indefinite), preserving today's semantics. | Backwards-compatible additive change. |
| `shared/governance/consent_gate.py` (capability filtering) | reads contract presence/absence per turn | **Yes — wrapped check.** Gate becomes `contract present AND (interval is None OR interval.active_at(now))`. | Single-line semantic upgrade once `ConsentContract` carries the interval. |
| `shared/transcript_read_gate.py` | path-based allow/deny | **No — orthogonal.** Path-class governance is independent of time-class governance. The R-7 audit explicitly called this out. | Decoupling preserved. |
| `agents/context_restore.py` | reads transcripts via the read gate | **No** (transitively per above). | — |
| `axioms/contracts/*.yaml` (consent contract files) | static YAML, no `interval` field | **Yes — schema extension.** Add an optional `interval:` block carrying `start_iso8601`/`end_iso8601`. The loader converts to `ConsentInterval`. | Validation: `start ≤ end`; missing `start` defaults to `created_at`; missing `end` is indefinite. |
| `shared/governance/revocation.py` | bulk-purge-by-contract-id | **No.** Manual revocation is independent of natural expiry; the gate handles "active" via the OR. Revocation can still operate post-expiry to drop persisted state. | Manual revocation remains the operator's escape hatch. |
| Daimonion CPAL impingement consumer (auditory consent) | per-tick gate | **Yes** through the consent gate above; no direct change. | Same path. |
| Studio compositor face-obscure layer (visual privacy) | independent of consent gate; pixelates always | **No.** Visual privacy at livestream egress is enforced at a fail-CLOSED pipeline layer, per `docs/governance/consent-safe-gate-retirement.md`. | Decoupling preserved. |

## Out of scope

- Allen's interval algebra completion. The four-relation subset
  (`active_at`, `before`, `overlaps`, `intersect`) is what consumers
  need; the full algebra is research, not contract.
- Distributed time / Lamport clocks. `time.time()` is the canonical
  clock for consent decisions on the operator's single workstation.
- Consent contract delegation across principals. The deferred-formalism
  doc (`memory/project_consent_formal_deferred.md`) explicitly returns
  to delegation only after practical wiring is live.
- Negative time (`active_before` / `withdraw_retroactive`). Consent
  decisions are forward-looking; retroactive revocation lives in
  `revocation.py`.

## Acceptance for this design task

The cc-task acceptance is "Produce a design/spec or close as superseded
with concrete evidence." This document IS the spec. The `Split
implementation only after the contract is clear` clause is satisfied by
the four candidate cc-tasks below — each is a self-contained wire that
respects the half-open invariant.

## Split — proposed cc-tasks

These are not yet filed as cc-tasks; the operator decides routing.
Each is XS-to-S effort relative to AUDIT-04's pattern.

1. **`temporal-consent-extend-consent-contract`** — add an optional
   `interval: ConsentInterval | None = None` field to
   `ConsentContract`. Default-`None` preserves all current behavior.
   Update the YAML loader in `shared/governance/consent.py` to parse
   an optional `interval:` block. Test the indefinite default.
   WSJF ~7 (low effort, unblocks the gate wire).
2. **`temporal-consent-gate-active-check`** — once 1 lands, switch
   `consent_gate.py` to query `contract.interval.active_at(now)` when
   present. Add tests for the four cases (indefinite, fresh, expired,
   future-start). WSJF ~6.5.
3. **`temporal-consent-near-expiry-warning`** — surface `near_expiry`
   contracts in the operator dashboard / nudge surface so the operator
   can renew before silent expiry. WSJF ~5.0.
4. **`temporal-consent-intersect-renewal-audit`** — when an operator
   renews a consent decision, persist the union of the prior interval
   and the new one (or the renewal-from-now interval) and emit a
   precedent record. WSJF ~5.5.

## Test pin

`tests/test_temporal_consent_contract_design.py` lands alongside this
doc as a public-API regression pin: every `ConsentInterval` and
`TemporalConsent` method this design relies on is exercised, and the
half-open invariant is asserted. A future PR that changes the contract
breaks the pin.
