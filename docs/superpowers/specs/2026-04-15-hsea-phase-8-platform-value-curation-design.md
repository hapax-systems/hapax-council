# HSEA Phase 8 — Platform Value Curation (Cluster E) — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction; HSEA execution remains alpha/beta workstream)
**Status:** DRAFT pre-staging — awaiting UP-12 parallel cluster basket opening
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 8 + `docs/research/2026-04-14-hapax-self-executes-tactics-as-content.md` drop #58 §3 Cluster E
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-8-platform-value-curation-plan.md`
**Branch target:** `feat/hsea-phase-8-platform-value-curation`
**Cross-epic authority:** drop #62 §5 UP-12 parallelizable cluster basket
**Unified phase mapping:** UP-12 sibling of HSEA Phases 4, 5, 6, 7, 9 — ~1,800 LOC across 14 E-deliverables

---

## 1. Phase goal

Ship the **live RESEARCH.md maintenance + morning briefing ritual + stimmung-annotated git log + spin-offs + retrospectives** — the content surfaces that document Hapax's own research journey as stream content. Cluster E is about "making the platform itself legible to viewers" — converting Hapax's internal state (git log, architectural decisions, documentation freshness, session chronicles) into audience-facing research content.

**What this phase is:** 14 E-cluster deliverables (E1-E14) that compose `ComposeDropActivity` or ship as Cairo overlay sources. Per drop #62 §10 Q3 rescoping, all E-cluster drafters are narration-only — they watch Hapax's own state and compose research drops / ticker content.

**What this phase is NOT:** does not ship revenue items (HSEA Phase 9 Cluster H), does not ship D-cluster self-monitoring (HSEA Phase 7), does not modify the platform's core operation.

**Substrate-agnostic.** All E-cluster deliverables work on any LLM substrate.

---

## 2. Dependencies + preconditions

- LRR UP-0 + UP-1 closed
- HSEA UP-2 + UP-4 + UP-10 closed (governance queue + visibility surfaces + activity taxonomy)
- HSEA Phase 3 (UP-11 portion) closed — E-cluster shares narrator pattern with C-cluster
- Existing git + hapax-state infrastructure

---

## 3. Deliverables (14 E-items)

### 3.1 E1 — Live RESEARCH.md maintenance

- **Scope:** `RESEARCH.md` at repo root is a rolling summary of open claims, current conditions, hypothesis state, recent evidence. Updated on each condition transition + each research drop merge.
- **Target files:** `agents/hapax_daimonion/e_cluster/e1_research_md_maintainer.py` (~200 LOC), `RESEARCH.md` at repo root (auto-generated with manual edit gates)
- **Size:** ~280 LOC

### 3.2 E2 — Morning briefing ritual

- **Scope:** Every morning at ~09:00 local, daimonion narrates a "morning briefing" summarizing overnight research events, new drops, governance queue state, upcoming session targets
- **Target files:** `agents/hapax_daimonion/e_cluster/e2_morning_briefing.py` (~250 LOC) + `systemd/user/hapax-morning-briefing.timer`
- **Size:** ~300 LOC

### 3.3 E3 — Stimmung-annotated git log ticker

- **Scope:** Cairo overlay ticker showing git log of current branch with stimmung dimension annotations (e.g., "commit `abc123` — merged PR #826 [intensity: 0.67, tension: 0.42]"). Scrolls through ~last 20 commits.
- **Target files:** `agents/studio_compositor/git_log_ticker_source.py` (~180 LOC)
- **Size:** ~240 LOC

### 3.4 E4 — Spin-off documentation drafter

- **Scope:** Detects when a refactor or subsystem could become a standalone library (e.g., the `camera_pipeline.py` resilience work); drafts a "spin-off proposal" research drop with scope, dependencies, audience
- **Target files:** `agents/hapax_daimonion/e_cluster/e4_spinoff_drafter.py` (~250 LOC), composes `ComposeDropActivity`
- **Size:** ~320 LOC

### 3.5 E5 — Architectural option-value audit narration

- **Scope:** Periodic (weekly) narration identifying unused architectural affordances (code paths that exist but are never exercised). Surfaces them as "option value" — things Hapax could do but chooses not to
- **Target files:** `agents/hapax_daimonion/e_cluster/e5_option_value_narrator.py` (~200 LOC)
- **Size:** ~260 LOC

### 3.6 E6 — Documentation freshness auto-check

- **Scope:** Weekly scan of `docs/` tree flagging any doc older than 90 days that references a file/function/config that no longer exists; composes a "documentation staleness" drop
- **Target files:** `agents/hapax_daimonion/e_cluster/e6_doc_freshness_checker.py` (~200 LOC), `scripts/check-doc-freshness.py` (~100 LOC standalone tool)
- **Size:** ~350 LOC

### 3.7 E7 — Studio session chronicle

- **Scope:** When operator completes a studio session (contact mic BPM pattern detects start + end), compose a chronicle drop summarizing the session (duration, BPM trajectory, equipment mentioned, any recorded output). Operator-private content-gate.
- **Target files:** `agents/hapax_daimonion/e_cluster/e7_studio_chronicle.py` (~250 LOC)
- **Size:** ~320 LOC

### 3.8 E8 — Weekly retrospective

- **Scope:** Every Sunday, compose a weekly retrospective drop: PRs shipped, drops authored, conditions transitioned, open claims, operator energy trend, notable events
- **Target files:** `agents/hapax_daimonion/e_cluster/e8_weekly_retrospective.py` (~200 LOC) + `systemd/user/hapax-weekly-retrospective.timer`
- **Size:** ~260 LOC

### 3.9 E9 — Public agent registry rendering

- **Scope:** Cairo source rendering the current agent registry (200+ agents per council architecture) as a searchable overlay when operator invokes `registry.view` via command registry
- **Target files:** `agents/studio_compositor/agent_registry_overlay.py` (~300 LOC)
- **Size:** ~380 LOC

### 3.10 E10 — Constitutional governance audit trail

- **Scope:** Reads `axioms/` + `axioms/precedents/` + `axioms/implications/` + ratification inflections; composes a "constitutional state" drop whenever new precedents or amendments land
- **Target files:** `agents/hapax_daimonion/e_cluster/e10_governance_audit.py` (~200 LOC)
- **Size:** ~260 LOC

### 3.11 E11 — Drops publication pipeline curator

- **Scope:** Curator agent that watches the governance queue for approved research drops, generates a "drop index" with categorization, tags, links between drops, and publishes to a public-facing `docs/research/INDEX.md`
- **Target files:** `agents/hapax_daimonion/e_cluster/e11_drops_curator.py` (~250 LOC)
- **Size:** ~320 LOC

### 3.12 E12 — Beat archive integration

- **Scope:** Integrates operator's beat archive (separate creative practice) as a content source for studio session narration. Reads beat metadata; correlates with stream-reactions for "this beat was made during condition X" cross-references
- **Target files:** `agents/hapax_daimonion/e_cluster/e12_beat_archive_integration.py` (~250 LOC)
- **Size:** ~320 LOC

### 3.13 E13 — Monthly retrospective (long-form)

- **Scope:** First of each month, compose a long-form (~3000 word) retrospective drop covering the month: research trajectory, claim state transitions, architectural evolution, notable operator-Hapax interactions
- **Target files:** `agents/hapax_daimonion/e_cluster/e13_monthly_retrospective.py` (~250 LOC) + monthly timer
- **Size:** ~300 LOC

### 3.14 E14 — Platform value posterior (operator-private)

- **Scope:** Aggregate metric tracking whether Hapax's value-curation outputs (E1-E13) are actually being consumed. Operator-private dashboard showing drop read counts, retrospective completeness, audit trail coverage. NOT on stream.
- **Target files:** `logos/data/platform_value_posterior.py` (~200 LOC) + private Logos panel
- **Size:** ~260 LOC

---

## 4. Phase-specific decisions

1. **All E-cluster items are narration-only** per drop #62 §10 Q3 — compose `ComposeDropActivity` or ship Cairo sources
2. **E7 + E12 are operator-private** by default (creative practice boundary per beta's research)
3. **E14 is operator-private** by constitutional design (platform value tracking is operator cognitive prosthetic, not public content)
4. **Substrate-agnostic** — no §14 reframing required
5. **All drop #62 §10 resolved**

---

## 5. Exit criteria

- All 14 E-deliverables registered as director activities OR systemd timers OR Cairo sources
- E1 RESEARCH.md auto-updates on condition transition
- E2 morning briefing fires at scheduled time
- E3 git log ticker renders on stream
- E6 doc freshness check surfaces at least 1 stale doc on initial run
- E7 studio chronicle correctly gates on operator-private content flag
- E8 + E13 weekly/monthly retrospectives fire on schedule
- E9 agent registry overlay renders when invoked
- E10 constitutional audit drop composed on a test precedent landing
- E14 platform value posterior dashboard accessible via command registry
- `hsea-state.yaml::phase_statuses[8].status == closed`
- Handoff doc

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| E1 RESEARCH.md edits collide with manual operator edits | Auto-generated sections marked with comment blocks; manual sections preserved |
| E2 morning briefing interrupts operator sleep if time is wrong | Timer is operator-configurable; default 09:00 local |
| E6 doc freshness check false-positives | Threshold tunable; 90-day default |
| E14 platform value posterior measures vanity metrics | Operator reviews + adjusts thresholds |
| Governance queue floods from 14 E-drafters | Per-deliverable spawn budget caps |

---

## 7. Open questions

1. E2 morning briefing delivery channel: stream audio vs operator-only?
2. E6 doc freshness tunable cadence (weekly default vs daily)
3. E11 drops index format (INDEX.md vs richer HTML site)
4. E13 monthly retrospective length (~3000 words default)

---

## 8. Plan

`docs/superpowers/plans/2026-04-15-hsea-phase-8-platform-value-curation-plan.md`. Execution order: E1 → E3 → E10 → E11 → E4 → E5 → E6 → E8 → E13 → E2 → E7 → E12 → E9 → E14.

---

## 9. End

Pre-staging spec for HSEA Phase 8 Platform Value Curation / Cluster E. 14 narration-only deliverables composing `ComposeDropActivity` from HSEA Phase 2. Substrate-agnostic.

Thirteenth complete extraction in delta's pre-staging queue this session.

— delta, 2026-04-15
