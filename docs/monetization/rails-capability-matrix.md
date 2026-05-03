# Monetization Rails — Capability Matrix

**Status:** 10/10 rails wired end-to-end + sharing the idempotency registry as of 2026-05-03.

Operator-facing reference for grant/sponsor outreach planning. Lists every wired payment rail with its auth shape, hosting cost, API endpoint, webhook event, 2026 changes, and current status.

For governance status (egress posture, refusal behavior, V5 publisher invariants), see `docs/governance/2026-05-03-monetization-rails-tier-1-wired-complete.md`.

## Active rails (10)

| Rail | Auth | Cost | API endpoint | Webhook event(s) | 2026 changes | Status |
|---|---|---|---|---|---|---|
| **GitHub Sponsors** | HMAC SHA-256 (`X-Hub-Signature-256`) + `X-GitHub-Delivery` UUID | $0 webhook; 0–6% platform fee on tiers | `https://api.github.com/sponsors/<org>` (REST, deprecated → GraphQL) | `sponsorship.{created,cancelled,tier_changed,pending_cancellation}` | REST → GraphQL deprecation 2026-03-10 — **rail unaffected** (webhook path stable; rail's receive-only invariant forbids API queries by design) | wired ✓ |
| **Stripe Payment Link** | HMAC SHA-256 timestamped (`Stripe-Signature: t=…,v1=…`) + 300s replay window | 2.9% + $0.30 / charge; $0 platform fee | `https://api.stripe.com/v1/...` | `payment_intent.succeeded`, `checkout.session.completed`, `customer.subscription.{created,deleted}` | `2026-03-25.dahlia` API version + `Stripe.Decimal` migration[^stripe-dahlia] — **rail forward-compat'd** (#2380 accepts integer + decimal-string forms). Thin-payload mode rejected by rail (would force outbound fetch). | wired ✓ |
| **Open Collective** | HMAC SHA-256 (`X-Open-Collective-Signature`) + `X-Open-Collective-Activity-Id` | $0 webhook; 5% platform fee + 2.9% + $0.30 / charge | `https://api.opencollective.com/v2/graphql` | `collective_transaction_created`, `order_processed`, `member_created`, `subscription_*` | API stable; multi-currency native | wired ✓ |
| **Liberapay** | Bridge-relayed HMAC SHA-256 (`X-Liberapay-Signature`) + bridge `delivery_id` (cloudmailin/mailgun) | €0; donations are weekly batched | **READ-ONLY** `https://liberapay.com/<user>/public.json`[^liberapay-readonly] | `payin_succeeded`, `tip_cancelled`, `pledge_created` (bridge-injected) | No native webhooks (still); bridge-required | wired ✓ |
| **Patreon** | HMAC **MD5** (`X-Patreon-Signature`)[^patreon-md5] + `X-Patreon-Webhook-Id` | $0 webhook; 8–12% platform fee | `https://www.patreon.com/api/oauth2/v2/...` | `members:create`, `members:update`, `members:pledge:create`, `members:pledge:delete` | OAuth2 flow stable; no breaking changes flagged | wired ✓ |
| **Ko-fi** | Token-in-payload (no HMAC) — `verification_token` field + body-borne `kofi_transaction_id` | $0 webhook; 0–5% platform fee | None — webhook-only product | `Donation`, `Subscription`, `Commission`, `Shop Order` | No API breaking changes (no API surface) | wired ✓ |
| **Buy Me a Coffee** | HMAC SHA-256 (`X-Signature-Sha256`) + body-borne `event_id` | $0 webhook; 5% platform fee | `https://app.buymeacoffee.com/api/...` | `donation`, `membership.{started,cancelled}`, `extras_*` | API stable | wired ✓ |
| **Mercury** | HMAC SHA-256 (`X-Mercury-Signature` or `X-Hook-Signature`) + body-borne `data.id` | $0 (banking) | `https://api.mercury.com/api/v1/...` | `transaction.{created,updated}` (incoming-only via direction filter) | API stable; dual-header acceptance for legacy integrations | wired ✓ |
| **Modern Treasury** | HMAC SHA-256 (`X-Signature`) + body-borne `data.id` | Negotiated banking-as-API tier | `https://app.moderntreasury.com/api/...` | `incoming_payment_detail.{created,completed}` | **5-second `2xx` response budget enforced** | wired ✓ |
| **Treasury Prime** | HMAC SHA-256 (`X-Signature`) + body-borne `data.id` | Negotiated banking-as-API tier | `https://api.treasuryprime.com/...` | `incoming_ach.create` (Phase 0, ledger accounts) + `transaction.create` (Phase 1, core direct accounts; data-level direction filter) | API stable | wired ✓ |

[^stripe-dahlia]: Stripe `2026-03-25.dahlia` introduces `Stripe.Decimal` for monetary amounts (replacing `Long`/`int`). Breaking for code that assumes integer cents. Rail handles minor units as `int` but the upgrade path needs migration when we adopt the new API version. Tracking: future cc-task `stripe-dahlia-decimal-migration`.
[^liberapay-readonly]: Liberapay has [zero write API](https://github.com/liberapay/liberapay.com/issues/688) and no native webhooks. The rail relies on email→webhook bridges (cloudmailin / mailgun / n8n) parsing donation-notification emails into structured JSON. Read-side polling against `public.json` is rate-limited; not used for monetary state.
[^patreon-md5]: Patreon signs webhooks with HMAC MD5 (not SHA-256) per their documented wire format. Cryptographically unusual but practically unforgeable for HMAC use (RFC 2104 §6 — keyed-HMAC's security proof does not require collision resistance). The rail's #2308 docstring covers the rationale.

## Idempotency

All 10 rails consume the shared sqlite registry at `shared/_rail_idempotency.py` (`get_idempotency_store(rail_subdir)` + `reset_idempotency_store()`). Per-rail subdirectory under `~/hapax-state/` (or `$HAPAX_HOME` for tests) holds `idempotency.db`. Duplicate event ids → `{"status": "duplicate", "<id-key>": ...}` 200 OK so the platform stops retrying without duplicate fulfillment. Spec: per-rail idempotency PRs #2329 → #2375.

## Receive-only invariants

Every rail enforces:

- **No outbound HTTP**. AST-pinned in `shared/_rail_idempotency.py`; rail-by-rail no-outbound-imports tests in `tests/test_payment_rails_routes.py`.
- **No PII surfaced** beyond opaque platform handles (sponsor login, supporter slug, customer ID). Banking-PII negative-pin tests on every rail with banking-shaped payloads (Mercury / Modern Treasury / Treasury Prime).
- **Receive-only OAuth scope** where applicable (Wise design — see `docs/research/2026-05-03-wise-ach-receive-only-rail-design.md`); the rail itself never holds write tokens.
- **Refusal-as-data** on cancellation events for rails with cancellation lifecycle (GH Sponsors, Liberapay, Stripe, Patreon, BMaC). Cancellation appends `RefusalEvent` to the canonical refusal log.

## Cross-link to receive-only modules

Every rail's source of truth:

- `shared/github_sponsors_receive_only_rail.py` — GH Sponsors
- `shared/stripe_payment_link_receive_only_rail.py` — Stripe Payment Link
- `shared/open_collective_receive_only_rail.py` — Open Collective
- `shared/liberapay_receive_only_rail.py` — Liberapay
- `shared/patreon_receive_only_rail.py` — Patreon
- `shared/ko_fi_receive_only_rail.py` — Ko-fi
- `shared/buy_me_a_coffee_receive_only_rail.py` — BMaC
- `shared/mercury_receive_only_rail.py` — Mercury
- `shared/modern_treasury_receive_only_rail.py` — Modern Treasury
- `shared/treasury_prime_receive_only_rail.py` — Treasury Prime

V5 publishers in `agents/publication_bus/<rail>_publisher.py`. FastAPI routes in `logos/api/routes/payment_rails.py`. Shared idempotency in `shared/_rail_idempotency.py`. Cross-cutting helpers in `agents/publication_bus/_rail_publisher_helpers.py`.

## Refused / vaporware

- **omg.lol Pay** — confirmed vaporware as of 2026-05-02 ([no shipped product](https://github.com/neatnik/omg.lol/issues)). Re-check annually per `project_omg_lol_mailhook_not_shipped`. Operator vault note: `~/Documents/Personal/30-areas/operator-projects/omg-lol-mailhook-not-shipped.md`.
- **Stripe ACH (direct, via Plaid)** — REJECTED per `docs/research/2026-05-03-wise-ach-receive-only-rail-design.md` § "Comparison to USD-only ACH alternatives". Doubles the security surface (HMAC + JWT-ES256). Use Stripe Payment Link for Stripe-mediated ACH instead.
- **Direct Debit (Wise active reception)** — REFUSED tier per the Wise design spike. Pull-payments are arguably outbound-initiated even though they collect funds.

## Suggested follow-ups

- `wise-receive-only-rail-implement` — implement the 11th rail per `docs/research/2026-05-03-wise-ach-receive-only-rail-design.md`.
- `omg-lol-pay-annual-recheck` — re-evaluate annually until shipped or formally deprecated.

**Resolved:**
- ~~`stripe-dahlia-decimal-migration`~~ — shipped as #2380. Receiver accepts integer minor units, integer-string, and decimal-string forms transparently.
- ~~`github-sponsors-graphql-migration`~~ — no migration needed; the deprecation only affects API-query code, which our receive-only rail forbids by design. Docstring updated to record this.

## Provenance

This doc captures the state of the monetization-rails family as of 2026-05-03 after PRs #2218 (license-router keystone) → #2375 (Stripe migration to shared idempotency). cc-task: `jr-publication-bus-monetization-rails-summary-doc` (WSJF 4, P3).
