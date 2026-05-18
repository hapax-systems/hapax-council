# Refusal Brief: Patreon Sponsorship Model

**Slug:** `leverage-REFUSED-patreon-sponsorship`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `single_user`
**Runtime refusal tag:** `full_auto_or_nothing` (RefusalEvent.axiom field value)
**Refusal classification:** Subscriber-relationship management + tier-perks delivery — operator-physical
**Status:** REFUSED — no Patreon account, no `agents/payment_processors/patreon.py`.
**Date:** 2026-04-26
**Related cc-task:** `leverage-REFUSED-patreon-sponsorship`
**CI guard:** `tests/test_forbidden_payment_imports.py`

## What was refused

- Patreon account creation and management
- Patreon SDK adoption (`patreon` / `patreon_python`)
- Patron-Discord role-sync (compounds with `leverage-REFUSED-discord-community`)
- Tier-specific content delivery (early access, behind-the-paywall posts)
- Outbound Patreon API calls, CRM surfaces, per-supporter relationship stores

Note: receive-only inbound webhook telemetry is allowed under the
Receive-Only Exception below.

## Why this is refused

### Subscriber-relationship management is operator-physical

Patreon's value proposition is **tier-based perks**: early access,
exclusive content, Discord roles, name-on-credits, monthly-thank-you-
notes, etc. Each perk requires operator-physical maintenance:

- **Early access** — manual content-staging across tiers
- **Discord roles** — compounds with refused Discord community surface
- **Bonus content** — operator authorship + per-tier delivery
- **Cancellation comms** — operator response to "why did you cancel"
  follow-ups
- **Tier-upgrade promotion** — campaigns marketed to existing patrons

None of these is daemon-tractable. The "free tier" pattern is also
problematic — it implies a relationship surface (Patreon's messaging
inbox) that requires operator engagement.

### Constitutional incompatibility

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
research / monetization surfaces not fully Hapax-automated.

### Single-operator axiom (compounding refusal)

Patreon implicitly creates a community — patrons identify themselves
to each other, comment on posts, etc. The single-operator axiom
precludes operator-mediated community moderation; this is the same
constitutional barrier as `leverage-REFUSED-discord-community`.

## Daemon-tractable money paths (replacements)

The receipt mechanism is replaced by:

1. **`leverage-money-lightning-nostr-zaps`** — Alby/LNbits self-hosted.
   Anonymous (no patron-name expectations), no tiers, no perks.
   Receipt = Lightning invoice settlement.
2. **`leverage-money-liberapay-recurring`** — Liberapay sub-threshold
   recurring. No tiers, no perks; donation amounts are public but
   donor-side anonymous-by-default.

Both paths are FULL_AUTO; daemon maintains them without
operator-physical intervention.

## CI guard

`tests/test_forbidden_payment_imports.py` scans `agents/`, `shared/`,
`scripts/`, `logos/` for any import of:

- `patreon` (Patreon API SDK)
- `patreon_python` / `patreon-python` (community-maintained SDKs)

CI fails on any match.

## Receive-Only Exception

The full Patreon account, tiers, SDK, CRM, and community management
remain permanently refused. However, a **receive-only inbound webhook
rail** is explicitly allowed under the following constraints:

- NO `patreon` or `patreon_python` SDK imports (CI guard enforced)
- NO outbound HTTP calls to Patreon APIs
- NO PII persistence (email, full_name, billing address discarded)
- NO supporter obligations, perks, tiers, or access control
- NO per-supporter relationship store or CRM surface

The receive-only rail (`shared/patreon_receive_only_rail.py`) accepts
inbound webhook deliveries, normalizes them to aggregate
`PledgeEvent` records, and dispatches to the publication bus as
refusal-artifact telemetry. Pledge-delete events auto-link to the
canonical refusal log.

This exception applies to `patreon-receiver` in the publication bus
surface registry (classified `FULL_AUTO`) and is distinct from the
refused `patreon` entry in the support surface registry (classified
`REFUSAL_CONVERSION`).

This decision establishes precedent: other payment rails may implement
receive-only webhook receivers under the same no-SDK/no-outbound/no-PII
constraints without requiring a new refusal brief.

**Tests:** `tests/shared/test_patreon_receive_only_rail.py`,
`tests/test_payment_rails_routes.py`

## Refused implementation

- NO `agents/payment_processors/patreon.py` (or any flavor)
- NO Patreon account creation or management
- NO Patreon-to-Discord role-sync (also refused via discord)
- License-request auto-reply does NOT mention Patreon as a sponsorship
  channel

## Lift conditions

This refusal is permanent. Patreon's value proposition is structurally
incompatible with full-automation; no foreseeable revision changes
that. Lift requires either:
- Constitutional retirement of `feedback_full_automation_or_no_engagement`
  (probe path: `~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`)
- Single-operator axiom retirement

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check both probes per its cadence policy.

## Cross-references

- cc-task vault note: `leverage-REFUSED-patreon-sponsorship.md`
- Replacement cc-task: `leverage-money-lightning-nostr-zaps.md`
- Replacement cc-task: `leverage-money-liberapay-recurring.md`
- CI guard: `tests/test_forbidden_payment_imports.py`
- Compounding refusal: `leverage-REFUSED-discord-community`
- Source research: `docs/research/2026-04-25-leverage-strategy.md`
