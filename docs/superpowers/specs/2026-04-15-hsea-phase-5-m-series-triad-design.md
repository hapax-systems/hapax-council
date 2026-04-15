# HSEA Phase 5 — Biometric + Studio + Archival Triad (M-series) — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction; HSEA execution remains alpha/beta workstream)
**Status:** DRAFT pre-staging — awaiting UP-12 parallel cluster basket opening before Phase 5 execution
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 5 (canonical source)
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-5-m-series-triad-plan.md`
**Branch target:** `feat/hsea-phase-5-m-series-triad`
**Cross-epic authority:** drop #62 §5 UP-12 parallelizable cluster basket
**Unified phase mapping:** UP-12 parallel cluster (sibling of HSEA Phases 4, 6, 7, 8, 9) — ~2,200 LOC for M1-M5 core; M6-M23 supporting touch points add ~1,500 LOC if all ship (many operator-gated)

---

## 1. Phase goal

Ship **the top 5 missed opportunities from drop #59** — the unique-to-Legomena novelty surface that no other stream can produce. The M-series fuses **biometric data (operator HRV via hapax-watch, IR presence, contact mic activity) + studio creative state (MIDI clock, BPM, beat archive) + archival longitudinal data (18 months of stream reactions)** into content surfaces that are impossible without this specific operator + this specific hardware envelope + this specific multi-year dataset.

**What this phase is:** 5 core M-deliverables (M1 biometric proactive loop, M2 retrieval-augmented voice memory, M3 creative-state composition, M4 long-horizon drift detector, M5 Reverie cognitive-state write channel) + 12 supporting M-series touch points (M6-M23) that extend the biometric/studio/archival pattern into adjacent content surfaces.

**What this phase is NOT:** does not ship Phase 4 code drafters (HSEA Phase 4), does not ship Phase 3 research orchestration (HSEA Phase 3), does not modify the hapax-watch wire protocol, does not extend the Qdrant schema beyond read patterns.

**Key framing:** M1-M5 are the "Legomena's unique novelty surface" — every other AI livestream has a director loop, a persona, an activity taxonomy. ONLY Legomena has (a) a working hip-hop producer with studio gear, (b) 18 months of ~2,758 indexed reactions to itself, (c) biometric integration via hapax-watch, (d) Reverie wgpu pipeline as a cognitive state write channel. Phase 5 M-series is the content that lands these unique affordances.

**Substrate-agnostic:** M1-M5 and the M6-M23 touch points do NOT depend on which LLM substrate Hapax uses. They depend on data sources (biometrics, Qdrant, MIDI, hapax-watch) that are all substrate-independent. Phase 5 can ship whether or not the Hermes abandonment reframing has resolved.

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62):**

1. **LRR UP-0 + UP-1 closed.** Standard chain.
2. **LRR UP-3 (Phase 2 archive instrument) closed.** M2 retrieval-augmented memory reads Qdrant across `documents` + `stream-reactions` + chronicle + research drops. M4 long-horizon drift detector reads 2,758 stream-reactions from Qdrant. Both depend on Phase 2's archival infrastructure.
3. **HSEA UP-2/UP-4/UP-10 closed.** Phase 5 deliverables use governance queue + spawn budget + ComposeDropActivity + Cairo source registration.
4. **LRR UP-11 Phase 8 closed** for M1 biometric loop (uses Phase 8 objective state for "why is the operator at this level of engagement" correlation).
5. **hapax-watch + contact mic + IR perception fleet deployed and producing signals.** M1/M3 depend on real biometric + perception data; Phase 5 opens only when the signal sources are reliably emitting.

**Intra-epic:** HSEA Phases 0-4 closed (preferred).

**Infrastructure:**

1. **hapax-watch wire protocol** — biometric signals landing at council logos API
2. **`agents/hapax_daimonion/presence_engine.py`** — IR presence detection (existing)
3. **Contact mic Cortado MKIII** — 9 gesture classifications (existing)
4. **MIDI clock via OXI One** — 45x likelihood ratio signal (existing)
5. **Qdrant `stream-reactions`** — 2,758 points of 18 months of reactions
6. **Reverie wgpu pipeline** — 9 expressive dimensions (existing)
7. **`ComposeDropActivity`** from HSEA Phase 2 3.6 — for narrator outputs
8. **`GovernanceQueue`** from HSEA Phase 0 0.2 — for operator-private M1 + M3 nudges
9. **PipeWire dedicated operator-only audio sink** — for M1 private delivery (not `mixer_master`)

---

## 3. Core deliverables (5 items: M1–M5)

### 3.1 M1 — Biometric-driven proactive intervention loop

**Scope:**
- Real-time HUD strip in bottom-left zone (NOT the HSEA Phase 1 HUD — a distinct biometric strip)
- Displays: operator HRV trend (24h window), sleep-debt score, hours-at-desk, IR-presence streak
- Trigger condition: HRV trends down >X% (tunable, default 10%) over 2h AND desk-streak >3h AND no break detected
- On trigger: daimonion prompt at low salience (0.35) — "HRV trended down 14% in 2h. Want a 20-min break nudge?"
- **Response is operator-private**, delivered via operator-only audio sink + Logos sidebar flash (NOT stream audio). M1 uses the Phase 8 attention-bid channels from LRR Phase 8 item 10.
- Data sources: hapax-watch biometrics (HRV, sleep), IR presence engine (IR-presence streak), contact mic (desk activity)
- Constitutional rationale: sustains operator commitment, which is the binding constraint on everything per `executive_function` axiom
- Consent: M1 only fires when operator has active consent contract for biometric use; no data persistence beyond the 24h sliding window
- **Target files:**
  - `agents/hapax_daimonion/m_series/m1_biometric_loop.py` (~300 LOC)
  - `agents/studio_compositor/biometric_strip_source.py` (~250 LOC Cairo source)
  - Config file `config/m1-thresholds.yaml` (operator-editable HRV drop threshold, desk-streak minimum, cooldown)
  - Tests (~250 LOC)
- **Size:** ~800 LOC

### 3.2 M2 — Retrieval-augmented operator memory in voice

**Scope:**
- Intercepts daimonion voice query path: before generating a fresh answer, queries Qdrant across `documents` + `stream-reactions` + chronicle + research drops
- Query embedding: the operator's narrative as embed query via nomic-embed-cpu
- If high-similarity prior answer exists (cosine > 0.85 default), surfaces it first:
  > "You asked about FDL-1 yesterday. Drop #52 traces it to camera_pipeline.stop(). That answer hasn't changed."
- Cited drop + condition_id renders briefly in Sierpinski slot (~3-5 second card)
- Cognitive-prosthetic gap closure per drop #58
- **Target files:**
  - `agents/hapax_daimonion/m_series/m2_retrieval_memory.py` (~350 LOC including Qdrant multi-collection query + cosine filter)
  - Extension to voice query dispatcher (`agents/hapax_daimonion/voice_session/` or wherever) to invoke M2 before fresh generation
  - Sierpinski slot renderer for the citation card (~100 LOC)
  - Tests (~200 LOC)
- **Size:** ~650 LOC

### 3.3 M3 — Studio creative-state composition daemon

**Scope:**
- Fusion daemon reading: contact mic BPM/gesture + MIDI clock + stimmung SEEKING + Qdrant beat-archive
- Trigger condition: operator is making something at stable BPM × for ≥20 min × nothing recorded yet × similar prior session exists in the beat archive
- On trigger: soft daimonion suggestion (operator-private) — "similar session 3 weeks ago hit at 94 BPM, ended up in the elegiac cluster; consider hitting record"
- Visible to stream as "studio scaffold active" pill (no per-session details, just active/inactive)
- Content kept operator-private — creative work is NOT public content
- **Unique to Legomena** — no other AI livestream serves a working hip-hop producer
- **Target files:**
  - `agents/hapax_daimonion/m_series/m3_studio_composition.py` (~400 LOC fusion daemon)
  - `agents/studio_compositor/studio_scaffold_pill_source.py` (~120 LOC Cairo pill)
  - Tests (~200 LOC)
- **Size:** ~720 LOC

### 3.4 M4 — Long-horizon stream-reactions drift detector

**Scope:**
- Weekly systemd timer — reads all `stream-reactions` from Qdrant over 18 months (2,758 points expected)
- PCA over reaction embedding vectors; per-week centroid + dispersion
- Detects drift events:
  > "Slum Village reactions drift from analytical to elegiac framing in last 6 weeks"
- Renders drift trajectory as Sierpinski content slot with cited reaction indices (clickable → drops #X, #Y, #Z)
- **Longest-horizon self-observation the data supports** — no other stream has 2,758 indexed reactions to itself
- Composed via `ComposeDropActivity` — the drift detector writes a research drop each week when a drift is detected
- **Target files:**
  - `agents/hapax_daimonion/m_series/m4_drift_detector.py` (~350 LOC including PCA + trajectory)
  - `systemd/user/hapax-m4-drift-detector.timer` + `.service` (weekly)
  - `agents/studio_compositor/drift_trajectory_source.py` (~150 LOC Sierpinski slot renderer)
  - Tests (~180 LOC)
- **Size:** ~680 LOC

### 3.5 M5 — Reverie wgpu as cognitive state write channel

**Scope:**
- Reverie's 9 GPU expressive dimensions become a STRUCTURED WRITE SURFACE (not just a read channel from stimmung)
- New affordance `gpu_state_signal` with registry of (cognitive event → 9-dim transform) mappings
- Registered cognitive events:
  - `frozen-files-block` → tense + coherence-loss transform
  - `drift-detection-m4` → temporal-distortion + depth-increase
  - `anomaly-resolution` → spectral-color-reset + diffusion-smooth
  - `research-integrity-flip` → intensity-drop + pitch-displacement-increase
  - `condition-transition` → full-dimension flash + 5s return-to-baseline
- Viewers learn to read the pipeline like sheet music — different cognitive events produce different visual signatures
- Closes the cross-modal write gap drop #58 identified but never named
- **Target files:**
  - `agents/reverie/gpu_state_signal_affordance.py` (~250 LOC affordance + event-to-transform registry)
  - `shared/gpu_state_signal_registry.yaml` (operator-editable event mappings)
  - Hook wiring from each of the 5 cognitive event sources → affordance pipeline
  - Tests (~150 LOC)
- **Size:** ~450 LOC

---

## 4. Supporting touch points (12 items: M6–M23)

These are lower-priority extensions of the M1-M5 patterns. Phase 5 opens M1-M5 as the required core; M6-M23 are stretch deliverables that ship as bandwidth allows. None of M6-M23 block Phase 5 close.

| # | Name | Scope (one-liner) | Substrate-agnostic? |
|---|---|---|---|
| M6 | Accountability ledger surfacing | Cairo display of operator's commitments (vault frontmatter extract) + completion signal | Yes |
| M7 | Cross-reference drops ↔ reactions | On drop ship, auto-cite relevant stream-reactions from Qdrant; embed the reaction index in drop body | Yes |
| M8 | Audience-driven preset chain composition | Aggregate chat signals → compose a preset chain; AGGREGATE-ONLY, no per-author state (consent-safe) | Yes |
| M9 | Album-identifier editorial expansion | Extends album-identifier with stream-history context ("this is the 5th time you've played X") | Yes |
| M10 | Ultradian rhythm ceremony rescheduling | Ceremony timers driven by HRV/energy not clock time | Yes |
| M13 | Spawn-budget heatmap as content | Daily budget visualization as Cairo surface ("today's thinking spent $0.23, top category: study") | Yes |
| M15 | Daimonion-narrated commit walkthrough | On PR merge, narrator walks through the commit changes at stream tempo | Yes |
| M16 | IR-fleet-driven proxemic Reverie response | Pi NoIR proximity signals drive Reverie intimate/distant dimensions | Yes |
| M18 | Vault daily-note → prompt context bridge | Obsidian daily note frontmatter extract feeds director loop context | Yes |
| M21 | Operator-correction live filter | Qdrant NN block — if operator corrected a class of response before, surface the correction to current response generation | Yes |
| M22 | Operator-absent dream-sequence content | When operator is inferred absent (IR + watch + keyboard), Hapax runs low-salience dream-sequence content from imagination pipeline | Yes |
| M23 | Axiom near-violation narration | When a proposed action comes within X% of an axiom boundary (consent, corporate_boundary, etc.), narrate the almost-violation to the operator privately | Yes |

**Target files for M6-M23:** each is a single-file module at `agents/hapax_daimonion/m_series/m<N>_<name>.py` (~150-250 LOC each) + tests + any needed Cairo source or config file. Total M6-M23: ~2,500 LOC if ALL ship.

**Sizing:** Phase 5 core (M1-M5) is ~3,300 LOC; if all M6-M23 ship, total is ~5,800 LOC. Realistic: M1-M5 + ~3 high-value touch points (e.g., M9 album-identifier, M15 commit walkthrough, M22 dream-sequence) = ~4,000 LOC.

---

## 5. Phase-specific decisions

1. **Phase 5 ships M1-M5 as the required core; M6-M23 are stretch.** Phase 5 close gates on M1-M5 exit criteria only; any M6-M23 that ship are bonus but not blocking.

2. **Operator-private delivery paths for M1 + M3** use the Phase 8 attention-bid channels (LRR Phase 8 item 10). Phase 5 must ship AFTER LRR Phase 8 has landed the attention-bid infrastructure, OR Phase 5 duplicates a thin attention-bid path of its own (adds ~100 LOC duplication).

3. **M4 drift detector reads 2,758 points** — runs weekly, ~5-10 minutes wall time per run. Not a real-time concern.

4. **M5 Reverie cognitive state write channel** requires the Reverie pipeline to be running + accepting external signals. Reverie's param bridge (`uniforms.json`) is the write surface; M5 writes to existing fields, no new schema.

5. **Substrate-independence:** Phase 5 is substrate-agnostic per §1. No §14 reframing required.

6. **All drop #62 §10 open questions closed.**

---

## 6. Exit criteria

Phase 5 closes when ALL of the following are verified:

1. **M1 triggers on simulated HRV drop** and produces a daimonion impingement; operator-private delivery verified (no stream audio)
2. **M2 retrieval works against real operator voice query** — high-similarity prior answer surfaces before fresh generation; citation card renders
3. **M3 triggers on simulated studio session** (fixture BPM + MIDI + stimmung SEEKING + prior similar session); suggestion delivered operator-private; "studio scaffold active" pill renders on stream
4. **M4 weekly timer runs** at least once successfully; if any drift detected, research drop composed via `ComposeDropActivity`; trajectory renders in Sierpinski slot
5. **M5 cognitive event → GPU signature** verified for at least one event type (e.g., frozen-files block → tense+coherence-loss); Reverie pipeline visibly responds
6. `hsea-state.yaml::phase_statuses[5].status == closed`
7. Phase 5 handoff doc written
8. M6-M23 shipped items (if any) documented in handoff

---

## 7. Risks + mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| hapax-watch offline or biometrics stale | M1 cannot trigger | Phase 5 opener verifies hapax-watch streaming before starting |
| M2 cosine threshold 0.85 too strict or too loose | False positives/negatives | Operator-tunable in `config/m2-retrieval.yaml`; start at 0.85, adjust after observation |
| M3 creative-state false positives interrupt operator flow | Bad UX | 20-min minimum stability window + operator "not now" override + stimmung-gate |
| M4 PCA fails on small cluster sizes | Some weeks have too few reactions for trajectory | Fallback: skip drift detection for weeks with <20 reactions |
| M5 cognitive event → GPU transform is too subtle to perceive | Viewers can't read the cognitive signature | Start with stronger transforms; tune down after viewer feedback |
| Phase 8 attention-bid infrastructure not yet ready | M1/M3 private delivery blocked | Phase 5 duplicates thin attention-bid path if Phase 8 not shipped; duplication flagged for later dedup |
| M6-M23 scope creep beyond session budget | Phase 5 runs long | M6-M23 are stretch; Phase 5 close gates on M1-M5 only |

---

## 8. Open questions

Phase-5-specific (all substrate-independent):

1. **M1 HRV drop threshold.** Default 10% over 2h; operator tunes based on personal baseline
2. **M3 minimum stable-BPM window.** Default 20 min; operator tunes
3. **M4 weekly cadence vs daily.** Weekly per epic spec; operator may want daily during active research periods
4. **M5 event-to-transform mappings.** Starting 5 events per spec; operator can add custom events via `shared/gpu_state_signal_registry.yaml`
5. **M6-M23 priority ordering.** No strict order; whichever session opens Phase 5 picks based on bandwidth + operator guidance

---

## 9. Companion plan doc

`docs/superpowers/plans/2026-04-15-hsea-phase-5-m-series-triad-plan.md`.

Execution order:

1. **M5 Reverie write channel** FIRST — enables cross-modal emphasis for all subsequent M-deliverables (M1/M3 can fire GPU signals via M5)
2. **M2 Retrieval memory** — self-contained, quickest to ship
3. **M1 Biometric loop** — depends on attention-bid path (Phase 8 or duplicate)
4. **M3 Studio composition** — depends on attention-bid path + M5
5. **M4 Drift detector** — largest M-deliverable; ships last in the core
6. **M6-M23 supporting touch points** — any that fit the bandwidth, in whatever order makes sense

---

## 10. End

Pre-staging spec for HSEA Phase 5 M-series biometric/studio/archival triad. 5 core deliverables + 12 stretch supporting touch points. Substrate-agnostic.

Twelfth complete extraction in delta's pre-staging queue this session. Execution remains alpha/beta workstream.

— delta, 2026-04-15
