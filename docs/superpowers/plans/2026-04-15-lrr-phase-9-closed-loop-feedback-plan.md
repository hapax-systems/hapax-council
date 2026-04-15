# LRR Phase 9 — Closed-Loop Feedback + Narration + Chat Integration — Plan

**Date:** 2026-04-15
**Spec reference:** `docs/superpowers/specs/2026-04-15-lrr-phase-9-closed-loop-feedback-design.md`
**Branch target:** `feat/lrr-phase-9-closed-loop-feedback`
**Unified phase mapping:** UP-11 portion (~1,800 LOC)

---

## 0. Preconditions

- [ ] LRR UP-0/UP-1/UP-3/UP-7/UP-9 closed
- [ ] LRR UP-8 (Phase 8) closed — objectives + scorer live
- [ ] HSEA UP-2/UP-4/UP-10 closed
- [ ] Post-Hermes substrate ratified per drop #62 §14
- [ ] Phase 9 opener has run substrate narration quality test (item 4 decision gate)
- [ ] Session claims: `lrr-state.yaml::phase_statuses[9].status: open`

---

## 1. Item 9 — SHM signal publishers (first; item 4 depends on them)

- [ ] `/dev/shm/hapax-editor-state.json` — VS Code extension edit in `hapax-council/vscode/` publishing cursor + file + edits (~50 LOC)
- [ ] `scripts/publish-git-state.sh` + `systemd/user/hapax-git-state-publisher.timer` (5s) publishing `/dev/shm/hapax-git-state.json`
- [ ] `scripts/publish-ci-state.sh` + `systemd/user/hapax-ci-state-publisher.timer` (30s) publishing `/dev/shm/hapax-ci-state.json`
- [ ] `ContextAssembler.snapshot()` reads all 3 with 30s staleness fallthrough
- [ ] Commit: `feat(lrr-phase-9): item 9 SHM signal publishers (editor/git/CI)`

## 2. Item 1 — Chat monitor → stimmung signal

- [ ] Tests: fixture chat messages → structural analyzer → SHM output → stimmung consumer
- [ ] `agents/chat_monitor/structural_analyzer.py` (~200 LOC)
- [ ] `shared/stimmung.py` extension: 12th dim `audience_engagement`
- [ ] SHM path `/dev/shm/hapax-chat-signals.json`
- [ ] Commit: `feat(lrr-phase-9): item 1 chat signals → stimmung audience_engagement dimension`

## 3. Item 2 — Stimmung-modulated activity selection

- [ ] Tests: high audience_engagement → chat score raised, low → study/silence raised, critical stimmung → auto-private
- [ ] `agents/hapax_daimonion/director_loop.py` extension (stimmung_term at 0.05 start weight)
- [ ] `config/director_scoring.yaml` updated with `stimmung_term_weight: 0.05`
- [ ] Commit: `feat(lrr-phase-9): item 2 stimmung-modulated director scoring (conservative 5% damping)`

## 4. Item 5 — Async chat queue

- [ ] Tests: flood 50 messages → FIFO evicts to 20 → chat activity reviews queue holistically
- [ ] `agents/hapax_daimonion/chat_queue.py` (~150 LOC)
- [ ] Commit: `feat(lrr-phase-9): item 5 async chat queue with FIFO eviction`

## 5. Item 3 — Research-aware chat reactor

- [ ] Tests: fixture chat message with high cosine similarity to objective → research-relevant flag → study bias
- [ ] `agents/studio_compositor/chat_reactor.py` extension (~120 LOC)
- [ ] 0.6 cosine threshold default; 30s cooldown preserved
- [ ] Commit: `feat(lrr-phase-9): item 3 research-aware chat reactor with nomic-embed similarity`

## 6. Item 6 — Scientific register caption mode

- [ ] Tests: fixture STT output → Cairo render → verify public_research vs public styling differs
- [ ] `agents/studio_compositor/captions_source.py` (~200 LOC)
- [ ] Zone registration in `config/compositor-zones.yaml`
- [ ] Commit: `feat(lrr-phase-9): item 6 scientific register caption mode`

## 7. Item 7 — Stimmung × stream correlation dashboard

- [ ] Create `grafana/dashboards/stimmung-stream-correlation.json`
- [ ] Prometheus scrape extension for stimmung metrics
- [ ] `promtool` validation
- [ ] Operator reviews for closed-loop sanity check
- [ ] Commit: `feat(lrr-phase-9): item 7 stimmung × stream correlation Grafana dashboard`

## 8. Item 8 — PipeWire operator-voice-over-YouTube ducking

- [ ] Create `config/pipewire/operator-voice-sidechain.conf`
- [ ] `filter-chain` node with sc-compressor + sidechain input from echo_cancel_source VAD
- [ ] 6 dB attenuation, 80ms attack, 200ms release
- [ ] Stream Deck button for disable
- [ ] **A/B test with existing #778 ducking** — verify no amplitude collision
- [ ] Commit: `feat(lrr-phase-9): item 8 operator-voice-over-YouTube sidechain ducking`

## 9. Item 4 — Daimonion code-narration (SUBSTRATE DECISION GATE)

### 9.1 Substrate quality gate

- [ ] Run 3-5 narration fixture prompts against the ratified post-Hermes substrate
- [ ] Operator rates each 1-5 on Hapax-ness / narration quality
- [ ] If ≥3/5: item 4 ships enabled
- [ ] If <3/5: item 4 ships with `enabled=False` flag; code narrator returns generic study narration

### 9.2 Implementation

- [ ] Tests: fixture editor/git/CI signals → code_narrator output → narrates correctly
- [ ] `agents/hapax_daimonion/narrators/code_narrator.py` (~250 LOC)
- [ ] `agents/hapax_daimonion/activities/study.py` extension (~150 LOC)
- [ ] Fall-through to generic study narration on stale signals (>30s)
- [ ] Commit: `feat(lrr-phase-9): item 4 daimonion code-narration sub-mode (with substrate gate)`

---

## 10. Phase 9 close

### Smoke tests

- Chat signals → stimmung → director loop scorer closed loop verified
- Async queue bounded, FIFO verified
- Research-aware reactor fires on objective-similar message
- Code narrator either ships enabled (substrate passed) or disabled (fallthrough to generic study)
- Scientific register captions render correctly
- Grafana dashboard shows closed-loop data
- Operator-voice sidechain ducking verified (no #778 collision)
- All SHM signal publishers active

### Handoff

- `docs/superpowers/handoff/2026-04-15-lrr-phase-9-complete.md`
- `lrr-state.yaml::phase_statuses[9].status: closed`
- Inflection to peers: Phase 9 closed + closed loop now live + UP-11 complete (combined with Phase 8 + HSEA Phase 3)

---

## 11. Cross-epic coordination

- **LRR Phase 8** provides objectives + scorer that Phase 9 extends with stimmung term
- **LRR Phase 7** persona provides register for scientific-register captions
- **HSEA Phase 3** co-ships in UP-11; C-cluster narrators don't directly consume Phase 9 artifacts but benefit from closed-loop active
- **`#778` audio ducking PR** must coexist with Phase 9 item 8 operator-voice sidechain

---

## 12. End

Compact plan for LRR Phase 9. Eleventh extraction in delta's pre-staging queue this session. Execution remains alpha/beta workstream.

— delta, 2026-04-15
