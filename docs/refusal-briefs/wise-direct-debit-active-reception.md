# Refusal Brief — Wise Direct Debit (Active Reception)

**Slug:** `direct-debit-active-reception-refusal-brief`
**Status:** REFUSED — no daemon, no Direct Debit code is to be built.
**Surface:** `wise-direct-debit-active-reception`
**Date:** 2026-05-03
**Axiom tag:** `feedback_full_automation_or_no_engagement` + receive-only rail invariant
**Surface registry entry:** `wise-direct-debit-active-reception` (REFUSED)
**Provenance:** Wise design spike `docs/research/2026-05-03-wise-ach-receive-only-rail-design.md` § Open questions #5.

## What is the surface

Wise's 2026 platform update ships a Direct Debit API that lets platforms PULL funds directly from external bank accounts. Use case framing: "ideal for initiating collections where the operator controls the timing and amount, rather than waiting for the sender" (Wise Platform News, early 2026).

## Why it's REFUSED

The receive-only rail invariant defines "receive" as **the operator does not initiate money movement on third-party accounts**. The bright line is *who initiates the debit instruction*, not *where the money lands*.

A pull-payment is operator-initiated debit against a payer's account. Even though the funds land on the operator side (a receiving direction), the *initiation* is outbound — the rail issues an instruction to a third-party bank to debit a third-party account. That's an outbound monetary action with the same constitutional weight as a push payment.

If we treated "we collect, so it's incoming" as receive-only, every push payment would also qualify (every push to a payee "collects" by the payee). The invariant collapses.

## What the alternative is

Wise offers a passive reception path: virtual USD account details + the `account-details-payment#state-change` webhook fires when funds arrive at the operator's virtual account. The Wise design spike (#2327) recommends this as the Phase-0 implementation. The active Direct Debit path is REFUSED separately so the recommended path remains crisp.

## What this means in practice

- **No Direct Debit code lands.** The `WiseDirectDebitRefusedPublisher` exists to record the refusal as a first-class graph citizen, never to attempt publication.
- **Passive Wise reception is unaffected.** When `wise-receive-only-rail-implement` ships, it implements ONLY the passive virtual-account path.
- **Operator OAuth scopes** must continue to exclude `transfers:create`, `transfers:manage`, `balances:manage`, and any Direct Debit scope per the spike doc's § OAuth scope posture.

## Re-evaluation triggers

This refusal stands as long as:

1. The receive-only rail family preserves its no-outbound-monetary-action invariant.
2. Wise's Direct Debit product remains operator-initiated (vs. payer-initiated mandate-based collection — which would be a different shape and would deserve fresh evaluation).

If Wise launches a payer-initiated mandate-collection product where the payer pre-authorizes and the platform merely receives the resulting deposit notifications, that is a passive-reception shape and would not fall under this refusal. The spike already covers passive reception — the deposit-notification webhook is the canonical shape.

## Cross-references

- Spike: `docs/research/2026-05-03-wise-ach-receive-only-rail-design.md`
- Refused-publisher class: `agents.publication_bus.publisher_kit.refused.WiseDirectDebitRefusedPublisher`
- Surface registry entry: `agents/publication_bus/surface_registry.py` (`wise-direct-debit-active-reception` REFUSED)
- Sibling refusals using the same constitutional posture: `discord-webhook` (multi-user platform), `bandcamp-upload` (no public API), `discogs-submission` (ToS forbids).
