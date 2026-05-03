# Monetization Rails Tier 1 — Wired Complete (10/10)

**Status doc · 2026-05-03 · epsilon session arc**

The Tier 1 e2e wiring epic is complete. All ten receive-only payment
rails shipped over the prior 72 hours now have FastAPI route
endpoints on logos `:8051`, V5 `Publisher` ABC subclasses with
allowlist + legal-name-leak guard + Prometheus counter, banking-PII
guards, and audit-pin registrations in both `PUBLISHER_WIRE_REGISTRY`
and `SURFACE_REGISTRY`.

This is the second milestone status doc in the rails arc — sibling
to `2026-05-02-monetization-rails-tier-1-complete.md` which marked
the receivers-only milestone. Tier 1 = "every shipping monetization
surface has a typed inbound contract AND a wired publication path";
the missing pieces are now operator-action gates (credentials,
platform onboarding, Wyoming-LLC) and downstream consumption
(aggregator wiring), not new code.

This doc follows the same defer-with-concrete-blockers governance
pattern.

## §1. What shipped (10/10 wired rails)

| # | PR | Rail | Surface slug | Signature shape |
|---|----|------|--------------|-----------------|
| 1 | #2280 | GitHub Sponsors | `github-sponsors-receiver` | HMAC SHA-256 in `X-Hub-Signature-256` |
| 2 | #2287 | Liberapay | `liberapay-receiver` | HMAC SHA-256 in `X-Liberapay-Signature` (bridge-forwarded) |
| 3 | #2291 | Open Collective | `open-collective-receiver` | HMAC SHA-256 in `X-Open-Collective-Signature`, multi-currency |
| 4 | #2294 | Stripe Payment Link | `stripe-payment-link-receiver` | timestamped HMAC SHA-256 (`t=<unix>,v1=<hex>`) in `Stripe-Signature` + 5 min replay tolerance |
| 5 | #2298 | Ko-fi | `ko-fi-receiver` | token-in-payload (NOT HMAC); `verification_token` JSON field |
| 6 | #2308 | Patreon | `patreon-receiver` | HMAC **MD5** in `X-Patreon-Signature` + event-kind in `X-Patreon-Event` (separate header) |
| 7 | #2310 | Buy Me a Coffee | `buy-me-a-coffee-receiver` | HMAC SHA-256 in `X-Signature-Sha256`, dotted event kinds |
| 8 | #2312 | Mercury (1st bank) | `mercury-receiver` | HMAC SHA-256 in `X-Mercury-Signature` (canonical) + `X-Hook-Signature` (legacy fallback); data-level direction filter |
| 9 | #2315 | Modern Treasury (2nd bank) | `modern-treasury-receiver` | HMAC SHA-256 in `X-Signature`; event-name-level direction filter |
| 10 | #2316 | Treasury Prime (3rd bank) | `treasury-prime-receiver` | HMAC SHA-256 in `X-Signature`; Phase 0 = ledger-account `incoming_ach.create` only |

**Cross-cutting invariants every wired rail enforces** (all asserted by
source-pin tests on every publisher and integration tests on every
route):

1. **Receive-only at the publisher boundary.** No `def send`,
   `def initiate`, `def payout`, `def transfer_*`, `def origination`,
   `def create_payment_order` anywhere in any publisher module.
2. **No outbound calls from the route module.** No
   `requests.`, `httpx.AsyncClient`, `urllib.request`, `aiohttp` in
   the route handler.
3. **Banking-PII guard for the bank rails.** Account numbers, routing
   numbers, addresses, memos, vendor IDs, ledger references, and
   trace numbers are all kept out of the manifest body. Negative-pin
   tests seed payloads with realistic banking PII and verify the
   serialized manifest contains none of those substrings.
4. **Cancellation auto-link** — for the 5 rails with cancellation-
   equivalent events (Sponsors `cancelled`, Liberapay `tip_cancelled`,
   Stripe `customer_subscription_deleted`, Patreon `members_pledge_delete`,
   BMaC `membership.cancelled`), the publisher emits a `RefusalEvent`
   to the canonical refusal log under axiom `full_auto_or_nothing`
   for the existing `refusal_annex_renderer` to aggregate. The 5
   rails without cancellation events (Open Collective, Ko-fi,
   Mercury, Modern Treasury, Treasury Prime) do not auto-link — the
   pattern is only triggered when the platform's event taxonomy has
   a cancellation semantic.
