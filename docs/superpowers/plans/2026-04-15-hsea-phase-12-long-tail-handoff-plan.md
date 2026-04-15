# HSEA Phase 12 — Long-tail Integration + Handoff — Plan

**Date:** 2026-04-15
**Spec reference:** `docs/superpowers/specs/2026-04-15-hsea-phase-12-long-tail-handoff-design.md`
**Branch target:** `feat/hsea-phase-12-long-tail-handoff`
**Unified phase mapping:** UP-13 terminal (~1,000 LOC + handoff doc)

---

## 0. Preconditions

- [ ] All prior HSEA phases (0-11) closed
- [ ] LRR UP-13 (Phase 10 observability + drills + polish) closed
- [ ] Shared index `research-stream-state.yaml::unified_sequence[UP-13]` at `status: open`
- [ ] Operator review bandwidth for final epic close handoff
- [ ] Session claims: `hsea-state.yaml::phase_statuses[12].status: open`

---

## Execution order: 3.2 session handoff → 3.3 merge queue triager → 3.4 doc drift sweeper → 3.1 long-tail sweep → 3.5 final epic close

### 1. Session handoff doc drafter (3.2)

- [ ] Tests: fixture session state → handoff markdown with all required sections
- [ ] `agents/hapax_daimonion/phase_12/session_handoff_drafter.py` (~300 LOC)
- [ ] `docs/superpowers/handoff/templates/session-handoff-template.md` (~100 lines)
- [ ] Read: recent commits + open PRs + TodoWrite state + outstanding items
- [ ] Compose: handoff markdown following existing handoff conventions
- [ ] Commit: `feat(hsea-phase-12): 3.2 session handoff doc drafter (second-order gap from drop #59)`

### 2. CI watch + merge queue triager (3.3)

- [ ] Tests: fixture stalled PR list → triage recommendation
- [ ] `agents/hapax_daimonion/phase_12/merge_queue_triager.py` (~250 LOC)
- [ ] Reads `gh pr list` + `/dev/shm/hapax-ci-state.json` (LRR Phase 9 item 9)
- [ ] Flags PRs with no merge activity >24h
- [ ] Hourly systemd timer
- [ ] Commit: `feat(hsea-phase-12): 3.3 CI watch + merge queue triager (second-order gap from drop #59)`

### 3. Documentation drift sweeper (3.4)

- [ ] Tests: fixture stale CLAUDE.md references → drift event detected
- [ ] `agents/hapax_daimonion/phase_12/doc_drift_sweeper.py` (~350 LOC)
- [ ] Detects: deleted file references, renamed function/class references, stale commit SHAs, stale PR URLs, outdated architecture diagrams
- [ ] Operator-gated auto-apply: governance queue entry per drift event → approve → sweeper applies
- [ ] Weekly systemd timer
- [ ] Commit: `feat(hsea-phase-12): 3.4 documentation drift sweeper`

### 4. Long-tail touch points sweep (3.1)

- [ ] Read the de-duplicated ~65-item touch-point inventory from drop #58 + drop #57 tactics
- [ ] Subtract everything shipped in Clusters B/C/D/E/F/G/H/I/M
- [ ] List residual items
- [ ] Ship what fits; explicitly defer what doesn't with rationale
- [ ] **Target file count varies** — the long-tail is whatever remains unclaimed
- [ ] Commit: `feat(hsea-phase-12): 3.1 long-tail touch points sweep`

### 5. Final epic close handoff (3.5 — SHIPS LAST)

- [ ] Write `docs/superpowers/handoff/2026-04-15-hsea-phase-12-complete.md` (~5000 lines markdown):
  - [ ] Total LOC shipped across 13 HSEA phases
  - [ ] Touch points deployed (count + list) vs deferred + rationale
  - [ ] Open items inherited from drops #57/#58/#59/#60/#61/#62 + resolution status
  - [ ] Recommended next-epic directions
  - [ ] Constitutional state (axiom precedents + implications)
  - [ ] Observability state (per-condition Prom, Langfuse, governance queue metrics)
  - [ ] Research program state (conditions, claims, OSF pre-regs)
  - [ ] Substrate state (current production LLM + post-Hermes landscape resolution)
  - [ ] Session coordination outcomes (protocol v1 + v1.5 evaluation)
- [ ] Operator reviews + edits + signs off before commit lands
- [ ] Commit: `docs(hsea-epic): final epic close handoff`

---

## Phase 12 close

- [ ] `hsea-state.yaml::overall_health == green`
- [ ] All 110 touch points shipped or explicitly deferred with rationale
- [ ] Final handoff doc operator-approved + committed
- [ ] All HSEA phase_statuses[0..12] == closed
- [ ] `research-stream-state.yaml::unified_sequence[UP-13].status == closed`
- [ ] Inflection to peers: HSEA epic complete

---

## Cross-epic coordination

- HSEA epic close depends on LRR Phase 10 completing UP-13 observability work
- Session handoff drafter is session-agnostic (works for alpha, beta, delta, future sessions)
- Doc drift sweeper runs against ALL repo docs, not just HSEA-authored ones
- Final handoff doc summarizes BOTH LRR and HSEA outcomes via cross-reference to drop #62

---

## End

Compact plan for HSEA Phase 12 Long-tail + Handoff. Terminal phase of the HSEA epic. Pre-staging.

— delta, 2026-04-15
