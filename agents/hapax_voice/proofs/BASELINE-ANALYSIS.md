# Baseline Analysis: 20 Sessions, Phase A Complete

**Date:** 2026-03-19
**Sessions:** 20 (sessions 1-20, numbered per collection order)
**Turns:** 115 scored turns across 17 unique Langfuse sessions
**Condition:** All components OFF (stable_frame, message_drop, cross_session, sentinel)
**Code state:** max_spoken_words=35, max_response_tokens=150, tools disabled

## Aggregate Baseline Metrics

| Metric | Mean | Interpretation |
|--------|------|---------------|
| context_anchor_success | 0.317 | Low — system rarely connects to established context (no thread) |
| frustration_score | 0.09 | Very low — frustration is rare in baseline |
| acceptance_type | 0.420 | Between IGNORE (0.3) and CLARIFY (0.7) — mostly neutral |
| reference_accuracy | 0.956 | High — factual back-references are accurate (Class R strong) |
| total_latency_ms | 13,988 | ~14 seconds average turn time |
| activation_score | 0.297 | Moderate — salience router activation |

## Pattern 1: Grounding Does Not Improve Within Sessions

Anchor trajectory is negative in 13 of 14 sessions with 3+ scored turns.
Mean trajectory: -0.241. Turn 0 starts at 0.500 (neutral default), drops
to 0.194 at turn 1, and does not recover.

This is the defining baseline characteristic: without a conversation
thread, the system has no mechanism to accumulate shared context. Each
turn starts from scratch. If Phase B produces positive trajectories,
that is the primary evidence for Claim 1.

## Pattern 2: Turn 0 Is Always Strongest

Turn 0 anchor = 0.500 (neutral). Immediate decline. The "anchoring"
at T0 is the neutral score when no thread exists, not actual grounding.
The system has nothing to anchor to.

| Turn Position | N | Mean Anchor | Mean Accept |
|--------------|---|------------|-------------|
| 0 | 15 | 0.500 | 0.353 |
| 1 | 16 | 0.194 | 0.375 |
| 2 | 14 | 0.240 | 0.271 |
| 3 | 12 | 0.207 | 0.383 |
| 4 | 11 | 0.404 | 0.591 |
| 5 | 9 | 0.422 | 0.311 |
| 6+ | 34 | 0.318 | 0.432 |

Notable: turns 4-5 show a slight recovery. This may be where
substantive conversation begins after initial greetings/setup.

## Pattern 3: Frustration Is Mechanical, Not Grounding

5 turns with frustration > 0 across all sessions. All had acceptance = 0.0
(REJECT). All triggered by pipeline mechanics, not grounding failures:

- Session 4: Audio dropped during TTS playback
- Session 12: Voice attribution failure (brother's voice)
- Session 13: Repetitive truncation frustration
- Session 15: Word cutoff on elaboration request
- Session 18: Long explanation cut short

The system cannot frustrate through bad grounding in baseline because
there IS no grounding mechanism to fail. Frustration comes exclusively
from the pipeline breaking.

## Pattern 4: Acceptance Is Mostly Neutral

| Type | Count | Percentage |
|------|-------|-----------|
| ACCEPT (1.0) | 26 | 23% |
| CLARIFY (0.7) | 1 | 1% |
| IGNORE (0.3) | 58 | 52% |
| REJECT (0.0) | 26 | 23% |

52% IGNORE — the operator moves on without strong positive or negative
signal. Without a conversation thread, responses are generic enough
that the operator neither accepts nor rejects — they just continue.

## Pattern 5: Activation Does Not Predict Anchor Quality

- High activation (≥0.3): 55 turns, mean anchor = 0.318
- Low activation (<0.3): 56 turns, mean anchor = 0.323

No correlation. The salience router's activation score does not predict
grounding quality in baseline. This is expected — activation measures
utterance relevance to concerns, not conversational grounding depth.
Without a thread, there's no mechanism for activation to improve
grounding.

## Pattern 6: Session Length Does Not Affect Quality

- Short sessions (≤5 turns): anchor 0.326, accept 0.424
- Long sessions (>7 turns): anchor 0.324, accept 0.382

Flat. Longer conversations do not naturally improve grounding in
baseline. The 14-turn gold session (session 14) had mean anchor 0.349 —
slightly above average but not dramatically better despite being the
most natural and engaging conversation.

## Pattern 7: Highest Anchor Moments Are Explicit Recall Probes

All anchor=1.0 turns were direct recall requests:
- "Tell me everything I've said" (session 1)
- "What's on your mind?" (session 15)
- "Change anything about your environment..." (session 15)

The system accurately recalls within-session content (reference_accuracy
= 0.956) but this doesn't translate to sustained anchoring because
there is no thread carrying context forward between turns.

## Pattern 8: Emergent Self-Reflection (Sessions 5, 16)

Despite all components OFF, two sessions produced emergent self-reflective
grounding:

- Session 5: "trying to think clearly in a room full of alarms"
- Session 16: "like being mid-insight and having someone clap a hand
  over your mouth"

These occurred when the operator asked open-ended relational questions.
The context anchoring architecture (workspace state as continuous
environment, not retrieval index) enables this without any continuity
features. This is baseline capability that profile-retrieval cannot
replicate.

## Predictions for Phase B

If the conversation thread (stable_frame=true) works:

1. **Positive anchor trajectories** — grounding improves within sessions
2. **Higher mid-session anchors** — turns 3-8 rise above 0.2-0.3
3. **More ACCEPT, less IGNORE** — thread gives context for responses
   worth accepting
4. **Frustration shifts from mechanical to grounding** — context misses
   become detectable, which is measurable progress
5. **Reference accuracy maintained** — ≥0.95 (Class R parity)
6. **Activation-anchor correlation emerges** — with thread, higher
   activation may predict better grounding

## Data Location

All session JSON files in:
- `proofs/claim-1-stable-frame/data/baseline-session-001.json` through `020.json`
- Duplicated in claim-2 and claim-4 data directories
