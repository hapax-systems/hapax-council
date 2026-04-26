# Refusal Brief: Hapax Inbox Panel Surfacing Mail Headers/Bodies

**Slug:** `mail-monitor-refused-inbox-panel`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `feedback_no_operator_approval_waits`, `interpersonal_transparency`
**Refusal classification:** Anti-pattern — manufactured HITL pressure + privacy violation
**Status:** REFUSED — no Logos / waybar / weblog panel surfacing inbound mail headers or bodies.
**Date:** 2026-04-26
**Related cc-task:** `mail-monitor-refused-inbox-panel`
**Sibling refusal-briefs:**
  - `awareness-pending-review-inboxes.md` — substrate-level "pending review" anti-pattern
  - `mail-monitor-aggregation-digest.md` — mail-monitor aggregation refusal
  - `mail-monitor-auto-reply.md` — mail-monitor outbound refusal

## What was refused

- Logos panel ("Hapax Inbox") rendering inbound mail headers
- Logos panel rendering mail body excerpts
- Waybar "unread mail" widget showing count
- omg.lol weblog page rendering recent mail subjects
- Watch tile showing inbound mail headers
- Any operator-facing surface that holds mail items pending operator
  read/disposition

## Why this is refused

### Reading-as-task vs reading-as-counter

An "inbox panel" is structurally a **reading-as-task** surface: the
operator looks at it expecting to read items and dispose of them.
That's HITL by construction.

The mail-monitor's daemon discipline is **reading-as-counter**: the
classifier reads each message, dispatches to its category processor,
files into vault, increments awareness counters. The operator never
needs to read the mail — the constitutional substrate is structural,
not perceptual.

An inbox panel collapses these two modes into the operator's
reading-as-task default, undoing the daemon discipline.

### Manufactured HITL pressure

Per `awareness-pending-review-inboxes.md` (already shipped) and per
`feedback_no_operator_approval_waits` (operator memory directive):
"Sessions NEVER wait on operator approval; reverting > stalling."

A mail inbox panel is structurally a wait surface — the operator
sees mail items, may feel obligated to act, and the daemon's
behavior is implicitly conditioned on operator attention. That
violates the no-wait directive.

### Privacy / interpersonal_transparency

Per `interpersonal_transparency` axiom (weight 88): no persistent
state about non-operator persons without active consent contract.

Mail bodies and headers contain non-operator-person data:
- Sender's name + email + signature
- Body text mentioning third parties
- Reply-thread context with prior correspondence

Surfacing this data on a Logos panel would persist non-operator data
in the operator-facing UI surface — violating the consent gate even
when the data already exists in the operator's mailbox (the panel
re-presents and re-persists the data into a different surface that
isn't covered by the original consent).

### Vault filing IS the surface

Each category processor files mail into a vault location:
- Refusal-feedback (Category E) → `/dev/shm/hapax-refusals/log.jsonl`
- LICENSE-REQUEST (Category A) → `~/hapax-state/license-requests/`
- Operational (Category D) → chronicle
- SUPPRESS (Category C) → `contact-suppression-list.yaml`

The operator opens the relevant vault file when interested — that's
**operator-initiated read, not daemon-pushed read**. The vault is
the surface; an inbox panel would be redundant + violate
non-operator-data persistence.

## Daemon-tractable boundary

Authorized mail-monitor consumption surfaces:
- Per-event chronicle entries (no body content)
- awareness-state field updates (counts, not contents)
- refusal-brief log appends
- Vault filing per category disposition (operator-initiated read
  pattern)

None of these surface mail headers or bodies in a UI panel.

## Refused implementation

- NO `agents/operator_awareness/inbox_panel.py`
- NO Logos React component rendering mail items
- NO waybar widget showing mail counts
- NO REST endpoint exposing mail headers or bodies
- NO omg.lol weblog page rendering inbound mail subjects

## Lift conditions

This is a constitutional refusal grounded in three directives. Lift
requires retirement of any of:

- `feedback_full_automation_or_no_engagement`
- `feedback_no_operator_approval_waits`
- `interpersonal_transparency` axiom (constitutional; not currently
  planned)

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check the probe per its cadence policy.

## Cross-references

- cc-task vault note: `mail-monitor-refused-inbox-panel.md`
- Substrate sibling: `awareness-pending-review-inboxes.md`
- Mail-monitor siblings: `mail-monitor-aggregation-digest.md`,
  `mail-monitor-auto-reply.md`
- Authorized vault filing locations:
  `~/hapax-state/license-requests/`,
  `~/hapax-state/contact-suppression-list.yaml`,
  `/dev/shm/hapax-refusals/log.jsonl`
- Source research: `docs/research/2026-04-25-mail-monitoring.md`
  §Anti-patterns
