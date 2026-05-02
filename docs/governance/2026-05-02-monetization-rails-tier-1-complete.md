# Monetization Rails Tier 1 — Complete

**Status doc · 2026-05-02 · epsilon session arc**

This document captures the milestone completion of Tier 1 of the
publication-bus monetization rails family. Tier 1 = ten typed,
fail-closed, receive-only rail receivers that normalize webhook
deliveries from each platform into payer-aggregate event records
without persisting PII. With Tier 1 done, every shipping monetization
surface has a typed inbound contract; the missing pieces are wiring,
not new receivers.

This is a **defer-with-concrete-blockers** doc per the
`status_doc_pattern` autonomous-overnight tooling — what shipped,
what didn't, why each deferral is a deferral, and what concrete
prerequisite gates each deferred item.

## §1. What shipped (Tier 1 — 10 rails)

| # | Rail | PR | Module | Pattern |
|---|------|----|--------|---------|
| 1 | GitHub Sponsors | #2218 | `shared/github_sponsors_receive_only_rail.py` | HMAC-SHA256 over raw body |
| 2 | Liberapay | #2219 | `shared/liberapay_receive_only_rail.py` | HMAC-SHA256 over raw body |
| 3 | Open Collective | #2226 | `shared/open_collective_receive_only_rail.py` | Multi-currency, slug counterparty |
| 4 | Stripe Payment Link | #2227 | `shared/stripe_payment_link_receive_only_rail.py` | Timestamped HMAC + replay tolerance |
| 5 | Ko-fi | #2230 | `shared/ko_fi_receive_only_rail.py` | Verification-token (NOT HMAC) divergence |
| 6 | Patreon | #2231 | `shared/patreon_receive_only_rail.py` | HMAC-MD5 divergence |
| 7 | Buy Me a Coffee | #2234 | `shared/buy_me_a_coffee_receive_only_rail.py` | HMAC-SHA256 (return to canonical) |
| 8 | Mercury Bank | #2251 | `shared/mercury_receive_only_rail.py` | Bank rail; data-level direction filter |
| 9 | Modern Treasury | #2255 | `shared/modern_treasury_receive_only_rail.py` | Bank rail; event-name-level direction filter |
| 10 | Treasury Prime (Phase 0) | #2258 | `shared/treasury_prime_receive_only_rail.py` | Bank rail (BaaS); ledger-account ACH only |

