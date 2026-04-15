# Deviation Record: DEVIATION-038

**Date:** 2026-04-14
**Phase at time of change:** baseline (LRR Phase 4 open pending — this DEVIATION is filed as part of the Phase 4 engineering bootstrap, before active Condition A collection begins)
**Author:** beta (LRR audit + Phase 4 bootstrap session)

## Files covered by this DEVIATION

This DEVIATION authorizes edits to the following frozen files (listed
verbatim for `check-frozen-files.py` substring-match coverage):

- `agents/hapax_daimonion/grounding_evaluator.py` — Inner Zone of
  `experiment-freeze-manifest.txt`. Edited to add `metadata` kwarg
  on `hapax_score(...)` calls so voice grounding DVs in Langfuse are
  attributable to the active research condition_id.
- `agents/hapax_daimonion/conversation_pipeline.py` — Middle Zone of
  `experiment-freeze-manifest.txt` AND listed in
  `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/condition.yaml::frozen_files`.
  Edited to (a) read the active research condition via the new
  `shared/research_marker.py` helper and (b) pass `condition_id`
  into the trace metadata dict on `hapax_trace(...)` + as a kwarg on
  every `hapax_score(...)` call that tags a grounding DV.
- `agents/hapax_daimonion/proofs/CYCLE-2-PREREGISTRATION.md` — Inner
  Zone (the entire `proofs/` subtree is frozen). Three surgical
  pre-filing amendments to §2.3, §3.2, §4.1 so the pre-registration
  document reflects the livestream-only data source before the OSF
  filing in Phase 4 scope item 4.

All three edits are bundled into a single DEVIATION because they are
components of one coherent change: LRR Phase 4 adopting the
livestream-only rule for experimental data collection. Splitting into
three DEVIATIONs would obscure that they are interdependent — the
research marker read is useless without the metadata kwargs that
consume it, and the pre-registration amendment describes the
implementation set that the other two effects realize.

## What Changed

Two discrete effects, bundled into one DEVIATION because they are both part of LRR Phase 4's engineering bootstrap and share a single conceptual root (adopting the livestream-only rule for experimental data collection):

### Effect 1 — Retire pre-LRR Cycle 2 Phase A dedicated-session data from Condition A sample counts

The ~431 grounding-act pairs from 2026-03-21, 2026-03-24, and 2026-03-25 voice sessions (captured before the LRR epic existed and before the research registry + research-marker infrastructure from Phase 1 was wired) are **excluded from the Condition A baseline sample**.

- **Data disposition:** preserved in Langfuse with their original scores. Not deleted. Not tagged with any condition_id (the tagging infrastructure did not exist when they were written).
- **Analytical disposition:** any analysis script filtering Langfuse scores by `metadata.condition_id = "cond-phase-a-baseline-qwen-001"` will naturally exclude them — the pre-LRR scores have no `condition_id` metadata field at all.
- **Sample count impact:** Condition A sample size starts at 0 at Phase 4 open and accumulates exclusively from livestream-running reactions + voice-grounding DVs tagged with `cond-phase-a-baseline-qwen-001`. The ~431 pre-LRR pairs do NOT contribute to the pre-registered minimum sample size.

### Effect 2 — Modify Inner Zone frozen files for condition_id metadata plumbing

Two files in the Inner Zone of `experiment-freeze-manifest.txt` are edited in follow-up commits on the `beta-phase-4-bootstrap` branch:

**`agents/hapax_daimonion/grounding_evaluator.py`** — every `hapax_score(...)` call for a grounding DV (`turn_pair_coherence`, `context_anchor_success`, `activation_score`, `acceptance_type`, `sentinel_retrieval`) gains a `metadata={"condition_id": <active>, ...}` kwarg. The active condition is read from the new `shared/research_marker.py` helper (5-second cache on the monotonic clock, fail-safe `None` on any filesystem or JSON error).

- **Change shape:** pure additive metadata on Langfuse score-writing calls. The computed score values are unchanged. The set of scores written per utterance is unchanged. The ordering is unchanged.
- **Score values:** unchanged. No new computation paths, no new thresholds, no new weighting.
- **Side effects on behavior:** none. The metadata does not feed back into any decision.

**`agents/hapax_daimonion/proofs/CYCLE-2-PREREGISTRATION.md`** — three surgical edits to pre-filing text:

- **§3.2 Setting:** clarify that data is collected during livestream runs in research mode, not dedicated voice-AI-user sessions.
- **§2.3 Phase Definitions:** reference DEVIATION-038 for the pre-LRR pilot exclusion and state that Condition A is accumulated from livestream context only.
- **§4.1 Implementation:** extend the implementation-file list to include `director_loop.py`, `shared/research_marker.py`, and `/dev/shm/hapax-compositor/research-marker.json` alongside the existing `conversation_pipeline.py` / `grounding_ledger.py` / `persona.py` / `conversational_policy.py`.

- **Change shape:** pre-filing clarifications to an unfiled document. The experimental design, claim, hypothesis, DVs, BEST analysis methodology, and phase structure are **unchanged**.
- **OSF filing:** happens in scope item 4 AFTER this amendment. Operator sign-off required before filing (OSF filing is one-way).

## Why

