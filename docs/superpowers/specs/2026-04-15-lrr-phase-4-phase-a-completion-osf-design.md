# LRR Phase 4 — Phase A Completion + OSF Pre-Registration — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction; LRR execution remains alpha/beta workstream)
**Status:** DRAFT pre-staging — time-gated phase (operator session cadence dominates)
**Epic reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 4
**Plan reference:** `docs/superpowers/plans/2026-04-15-lrr-phase-4-phase-a-completion-osf-plan.md`
**Branch target:** `feat/lrr-phase-4-phase-a-completion`
**Cross-epic authority:** drop #62 §5 UP-6 + §14 (substrate reframing — Hermes abandoned) + §16 (scenario 1 + scenario 2 ratification) + §17 (scenario 2 Option C parallel-backend pivot)
**Unified phase mapping:** **UP-6 Phase A completion + OSF pre-reg** (drop #62 §5); depends on UP-1 + UP-5

> **2026-04-15T08:10Z note:** the epic spec's "control arm lockdown" framing assumed Condition A' would be a Hermes 3 substrate swap. Per drop #62 §14, Condition A' target is now TBD per operator substrate ratification. Phase 4 is UNAFFECTED by §14 in its Phase A COLLECTION scope — Condition A is still Qwen3.5-9B and the collection lockdown is still valid. Only the downstream "what Condition A' is" is superseded. Phase 4 opener should NOT modify the Condition A lockdown based on §14; the lockdown is the control arm and is substrate-independent on the A side.

> **2026-04-15T22:45Z update (queue #177 alignment patch):** drop #62 §16 subsequently ratified the post-§14 substrate arrangement — scenario 1 is Qwen3.5-9B + RIFTS baseline; scenario 2 is OLMo 3-7B × {SFT, DPO, RLVR} as three parallel arms. §17 then pivoted scenario 2 execution to Option C (parallel TabbyAPI :5001 backend) after beta's #209 report that exllamav3 0.0.29 is incompatible with TabbyAPI's pinned cu12 stack. Phase 4 scope is UNCHANGED — Condition A is still Qwen3.5-9B and the collection lockdown still holds — but the "Condition A' target is TBD" phrasing in §1 below is no longer accurate. Condition A' is now the scenario 2 OLMo parallel arms that Phase 5 executes. No structural changes to Phase 4 deliverables or plan; framing-only update. See also queue #171 for the v0.0.28 intermediate-version assessment that may retire Option C in favor of scenario 2 Option A.

---

## 1. Phase goal

Complete the **Condition A control arm data collection** under Qwen3.5-9B with experiment-freeze active. File the **OSF pre-registration** for `claim-shaikh-sft-vs-dpo`. Lock Condition A data integrity with sha256 checksums + Qdrant snapshot. Establish the ready-to-swap state.

**Theoretical grounding (post-§14):** under Option B (archive as research instrument), Condition A must have a real sample size before any swap. The Hermes 3 plan recommendation "Complete current Phase A baseline with Qwen3.5-9B, then introduce Condition A' via deviation record" remains structurally valid even though the specific Condition A' target (Hermes 3) is now TBD. Phase 4 is the "Condition A sample size + data integrity + OSF pre-reg" phase; Phase 5 will be whatever substrate ends up being the comparison arm.

**What this phase is:** voice grounding sessions counted toward ≥10; mid-collection integrity checks; OSF project creation + pre-reg upload; data checksums + Qdrant snapshot; ORCID + Zenodo + GitHub Pages setup (infrastructure plumbing); Condition A `collection_halt_at` marker.

**What this phase is NOT:** does not modify Condition A itself (frozen); does not open Condition A' (Phase 5); does not run any statistical analysis (Phase 1 item 7 stats.py + Phase 10 per-condition Prometheus do analysis).

**Sprint 0 G3 blocker handling:** Phase 4 opens with a G3 resolution step. Two options per epic:
- **Option 1 (resolve inside LRR, DEFAULT):** identify G3 definition, execute pending Claim 5 correlation analysis (Measure 7.2), close the gate, resume Phase A collection
- **Option 2 (resolve outside LRR):** document G3 as `blocked_on: sprint-0-g3` in condition registry; operator or separate Bayesian session resolves
- Default: Option 1.

---

## 2. Dependencies + preconditions

1. **LRR UP-0 + UP-1 closed** (research registry + condition_id plumbing live)
2. **LRR UP-5 (Phase 3 hardware validation, post-§14 reframed) closed** — hardware envelope stable for Qwen3.5-9B production
3. **Sprint 0 G3 gate resolved** (per Option 1 or 2 above)
4. **Frozen-file pre-commit enforcement running** (LRR Phase 1 item 4) — so that any mid-collection edit to frozen files is blocked
5. **Operator session cadence** — Phase 4 is time-gated; 10+ voice grounding sessions required
6. **OSF account** accessible (operator action for pre-reg filing)

---

## 3. Deliverables (7 items)

### 3.1 Target sample size
- ≥10 voice grounding sessions under Qwen3.5-9B with `cond-phase-a-baseline-qwen-001` tag (per pre-registration minimum)
- Actual target operator-determined; 10 is the floor
- **Target files:** none (session count is the deliverable)

### 3.2 Daily data collection cadence
- Operator runs voice grounding sessions as scheduled; each writes reactions tagged with condition_id per LRR Phase 1 item 2 wiring
- Reactions persist to Qdrant + JSONL + Langfuse
- Frozen-file hook prevents accidental mid-collection edits
- **Target files:** no new files; existing infrastructure

### 3.3 Mid-collection integrity checks
- Every N sessions (default N=3):
  - Verify `research-registry current` returns `cond-phase-a-baseline-qwen-001`
  - Verify no frozen-file diffs applied
  - Verify `stream-reactions` Qdrant point count is growing
  - Verify Langfuse traces are tagged
- Shell script: `scripts/lrr-phase-4-integrity-check.sh` (~60 LOC)
- Cron or systemd timer (every 24h) for automated check
- **Target files:** `scripts/lrr-phase-4-integrity-check.sh`, `systemd/user/hapax-lrr-phase-4-integrity.timer`

### 3.4 OSF project creation + pre-registration filing
- **Operator action (not code):**
  - Create OSF project for `claim-shaikh-sft-vs-dpo`
  - Upload pre-registration document (already written per `RESEARCH-STATE.md`)
  - Generate OSF pre-reg URL
- **Code action:**
  - Update `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/condition.yaml` with `osf_project_id` + `pre_registration.url` + `pre_registration.filed: true`
  - Use LRR Phase 1 item 8 CLI: `research-registry.py set-osf <cond> <project_id>` + `research-registry.py file-prereg <cond> <url>`
- **Target files:** condition.yaml (session-local; not committed)

### 3.5 ORCID + Zenodo + GitHub Pages setup
- Research infrastructure plumbing, not gating Phase 5 swap, but authored during Phase 4 idle time (voice sessions run sequentially; engineering work is light between sessions)
- **Deliverables:**
  - ORCID ID linked to operator's research profile
  - Zenodo account with DOI reservation for `claim-shaikh-sft-vs-dpo` publication
  - GitHub Pages site at `ryanklee.github.io/hapax-research/` (or equivalent) publishing research drops + condition state
- **Target files:** `docs/research/protocols/orcid-zenodo-setup.md` (~100 lines), GitHub Pages config in a new `gh-pages/` branch or `docs/` setup
- **Size:** ~200 LOC

### 3.6 Data integrity lock
- At Phase 4 completion:
  - Compute sha256 of each Condition A JSONL file (reactor logs)
  - Record in `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/data-checksums.txt`
  - Take a Qdrant snapshot (qdrant CLI export) for Condition A points
  - Store at `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/qdrant-snapshot.tgz`
- **Target files:** `scripts/lrr-phase-4-integrity-lock.sh` (~80 LOC; computes checksums + invokes qdrant export), data files under research-registry
- **Size:** ~80 LOC

### 3.7 Condition A `collection_halt_at` marker
- Write a `collection_halt_at: <timestamp>` field to Condition A's condition.yaml — NOT a condition close (conditions never close per P-3), but a marker that data collection for Condition A has halted in favor of Condition A' (whatever substrate ends up being that arm per §14)
- **CLI shipped:** use `research-registry.py set-collection-halt <cond> <ts>` (or `now` for wall-clock). Shipped in **PR #845** (commit `c3d2326d9`) during delta's nightly queue refill item #44 cycle. Accepts ISO-8601 UTC timestamps (normalized to `Z` suffix), offset-aware timestamps, or the literal `now`. Refuses naive timestamps. `--force` required to overwrite an existing non-null marker. 8 unit tests in `tests/test_research_registry.py::TestSetCollectionHaltSubcommand`.
- **Target files at Phase 4 open:** condition.yaml update only. The CLI is pre-existing — no extension needed.

---

## 4. Phase-specific decisions

1. **Phase 4 is the ONLY phase where operator action dominates** — voice grounding sessions require operator's physical presence. Engineering work is minimal during collection windows.

2. **Condition A collection is SUBSTRATE-INDEPENDENT.** The fact that Condition A' target is now TBD per §14 does NOT affect Phase 4 — Phase 4 completes Condition A collection regardless of what swap will happen next.

3. **G3 resolution is Option 1 by default** — handle inside LRR unless surface methodology decisions push to Option 2.

4. **OSF pre-reg filing is a ONE-WAY step** — once filed, the claim is public. Operator sign-off required before filing.

5. **ORCID + Zenodo + GitHub Pages are "fill idle time"** — low priority, authored during voice session gaps, not blocking Phase 5.

---

## 5. Exit criteria

1. ≥10 voice grounding sessions completed with Qwen3.5-9B + Condition A tag
2. All sessions have reactions in stream-reactions Qdrant + JSONL + Langfuse with `condition_id=cond-phase-a-baseline-qwen-001`
3. No frozen-file deviations filed during Condition A collection (or any deviations explicitly recorded as such in `research/protocols/deviations/`)
4. OSF project exists; pre-reg uploaded; URL recorded in condition registry
5. Data checksums captured; Qdrant snapshot created
6. `research-registry current` still `cond-phase-a-baseline-qwen-001` with `collection_halt_at: <ts>` marked
7. `RESEARCH-STATE.md` updated with Phase A complete status
8. `lrr-state.yaml::phase_statuses[4].status == closed`
9. Phase 4 handoff doc written

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Operator session cadence slower than 10/week | Time-gated phase; allow flex; no fixed deadline |
| Mid-collection frozen-file edit invalidates Condition A | Phase 1 item 4 pre-commit hook running; verify before each session |
| OSF pre-reg filing is irreversible | Operator sign-off before filing |
| Cycle 2 `continuity-v2` config differs from canonical Condition A substrate | Verify at phase open via `RESEARCH-STATE.md` cross-reference |
| G3 resolution requires non-LRR work | Fall back to Option 2; document blocker |

---

## 7. Open questions

1. Exact target sample size above the 10 floor — operator-determined
2. Session cadence (daily? weekly?) — operator-determined
3. OSF pre-reg filing date — operator-determined after ≥10 sessions
4. ORCID/Zenodo/GitHub Pages priority — may ship after Phase 5 if Phase 4 closes quickly

---

## 8. Plan

`docs/superpowers/plans/2026-04-15-lrr-phase-4-phase-a-completion-osf-plan.md`. Execution order: G3 resolution → voice session cadence start → mid-collection integrity checks (runs during cadence) → ORCID/Zenodo/GitHub Pages (idle fill) → OSF pre-reg filing (after ≥10 sessions) → data integrity lock → collection_halt_at marker → handoff.

---

## 9. End

Pre-staging spec for LRR Phase 4 Phase A Completion + OSF Pre-Registration. Time-gated by operator voice session cadence. Substrate-independent (Condition A is Qwen3.5-9B regardless of §14 reframing). Phase 5's Condition A' target is TBD per §14.

Nineteenth complete extraction in delta's pre-staging queue this session.

— delta, 2026-04-15