Plus two adjacent governance modules from the same arc:
- `payment-aggregator-v2-support-normalizer` (PR #2214) — typed
  normalizer for the older 3-rail tier (Lightning / Nostr Zap /
  Liberapay-receiver).
- `omg-lol-support-directory-publisher` (PR #2241) — typed composer
  that renders the rails' canonical public receive URLs to
  deterministic markdown for posting via the existing
  `OmgLolWeblogPublisher`.

**Cross-cutting invariants every Tier 1 rail enforces:**

1. **Receive-only.** No `def send`, `def initiate`, `def payout`,
   `def transfer_out`, `def origination`, `def create_payment_order`
   anywhere in the module. Asserted by source-pin tests on every
   rail.
2. **No outbound calls.** No imports of `requests`, `httpx`,
   `urllib.request`, `aiohttp`, or platform SDKs. Asserted by
   source-pin tests.
3. **No PII.** Schemas exclude email, address, account number,
   routing number, memo, vendor ID, ledger reference, and any
   field that would constitute material payer identity beyond the
   public display the platform already shows on the operator's
   dashboard. Asserted by negative-pin tests that seed the payload
   with realistic PII and verify the serialized normalized event
   contains none of those substrings.
4. **Frozen + extra="forbid".** Pydantic schemas reject extras at
   construction; cannot accidentally smuggle a new field through.
5. **HMAC verification.** Every rail with a signature mechanism
   validates the digest against the per-rail secret env var, with
   `hmac.compare_digest` (timing-leak-safe) on the raw body bytes.
   Mismatch fails closed.

## §2. What's deferred (concrete next-pickup tasks)

Each deferral below is gated on a concrete prerequisite. None of
them is a "soft maybe" — each is a straightforward downstream task
that can be claimed when the prerequisite resolves.

### §2.1 Wise rail — DEFERRED on architectural-pattern friction

**Why deferred:** Wise uses asymmetric **RSA-SHA256** webhook
signatures (verified against a Wise-published public key fetched
from `GET /v1/webhooks/public-key`) rather than the symmetric
HMAC-SHA256 pattern the other 10 rails share. Additionally, Wise
schema v4.0.0 ships **64-bit integer IDs** that JavaScript-style
JSON parsers corrupt (precision loss on `Number.parseInt`). The
combination of (a) a different cryptographic primitive and (b) a
different JSON-parsing constraint makes Wise architecturally
distinct from the rest of Tier 1. Per the Jr currentness-scout
packet's senior intake, Wise is "not the cleanest 8th rail."

**Resolution path:** open a separate cc-task
`wise-receive-only-rail` with explicit RSA-SHA256 verifier +
BigInt-safe JSON parser. Keep the schema in a sibling module to
avoid contaminating the Tier 1 HMAC pattern. ~600 LOC including
the public-key cache and rotation handling.

**Why this is a real deferral and not a refusal:** Wise is the
dominant multi-currency cross-border-receive rail; the operator
will eventually need it for international grant disbursements that
don't route through ACH. Tier 2 of the rail family will include
Wise.

### §2.2 Wyoming-LLC bootstrap — DEFERRED on operator-action gate

**Why deferred:** Wyoming SOS Articles of Organization filing,
EIN application via IRS Form SS-4, business bank account opening
(Mercury/Relay), DBA registration, and W-9 updates on every
revenue platform are physical-world legal/banking actions that
require the operator personally. Per epsilon's directive #9
("Full automation or no engagement") and #10 ("Never list
operator-action as blocker for non-physical gates"), the
implementer lane does not claim operator-physical tasks.

**Resolution path:** the operator runs the bootstrap. This is the
WSJF-14.5 task at the top of the offered queue and is the
gating prerequisite for the FastAPI handlers in §2.3 going live
under a real legal entity.

### §2.3 FastAPI webhook handlers (10 of them) — DEFERRED on legal entity

**Why deferred:** every Tier 1 rail receiver expects an upstream
FastAPI handler that captures the raw HTTP body, hands the parsed
payload + raw bytes + signature header to `ingest_webhook()`, and
returns 2xx (within 5 seconds for Modern Treasury and Wise per
their documented contracts). The handlers themselves are minor
glue (~30 LOC each) but they must terminate at endpoints
registered with the platforms — and platform registration requires
the legal entity (W-9 / 1099 / billing identity).

**Resolution path:** one cc-task per rail; each ships the FastAPI
handler + URL-path registration + secret-env-var bootstrap doc.
Order is bottom-up by platform-onboarding cost (Stripe and Ko-fi
are easiest; Mercury / Modern Treasury / Treasury Prime require
banking-platform onboarding which depends on the legal entity).

### §2.4 Aggregator wiring — DEFERRED on schema-design decision

**Why deferred:** `agents/payment_processors/monetization_aggregator.py`
currently aggregates 3 rails (Lightning, Nostr Zap, Liberapay) by
counting `PaymentEvent` records from a JSONL log at
`agents/payment_processors/event_log.py`. The 10 Tier 1 rails
produce 10 different normalized event types (`SponsorshipEvent`,
`CoffeeEvent`, `MercuryTransactionEvent`, etc.) — none of them
write to the canonical event log. Wiring them in requires deciding
between two schemas:

- **Option A — Translator approach.** Build a typed
  `RailEventTranslator` in `shared/` that converts each Tier 1
  event type to a canonical `PaymentEvent` record on the existing
  log. Pro: minimal changes to the aggregator. Con: 10 translation
  functions, each subject to Liberapay/Lightning/Nostr-pattern
  shoehorning.
- **Option B — Native canonical schema.** Define a new
  `RailEventCanonical` schema (matches the new rails' shape:
  `amount_currency_cents` + `currency` rather than
  `amount_sats|amount_eur`) and migrate the 3 old rails to write
  it. Pro: clean uniform shape across all 13 rails. Con:
  schema migration touches `MonetizationBlock` (in
  `agents/operator_awareness/state.py`) which is awareness-pipeline
  shared state.

**Resolution path:** operator picks Option A or Option B. Then a
single cc-task ships the chosen approach. Either is ~250 LOC.

### §2.5 omg.lol weblog entry-id allowlist — DEFERRED on operator
curation

**Why deferred:** `OmgLolWeblogPublisher` (`omg-lol-weblog-bearer-fanout`
surface) gates publication on an entry-id allowlist that the
operator curates. The `omg-lol-support-directory-publisher` (PR
#2241) ships the typed composer; the allowlist update + publish
script that materializes the directory as a real omg.lol weblog
entry is operator-curation-gated.

**Resolution path:** the operator decides the canonical entry-id
slug ("support" / "donate" / "patrons" / etc.) and adds it to the
operator-curated allowlist on `OmgLolWeblogPublisher`. Then a
short driver script invokes the composer + publisher.

### §2.6 Treasury Prime Phase 1 (`transaction.create`) — DEFERRED on
core direct account

**Why deferred:** Phase 0 of Treasury Prime (PR #2258) accepts only
the ledger-account event `incoming_ach.create`. The
`transaction.create` event for core direct accounts requires a
data-level direction filter (Mercury shape) and only fires if the
operator has a core direct account with Treasury Prime — the legal
entity (§2.2) gates that account opening.

**Resolution path:** after the operator has a core direct account,
ship `treasury-prime-phase-1-transaction-create` as an extension
(adds the data-level direction filter on the receiver's
`_extract_direction` helper, similar to Mercury #2251).

## §3. Tasks split out for downstream lanes

The following sub-tasks are explicit splits — they are not blocked,
just out-of-lane for epsilon's typed-contract pattern:

- **Aggregator wiring schema design** (§2.4) — needs operator
  decision; not implementable by epsilon without that input.
- **FastAPI handler tier** (§2.3, 10 sub-tasks) — implementer-lane
  work with platform-onboarding dependencies; each handler is a
  small task best claimed individually.
- **Wise rail receiver** (§2.1) — different architectural pattern
  (RSA-SHA256 + BigInt); separate cc-task.
- **Treasury Prime Phase 1** (§2.6) — extension task, gated on
  account-type prerequisite.
- **Wyoming LLC bootstrap** (§2.2) — operator-action lane.

## §4. Shared prerequisites across the deferrals

Three prerequisites gate most of the deferred items:

1. **Legal entity exists.** Wyoming LLC + EIN + DBA + business bank
   account. Without it: no platform onboarding, no W-9, no 1099,
   no live webhook traffic on any handler. Gates §2.3, §2.6, and
   the live-traffic phase of §2.1.

2. **Per-rail webhook secret in operator credential store.** Each
   rail receiver reads `<RAIL>_WEBHOOK_SECRET` from the environment;
   the FastAPI handler reads from `pass`. The secret-bootstrap
   doc per rail is small but must accompany each §2.3 handler PR.

3. **omg.lol weblog allowlist update.** §2.5 plus any future
   weblog-published artifacts (refusal annexes, license-request
   responses, etc.).

## §5. What's unchanged (no scope creep)

- The 3 older rails (Lightning, Nostr Zap, Liberapay-receiver in
  `agents/payment_processors/`) continue to work as-is. Tier 1
  did not modify them.
- `OmgLolWeblogPublisher` (`agents/publication_bus/omg_weblog_publisher.py`)
  was not touched; the support-directory composer (PR #2241)
  produces a markdown body the publisher can consume but does not
  modify the publisher itself.
- Awareness pipeline shared state (`MonetizationBlock` in
  `agents/operator_awareness/state.py`) is unchanged. The
  aggregator-wiring decision in §2.4 will modify it; deliberately
  deferred to keep the high-blast-radius change scoped to a single
  operator-decided PR.

## §6. Supersession (what this arc replaces)

- The proposed `wyoming-llc-bootstrap-runner` Playwright runner
  (WSJF 9.0) is **not superseded** by this arc — it remains the
  cleanest path to automating the §2.2 bootstrap if the operator
  wants Playwright over manual filing.
- The `publication-bus-monetization-rails-surfaces` task
  (WSJF 9.0) was the umbrella spec for the 7 creator-platform
  rails (#1–#7 in §1); with Mercury / Modern Treasury / Treasury
  Prime added by this arc, the umbrella's scope is **extended
  beyond its original Phase 0 plan** (Phase 0 specified 5 rails;
  arc shipped 10).
- The `omg-lol-support-directory-publisher` task (this arc, PR
  #2241) **does not supersede** the `publication-bus-omg-rss-fanout`
  helper — they are parallel surfaces. The directory composer
  produces one weblog body; the RSS fanout helper composes
  multiple weblog publishers.

---

**Next-vector decision points for the operator:**

1. Pick Option A or Option B for §2.4 aggregator wiring. epsilon
   will ship within one autonomous arc once chosen.
2. Confirm Wyoming-LLC bootstrap (§2.2) is the right next legal
   action, or signal a different sequencing.
3. Curate the omg.lol weblog entry-id slug (§2.5) so the
   support-directory composer can be wired into a live weblog
   entry.
4. Authorize / decline a Wise rail Tier 2 build (§2.1).

cc-task: none (this is an arc-summary doc, not a tracked work
item). If the operator wants a follow-up task created, name the
slug and epsilon will create it in the vault.
