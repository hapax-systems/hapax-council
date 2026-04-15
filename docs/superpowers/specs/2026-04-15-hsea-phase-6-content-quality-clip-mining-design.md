# HSEA Phase 6 — Content Quality + Clip Mining (Cluster B) — Design Spec

**Date:** 2026-04-15
**Author:** beta (pre-staging extraction per delta's nightly queue Item #15 / #46; matches delta's HSEA Phase 0/1/2/3/4/5/8/9/10/11/12 extraction pattern)
**Status:** DRAFT pre-staging — awaiting operator sign-off + HSEA UP-10 (Phase 2) + HSEA UP-2 (Phase 0) close before Phase 6 open
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 6 (lines 499–514)
**Thesis reference:** drop #58 §3 Cluster B (content quality feedback loop)
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-6-content-quality-clip-mining-plan.md`
**Branch target:** `feat/hsea-phase-6-content-quality-clip-mining`
**Cross-epic authority:** drop #62 §5 UP-12 cluster basket (Phase 6 is one of the parallel UP-12 phases — can ship whenever its dependencies close)

---

## 1. Phase goal

Ship the **content quality feedback loop** — clipability scoring, exemplar auto-curation, live anti-pattern detection, self-A/B testing, clip mining. Transform the stream's output quality from "whatever the director loop produces" into "tracked + improved + pattern-detected + mined for highlights" via a closed loop that operates on the substrate's own output.

**What this phase is:** 10 Cluster B deliverables (B1–B11, with B9 skipped per drop #58 numbering) that turn stream output into an observable quality signal + operator-visible improvement loop.

**What this phase is NOT:** does not ship the activity taxonomy extension (that's HSEA Phase 2), does not ship persona specs (LRR Phase 7), does not change the substrate, does not extend the director loop with new activities. Phase 6 is a quality-feedback layer on top of existing activities.

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62):**

1. **HSEA UP-2 (Phase 0 foundation primitives) closed.** B2 + B3 + B7 all consume governance queue + spawn budget ledger. B3 grep filter calls `scripts/promote-drop.sh` for rewriter proposals.
2. **HSEA UP-10 (Phase 2 core director activities) closed.** B4 (`critique` activity) is literally Phase 2 deliverable 3.4 extended with clipability scoring; Phase 6 cannot ship without the Phase 2 foundation.
3. **LRR UP-1 (Phase 1 research registry) closed.** B6 condition-boundary retrospection reads condition.yaml + transition timestamps.
4. **LRR UP-3 (Phase 2 archive instrument) closed.** B10 clip-miner reads archive segments + sidecars.
5. **Substrate-agnostic** — no §14 reframing required.

**Intra-epic:** no prior HSEA phase beyond 0/2/10 is strictly required. Phase 6 is a UP-12 parallel cluster.

**Infrastructure:**

1. `agents/hapax_daimonion/activities/compose_drop.py::ComposeDropActivity` (HSEA Phase 2 3.6 public API for the exemplar curation output path)
2. `shared/exemplars.yaml` + `shared/antipatterns.yaml` (HSEA Phase 0 0.4 empty shells; LRR Phase 7 populates authoritatively; Phase 6 extends from operator-approved governance queue entries)
3. `shared/governance_queue.py::GovernanceQueue` (HSEA Phase 0 0.2)
4. `shared/spawn_budget.py::SpawnBudgetLedger` (HSEA Phase 0 0.3)
5. `nomic-embed-cpu` + Qdrant `stream-reactions` collection
6. Archive segment access per LRR Phase 2 item 1
7. `agents/studio_compositor/` Cairo source pattern for B10 clip-miner visibility

---

## 3. Deliverables (10 Cluster B items)

### 3.1 B1 — Clipability scorer

- Per-reaction scoring function that assigns a `clipability` score 0.0–1.0 based on: music salience alignment, turn length, emotional contour, non-repetition, novelty vs recent exemplars
- Scoring writes to `~/hapax-state/clipability-scores.jsonl` + extends `stream-reactions` Qdrant payload with a `clipability` field
- Per-reaction latency target: <100 ms (runs after reaction emission, not blocking)
- **Target files:** `agents/hapax_daimonion/b_cluster/b1_clipability_scorer.py` (~200 LOC), `tests/` (~120 LOC)
- **Size:** ~320 LOC

### 3.2 B2 — Exemplar auto-curation (weekly ceremony)

- Weekly Saturday 09:00 local timer: reads last 7 days of clipability-scored reactions; selects top N (operator-configurable, default 12) for exemplar review; composes `ComposeDropActivity` output with proposed exemplar additions
- Operator approves/rejects via governance queue + inbox frontmatter flip
- Approved exemplars promoted to `shared/exemplars.yaml` via `scripts/promote-exemplar.sh` (HSEA Phase 0 0.4)
- **Target files:** `agents/hapax_daimonion/b_cluster/b2_exemplar_curator.py` (~250 LOC), `systemd/user/hapax-exemplar-ceremony.timer` + `.service`, tests (~120 LOC)
- **Size:** ~380 LOC

### 3.3 B3 — Live anti-pattern detection

- **Grep filter** on live reaction output: regex patterns from `shared/antipatterns.yaml` scanned on each emitted reaction; match → reaction flagged for critic review
- **LLM critic** (via HSEA Phase 2 `critique` activity) examines flagged reactions; if the critic agrees it's an anti-pattern, proposes a rewrite
- **Rewriter** composes the corrected reaction as a `draft` activity output via the governance queue (does NOT auto-replace the live output; operator approves, future emissions learn)
- Grep+critic+rewriter chain completes within 500 ms budget; graceful degrade if critic times out
- **Target files:** `agents/hapax_daimonion/b_cluster/b3_antipattern_detection.py` (~280 LOC including grep+critic+rewriter wiring), tests (~150 LOC)
- **Size:** ~430 LOC

### 3.4 B4 — `critique` activity (Phase 2 foundation extended)

- Extends HSEA Phase 2 deliverable 3.4 `critique` activity with clipability-aware critique prompts: "is this output exemplar-quality, anti-pattern, or neutral?"
- Output schema: `{critique_verdict: "exemplar" | "antipattern" | "neutral", confidence: float, reasoning: str}`
- Used by B3 (anti-pattern) and B5 (self-A/B) as the critic path
- **Target files:** `agents/hapax_daimonion/activities/critique.py` extension (~150 LOC), tests (~80 LOC)
- **Size:** ~230 LOC

### 3.5 B5 — Self-A/B testing director prompt variants

- Periodic (hourly) prompt-variant A/B test: director loop runs 2 variants for a small number of reactions (e.g., 10 per variant per hour); clipability scores of each variant compared; operator sees "variant B is 18% higher clipability this week" narration
- Variants operator-editable at `config/director_prompt_variants.yaml`
- **Safety:** A/B test variants are GATED on `stream-mode != public_research` — research-mode streams run the frozen variant only
- **Target files:** `agents/hapax_daimonion/b_cluster/b5_self_ab_testing.py` (~250 LOC), config, tests (~150 LOC)
- **Size:** ~420 LOC

### 3.6 B6 — Condition-boundary retrospection

- On condition transition (research registry `current` changes), compose a retrospection drop summarizing Condition N: sample sizes, mean clipability, exemplar contributions, anti-pattern frequency, notable moments
- Reads condition.yaml + stream-reactions Qdrant filtered by condition_id
- Composes `ComposeDropActivity`
- **Target files:** `agents/hapax_daimonion/b_cluster/b6_condition_retrospection.py` (~220 LOC), tests (~100 LOC)
- **Size:** ~320 LOC

### 3.7 B7 — Self-prompt-engineering proposals (operator-approved)

- Weekly: analyzes prior week's B5 A/B results + B6 condition retrospections + governance queue rejections; proposes concrete director-loop prompt changes ("the current persona header over-weights tension when clipability is low — consider rebalancing")
- Output routed through `promote-patch.sh` (HSEA Phase 0 0.4) so operator approval is required before the prompt change lands
- **Target files:** `agents/hapax_daimonion/b_cluster/b7_prompt_eng_proposals.py` (~250 LOC), tests (~120 LOC)
- **Size:** ~370 LOC

### 3.8 B8 — Music-aware self-observation ("Dilla discipline")

- Contact mic + BPM + MIDI signals from the studio pipeline feed a "musical self-observation" context that biases clipability scoring toward rhythm-locked reactions
- "Dilla discipline" reference: J Dilla's intentional off-grid placement as a quality signal — hapax should recognize that clipability is not always quantized
- **Target files:** `agents/hapax_daimonion/b_cluster/b8_music_awareness.py` (~200 LOC), tests (~100 LOC)
- **Size:** ~300 LOC

### 3.9 B10 — Clip-miner visible decision

- Periodic (every 15 min) pass over recent clipability-scored reactions: selects candidate highlights; for each, composes a `compose_drop` output "I'd highlight this moment because X"; operator reviews
- Makes the clip-mining decision visible on-stream (Cairo surface: "hapax is considering clipping moment T — press yes/no on stream deck")
- Operator yes → clip is marked for later extraction; operator no → reason recorded for future clipability-scoring calibration
- **Target files:** `agents/hapax_daimonion/b_cluster/b10_clip_miner_visible.py` (~280 LOC), `agents/studio_compositor/clip_consideration_source.py` (~150 LOC Cairo overlay), tests
- **Size:** ~540 LOC

### 3.10 B11 — Operator-collaboration ceremony

- Per-session end-of-session ceremony: daimonion narrates a 2-minute summary of the session's clipability trajectory + exemplar hits + anti-pattern misses + proposed next-session variants
- Voice delivery via operator-private audio sink (not stream)
- Operator can acknowledge, redirect, or defer
- **Target files:** `agents/hapax_daimonion/b_cluster/b11_collab_ceremony.py` (~220 LOC), tests (~100 LOC)
- **Size:** ~320 LOC

---

## 4. Phase-specific decisions since epic authored

1. **All Cluster B items compose `ComposeDropActivity` or are activity extensions per drop #62 §10 Q3** — narration-only framework applies to B-cluster the same as C/D/E/F/G/H/I clusters. No direct code mutation; operator approval gates every promotion.
2. **Substrate-agnostic** — no §14 reframing required. B-cluster does not depend on which LLM substrate is active.
3. **LRR Phase 7 persona spec ownership of `shared/exemplars.yaml` + `shared/antipatterns.yaml`** — Phase 6 extends from operator-approved queue entries; authoritative initial population is LRR Phase 7.
4. **B5 self-A/B safety gate** — A/B variants are LOCKED OUT in `public_research` stream mode. Research integrity trumps content quality optimization.
5. **Clipability scoring Qdrant payload extension** — B1 writes to `stream-reactions` payload; this is a schema extension to the LRR-owned collection. LRR Phase 1 item 2 (per-segment metadata) is the authoritative schema surface; Phase 6 appends `clipability` as a new field without breaking prior readers.

---

## 5. Exit criteria

Phase 6 closes when ALL of the following are verified:

1. B1 clipability scorer shipped; all live reactions emit a clipability score within 100 ms
2. B2 weekly exemplar ceremony runs; at least one cycle produces a governance queue entry
3. B3 anti-pattern detection running live; at least one anti-pattern detected + rewriter proposal composed + operator reviewed (approved or rejected)
4. B4 `critique` activity extended; used by B3 + B5 paths
5. B5 self-A/B ran at least one cycle; variant comparison report delivered; research-mode gate verified
6. B6 condition-boundary retrospection triggered on at least one condition transition; drop composed + operator reviewed
7. B7 weekly self-prompt-engineering proposal composed; operator review round completed
8. B8 music-aware self-observation integrated into B1 clipability scoring; Cairo surface acknowledges
9. B10 clip-miner visible decision renders on stream; at least 3 operator yes/no decisions captured
10. B11 end-of-session collaboration ceremony delivered via operator-private audio at least once
11. Phase 6 handoff doc written

---

## 6. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| B1 clipability score is noisy; operator ignores | MEDIUM | Quality loop never closes | Ship with explicit operator feedback loop; weekly review of false positive rate |
| B3 anti-pattern grep is too aggressive; good reactions flagged | MEDIUM | Creative suppression | Grep patterns operator-tunable; critic veto path; rewriter does NOT auto-replace |
| B5 A/B testing leaks research-mode boundary | LOW | Research integrity breach | HARD GATE on `stream-mode != public_research`; test verifies the gate |
| B10 clip-miner decision surface distracts operator mid-stream | MEDIUM | Cognitive load increase | Surface is low-opacity + only appears on strong-candidate threshold (e.g., clipability > 0.75) |
| Phase 6 never closes because exemplar quality is subjective | HIGH | Phase 6 drags indefinitely | Operator-defined exit criteria; default to "exemplar pool has ≥50 entries" |

---

## 7. Open questions

1. Clipability score threshold for B10 clip-miner surface — default 0.75? tunable?
2. B8 BPM awareness — does it use the existing contact mic Cortado signal or a new signal source?
3. B11 ceremony length — 2 minutes is a guess; operator may prefer 30 sec
4. Exemplar curation ceremony cadence — weekly or monthly?
5. Anti-pattern grep patterns — who authors the initial set? (Operator? LRR Phase 7 persona work?)

---

## 8. Companion plan doc

TDD checkbox task breakdown at `docs/superpowers/plans/2026-04-15-hsea-phase-6-content-quality-clip-mining-plan.md`.

**Execution order inside Phase 6:**

1. **B1 clipability scorer** — foundational; all other B items consume it
2. **B4 `critique` extension** — ships before B3 + B5 which call it
3. **B8 music-aware self-observation** — feeds B1 scoring; ships early
4. **B3 anti-pattern detection** — depends on B4
5. **B5 self-A/B** — depends on B1 + B4
6. **B6 condition-boundary retrospection** — independent; ships anytime after B1
7. **B2 weekly exemplar ceremony** — depends on B1; ships mid-phase
8. **B10 clip-miner visible** — depends on B1; ships mid-phase
9. **B7 self-prompt-engineering proposals** — depends on B5 + B6 data; ships late
10. **B11 operator-collaboration ceremony** — depends on most others; ships last

---

## 9. End

Standalone per-phase design spec for HSEA Phase 6 Content Quality + Clip Mining. Extracts drop #58 §3 Cluster B content + HSEA epic §5 Phase 6 into the delta 9-section pattern. Pre-staging only; does not open Phase 6.

— beta (PR #819 author) per delta's nightly queue Item #15 / #46, 2026-04-15
