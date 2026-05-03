# Monetization Rails Arc — Complete (2026-05-03)

**Author:** epsilon
**Status:** Arc complete; well dry pending operator-action and sandbox access.
**Successor doc:** `docs/monetization/rails-capability-matrix.md`

## What's shipped

19 PRs merged in this arc, organized into five waves:

**Wave 1 — End-to-end wiring (10/10 rails, 2026-05-02 → -03):**
- #2218 license-router keystone
- #2280 GitHub Sponsors • #2287 Liberapay • #2291 Open Collective • #2294 Stripe Payment Link • #2299 Ko-fi • #2308 Patreon • #2311 Buy Me a Coffee • #2313 Mercury • #2315 Modern Treasury • #2317 Treasury Prime
- #2318 Tier-1 wired-complete governance status
- #2320 cross-cutting publisher helpers extract (-210 LOC across 10 publishers)

**Wave 2 — Security hardening (#2322 → #2329):**
- #2322 Stripe replay + idempotency + thin-event refusal + secret-validation
- #2325 GitHub Sponsors cents-int normalization (float → int + `_canonical_bytes` parity)
- #2327 Wise + ACH receive-only rail design spike (no implementation; RSA vs Ed25519 unresolved)
- #2329 Patreon idempotency pin + extracts shared `IdempotencyStore` to `shared/_rail_idempotency.py`

**Wave 3 — Idempotency chain (8 rails, #2333 → #2369):**
- #2333 Ko-fi • #2336 BMC • #2343 Liberapay • #2350 Open Collective • #2354 Mercury • #2360 Modern Treasury • #2365 Treasury Prime • #2369 GitHub Sponsors (FINAL rail)

**Wave 4 — Consolidation (#2373, #2375):**
- #2373 extract shared idempotency-store registry (-88 LOC; 9 rails on shared registry)
- #2375 migrate Stripe to shared registry (10/10 rails on shared registry)

**Wave 5 — Forward-compat + capstone docs (#2379, #2380, #2383, #2386):**
- #2379 capability matrix doc (`docs/monetization/rails-capability-matrix.md`)
- #2380 Stripe Dahlia decimal-string forward-compat
- #2383 GitHub Sponsors GraphQL deprecation no-op record (rail unaffected by design)
- #2386 Wise Direct Debit (active reception) REFUSED tier (publisher + brief + registry)

## What's deferred

**Wise implementation (`wise-receive-only-rail-implement`)** — blocked on:
1. **Signature algorithm** — packets disagree (RSA-SHA256 vs Ed25519). Resolution requires capturing a real Wise sandbox webhook delivery and running the verifier against both algorithms.
2. **mTLS termination** — Wise mandates mTLS for production partner integrations in 2026. TLS-layer concern (Caddy/nginx), not rail-internal, but the operator's `logos-api` deployment must support mTLS termination before Wise will deliver to the endpoint.
3. **Public-key bootstrap** — operator-action bound: `scripts/fetch-wise-public-key.sh` to be authored, and the operator must run it once + register an annual rotation timer. Implementation has the shape, just needs the operator's Wise account.

## Split tasks

None — clean closure. The arc was self-contained; no work bled into other domains.

## Shared prerequisites (no rail action without these)

- **Wyoming SMLLC + DBA + EIN bootstrap** (`wyoming-llc-dba-legal-entity-bootstrap`, WSJF 14.5) — every monetization rail's W-9 / 1099 / billing onboarding requires the legal entity. Operator-action only (Wyoming SOS filing + IRS SS-4 + Mercury/Relay account opening). Rails are receive-ready but cannot legally accept revenue without this.
- **Stripe / Patreon / Ko-fi / BMC / Liberapay / OC / GH Sponsors page configuration** — webhook URL pointed at `logos:8051`, secret pasted into the per-rail `*_WEBHOOK_SECRET` env var via `pass`. Operator-action gated.
- **Mercury / Modern Treasury / Treasury Prime account opening** — banking-as-API providers require operator KYC before webhook delivery is enabled.

## Unchanged (invariants this arc preserved)

- **Receive-only rail family invariant** — no outbound HTTP from any rail receiver. AST-pinned in `shared/_rail_idempotency.py` + per-rail `test_no_outbound_network_calls_during_ingest` tests.
- **No PII surfacing** beyond opaque platform handles (`sponsor_login`, `customer_handle`, `originating_party_handle`, etc.). Banking-PII negative-pin tests on every rail with banking-shaped payloads.
- **Cents-int policy** — all rails use integer minor units; fractional-cent fallbacks fail-closed (matches GH Sponsors normalization #2325 + Stripe Dahlia forward-compat #2380).
- **Refusal-as-data** on cancellation events for rails with cancellation lifecycle. Cancellation appends `RefusalEvent` to the canonical refusal log under axiom `full_auto_or_nothing`.

## Supersession

- **`docs/monetization/rails-capability-matrix.md`** is the canonical operator-facing surface doc going forward. This arc-completion doc captures the *path*; the matrix captures the *state*.
- **`docs/governance/2026-05-03-monetization-rails-tier-1-wired-complete.md`** (the mid-arc status PR #2318) is now superseded by the capability matrix + this doc.

## Suggested next pickups

When operator/sandbox unblocks:

1. **Wise public-key bootstrap script** (`scripts/fetch-wise-public-key.sh`) — small bash + systemd timer for annual rotation. Spike has the shape.
2. **Wise rail implementation** — once a sandbox webhook is captured and signature algorithm confirmed.
3. **omg.lol Pay annual re-check** — calendar item; re-evaluate vaporware status circa 2027-05.
4. **Stripe Dahlia API version pin upgrade** — when the operator's Stripe Dashboard migrates to `2026-03-25.dahlia`, update the rail's documented API version in the docstring (no code change needed; #2380 already accepts the new payload shape).

## Provenance

cc-task: this doc itself is the closure record for the arc. No standalone cc-task; companion to #2379 capability matrix + the per-PR cc-tasks already merged.
