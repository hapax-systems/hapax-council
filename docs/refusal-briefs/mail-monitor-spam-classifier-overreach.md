# Refusal Brief: Spam Classifier Overreach

**Slug:** `mail-monitor-refused-spam-classifier-overreach`
**Axiom tag:** `feedback_full_automation_or_no_engagement`, refusal-as-data substrate
**Refusal classification:** False-negative on refusal-feedback violates refusal-as-data preservation
**Status:** REFUSED — daemon-side spam classifier with reach into refusal-feedback (Category E) is forbidden.
**Date:** 2026-04-26
**Related cc-task:** `mail-monitor-refused-spam-classifier-overreach`
**Sibling refusal-briefs:**
  - `mail-monitor-aggregation-digest.md`
  - `mail-monitor-auto-reply.md`
  - `mail-monitor-inbox-panel.md`
  - `mail-monitor-out-of-label-read.md`
  - `mail-monitor-sentiment-analysis.md` (same false-classification-loses-refusal-data failure mode)

## What was refused

- Custom daemon-side spam classifier (e.g., scikit-learn /
  transformers / vaderSentiment running in mail_monitor) that
  classifies refusal-feedback (Category E) mail
- "Suspicious sender" auto-rejection of SUPPRESS-bearing mail
- ML-based spam reach into Category C (cold-contact replies) —
  same failure mode (false-negative loses SUPPRESS data)
- Bayesian / heuristic classifier that filters before category
  dispatch
- `agents/mail_monitor/spam_classifier.py`

## Why this is refused

### False-negative on refusal-feedback is a constitutional violation

The cc-task's refusal_reason is direct: "False-negative on
refusal-feedback (i.e. classifying a SUPPRESS-bearing reply as
spam) is a constitutional violation; refusal-as-data MUST never
be lost to spam classification."

A SUPPRESS reply is the operator-target's refusal of cold-contact —
it's first-class refusal-as-data. Mis-classifying it as spam
silently destroys that refusal event, breaking the substrate.

### Gmail's built-in spam filter is permitted

Gmail's server-side spam filter (which routes likely-spam to the
`SPAM` label, never to `INBOX`) operates BEFORE the mail-monitor
daemon sees mail. Per scope-control mechanism (label-scoped reads
per `mail-monitor-out-of-label-read`), the daemon never reads `SPAM`
label. So Gmail's spam filter is structurally separate from the
daemon and is permitted.

The refusal applies to **daemon-side** classifiers — anything inside
`agents/mail_monitor/` that re-classifies post-Gmail-spam-filter.

### Cumulative refusal lossiness with sentiment-analysis

`mail-monitor-refused-sentiment-analysis` (already shipped) refuses
sentiment classification because SUPPRESS-bearing mail often reads
as "hostile." This brief refuses spam classifier overreach for the
same structural reason: ML classifiers that don't understand the
constitutional substrate's value of SUPPRESS will mis-classify it.

The two refusals are siblings; together they preclude any
ML-classifier-shaped processing that could lose refusal data.

### Conservative dispatch instead

Per `feedback_no_operator_approval_waits` and the daemon's
"decide using best-available state" principle (per
`awareness-pending-review-inboxes`):

- Mail labelled `Hapax/Refusal-feedback` by server-side filters
  (per scope-control mechanism #1) is treated as Category E
- Body line-anchored regex (`^SUPPRESS\s*$`) is the canonical
  detection — deterministic, no ML
- Reply-thread verification (In-Reply-To matches outbound
  Message-ID) confirms it's a Hapax-conversation reply
- All three together produce a high-confidence Category E
  classification without ML

The dispatcher's confidence is structural (label + regex +
thread-verification), not learned.

## Daemon-tractable boundary

Authorized mail classification:
- **Server-side Gmail filters** (operator-curated, label-routed)
- **Body regex matching** (line-anchored deterministic patterns)
- **Reply-thread verification** (Message-ID ↔ chronicle lookup)
- **Suppression-list lookup** (boolean, not graded)

None of these is ML-based. None can mis-classify SUPPRESS as spam.

## Refused implementation

- NO `agents/mail_monitor/spam_classifier.py`
- NO `scikit-learn` / `transformers` / `vaderSentiment` imports for
  classification purposes in `agents/mail_monitor/`
- NO Bayesian / heuristic classifier branch in any category
  processor
- NO "suspicious sender" auto-rejection branch
- NO classifier confidence threshold gating Category E dispatch

## Lift conditions

This is a constitutional refusal grounded in the refusal-as-data
substrate principle. Lift requires retirement of:

- The substrate principle (refusal events as discrete first-class
  data points) — constitutional; not currently planned
- `feedback_full_automation_or_no_engagement`

## Cross-references

- cc-task vault note: `mail-monitor-refused-spam-classifier-overreach.md`
- Sibling failure-mode brief: `mail-monitor-sentiment-analysis.md`
  (same SUPPRESS-mis-classification risk)
- Authorized classification: server-side filters, regex, reply-
  verification — see `mail-monitor-001-design-spec` (offered)
- Source research: `docs/research/2026-04-25-mail-monitoring.md`
  §Anti-patterns
