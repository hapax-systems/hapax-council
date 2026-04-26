# Refusal Brief: "Pending Review" Inbox Surfaces

**Slug:** `awareness-refused-pending-review-inboxes`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, `feedback_no_operator_approval_waits`, `feedback_hapax_authors_programmes`
**Refusal classification:** Anti-pattern #3 (drop-6 §10) — queues create obligation by holding work
**Status:** REFUSED — no "pending review" / "approval queue" / "needs decision" surfaces.
**Date:** 2026-04-26
**Related cc-task:** `awareness-refused-pending-review-inboxes`
**Sibling refusal-briefs:**
  - `awareness-acknowledge-affordances.md`
  - `awareness-additional-affordances.md`
  - `awareness-aggregation-api.md`
  - `awareness-public-marketing-dashboards.md`
  - `awareness-email-digest-with-links.md`
  - `awareness-ntfy-action-buttons.md`

## What was refused

- "Pending review" inbox UI on Logos, waybar, watch tile, weblog, or
  any operator-facing surface
- "Needs operator decision" queue endpoint (e.g.,
  `/api/awareness/pending`)
- "Approval needed" notification with a link back to a queue
- Any data-shape that holds work waiting for operator dispatch
- `agents/operator_awareness/pending_queue/` package
- Status frontmatter values like `pending_review` / `awaiting_decision`
  in cc-tasks (the cc-task lifecycle uses `offered` / `claimed` /
  `in_progress` / `done` only)

## Why this is refused

### Queues create obligation by holding work

A "pending review" inbox is not just a UI affordance — it's a
**data-shape that holds work**. The act of holding implies the act of
processing; the operator who sees the inbox sees an obligation
("there's work waiting for me"). That obligation is operator-physical
attention by construction.

Per `feedback_full_automation_or_no_engagement` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses
research / engagement surfaces not fully Hapax-automated. A queue
is a HITL pattern by definition.

### `feedback_no_operator_approval_waits` (operator memory directive)

Per the operator's memory entry: "Sessions NEVER wait on operator
approval." Reverting > stalling. A pending-review inbox is
structurally a wait surface — it embodies the anti-pattern at the
data layer.

### Hapax authors decisions; doesn't queue them

Per `feedback_hapax_authors_programmes`: programme authorship is
fully Hapax-generated. By extension: decisions made under those
programmes are Hapax-decided, not operator-queued. If a daemon
encounters work it cannot dispatch deterministically:

1. **Decide using best-available state** — act, even imperfectly
2. **Log decision + alternatives to chronicle** — the decision is
   recorded; the alternatives are recorded
3. **Operator-correction event re-trains** — if the decision was
   wrong, the operator's correction comes through the existing
   operator-correction channel (post-hoc adjustment, not pre-hoc
   approval)

This is the "revert > stall" pattern at the daemon level.

### Mis-classification check

If a daemon truly cannot decide, the work is **mis-classified**:

- It's either a **deterministic decision** that should be code, not
  LLM, not queue
- Or it's **REFUSED entirely** (the daemon has no constitutional
  basis to decide)

Neither case yields a queue. Queues conceal mis-classification.

## Daemon-tractable boundary

Authorized read-only awareness surfaces:
- `/api/awareness` — current state, ambient pulse, no queue semantics
- `/api/refusals` — refusal-event tail, raw rows
- waybar widget, Logos panel, omg.lol statuslog — all read-only

None of these embody "pending" semantics. They surface state, not
obligation.

## Refused implementation

- NO `/api/awareness/pending` endpoint
- NO Logos panel widget showing "items awaiting review"
- NO waybar widget that color-codes by "pending count"
- NO ntfy notification format that includes "review by Friday"
- NO cc-task vault frontmatter values like `pending_review`
- NO `agents/operator_awareness/pending_queue/` package
- NO database materialized view of "pending"-shaped state

## Lift conditions

This is a constitutional refusal grounded in three directives. Lift
requires retirement of any of:

- `feedback_full_automation_or_no_engagement`
- `feedback_no_operator_approval_waits`
- `feedback_hapax_authors_programmes`

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check the probe per its cadence policy.

## Cross-references

- cc-task vault note: `awareness-refused-pending-review-inboxes.md`
- Sibling refusals: see header
- Authorized awareness consumption pattern:
  `awareness-state-stream-canonical.md` (read-only ambient)
- Operator memory directives:
  `feedback_no_operator_approval_waits` (NO operator-approval waits)
- Source research: drop-6 §10 anti-pattern #3
