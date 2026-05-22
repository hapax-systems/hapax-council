---
type: research-artifact
task_id: 20260515-governance-repair-str-p1-payment-sot-reconciliation
title: "Patreon/refusal source-of-truth reconciliation"
authority_case: CASE-GOVERNANCE-REPAIR-20260515
created_at: 2026-05-22
kind: finding
---

# Finding: Patreon/Refusal Source-of-Truth Reconciliation

## Authoritative Source Declaration

**The refusal policy is authoritative for access decisions.**

Patreon membership state (received via webhook) is telemetry only. It has
no authorization role in the system. The refusal brief
(`docs/refusal-briefs/leverage-patreon.md`) explicitly prohibits:

- Access control based on patron status
- Tier-based perk delivery
- Per-supporter relationship stores
- Any obligation created by membership state

The receive-only rail (`shared/patreon_receive_only_rail.py`) normalizes
inbound webhooks to aggregate `PledgeEvent` records and dispatches them to
the publication bus as refusal-artifact telemetry. This is the only code
path that touches Patreon membership state.

## Conflict Analysis

The council finding that there is a "source-of-truth conflict" stems from
the fact that two systems carry membership-relevant state:

1. **Patreon's platform** — knows who is `active_patron` / `declined_patron` / `former_patron`
2. **Hapax's receive-only rail** — receives PledgeEvent webhooks with status fields

The potential conflict: if code were to read PledgeEvent.patron_status and
use it to grant or revoke access, which system would be authoritative?

## Finding: No Live Payment-Safety Bug

This is **not** a live payment-safety defect. The conflict is structural
(two systems hold membership state) but not operational (no code path uses
membership state for authorization). Specifically:

1. **No access is granted based on Patreon state.** Exhaustive search of
   `agents/`, `shared/`, `logos/`, `scripts/` confirms no import of
   PledgeEvent or patron_status is used in any conditional that controls
   access, feature gating, or content delivery.

2. **The receive-only rail discards authorization-relevant fields.**
   PledgeEvent contains only: event kind, amount (cents), currency, patron
   handle (vanity slug), and timestamp. It does NOT contain: tier ID, perk
   entitlements, or access tokens.

3. **The refusal brief explicitly prohibits access control.** The
   `Receive-Only Exception` section constrains the rail to: no SDK, no
   outbound, no PII, no supporter obligations/perks/tiers/access control.

4. **Existing CI guards enforce the boundary.** `tests/test_patreon_refusal_correspondence.py`
   verifies: no SDK imports, no outbound HTTP, no PII fields, no perk
   side effects, and cross-registry correspondence between refusal brief,
   surface registry, and code constants.

## Why This Is Not Automatically a Payment-Safety Bug

The council flagged this as potentially payment-safety-relevant because:
if Patreon reports a patron as `former_patron` (lapsed), and the system
somehow still grants access that was predicated on active patronage, that
would be a payment-safety bug (charging without delivering, or delivering
without charging).

However, the system never grants access predicated on patronage in the
first place. The refusal policy is constitutional (axiom-backed by
`single_user` + `feedback_full_automation_or_no_engagement`). There is
no state machine that transitions on patron_status. There is no "active
member" concept in the authorization layer.

## Reconciliation Action

The conflict is resolved by documentation clarity, not code change:

- **Authoritative for access decisions:** Refusal policy (refusal brief + CI guards)
- **Authoritative for telemetry/revenue reporting:** PledgeEvent via receive-only rail
- **No reconciliation code needed:** These two domains do not overlap

## Regression Guard

A new test (`tests/test_patreon_lapsed_no_access.py`) asserts that:
- No code path grants access based on PledgeEvent state
- The PledgeEvent model contains no access-granting fields
- No import of PledgeEvent exists in authorization-adjacent modules
