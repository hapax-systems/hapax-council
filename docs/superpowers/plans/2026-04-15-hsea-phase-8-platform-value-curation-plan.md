# HSEA Phase 8 — Platform Value Curation (Cluster E) — Plan

**Date:** 2026-04-15
**Spec reference:** `docs/superpowers/specs/2026-04-15-hsea-phase-8-platform-value-curation-design.md`
**Branch target:** `feat/hsea-phase-8-platform-value-curation`
**Unified phase mapping:** UP-12 sibling (~1,800 LOC)

---

## 0. Preconditions

- [ ] LRR UP-0/UP-1 closed
- [ ] HSEA UP-2/UP-4/UP-10 closed (governance queue + visibility + activity taxonomy)
- [ ] HSEA Phase 3 closed (narrator pattern reference)
- [ ] Session claims: `hsea-state.yaml::phase_statuses[8].status: open`

---

## Execution order (per spec §8): E1 → E3 → E10 → E11 → E4 → E5 → E6 → E8 → E13 → E2 → E7 → E12 → E9 → E14

### 1. E1 — Live RESEARCH.md maintenance

- [ ] Tests: fixture condition transition → RESEARCH.md auto-update sections
- [ ] `agents/hapax_daimonion/e_cluster/e1_research_md_maintainer.py` (~200 LOC)
- [ ] Auto-generated section markers in `RESEARCH.md` preserve manual edit blocks
- [ ] Commit: `feat(hsea-phase-8): E1 live RESEARCH.md maintenance`

### 2. E3 — Stimmung-annotated git log ticker

- [ ] Tests: fixture git log + stimmung snapshots → Cairo ticker draw ops
- [ ] `agents/studio_compositor/git_log_ticker_source.py` (~180 LOC)
- [ ] Scrolls last 20 commits with `[intensity: X, tension: Y]` annotations
- [ ] Commit: `feat(hsea-phase-8): E3 stimmung-annotated git log ticker`

### 3. E10 — Constitutional governance audit trail

- [ ] Tests: fixture precedent landing → audit drop composed
- [ ] `agents/hapax_daimonion/e_cluster/e10_governance_audit.py` (~200 LOC)
- [ ] Commit: `feat(hsea-phase-8): E10 constitutional governance audit trail`

### 4. E11 — Drops publication pipeline curator

- [ ] Tests: governance queue approval → drop index update
- [ ] `agents/hapax_daimonion/e_cluster/e11_drops_curator.py` (~250 LOC)
- [ ] Auto-generates `docs/research/INDEX.md`
- [ ] Commit: `feat(hsea-phase-8): E11 drops publication pipeline curator`

### 5. E4 — Spin-off documentation drafter

- [ ] Tests: fixture subsystem (e.g., camera_pipeline.py) → spin-off proposal drop
- [ ] `agents/hapax_daimonion/e_cluster/e4_spinoff_drafter.py` (~250 LOC), composes `ComposeDropActivity`
- [ ] Commit: `feat(hsea-phase-8): E4 spin-off documentation drafter`

### 6. E5 — Architectural option-value audit narration

- [ ] Tests: detect unused code paths + compose narration
- [ ] `agents/hapax_daimonion/e_cluster/e5_option_value_narrator.py` (~200 LOC)
- [ ] Commit: `feat(hsea-phase-8): E5 architectural option-value audit narration`

### 7. E6 — Documentation freshness auto-check

- [ ] Tests: weekly scan `docs/` tree, detect stale references
- [ ] `agents/hapax_daimonion/e_cluster/e6_doc_freshness_checker.py` (~200 LOC)
- [ ] `scripts/check-doc-freshness.py` standalone (~100 LOC)
- [ ] Commit: `feat(hsea-phase-8): E6 documentation freshness auto-check`

### 8. E8 — Weekly retrospective

- [ ] Tests: fixture week-of-events → retrospective drop composed
- [ ] `agents/hapax_daimonion/e_cluster/e8_weekly_retrospective.py` (~200 LOC)
- [ ] `systemd/user/hapax-weekly-retrospective.timer` (Sunday)
- [ ] Commit: `feat(hsea-phase-8): E8 weekly retrospective`

### 9. E13 — Monthly retrospective (long-form)

- [ ] Tests: fixture month-of-events → ~3000 word retrospective drop
- [ ] `agents/hapax_daimonion/e_cluster/e13_monthly_retrospective.py` (~250 LOC)
- [ ] Monthly timer (first of month)
- [ ] Commit: `feat(hsea-phase-8): E13 monthly retrospective long-form`

### 10. E2 — Morning briefing ritual

- [ ] Tests: fixture overnight state → morning briefing narration
- [ ] `agents/hapax_daimonion/e_cluster/e2_morning_briefing.py` (~250 LOC)
- [ ] `systemd/user/hapax-morning-briefing.timer` (09:00 local default, operator-configurable)
- [ ] Commit: `feat(hsea-phase-8): E2 morning briefing ritual`

### 11. E7 — Studio session chronicle (operator-private)

- [ ] Tests: fixture BPM pattern + contact mic → session chronicle drop
- [ ] `agents/hapax_daimonion/e_cluster/e7_studio_chronicle.py` (~250 LOC)
- [ ] Operator-private gate on creative work content
- [ ] Commit: `feat(hsea-phase-8): E7 studio session chronicle (operator-private)`

### 12. E12 — Beat archive integration

- [ ] Tests: fixture beat metadata + stream-reactions cross-reference
- [ ] `agents/hapax_daimonion/e_cluster/e12_beat_archive_integration.py` (~250 LOC)
- [ ] Operator-private content gate
- [ ] Commit: `feat(hsea-phase-8): E12 beat archive integration`

### 13. E9 — Public agent registry rendering

- [ ] Tests: fixture 200-agent registry → Cairo searchable overlay
- [ ] `agents/studio_compositor/agent_registry_overlay.py` (~300 LOC)
- [ ] Command registry integration: `registry.view`
- [ ] Commit: `feat(hsea-phase-8): E9 public agent registry rendering`

### 14. E14 — Platform value posterior (operator-private)

- [ ] Tests: fixture drop consumption metrics → private dashboard
- [ ] `logos/data/platform_value_posterior.py` (~200 LOC)
- [ ] Private Logos panel
- [ ] Commit: `feat(hsea-phase-8): E14 platform value posterior dashboard (operator-private)`

---

## Phase 8 close

- [ ] All 14 E-deliverables shipped + registered as director activities or systemd timers or Cairo sources
- [ ] Smoke tests per spec §5 exit criteria
- [ ] Handoff doc: `docs/superpowers/handoff/2026-04-15-hsea-phase-8-complete.md`
- [ ] `hsea-state.yaml::phase_statuses[8].status: closed`
- [ ] Inflection to peers: Phase 8 closed

---

## Cross-epic coordination

- All 14 E-drafters compose `ComposeDropActivity` from HSEA Phase 2 deliverable 3.6
- E7 + E12 + E14 are operator-private (creative practice + platform metrics boundary)
- E1 RESEARCH.md auto-update preserves manual operator edit blocks
- E9 agent registry rendering depends on 200+ agent registry being maintained

---

## End

Compact plan for HSEA Phase 8 Platform Value Curation / Cluster E. Pre-staging.

— delta, 2026-04-15