5. **Audit-pin registration from day 1.** `PUBLISHER_WIRE_REGISTRY`
   in `wire_status.py` and `SURFACE_REGISTRY` in `surface_registry.py`
   both register every wired publisher. Caught the audit-pin gap on
   the first PR (#2280); every subsequent PR has both registrations.

## §2. What's deferred (concrete next-pickup tasks)

Each deferral is gated on a named prerequisite. None is "soft maybe."

### §2.1 Wise rail — DEFERRED on architectural-pattern friction

Wise uses asymmetric **RSA-SHA256** webhook signatures (verified
against a public key fetched from `GET /v1/webhooks/public-key`)
rather than the symmetric HMAC-SHA256 pattern the other 10 rails
share. Wise schema v4.0.0 also ships **64-bit integer IDs** that
JavaScript-style JSON parsers corrupt (precision loss). Wise is
architecturally distinct from the rest of Tier 1; per the Jr
currentness-scout packet's senior intake, "not the cleanest 8th
rail." The Tier 2 build path is `shared/wise_receive_only_rail.py` +
`agents/publication_bus/wise_publisher.py` with explicit
RSA-SHA256 verifier + BigInt-safe JSON parser, ~600 LOC.

**Why this is a real deferral:** Wise is the dominant multi-currency
cross-border-receive rail; the operator will eventually need it for
international grant disbursements. Tier 2 of the rail family will
include Wise.

### §2.2 Wyoming-LLC bootstrap — DEFERRED on operator-action gate

Wyoming SOS Articles of Organization filing, EIN application via
IRS Form SS-4, business bank account opening (Mercury/Relay), DBA
registration, and W-9 updates on every revenue platform are
physical-world legal/banking actions. Per directives #9 ("Full
automation or no engagement") and #10 ("Never list operator-action
as blocker for non-physical gates"), the implementer lane does not
claim this. **This task is the gating prerequisite for live traffic
on every wired rail above** — without the legal entity, platform
W-9 / 1099 / billing onboarding cannot complete.

### §2.3 Aggregator wiring — DEFERRED on operator schema decision

`agents/payment_processors/monetization_aggregator.py` aggregates 3
older rails (Lightning, Nostr Zap, Liberapay-receiver) by counting
`PaymentEvent` records from a JSONL log. The 10 Tier 1 wired rails
each emit their own typed event class to a per-rail manifest path
under `~/hapax-state/publications/{rail}/`. Wiring them into the
aggregator requires deciding between two schemas:

- **Option A — Translator approach.** Build a typed
  `RailEventTranslator` in `shared/` that converts each Tier 1
  publisher's manifest record to a canonical `PaymentEvent` log row.
  Pro: minimal aggregator change. Con: 10 translator functions.
- **Option B — Native canonical schema.** Define a new
  `RailEventCanonical` schema that all 13 rails (3 old + 10 new)
  emit. Pro: clean uniform shape. Con: schema migration touches
  `MonetizationBlock` in `agents/operator_awareness/state.py`
  (awareness-pipeline shared state).

**Resolution path:** operator picks Option A or Option B. Either is
~250 LOC.

### §2.4 omg.lol weblog entry-id curation — DEFERRED on operator
curation

`OmgLolWeblogPublisher` (cc-task `omg-lol-support-directory-publisher`,
shipped #2241) renders the 7 creator-platform receive URLs into a
deterministic markdown body suitable for a weblog entry. The
operator-curated entry-id allowlist on the publisher's
`AllowlistGate` is the gate; the publisher is fail-closed until the
operator adds the canonical entry-id slug ("support" / "donate" /
etc.) to the allowlist.

### §2.5 Treasury Prime Phase 1 (`transaction.create`) — DEFERRED
on core direct account

Phase 0 (#2316) accepts only `incoming_ach.create` (ledger
accounts). The `transaction.create` event for core direct accounts
includes both incoming and outgoing flows and requires a data-level
direction filter (Mercury shape). Phase 0 explicitly rejects
`transaction.create` with "out of Phase 0 scope." Phase 1 is a
straightforward extension once the operator opens a core direct
account.

### §2.6 FastAPI handler tier — NOT DEFERRED (DONE)

This was item §2.3 in the prior milestone doc; this PR closes it.
All 10 handlers are now live on logos `:8051` under
`/api/payment-rails/{rail}`.

## §3. Operator-action prerequisites (credentials per rail)

Per-rail bootstrap items (most blocked on §2.2 Wyoming-LLC):

| Rail | pass key | Platform setup |
|------|---------|---------------|
| GitHub Sponsors | `github-sponsors/webhook-secret` | Sponsors profile + tier setup; webhook config |
| Liberapay | `liberapay/webhook-secret` | Bridge config (cloudmailin/mailgun/n8n) |
| Open Collective | `open-collective/webhook-secret` | OSC fiscal-sponsor application + webhook |
| Stripe Payment Link | `stripe-payment-link/webhook-secret` | Stripe master account + payment-link creation |
| Ko-fi | `ko-fi/webhook-verification-token` | Ko-fi page + webhook token |
| Patreon | `patreon/webhook-secret` | Patreon creator page + webhook |
| Buy Me a Coffee | `buy-me-a-coffee/webhook-secret` | BMaC page + webhook |
| Mercury | `mercury/webhook-secret` | Business bank account + webhook |
| Modern Treasury | `modern-treasury/webhook-secret` | Account + ACH-receive setup |
| Treasury Prime | `treasury-prime/webhook-secret` | Ledger account + webhook |

All rails will emit refusal-events to the canonical log if their
secret env var is unset and a signature is provided — fail-closed
on misconfiguration.

## §4. Cross-cutting next moves

The 10 wired rails share substantial boilerplate. Three concrete
follow-up paths the operator may want:

### §4.1 jr-monetization-rails-cross-cutting-helpers-extract (refactor)

Extract the shared shape across all 10 publishers into a typed
helper module — `agents/publication_bus/_rail_publisher_helpers.py`.
Candidates for extraction:

- `_default_output_dir(rail_slug)` — every rail computes the same
  `~/hapax-state/publications/{rail}/` path.
- `_render_aggregate_manifest_body(headers, rows)` — the manifest
  body shape is structurally identical across rails (just different
  field names).
- `_safe_filename_for_event(event_kind_value, sha)` — the
  `replace(".", "_")` sanitization is duplicated 10×.
- `_auto_link_cancellation_to_refusal_log(payload, axiom, surface, reason)`
  — 5 of the 10 publishers carry near-identical implementations.
- A typed `RailManifestRecord` Pydantic model that every publisher
  could project its event onto.

Estimated impact: ~30% LOC reduction across the 10 publisher
modules; cleaner boundary between the typed-event-specific
metadata and the publisher mechanics. **This is epsilon's domain
expertise after shipping all 10**, and is the natural next move.

### §4.2 jr-publication-bus-monetization-rails-summary-doc (capability matrix)

A reference doc that surfaces the 10-rail capability matrix in a
single place — signature shape, event kinds, cancellation handling,
multi-currency support, banking-PII handling, audit-pin status. Live
at `docs/superpowers/specs/2026-05-03-monetization-rails-capability-matrix.md`
or similar. Useful for: future rail additions (Wise, Patreon V3,
etc.); operator dashboards; new-engineer onboarding (this doc covers
the governance shape; the matrix doc covers the wire shape).

### §4.3 Aggregator wiring (§2.3) — operator schema decision

See §2.3 above. Once operator picks Option A or B, ship within one
autonomous arc.

## §5. What's unchanged (no scope creep)

- The 7 creator-platform rail receivers in `shared/*_receive_only_rail.py`
  retain their pre-wiring structure; the wiring PRs added an
  optional `raw_body=` kwarg to those that lacked it (#2280, #2287,
  #2291, #2294, #2308) but did not change any other behavior.
- `agents/payment_processors/monetization_aggregator.py` is unchanged;
  the aggregator wiring is deferred per §2.3.
- `OmgLolWeblogPublisher` is unchanged; the entry-id curation is
  deferred per §2.4.

## §6. Supersession

- `docs/governance/2026-05-02-monetization-rails-tier-1-complete.md`
  §2.3 ("FastAPI webhook handlers — DEFERRED on legal entity") is
  **superseded** by this doc. The handlers are now live; the
  legal-entity gate now applies to live traffic, not to the
  handlers themselves.
- The Wise rail deferral (§2.1 here) is unchanged from the prior
  milestone doc.
- The aggregator wiring deferral (§2.3 here) is unchanged.

---

**Next-vector decision points for the operator:**

1. Authorize the §4.1 cross-cutting refactor (epsilon will ship
   within one autonomous arc).
2. Authorize the §4.2 capability-matrix summary doc.
3. Pick Option A or Option B for §2.3 aggregator wiring.
4. Sequence Wyoming-LLC bootstrap (§2.2) — gating prerequisite for
   live revenue capture.
5. Curate omg.lol weblog entry-id slug (§2.4).
6. Authorize Wise Tier 2 build (§2.1).

cc-task: none (this is an arc-summary doc, not a tracked work item).
