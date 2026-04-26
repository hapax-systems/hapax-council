# Refusal Brief: Mail-Monitor Weekly Digest / Aggregation Summary

**Slug:** `mail-monitor-refused-aggregation-digest`
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Refusal classification:** Anti-pattern #5 (mail-monitor research §Anti-patterns) — aggregation obscures refusal-as-data
**Status:** REFUSED — no daemon produces weekly / daily / monthly digests of mail-monitor activity.
**Date:** 2026-04-26
**Related cc-task:** `mail-monitor-refused-aggregation-digest`
**Sibling refusal-briefs (substrate-level):**
  - `awareness-aggregation-api.md` — refusal-as-data preservation
    on the awareness substrate (same principle, awareness scope)
  - `awareness-additional-affordances.md` — scheduled-summary-cadence
    is one of four additional refused awareness affordances
  - `awareness-email-digest-with-links.md` — email-digest is the
    delivery-mechanism sibling

## What was refused

- Weekly digest email of mail-monitor SUPPRESS / VERIFY / OPERATIONAL
  events
- Daily digest variant of same
- Monthly summary aggregation
- "You got N SUPPRESSes this week" notification
- Aggregation API endpoint exposing counts of mail-monitor categories
- Static-site renderer producing aggregated mail-stats pages

## Why this is refused

### Refusal-as-data preservation

A SUPPRESS event is constitutional substrate — it's the operator-
target's refusal of cold-contact. Each SUPPRESS is a first-class
data point in the refusal-as-data substrate. A "you got 4 SUPPRESSes
this week" digest aggregates events into a number — losing the
individual refusal as a first-class entity.

The same anti-pattern is documented at the awareness-substrate level
in `awareness-aggregation-api.md`. This brief restates the principle
for the mail-monitor surface specifically because mail-monitor is a
distinct daemon with its own configuration / state surface; without
explicit per-surface refusal documentation, drift toward "just one
quick digest endpoint" is plausible during implementation.

### Awareness-state policy invariant

Per `awareness-state-stream-canonical` policy: "Refusal events are a
first-class field in the state model, NEVER aggregated, never
archived by operator action." Mail-monitor refusal events flow into
the same state-stream principle.

### Sibling delivery-mechanism refusal

`awareness-email-digest-with-links.md` (shipped #1590) refuses email
digests as a delivery medium for awareness substrate. This brief is
narrower: it refuses the **content shape** (aggregation) regardless
of delivery medium. Even if email-as-medium were permitted, the
aggregation-shape would still be refused.

## Daemon-tractable boundary

Authorized mail-monitor consumption surfaces:
- Raw refusal-event tail via `agents/refusal_brief/` writer (already
  shipped)
- Per-event chronicle entries (each SUPPRESS / VERIFY individuated)
- Per-event awareness-state field updates (when
  `awareness-state-stream-canonical` ships)

None of these embody aggregation. Each refusal event is rendered
individually in any consumer surface.

## Refused implementation

- NO `agents/mail_monitor/digest_renderer/` package
- NO `/api/mail-monitor/aggregate` endpoint
- NO scheduled job that produces weekly / daily / monthly summary
- NO email-digest sender for mail-monitor activity
- NO Grafana panel that pulls aggregated mail-monitor counts

## Lift conditions

This is a constitutional refusal grounded in
`feedback_full_automation_or_no_engagement` + refusal-as-data
substrate principle. Lift requires retirement of either.

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check the probe per its cadence policy.

## Cross-references

- cc-task vault note: `mail-monitor-refused-aggregation-digest.md`
- Substrate-level sibling: `awareness-aggregation-api.md`
- Delivery-mechanism sibling: `awareness-email-digest-with-links.md`
- Source research: `docs/research/2026-04-25-mail-monitoring.md`
  §Anti-patterns #5
