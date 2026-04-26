# Refusal Brief: Stripe Payment Link / Stripe Connect

**Slug:** `leverage-money-stripe-payment-link-REFUSED`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `single_user`
**Refusal classification:** Operator-physical KYC — not daemon-tractable
**Status:** REFUSED — no Stripe Connect onboarding, no Payment Link generation, no webhook integration.
**Date:** 2026-04-26
**Related cc-task:** `leverage-money-stripe-payment-link-REFUSED`
**CI guard:** `tests/test_forbidden_payment_imports.py`

## What was refused

- **Stripe Connect onboarding** — Connected Account creation
- **Stripe Payment Link generation** — receipt mechanism for LICENSE-REQUEST flows
- **Stripe webhook integration** — `agents/payment_processors/stripe.py` and any equivalent
- **Stripe Python SDK adoption** — `import stripe` blocked by CI guard

## Why this is refused

### Operator-physical KYC

Stripe Connect onboarding requires operator to:

1. Upload government ID (passport / state ID)
2. Verify bank-account ownership (micro-deposit verification or
   instant-verify via Plaid)
3. Accept 1099-K reporting threshold (US tax form for $600+ in
   payments)
4. Maintain ongoing KYB/KYC re-verification

Each of these is operator-physical. There is no daemon-tractable
pathway through Stripe's onboarding flow — KYC is the entire point
of Stripe's compliance posture, and bypassing it would be both
forbidden by Stripe and constitutionally incompatible with
single-operator + full-automation.

### Constitutional incompatibility

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T22:30Z): the operator refuses
research / monetization surfaces not fully Hapax-automated. Stripe
Connect implicitly assumes a Connected Account model that the
daemon cannot maintain on the operator's behalf without forging
KYC.

### Single-operator axiom

Stripe Connect's Connected Account model implicitly multi-tenant
(platform owners, marketplace sellers, etc.). Even for a single
Connected Account, the platform-side reporting + dispute-handling
flows assume a relationship between platform and seller — that
relationship is operator-physical.

## Daemon-tractable money paths (replacements)

The receipt mechanism for LICENSE-REQUEST is replaced by:

1. **`leverage-money-lightning-nostr-zaps`** — Alby / LNbits
   self-hosted Lightning node. No KYC; the operator runs the
   Lightning node on Hapax infrastructure. Receipt = invoice
   settlement event; verification = local LND query.
2. **`leverage-money-liberapay-recurring`** — Liberapay subscription.
   Sub-threshold (typically <$500/mo per donor) so 1099-K does not
   apply; no KYC required. Receipt = Liberapay weekly settlement
   webhook.

Both paths are FULL_AUTO and KYC-free; the daemon maintains them
without operator-physical intervention.

## CI guard

`tests/test_forbidden_payment_imports.py` scans `agents/`, `shared/`,
`scripts/`, `logos/` for any import of:

- `stripe` (Stripe Python SDK)
- `paypalrestsdk` / `paypal-checkout-serversdk` (anticipated; same
  KYC posture)
- `squareup` / `square` (anticipated; same KYC posture)

CI fails on any match.

## Refused implementation

- NO `agents/payment_processors/stripe.py` (or any flavor)
- NO Stripe Payment Link in operator-facing UIs
- NO Stripe webhook receivers in council or officium
- License-request auto-reply mentions Lightning + Liberapay only;
  Stripe is omitted from all monetization documentation
- The `pass` store will NOT carry Stripe API keys

## Lift conditions

This refusal is permanent. Any "delegated KYC service" / "Stripe-via-LLC"
reframing collapses single-operator + multi-tenant axioms — the
LLC-as-operator pattern requires multi-party legal coordination that
is itself operator-physical.

For the refusal-lifecycle watcher: the lift probe is constitutional
absence (probe path: `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`;
lift keyword: absence of `feedback_full_automation_or_no_engagement`).

## Cross-references

- cc-task vault note: `leverage-money-stripe-payment-link-REFUSED.md`
- Replacement cc-task: `leverage-money-lightning-nostr-zaps.md`
- Replacement cc-task: `leverage-money-liberapay-recurring.md`
- CI guard: `tests/test_forbidden_payment_imports.py`
- License-request mail routing: `leverage-money-license-request-mail-routing.md`
- Source research: `docs/research/2026-04-25-leverage-strategy.md`
  §Money paths #1b