**Operator directive 2026-04-14.** The LRR epic name is "LIVESTREAM RESEARCH READY" and its end-state triad centers on Hapax running 24/7 on livestream with continual research programming. The old Phase 4 spec carried forward the pre-LRR Cycle 2 Phase A dedicated-session paradigm, which the LRR epic was supposed to retire. Operator issued an explicit correction: every grounding experiment observation is collected exclusively while the livestream is running in research mode with an active condition. Dedicated 1-on-1 voice sessions are not a data source for any phase of the LRR epic.

**Why the two effects are bundled into one DEVIATION:**

They share a single root (livestream-only rule adoption), both are surfaced by the same Phase 4 scope item (item 1 in the Phase 4 re-spec), and bundling avoids filing two separate DEVIATIONs for changes whose impact on experimental validity must be assessed together. Condition A's sample constitution depends simultaneously on which data is counted (effect 1) and whether the data has the condition_id tag that makes it countable (effect 2).

**Why the metadata plumbing edit is a frozen-file touch:**

`grounding_evaluator.py` is in the Inner Zone of `experiment-freeze-manifest.txt` because it computes the pre-registered dependent variables. Any change to what the DV computations produce would threaten experimental validity. This change does NOT alter what the DVs produce — it only adds a `metadata={"condition_id": ...}` kwarg to the `hapax_score(...)` calls that write the DV values to Langfuse. The score values themselves are bit-identical to pre-change. The purpose is analytical attribution: allow downstream queries to filter Langfuse scores by research condition so Condition A and Condition A' (post Phase 5 Hermes 3 swap) can be compared cleanly.

**Why `CYCLE-2-PREREGISTRATION.md` needs amendment:**

The pre-registration document is in the Inner Zone (the `proofs/` subtree of `hapax_daimonion`). Its current text references a "daily voice AI user" setting and implementation files that predate the livestream-only rule. Filing it as-is to OSF would misrepresent the actual data collection context. The three surgical edits (§3.2 Setting, §2.3 Phase Definitions, §4.1 Implementation) bring the document into alignment with the livestream-only rule before operator-side OSF filing. The experimental design itself — claim, hypothesis, DVs, analysis methodology, phase structure — is unchanged.

## Impact on Experiment Validity

**Assessment: MINIMAL.**

The pre-LRR dedicated-session data exclusion is not a threat to validity because the data in question was collected before the LRR epic existed, before the research registry was built, and before Phase 4's condition_id tagging infrastructure was wired. It was never formally part of a pre-registered condition — it was pilot-quality data from Cycle 2 Phase A under the old dedicated-session paradigm. The claim of the experiment (`claim-shaikh-sft-vs-dpo`) depends on comparing Condition A (Qwen3.5-9B) vs Condition A' (Hermes 3 70B) under a livestream-running research mode, which is the new Phase 4 specification. Excluding pilot data that does not meet the new specification is an inclusion-criterion refinement, not a data tampering event.

The metadata plumbing edit to `grounding_evaluator.py` is a pure analytical attribution change. The DV values are unchanged. No decision logic sees the new metadata. The sole consumer of the new metadata is post-hoc analysis scripts that filter Langfuse scores by `metadata.condition_id` to distinguish Condition A from Condition A'. Without the metadata, those scripts would have no way to separate the two conditions after the Phase 5 swap — which would make the core experiment analytically unreachable. The edit is therefore not a threat to validity; it is a prerequisite for the pre-registered analysis to function.

The `CYCLE-2-PREREGISTRATION.md` amendment is a pre-filing clarification. The document has never been filed to OSF. Its current text is a working draft. Amending it before filing is the normal workflow for pre-registration authoring and does not constitute a post-hoc change to a filed registration. Operator sign-off is required before the actual OSF filing in Phase 4 scope item 4.

## Mitigation

**Preservation of the pre-LRR pilot data:** the ~431 pairs remain in Langfuse with their original scores, authors, timestamps, and content. Langfuse retention applies. Any future analysis that wants to compare the pre-LRR pilot data against the post-LRR baseline can retrieve it via the time-range filter (2026-03-21 to 2026-03-25). The exclusion from Condition A sample counts is a labeling choice at analysis time, not a data deletion.

**Metadata edit is behaviorally neutral:** `grounding_evaluator.py` computes DV values identically before and after this DEVIATION. The change adds a kwarg to `hapax_score(...)` that carries the active research condition_id (or is absent when no condition is active). Tests pin the pre-change score computations; they continue to pass after the edit. A regression would be visible as a Langfuse score mismatch, not a metadata shape change.

**Pre-registration amendment is pre-filing:** the amendment lands in the worktree before Phase 4 scope item 4 files the document to OSF. Operator sign-off on the amended text is required before filing. If any amendment is later judged problematic, the filing can be paused indefinitely — the DEVIATION only authorizes the engineering bootstrap's code + doc touches, not the OSF filing itself.

**Cross-reference:** beta's pass-5 audit artifact
`~/.cache/hapax/relay/context/2026-04-14-beta-lrr-audit-pass-5.md` and the
Phase 4 re-spec alpha drop
`~/.cache/hapax/relay/context/2026-04-14-beta-lrr-phase-4-respec-livestream-only.md`
both document the reasoning for the livestream-only rule and the
engineering gap that scope item 1 + this DEVIATION close. Any future
session reviewing this DEVIATION can read those artifacts to reconstruct
the full context.

**Registers under:** claim `claim-shaikh-sft-vs-dpo`.
