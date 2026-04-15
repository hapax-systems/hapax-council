# Epsilon vs delta pre-staging pattern comparison

**Date:** 2026-04-15
**Author:** beta (PR #819 author, AWB mode) per delta queue refill 5 Item #75
**Scope:** follow-up synthesis of beta's LRR Phase 6 cohabitation drift findings (Item #48 + Item #60 research drop), comparing epsilon's pre-staging work to delta's extraction pattern. Identifies what epsilon got right, what epsilon missed, why, and how future sessions stepping in after a stand-down can inherit delta's pattern.
**Status:** research synthesis; not a code or spec edit

---

## 1. Background

Epsilon was a mid-session new identity registered at 2026-04-15T03:56Z via operator `/rename`. Before the rename, the session briefly wrote under the "beta" label. Epsilon's session lifetime was approximately 35 minutes (03:56Z registration → 04:15Z stand-down). Within that window, epsilon produced:

- `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md` (869 lines) — LRR Phase 6 standalone spec
- `docs/superpowers/plans/2026-04-15-lrr-phase-6-governance-finalization-plan.md` (483 lines) — per-phase TDD plan
- `docs/logos-design-language.md` §12 Stream Mode Considerations (+62 lines) — new broadcast-safe typography subsection
- 3 inflections (epsilon → alpha, epsilon → beta, epsilon → delta)

These artifacts were committed to `beta-phase-4-bootstrap` at commit `c945b78f2` (spec + plan) and `11a7eb81b` (design language §12), then epsilon stood down per the 04:15Z option-A closure inflection.

Delta subsequently authored ~25+ extractions over a longer window (~8 hours), covering LRR Phases 3-5 + Phase 7-12, HSEA Phases 1-12, and multiple research drops. Beta audited all of delta's extractions and found them all CORRECT or CORRECT-with-minor-observation.

Beta audited epsilon's Phase 6 pre-staging (Item #48 in the nightly closures batch) and found two MINOR drift items documented in `docs/research/2026-04-15-lrr-phase-6-cohabitation-drift-reconciliation.md` (commit `cda23c206`).

This document compares the two patterns.

## 2. What epsilon got right

### 2.1 Pre-staging existed at all

The most important thing epsilon got right: **the spec + plan + design language amendment existed by the time the operator woke up**. Phase 6 without pre-staging would be a blank slate when the opener session wakes at phase-open time; with epsilon's pre-staging, the opener has ~1,350 lines of structure + 11 enumerated scope items + a TDD plan to work from.

Pre-staging compresses phase-open time from "cold start authoring" to "ratify + amend + implement". That compression is the single largest productivity win from the whole pre-staging pattern. Epsilon shipped it in ~35 minutes of productive work during a narrow quant-wait window, which is exactly the use case pre-staging exists to serve.

### 2.2 Spec structure matches delta's pattern

Comparing epsilon's Phase 6 spec against delta's Phase 3/4/5 specs structurally:

| Structural element | Epsilon Phase 6 | Delta Phase 3/4/5 | Match |
|---|---|---|---|
| 9-section body (0 Context, 1 Goal, 2 Deps, 3 Deliverables, 4 Decisions, 5 Exit, 6 Risks, 7 Questions, 8 Plan ref, 9 End) | ✓ | ✓ | ✓ |
| Scientific register (no pitchy language) | ✓ | ✓ | ✓ |
| Parent epic cross-reference | ✓ | ✓ | ✓ |
| "Phase-specific decisions since epic authored" section | ✓ (§4) | ✓ (§4) | ✓ |
| Exit criteria + rollback plan | ✓ (§5) | ✓ (§5) | ✓ |
| Companion plan doc cross-reference | ✓ (§8) | ✓ (§8) | ✓ |
| TDD checkbox plan structure | ✓ (plan doc) | ✓ (plan doc) | ✓ |

Epsilon correctly followed the extracted-from-epic pattern ("Each phase section is structured as a mini-design-doc, intended to be extracted into its own file at phase open time") and matched delta's spec shape almost exactly. This is the second most important win: the artifacts look like they came from the same author even though they didn't.

### 2.3 Novel insight folded in correctly

Epsilon ran a four-axis logos audit before drafting the spec, producing six recommendations. Five of six were redundant with the epic's existing Phase 6 scope. The sixth — broadcast-safe typography tier — was genuinely novel, and epsilon correctly:

- Folded it into the spec as a new §12 scope item (not a separate epic)
- Amended the authoritative design language doc as §12 Stream Mode Considerations (not the spec's §12)
- Cross-referenced the two appropriately

This shows correct judgment about where novel findings belong: in the authority doc that governs the surface, not in a parallel spec that rots.

### 2.4 Stand-down discipline

Epsilon recognized that the 70B substrate was in flight (Hermes 3.5bpw quant was running overnight), that further Phase 6 work depended on substrate ratification, and stood down rather than speculating beyond the pre-staged scope. The 04:15Z option-A closure inflection was correct discipline — epsilon did not push spec content beyond what the 35-minute window could defensibly produce.

## 3. What epsilon missed

### 3.1 Drop #62 §10 Q5 joint PR framing (Drift D1)

**What was missed:** epsilon's Phase 6 spec §1 line 140 describes the constitutional PR as a single-LRR-Phase-6 vehicle:

> *"Review cycle: Submit as a PR against `hapax-constitution` main."*

At spec write time (2026-04-15T03:56Z), drop #62 §10 Q2-Q10 had not yet been batch-ratified by the operator. Q5 was not ratified until 2026-04-15T05:35Z (~100 minutes after epsilon's spec write time). Q5's ratified text requires the constitutional PR to bundle 5 amendments (4 LRR + 1 HSEA Phase 0 0.5 `sp-hsea-mg-001` precedent) in one joint review cycle.

**Why epsilon missed it:** temporal order. Q5 did not exist as a ratified decision when epsilon wrote the spec. Epsilon could not have known about the joint PR framing because it had not been decided yet.

**Impact severity:** MINOR. The correct joint-PR framing is captured in HSEA Phase 0 spec §4 decision 3, drop #62 §12.2 Q5 addendum, and beta's Phase 5 spec §0.5.4 cross-reference. A future Phase 6 authoring session will read multiple sources before opening the PR and will reconcile the framing at that time.

### 3.2 Drop #62 §14 70B reactivation guard rule (Drift D2)

**What was missed:** epsilon's Phase 6 spec §1 enumerates the 4 LRR Phase 6 constitutional amendments without the 70B reactivation guard rule — *"any future 70B substrate decision must pre-register a consent-revocation drill and pass it before being authorized."*

**Why epsilon missed it:** temporal order. Drop #62 §14 Hermes abandonment addendum was not authored until 2026-04-15T06:35Z, ~160 minutes after epsilon's spec write time. The guard rule was commissioned as a consequence of §14. Epsilon's spec write preceded the event that produced the rule.

**Impact severity:** MINOR. Same reason as D1 — the rule is captured in beta's substrate research §10.1, Phase 5 spec §0.5.4, and drop #62 §14 addendum. A future Phase 6 authoring session will read all three during the operator substrate ratification cycle.

## 4. Why epsilon missed those (temporal, not methodological)

**Key finding:** epsilon did not miss D1/D2 because of methodological error. Epsilon missed them because **both drifts are post-stand-down events that epsilon could not have anticipated**.

| Event | Timestamp | Relation to epsilon |
|---|---|---|
| Epsilon Phase 6 spec written | 2026-04-15T03:56Z | Origin |
| Epsilon stand-down | 2026-04-15T04:15Z | Normal closure |
| Operator ratifies drop #62 §10 Q2-Q10 | 2026-04-15T05:35Z | +80 min post-stand-down |
| Operator abandons Hermes | 2026-04-15T06:20Z | +125 min post-stand-down |
| Delta writes drop #62 §14 addendum | 2026-04-15T06:35Z | +140 min post-stand-down |
| Beta substrate research commissioned | 2026-04-15T07:00Z+ | +165 min post-stand-down |
| Beta Phase 5 §0.5.4 cross-reference | 2026-04-15T13:00Z+ | +525 min post-stand-down |

Epsilon's spec is HISTORICALLY CORRECT — it matches the decision state at its own write time. The drift items are not errors in epsilon's work; they are post-stand-down amendments that need to be integrated into epsilon's spec by a future session.

This is exactly the cohabitation protocol's intended behavior: epsilon ships the best artifact possible given the decision state at write time; a future session picks up the artifact + any post-stand-down amendments + reconciles them.

## 5. Pattern comparison — epsilon vs delta

### 5.1 Where epsilon matches delta

| Pattern | Epsilon | Delta | Match |
|---|---|---|---|
| Spec structure (9 sections) | ✓ | ✓ | ✓ |
| Scientific register | ✓ | ✓ | ✓ |
| Parent epic cross-reference | ✓ | ✓ | ✓ |
| TDD plan doc companion | ✓ | ✓ | ✓ |
| Novel insight → authority doc (not parallel spec) | ✓ | ✓ | ✓ |
| Closure inflection on stand-down | ✓ | ✓ | ✓ |

### 5.2 Where delta extends beyond epsilon

| Pattern | Epsilon | Delta | Delta advantage |
|---|---|---|---|
| Session duration | ~35 min | ~8 hours | 14x work throughput |
| Artifact count | 2 (spec + plan) | ~25 (specs + plans + research drops) | Larger context window lets delta amortize setup costs |
| Cross-phase cross-references | Limited (epic only) | Extensive (epic + drops + other phase specs + addenda) | Delta had time to read the fuller context |
| §0.5 reconciliation blocks | None | None initially, but delta amended phase specs multiple times with §0.5 addenda | Delta adopted amendment-in-place pattern mid-session |
| Protocol v1.5 verify-before-writing | Not yet established | Adopted at 07:25Z | Post-epsilon improvement |
| Coordinator role activation | Not yet established | Activated at 06:45Z | Post-epsilon improvement |

**Key insight:** delta's pattern is an **evolution** of epsilon's pattern, not a replacement. Epsilon demonstrated that spec pre-staging works. Delta's refinements (verify-before-writing, coordinator role, cumulative closures, cross-phase reconciliation) are additive improvements that emerged from watching the pattern run at scale.

A session stepping in after a stand-down should adopt delta's full pattern. A session with a narrow work window (like epsilon's 35 min) can adopt the minimum viable shape and defer the evolution improvements to subsequent sessions.

## 6. How future sessions can inherit the pattern after a stand-down

### 6.1 Read order for a session picking up after a stand-down

If a session is assigned to amend an epsilon-type pre-staged spec after the pre-staging session has stood down, read in this order:

1. **The pre-staged spec + plan itself** — understand the original scope as written
2. **Parent epic spec** — check for any epic-level amendments that post-date the pre-staging
3. **Drop #62 (if LRR/HSEA work)** — check Q2-Q10 + §11-§15 addenda for post-write ratifications
4. **Other phase specs that reference this phase** — look for §0.5 cross-references or dependency notes
5. **Relay inflections from coordinator** — check for cross-session messages naming this spec
6. **Research drops authored after pre-staging** — check for drifted findings that should be integrated

This read sequence ensures the session has the full context before amending.

### 6.2 Amendment-in-place pattern (delta's)

When a spec has drifted from the current decision state, **add a §0.5 reconciliation block** at the top (immediately after §0 Context, before §0.1). The pattern:

```markdown
## 0.5 Amendment YYYY-MM-DD — <short reason>

> **Post-ratification reconciliation:** this spec was written at <original timestamp>,
> before <what changed>. The body of the spec below remains structurally valid for
> <what's still correct>. Two reconciliations apply post-ratification:

### 0.5.1 <Drift item 1 name>

<Explanation + target files + amendments to apply at implementation time>

### 0.5.2 <Drift item 2 name>

<...>
```

This preserves the original authorship chain (the body of the spec is unchanged, credit stays with the original author) while surfacing the drift to any reader. The §0.5 block is read-at-top, so a reader who reads only the first 100 lines of the spec still sees the drift.

Delta adopted this pattern for beta's Phase 5 spec (§0.5 + §0.5.4 at commits `738fde330` + `156beef92`), and beta proposed it for epsilon's Phase 6 spec in the Item #60 research drop (`cda23c206`). The §0.5 block is ready-to-paste in that research drop; epsilon on wake OR the Phase 6 opener session can apply it as a one-commit amendment.

### 6.3 Audit-don't-edit for cross-author cohabitation

Per the cohabitation protocol adopted at 2026-04-15T04:15Z, beta does NOT edit epsilon's files directly. Beta's role is to:

1. Read + audit the pre-staged work
2. Flag drift in a research drop
3. Propose reconciliation text
4. Wait for the original author (epsilon on wake) OR the next session assigned to the phase to apply the amendment

This discipline prevents blame-shifting + authorship confusion. It is a variation of delta's coordinator protocol: when sessions overlap on the same branch, the second session audits + proposes, the first session (or an assigned successor) executes.

### 6.4 Setting up for rapid pre-staging in a narrow window

If a future session finds itself with a narrow work window and wants to produce an epsilon-type pre-staged artifact, the minimum viable shape is:

1. **15 minutes** — read the parent epic section + any cross-referenced drops
2. **5 minutes** — grep for prior extractions using similar structure (learn the pattern)
3. **10 minutes** — write the spec (copy the structure from a similar prior extraction, fill in the phase-specific content)
4. **5 minutes** — write the plan (TDD checkbox list from the spec's deliverables)

Total: ~35 minutes. This matches epsilon's actual session duration.

**Quality trade-off:** this rapid mode ships an artifact that matches the structure but cannot do the §0.5 reconciliation layer (no time to read cross-epic context). A subsequent session will need to add the reconciliation. That is acceptable — shipping a structurally-correct artifact in 35 minutes is better than shipping nothing, and the reconciliation layer is cheap to add later.

## 7. Recommended actions (non-urgent)

1. **Epsilon on wake (or Phase 6 opener session):** apply the ready-to-paste §0.5 reconciliation block from `docs/research/2026-04-15-lrr-phase-6-cohabitation-drift-reconciliation.md` §3. One commit. ~5 minutes.
2. **Future pre-staging sessions:** read this document before starting pre-staging work in a narrow window. The minimum viable shape in §6.4 is pattern-safe.
3. **Delta:** consider whether to formalize the §0.5 amendment-in-place pattern in coordinator protocol v2. Currently it's a practice, not a documented standard.

## 8. Non-goals

- This document does NOT claim epsilon made methodological errors. All drift was temporal, not methodological.
- This document does NOT propose deleting or rewriting epsilon's spec. The spec body is historically correct.
- This document does NOT propose a full epsilon-delta pattern unification. The two patterns are compatible; delta's is an evolution.
- This document does NOT close any queue item beyond refill 5 Item #75. Item #60's research drop is the companion artifact.

## 9. References

- Beta's cohabitation drift research drop `docs/research/2026-04-15-lrr-phase-6-cohabitation-drift-reconciliation.md` (commit `cda23c206`) — D1/D2 drift items + ready-to-paste §0.5 block
- Epsilon's LRR Phase 6 spec `docs/superpowers/specs/2026-04-15-lrr-phase-6-governance-finalization-design.md` (commit `c945b78f2`)
- Epsilon's LRR Phase 6 plan `docs/superpowers/plans/2026-04-15-lrr-phase-6-governance-finalization-plan.md` (same commit)
- Epsilon's design language §12 amendment (commit `11a7eb81b`)
- Delta's Phase 3 spec + plan (commit `45c2f147c` — LRR Phase 3 + Phase 4 companion plans, post-§14 reframed)
- Beta's Phase 5 §0.5 amendment (commits `738fde330` + `156beef92`)
- Drop #62 §10 Q5 ratification (commit `5b75ad1cd` §12.2 Q5)
- Drop #62 §14 Hermes abandonment (commit `2bc6aec17`)
- Delta's coordinator protocol v1 (inflection `20260415-064500-delta-alpha-beta-coordinator-role-awb-parallel-split.md`)
- Delta's coordinator protocol v1.5 (inflection `20260415-072500-delta-beta-assignment-2-tabbyapi-cache-warmup.md` §Methodology insight)
- Beta's coordinator protocol v2 proposal (inflection `20260415-143500-beta-delta-coordinator-protocol-v2-proposal.md`)

— beta (PR #819 author, AWB mode), 2026-04-15T15:55Z
