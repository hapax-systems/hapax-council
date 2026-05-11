# ytb-SS3 Long-Arc Narrative Continuity

Status: deferred design / blocked execution

Task: `~/Documents/Personal/20-projects/hapax-cc-tasks/active/ytb-SS3-long-arc-narrative-continuity.md`

Date: 2026-05-11

## Disposition

Keep ytb-SS3 open as a conditional successor to ytb-SS2. This document is the
focused continuity plan required while execution remains blocked.

No runtime code, public prompt integration, YouTube metadata update, caption
update, live description update, or other YouTube write is authorized by this
spec. The only shipped artifact is this deferred contract and its regression
pin.

## Gate State

`wsjf-008` is satisfied. The Tavily three-day audit task closed via PR #2211 and
removed the deferred public-growth gate as a blocker for later YouTube research
translation work.

`ytb-SS2` is not complete. As of 2026-05-11 it is active and claimed by
`cx-red`, with the first substantive-speech calibration cycle pending operator
scoring. ytb-SS3 cannot move into implementation until ytb-SS2 reaches its
published convergence criteria:

- at least three calibration cycles completed and logged;
- final-cycle rubric score at least 4/5;
- grounding coverage sustained at or above 0.7;
- novelty sustained above the selected baseline; and
- cycle summaries available in a form safe for downstream continuity work.

This spec therefore treats `SS2_DONE` as a required hard gate. A future SS3
implementation must fail closed whenever `SS2_DONE` is absent, stale, or
ambiguous.

## Prior Evidence

The plan is grounded in these existing contracts:

- ytb-SS2 research design: ytb-SS3 is explicitly out of scope until
  per-emission substantiveness has converged, and SS3 may consume only
  cycle-level summaries before private QM5 material is safe to summarize.
- SS1 autonomous narrative director: coherent emissions are in scope, but
  multi-session long-arc continuity is reserved for ytb-SS3.
- autonomous narration triad continuity ledger: durable continuity may be built
  from observations, assessments, intended outcomes, and witnessable follow-up;
  playback alone is not semantic satisfaction.
- livestream substrate registry and director substrate control-plane specs: SS2
  and SS3 remain blocked research/narrative substrates until audio, egress,
  quality feedback, and public-growth gates are open.

## Continuity State Boundaries

Allowed SS3 continuity state is bounded to operator-owned, system-owned, or
aggregate public-safe facts:

- programme id, programme run id, condition id, emission id, and archive id;
- autonomous narration triad ids, statuses, stale flags, and outcome summaries;
- ytb-SS2 cycle-level summaries, rubric totals, grounding coverage bands, and
  novelty bands;
- public-safe broadcast event ids and provenance references;
- aggregate chat or ambient statistics without viewer identity, handle history,
  quote history, or inferred personal facts;
- world-capability-surface references, capability outcome ids, substrate health,
  and egress/public-claim gate state; and
- operator-authored public episode themes or run-level narrative intents.

Forbidden SS3 continuity state is any durable record that would turn private or
non-operator material into narrative memory:

- no persistent state keyed by non-operator persons, viewers, chat handles,
  employers, clients, organizations, or inferred social relationships;
- no raw QM5 text, raw private feedback, raw vault note text, daily note text,
  sidechat text, or hidden operator annotation in the public continuity layer;
- no durable memory of consent-sensitive facts about non-operator persons;
- no claims that the system monitored, remembered, cared about, or followed up
  on a non-operator person unless that claim is backed by an explicit
  public-safe event contract and operator approval;
- no public narrative continuity derived from private sentinel phrases, private
  affordance names, credential hints, secret names, or internal control-plane
  labels; and
- no YouTube writes from continuity frames, including description edits,
  metadata patches, captions, cuepoints, live chat, community posts, or Shorts.

## Proposed Frame

The eventual implementation should build a `LongArcContinuityFrame` as an
ephemeral prompt input, not as a free-standing memory system. The frame is
derived at render time from already-audited sources and may be cached only under
the same privacy class as the most restrictive input.

```json
{
  "schema_version": 1,
  "frame_id": "long_arc_frame:dry_run:2026-05-11",
  "status": "blocked",
  "required_gate": "SS2_DONE",
  "public_claim_allowed": false,
  "youtube_writes_allowed": false,
  "sources": [
    "ytb-SS2.cycle_summary",
    "autonomous_narration.triad_continuity",
    "content_programme.run_summary",
    "livestream_substrate_registry.public_claim_permissions"
  ],
  "allowed_continuity": {
    "programme_refs": ["programme_id", "condition_id", "emission_id"],
    "triad_refs": ["triad_id", "status", "outcome_summary"],
    "ss2_refs": ["cycle_id", "rubric_total", "grounding_band", "novelty_band"]
  },
  "forbidden_continuity": [
    "non_operator_person_key",
    "chat_handle_history",
    "raw_qm5_text",
    "raw_private_feedback",
    "daily_note_text",
    "private_sentinel_phrase",
    "secret_or_credential_hint"
  ]
}
```

Prompt integration must render only short continuity hints from the frame, for
example: "Last public-safe run left open triad T with outcome O and SS2 summary
S." It must not render raw notes, raw scoring text, private sentinels, viewer
handles, or non-operator person identifiers.

## Implementation Preconditions

SS3 implementation may start only after all of these are true:

- ytb-SS2 is closed with evidence that its convergence criteria were met;
- the SS2 output exposed to SS3 is a redacted cycle-summary surface rather than
  raw QM5/private text;
- the livestream egress and public-claim gates are green for the target surface;
- audio and public narration safety gates are green for any live speech path;
- triad continuity stale and orphan rates are understood for the selected
  lookback window; and
- a dry-run frame builder can explain why each continuity hint is public-safe.

## Future Acceptance

A future implementation PR should include these checks:

- frame building fails closed without `SS2_DONE`;
- frame building rejects non-operator person keys, chat handles, raw QM5 text,
  private sentinel phrases, daily-note text, and credential-like strings;
- deterministic tests prove the same audited inputs produce the same continuity
  frame;
- prompt-render tests prove the public prompt receives only summaries and ids;
- no YouTube description, metadata, caption, cuepoint, live chat, community
  post, or Shorts writer can be reached from the continuity path; and
- operator-facing diagnostics explain whether the blocker is SS2, privacy,
  egress, audio, or stale evidence.

## Work Plan

1. SS2 completion intake: review the final SS2 cycle log, rubric outcome,
   grounding coverage, novelty signal, and any operator notes on acceptable
   speech quality.
2. Boundary freeze: confirm the allowed and forbidden continuity fields above
   still match the completed SS2 output surface.
3. Dry-run builder: add a private `LongArcContinuityFrame` builder that reads
   only cycle summaries, triad summaries, programme state, and public-claim
   gate evidence.
4. Prompt integration: add bounded continuity hints behind an explicit
   dry-run/private flag.
5. Live smoke: only after public gates are green, run a supervised emission
   proving continuity improves arc coherence without private leakage.

## Retirement Criteria

Retire ytb-SS3 instead of implementing it if ytb-SS2 fails to converge after
five completed calibration cycles, if the operator closes the autonomous public
narration lane, or if the only useful long-arc signal requires durable memory
about non-operator persons. In that case, keep the existing triad continuity
ledger as internal/private narration support and do not create a public long-arc
continuity layer.
