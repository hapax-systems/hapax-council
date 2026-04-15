# HSEA epic Hermes-drift sweep (post drop #62 §14 + §16)

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #141)
**Scope:** Sweep all HSEA phase spec + plan files on main for "Hermes" references. Classify each hit (archival / live-execution / incidental). Recommend remediation per class.
**Register:** scientific, neutral
**Complements:** LRR Phase 5 re-spec (PR #896 queue #138) + LRR Phase 3 Hermes cleanup (PR #897 queue #139). Together, closes the Hermes-abandonment drift debt across both epics.

## 1. Headline

**10 HSEA files contain Hermes references. 19 distinct hits total. Classification:**

| Class | Count | Remediation |
|---|---|---|
| **A — Archival / already-superseded** (author already cross-references §14) | 11 hits | **Keep as-is.** Preserves audit trail. Phase opener reads §14 + §16 + this audit and interprets correctly. |
| **B — Live-execution retargeting needed** (phase opener must pick new substrate target) | 6 hits | **Defer to phase opener.** All 6 are in HSEA Phase 4 narrator I4/I5 slots that were explicitly written to be retargeted at phase open time. With §16 ratified, the retarget target is clearer (substrate scenario 1+2) but the actual retargeting is phase-open work, not sweep-time work. |
| **C — Incidental / low-value** (mentions in passing; minimal impact) | 2 hits | **Keep as-is.** Rephrasing would create churn without semantic change. |

**Bottom line:** no HSEA file needs sweep-time remediation editing. The Hermes references that matter are either already marked superseded OR are deferred to phase-opener decisions. The audit trail is legible.

## 2. Method

```bash
grep -l "Hermes\|hermes" docs/superpowers/specs/*hsea* docs/superpowers/plans/*hsea*
for f in <hits>; do
  grep -c "Hermes\|hermes" "$f"  # count per file
  grep -n "Hermes\|hermes" "$f"  # contextual inspection
done
```

## 3. Per-file classification

### 3.1 `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` (1 hit)

- **L409 — Class B (live-execution retargeting)** — I4 narrator references `hermes_8b_pivot_narrator` target. Phase 4 opener must retarget to substrate scenario 1+2 execution narration per §16.

**Remediation:** defer to Phase 4 opener. No sweep-time edit needed; already acknowledged in the file's post-§14 notes.

### 3.2 `docs/superpowers/specs/2026-04-15-hsea-phase-10-reflexive-stack-design.md` (2 hits)

- **L20 — Class A (archival)** — "Per drop #62 §14, post-Hermes substrate quality gate applies to F-layers..." Already cross-references §14. **Keep as-is.** With §16, the "post-Hermes" framing now resolves to "substrate scenario 1+2 quality gate" but the phase opener can interpret correctly.
- **L107 — Class A (archival)** — "If Qwen3.5-9B remains the production substrate..." explicitly already accommodates the §16-ratified state (Qwen remains + OLMo adds). **Keep as-is.**

### 3.3 `docs/superpowers/specs/2026-04-15-hsea-phase-11-multi-agent-spawner-design.md` (1 hit)

- **L20 — Class A (archival)** — "Per drop #62 §14, post-Hermes substrate quality gate applies." Same pattern as Phase 10. **Keep as-is.**

### 3.4 `docs/superpowers/specs/2026-04-15-hsea-phase-12-long-tail-handoff-design.md` (1 hit)

- **L102 — Class C (incidental)** — "Substrate state — current production LLM, post-Hermes landscape resolution" in a context-capture checklist. **Keep as-is.** Minor language mention; rephrasing adds no value.

### 3.5 `docs/superpowers/specs/2026-04-15-hsea-phase-3-research-program-orchestration-design.md` (2 hits)

- **L130 — Class B (live-execution retargeting)** — "Watches for the 8B pivot event (condition transition from Qwen3.5-9B to Hermes 3 8B)." The 8B pivot is abandoned. Phase 3 opener retargets to the actual substrate transition per §16.
- **L131 — Class B (live-execution retargeting)** — `cond-phase-a-prime-hermes-8b-002` is a stale condition ID. Phase 3 opener will define the new condition ID for scenario 1+2 at opener time.

**Remediation:** defer to Phase 3 opener. No sweep-time edit needed.

### 3.6 `docs/superpowers/specs/2026-04-15-hsea-phase-4-code-drafting-cluster-design.md` (7 hits)

Most Hermes references land here because Phase 4 originally orchestrated the Hermes narrator work.

- **L9 — Class A (archival)** — Cross-epic authority: "drop #62 §14 (Hermes abandoned)". **Keep as-is.**
- **L12 — Class A (archival)** — "2026-04-15T07:20Z substrate reframing note: ... Phase 4 opener MUST read drop #62 §14 before starting I4/I5 work and retarget them to whichever substrate transition the operator ratifies." **Still valid with §16** — the retarget target is now clearer (substrate scenario 1+2). **Keep as-is.**
- **L34 — Class A (archival)** — "Per drop #62 §14 Hermes abandonment, UP-7 now means 'whichever substrate replaces Hermes gets ratified and shipped'." Already post-§14. **Keep as-is.**
- **L127 — Class B (live-execution retargeting)** — I4 `t2_6_hermes_8b_pivot_narrator` retarget language. Phase 4 opener retargets to substrate scenario 1+2 narration.
- **L129 — Class B (live-execution retargeting)** — I5 `t2_8_guardrail_narrator` retarget language. Same deal.
- **L185 — Class A (archival)** — "Drop #62 §14 Hermes abandonment supersedes I4 + I5 narration targets." Already post-§14.
- **L186 — Class A (archival)** — "Option A: retarget I4 to 'Hermes abandonment + production fixes' narration." Option A is the pre-§16 hedge language. Post-§16 ratification, the phase 4 opener now has an explicit target (substrate scenario 1+2 narration). Option A framing is historical but not wrong.

**Remediation:** Phase 4 opener reads this file + §14 + §16 + this audit. I4/I5 narrator retarget happens at phase open, not sweep time.

### 3.7 `docs/superpowers/specs/2026-04-15-hsea-phase-5-m-series-triad-design.md` (1 hit)

- **L24 — Class A (archival)** — "Phase 5 can ship whether or not the Hermes abandonment reframing has resolved." Already acknowledges substrate-independence. With §16, the resolution is complete. **Keep as-is.**

### 3.8 `docs/superpowers/plans/2026-04-15-hsea-phase-10-reflexive-stack-plan.md` (1 hit)

- Class A (archival) — post-§14 cross-reference. **Keep as-is.**

### 3.9 `docs/superpowers/plans/2026-04-15-hsea-phase-12-long-tail-handoff-plan.md` (1 hit)

- Class C (incidental). **Keep as-is.**

### 3.10 `docs/superpowers/plans/2026-04-15-hsea-phase-4-code-drafting-cluster-plan.md` (2 hits)

- Class B (live-execution retargeting) — I4/I5 narrator work. Deferred to Phase 4 opener.

## 4. Summary table

| File | Hits | A | B | C |
|---|---|---|---|---|
| hsea-epic-design.md | 1 | 0 | 1 | 0 |
| hsea-phase-3-research-program-orchestration-design.md | 2 | 0 | 2 | 0 |
| hsea-phase-4-code-drafting-cluster-design.md | 7 | 5 | 2 | 0 |
| hsea-phase-4-code-drafting-cluster-plan.md | 2 | 0 | 2 | 0 |
| hsea-phase-5-m-series-triad-design.md | 1 | 1 | 0 | 0 |
| hsea-phase-10-reflexive-stack-design.md | 2 | 2 | 0 | 0 |
| hsea-phase-10-reflexive-stack-plan.md | 1 | 1 | 0 | 0 |
| hsea-phase-11-multi-agent-spawner-design.md | 1 | 1 | 0 | 0 |
| hsea-phase-12-long-tail-handoff-design.md | 1 | 0 | 0 | 1 |
| hsea-phase-12-long-tail-handoff-plan.md | 1 | 0 | 0 | 1 |
| **Total** | **19** | **11** (58%) | **6** (32%) | **2** (11%) |

## 5. Why no sweep-time edits recommended

1. **Class A hits are already post-§14** — authors proactively cross-referenced §14 at pre-staging time. Adding §16 cross-references would be purely cosmetic; phase openers will read §16 via drop #62 regardless.
2. **Class B hits are phase-opener-owned** — they explicitly defer to phase open time for retargeting. The purpose of the Class B annotations is to flag "must retarget at phase open", not "must retarget at sweep time." Editing them at sweep time creates git churn without operational benefit.
3. **Class C hits are incidental** — "post-Hermes landscape resolution" in a checklist. Rephrasing to "substrate scenario 1+2 landscape" is semantically identical and cosmetically different.

**The real remediation is that phase openers read drop #62 §14 + §16 + this audit + the relevant phase spec** and interpret the Hermes references correctly. This sweep produces the audit doc; the phase openers produce the concrete retargeting.

## 6. Complementary work

- **LRR Phase 3 Hermes cleanup (queue #139, PR #897)** — added §0.5 amendment block to LRR Phase 3 spec + plan. Same non-invasive pattern (preserve body as historical, add amendment at top). That precedent applies to HSEA Phase 4 if a future session wants to add a similar §0.5 amendment block. Alpha did not add one here because the existing §"2026-04-15T07:20Z substrate reframing note" at L12 already fulfills that role.
- **LRR Phase 5 re-spec (queue #138, PR #896)** — new standalone spec at `docs/superpowers/specs/2026-04-15-lrr-phase-5-substrate-scenario-1-2-design.md`. Replaces the Hermes-framed LRR Phase 5 spec entirely. Phase 4 openers who were going to cross-reference the old LRR Phase 5 spec should cross-reference the new one.

## 7. Class B hit remediation (for phase openers)

For posterity, here's what Phase 3 + Phase 4 openers should do with the Class B hits when they open those phases:

### 7.1 HSEA Phase 3 L130-L131

- **Old text:** "Watches for the 8B pivot event (condition transition from Qwen3.5-9B to Hermes 3 8B)... `cond-phase-a-prime-hermes-8b-002`"
- **New text template:** "Watches for the substrate scenario 1+2 deployment event (new LiteLLM routes `local-research-sft`, `-dpo`, `-rlvr` go live, or new condition ID for Qwen+OLMo parallel deployment). The new condition ID is defined by LRR Phase 4 per drop #62 §16."

### 7.2 HSEA Phase 4 L127 (I4 narrator)

- **Old text:** "t2_6_hermes_8b_pivot_narrator — watches LRR UP-7a for TabbyAPI + LiteLLM + conversation_pipeline landings..."
- **New text template:** "I4 substrate_scenario_1_2_narrator — watches LRR Phase 5 execution for (a) exllamav3 0.0.29 upgrade + RIFTS empirical landing (scenario 1), (b) OLMo 3-7B × 3 variants deployed + LiteLLM `local-research-*` routes added (scenario 2), (c) claim-shaikh-sft-vs-dpo-vs-rlvr cycle 2 stub landing. Line cap 300 still applies; narration covers the arc from Hermes abandonment (§14) through §16 ratification through Phase 5 execution."

### 7.3 HSEA Phase 4 L129 (I5 narrator)

- **Old text:** "t2_8_guardrail_narrator — watches LRR UP-7a DEVIATION-037 landing..."
- **New text template:** "I5 guardrail_narrator — watches LRR Phase 5's DEVIATION-037 amendment (if any) OR any new DEVIATION that the substrate scenario 1+2 execution generates for frozen-file writes. If no substrate-gate DEVIATION materializes, I5 narrates any other substrate-related DEVIATION that ships during Phase 5 execution (e.g., consent-revocation drill failures, speech continuity test failures)."

These text templates are **recommendations, not commitments.** Phase openers adapt as needed.

## 8. Recommendations

### 8.1 Priority

**None.** The sweep finds zero live regressions that block execution. All Hermes references are either already post-§14 annotated or defer to phase-opener retargeting.

### 8.2 Optional future work

1. **Add §0.5 amendment block to HSEA Phase 4 spec** if a future session wants the same pattern as LRR Phase 3. Not urgent — the existing L12 "substrate reframing note" already serves the same function.
2. **Add a §16 cross-reference to the L12 substrate reframing note** to explicitly mention §16 resolution. Cosmetic; ~5 LOC edit.
3. **Update condition ID references** in HSEA Phase 3 L131 at phase open time using the template in §7.1.

None are blockers.

## 9. Closing

HSEA epic is clean. 19 Hermes hits across 10 files, 11 already post-§14 annotated, 6 are phase-opener deferrals (by design), 2 incidental. No sweep-time remediation editing required. Phase openers use this audit + drop #62 §14 + §16 + the relevant phase spec as the authoritative source.

Branch-only commit per queue item #141 acceptance criteria.

## 10. Cross-references

- **Drop #62 §14** (Hermes abandonment): `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §14
- **Drop #62 §16** (scenario 1+2 ratification): ibid §16 (PR #895, queue #137)
- **LRR Phase 5 re-spec** (queue #138, PR #896): `docs/superpowers/specs/2026-04-15-lrr-phase-5-substrate-scenario-1-2-design.md`
- **LRR Phase 3 Hermes cleanup** (queue #139, PR #897): amendment block pattern
- **Queue #140 PR #819 disposition**: complementary audit for PR-level disposition
- **HSEA coverage audit** (queue #108, PR #867): upstream inventory of HSEA phase docs

— alpha, 2026-04-15T20:25Z
