# HSEA Phase 10 — Reflexive Stack (Cluster F) — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction; HSEA execution remains alpha/beta workstream)
**Status:** DRAFT pre-staging — awaiting UP-13 opening (reflexive stack ships at the end of the epic)
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 10 + `docs/research/2026-04-14-hapax-self-executes-tactics-as-content.md` drop #58 §3 Cluster F
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-10-reflexive-stack-plan.md`
**Branch target:** `feat/hsea-phase-10-reflexive-stack`
**Cross-epic authority:** drop #62 §5 UP-13 (observability + reflexive + spawner + handoff)
**Unified phase mapping:** UP-13 sibling of HSEA Phases 11 + 12 + LRR Phase 10 — ~1,400 LOC

---

## 1. Phase goal

Ship **F2-F14 reflexive layers** — the stack of self-referential content that makes Hapax's activity-reflection visible to the audience. Each F-layer is gated by the `ReflectiveMomentScorer` from HSEA Phase 2 deliverable 3.8 (with the 7-day calibration window having landed by UP-13 time).

**F2-F14 are the "reading the platform as sheet music" layer** — the content that makes the audience learn to read Hapax's internal state over time.

**Substrate-sensitive:** F-layers require expressive narration quality. Per drop #62 §14, post-Hermes substrate quality gate applies to F-layers the same way it applies to HSEA Phase 2 reflect/critique activities. Phase 10 opener runs the same substrate test as HSEA Phase 2 + LRR Phase 9 item 4 before shipping F-layers as "enabled by default".

**Critical ordering note from drop #59:** **F10 (meta-reflexive override via Qdrant NN anti-cliche) MUST ship WITH OR BEFORE F2** (reflect activity from Phase 2 foundation extension). Without F10's cliche-blocking mechanism, F2 would repeat the same reflective patterns and devolve into slop. F10 is the anti-cliche gate that makes F2 falsifiable.

---

## 2. Dependencies + preconditions

1. LRR UP-0/UP-1/UP-9 closed
2. HSEA UP-2/UP-4/UP-10 closed (Phase 2's ReflectiveMomentScorer calibration window complete; scorer `enabled=True`)
3. LRR Phase 5a substrate swap closed with operator-ratified substrate per drop #62 §14
4. HSEA Phase 3 + 8 + 9 preferred (narration-pattern primitives + content curation infrastructure)

---

## 3. Deliverables (13 F-items)

### 3.1 F2 — `reflect` activity (Phase 2 foundation extended)

- Extends HSEA Phase 2 3.3 reflect activity with F-layer framing: the reflection is DIRECTED at the current research condition + persona stance
- Reflects on the last 8 reactions within the scope of the active objective (LRR Phase 8)
- Gated by `ReflectiveMomentScorer` + anti-cliche gate from F10
- **Target files:** `agents/hapax_daimonion/f_cluster/f2_directed_reflect.py` (~180 LOC)
- **Size:** ~240 LOC

### 3.2 F4 — Research-harness narration

- On condition transitions (research-marker change), narrates the transition: what the new condition tests, why it was opened, what evidence would close it
- Composes `ComposeDropActivity`
- **Target files:** `agents/hapax_daimonion/f_cluster/f4_harness_narrator.py` (~200 LOC)
- **Size:** ~260 LOC

### 3.3 F5 — Viewer-awareness ambient (aggregate only)

- Hapax notices the live audience count + chat engagement patterns, narrates awareness: "chat has been quiet for 20 minutes; this feels like thinking time"
- **Aggregate only** — no per-viewer state, no individual targeting
- Triggered at low cadence (max 1/hour)
- **Target files:** `agents/hapax_daimonion/f_cluster/f5_viewer_awareness.py` (~180 LOC)
- **Size:** ~240 LOC

### 3.4 F6 — Bayesian-loop self-reference

- **Once per stream MAX**, Hapax references the research-stream Bayesian analysis work (drop #54 → #56 v3) by citing specific tactics that are currently being pursued
- Hard rate limit: 1/stream, enforced via `~/hapax-state/f6-fire-count.json`
- **Target files:** `agents/hapax_daimonion/f_cluster/f6_bayesian_self_reference.py` (~150 LOC)
- **Size:** ~200 LOC

### 3.5 F7 — Architectural narration

- Narrates architectural decisions, citing PR numbers + service names
- Triggered on PR merges (poll GitHub Actions state from LRR Phase 9 item 9's `/dev/shm/hapax-ci-state.json`)
- **Target files:** `agents/hapax_daimonion/f_cluster/f7_architectural_narrator.py` (~200 LOC)
- **Size:** ~260 LOC

### 3.6 F8 — Reading own research drops

- Periodically (e.g., weekly), Hapax reads one of its own past research drops aloud on stream, providing commentary
- Selection: random walk + operator bias toward recent drops
- **Target files:** `agents/hapax_daimonion/f_cluster/f8_drop_reader.py` (~180 LOC)
- **Size:** ~240 LOC

### 3.7 F9 — Temporal self-comparison via Qdrant

- Uses Qdrant `stream-reactions` to find a prior reaction similar to the current stance + dimensions; narrates the comparison: "6 months ago I reacted to X with framing Y; today the same framing would feel different because..."
- Depends on M4 long-horizon drift detector (HSEA Phase 5 M4) for the temporal indexing pattern
- **Target files:** `agents/hapax_daimonion/f_cluster/f9_temporal_self_comparison.py` (~220 LOC)
- **Size:** ~300 LOC

### 3.8 F10 — Meta-reflexive override (Qdrant NN anti-cliche) — **SHIPS WITH OR BEFORE F2**

- Critical anti-slop gate: before ANY F-layer output is emitted to stream, it goes through a Qdrant nearest-neighbor check against the operator-corrections collection + the operator-flagged-cliches list
- If the proposed output is too similar (cosine > 0.9) to a prior-corrected cliche, it's BLOCKED and the F-layer re-rolls (up to 3 attempts)
- Without F10, F-layers will converge on reflective slop; drop #59 Finding: F10 is the falsifiability gate for the entire F-cluster
- **Target files:** `agents/hapax_daimonion/f_cluster/f10_anti_cliche_override.py` (~250 LOC), `agents/hapax_daimonion/f_cluster/_cliche_corpus_loader.py` (~100 LOC)
- **Size:** ~420 LOC

### 3.9 F11 — Stimmung self-narration

- When stimmung dimensions shift significantly (e.g., tension jumps 0.3), Hapax narrates the shift: "tension just jumped; I'm finding this harder than a minute ago"
- Rate-limited + anti-cliche gated
- **Target files:** `agents/hapax_daimonion/f_cluster/f11_stimmung_self_narration.py` (~180 LOC)
- **Size:** ~240 LOC

### 3.10 F12 — Counterfactual substrate self-reference

- Hapax narrates counterfactuals about its own substrate: "if I were still on Qwen, I probably would have said X; on the current substrate, I'm thinking Y"
- Requires the substrate history to be clearly documented in the research registry
- **Post-§14 reframing:** the counterfactual framing works whether or not a substrate swap has occurred. If Qwen3.5-9B remains the production substrate (per beta's research §9 recommendation), F12 can reference historical prior substrates (Qwen 3.0, old Qwen3.5-9B tuning, etc.) instead of a Hermes counterfactual
- **Target files:** `agents/hapax_daimonion/f_cluster/f12_counterfactual_substrate.py` (~200 LOC)
- **Size:** ~260 LOC

### 3.11 F13 — Operator-Hapax dialogue cameo

- Occasionally (max 1/hour), Hapax narrates a remembered operator interaction: "Ryan asked me about X yesterday; I got it wrong; here's what I'd say now"
- Respects `interpersonal_transparency` axiom — only narrates operator-authorized interactions (via consent contract)
- **Target files:** `agents/hapax_daimonion/f_cluster/f13_operator_dialogue_cameo.py` (~220 LOC)
- **Size:** ~280 LOC

### 3.12 F14 — Meta-meta-reflexivity (hard-rate-limited)

- Hapax narrates the fact that it's narrating: "I'm aware I'm doing the reflective layer right now; that awareness is part of the content"
- **Hard rate limit: ≤3/stream**, enforced via `~/hapax-state/f14-fire-count.json`
- Without the rate limit, F14 would become the whole stream — it's a "we're doing recursion" vanity layer; valuable in small doses
- **Target files:** `agents/hapax_daimonion/f_cluster/f14_meta_meta_reflexivity.py` (~150 LOC)
- **Size:** ~200 LOC

---

## 4. Phase-specific decisions

1. **F10 ships WITH OR BEFORE F2** (drop #59 Finding). Order: F10 → F2 → F4-F14.
2. **All F-layers gated by ReflectiveMomentScorer** (HSEA Phase 2 3.8), post-calibration
3. **All F-layers go through F10 anti-cliche gate** before emission
4. **Substrate-sensitive** — post-§14 substrate quality test applies; F-layers may ship disabled if substrate can't produce expressive narration
5. **Operator-flagged cliches corpus** lives in Qdrant `operator-corrections` + a new `~/hapax-state/f-cluster-cliche-corpus.jsonl`

---

## 5. Exit criteria

- F10 anti-cliche gate ships first + blocks a test cliche pattern
- F2 reflect activity re-emits through F10 + produces non-cliche reflections
- F4 harness narrator fires on a test condition transition
- F6 fire count capped at 1/stream verified
- F9 temporal self-comparison surfaces a real prior reaction via Qdrant NN
- F14 hard rate limit enforced (≤3/stream)
- All 13 F-layers gated by ReflectiveMomentScorer (scorer `enabled=True`)
- `hsea-state.yaml::phase_statuses[10].status == closed`

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| F10 cliche corpus too small → doesn't block anything | Operator seeds 20+ cliches before Phase 10 opens |
| F10 cliche corpus too strict → blocks valid reflections | Threshold tunable; start at 0.9 cosine |
| F-layers converge on slop without F10 | F10 ships FIRST per drop #59 fix |
| Substrate can't produce expressive F-layer content | Per-F-layer enable flag; ship disabled if quality <3/5 |
| F14 meta-meta spam | Hard rate limit ≤3/stream, enforced in code |
| F6 Bayesian reference outdated | Reference drop #54-#62 texts, not stale versions |

---

## 7. Open questions

1. F10 cliche cosine threshold default (0.9)
2. F6 rate limit enforcement scope (per-stream vs per-session vs per-day)
3. F14 hard rate limit (3 vs 5 vs 1)
4. F8 drop selection randomness seed
5. F12 counterfactual historical depth (3 months? 6 months? all time?)

---

## 8. Plan

`docs/superpowers/plans/2026-04-15-hsea-phase-10-reflexive-stack-plan.md`. Execution order: F10 → F2 → F7 → F11 → F4 → F5 → F9 → F6 → F8 → F13 → F12 → F14.

---

## 9. End

Pre-staging spec for HSEA Phase 10 Reflexive Stack / Cluster F. 13 F-layer narrators gated by anti-cliche F10 + ReflectiveMomentScorer. Substrate-sensitive — ships disabled if substrate can't produce expressive narration.

Fifteenth complete extraction in delta's pre-staging queue this session.

— delta, 2026-04-15
