# Refusal Brief: Mail-Monitor Sentiment Analysis

**Slug:** `mail-monitor-refused-sentiment-analysis`
**Axiom tag:** `interpersonal_transparency`, `feedback_full_automation_or_no_engagement`
**Refusal classification:** Privacy + anti-anthropomorphization — scoring/coloring operator's correspondence
**Status:** REFUSED — no sentiment / tone / emotion classification on operator's mail.
**Date:** 2026-04-26
**Related cc-task:** `mail-monitor-refused-sentiment-analysis`
**Sibling refusal-briefs:**
  - `mail-monitor-aggregation-digest.md`
  - `mail-monitor-auto-reply.md`
  - `mail-monitor-inbox-panel.md`
  - `mail-monitor-out-of-label-read.md`

## What was refused

- Sentiment classification on inbound mail bodies (positive / negative
  / neutral / urgent / friendly / hostile / etc.)
- Tone analysis (formal / casual / aggressive / passive / etc.)
- Emotion detection (happy / sad / angry / fearful / etc.)
- "Sender mood" inference per correspondent over time
- Color-coding mail items by sentiment in any UI
- Sentiment-shaped routing (e.g., "if hostile → operator-attention
  flag")
- `agents/mail_monitor/sentiment.py` package
- Any `transformers` / `huggingface_hub` / `vaderSentiment` /
  `textblob` import in mail_monitor paths

## Why this is refused

### Privacy violation per `interpersonal_transparency`

Per `interpersonal_transparency` axiom (weight 88): no persistent
state about non-operator persons without active consent contract.

Sentiment classification produces **derived state about the
sender's emotional disposition**. That derived state is non-operator-
person data even if the underlying mail body is already in the
operator's mailbox. The classification creates a new persistent
signal (a sentiment label) that wasn't part of the original consent
gate.

The cc-task's refusal_reason names this directly: "Scoring or
coloring operator's mail correspondence is a privacy violation."

### Anti-anthropomorphization

Sentiment analysis treats mail correspondents as **emotional
subjects** rather than as senders in a routing graph. The model
outputs ("the sender feels frustrated") anthropomorphize the
structural input. That contradicts Hapax's anti-anthropomorphization
posture.

Hapax processes structural data; sentiment is a perceptual /
interpretive layer that the operator (a person) might apply when
reading mail, but the daemon doesn't apply it as part of its
routing discipline.

### Refusal-as-data lossiness

Sentiment classification can mis-classify SUPPRESS-bearing mail as
"hostile" (because saying NO often reads as negative-sentiment).
Routing on sentiment-derived signals can therefore lose
refusal-as-data — exactly the same failure mode as
`mail-monitor-refused-spam-classifier-overreach.md`. Sentiment is
the spam-classifier-overreach pattern with a different label.

### Full-automation envelope

Per `feedback_full_automation_or_no_engagement`: any operator-facing
sentiment-coloring affordance creates a perceptual surface that
demands operator interpretation. That violates the no-perceptual-
surface posture for awareness.

## Daemon-tractable boundary

Authorized mail-monitor classification:
- **Category dispatch** (A–F: Accept, Verify, Suppress, Operational,
  Refusal-feedback, Anti-pattern) — structural, not emotional
- **Suppression-list lookup** — boolean, not graded
- **Reply-to-Hapax-thread verification** — message-id matching, not
  sentiment

None of these involve sender-emotion inference.

## Refused implementation

- NO `agents/mail_monitor/sentiment.py`
- NO `agents/mail_monitor/tone_analyzer.py`
- NO `agents/mail_monitor/emotion_classifier.py`
- NO `transformers` / `huggingface_hub` / `vaderSentiment` /
  `textblob` / `nltk.sentiment` imports in `agents/mail_monitor/`
- NO sentiment-shaped routing branches in any category processor
- NO sentiment field in chronicle entries / awareness state /
  refusal-brief log

## Lift conditions

This is a constitutional refusal grounded in two directives. Lift
requires retirement of either:

- `interpersonal_transparency` axiom (constitutional)
- `feedback_full_automation_or_no_engagement`

The `refused-lifecycle-constitutional-watcher` daemon (when shipped)
will check the probe per its cadence policy.

## Cross-references

- cc-task vault note: `mail-monitor-refused-sentiment-analysis.md`
- Sibling refusals: see header
- Adjacent refusal: `mail-monitor-spam-classifier-overreach`
  (offered) — same false-classification-loses-refusal-as-data
  failure mode, narrower scope
- Source research: `docs/research/2026-04-25-mail-monitoring.md`
- Constitutional anchor: `interpersonal_transparency` axiom in
  `axioms/registry.yaml`
