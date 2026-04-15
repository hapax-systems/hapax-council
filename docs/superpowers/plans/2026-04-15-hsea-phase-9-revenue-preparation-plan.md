# HSEA Phase 9 — Revenue Preparation (Cluster H) — Plan

**Date:** 2026-04-15
**Spec reference:** `docs/superpowers/specs/2026-04-15-hsea-phase-9-revenue-preparation-design.md`
**Branch target:** `feat/hsea-phase-9-revenue-preparation`
**Unified phase mapping:** UP-12 sibling (~2,800 LOC)

---

## 0. Preconditions

- [ ] LRR UP-0/UP-1 closed
- [ ] LRR UP-8 (Phase 6 governance + `sp-hsea-mg-001` axiom precedent joint PR) closed
- [ ] HSEA UP-2 closed (governance queue + spawn budget + axiom precedent draft)
- [ ] HSEA UP-10 closed (ComposeDropActivity base)
- [ ] LRR UP-9 (Phase 7 persona) closed — "intrinsic motivation" clause references persona engagement commitments
- [ ] **H3 Phase 1 employer pre-disclosure hard-gates Phase 2** — this is a constitutional constraint, NOT optional
- [ ] Operator review bandwidth for revenue artifacts
- [ ] Session claims: `hsea-state.yaml::phase_statuses[9].status: open`

---

## Execution order (per spec §8): H8 → H1 → H4 → H2 → H3 → H7 → H6 → H5

### 1. H8 — Axiom compliance gate (ships FIRST)

- [ ] Tests: bats tests rejecting `\bdonors?\b` / `\bsubscribers?\b` / `\bguarantee\b` / `\bpromise\b` / email-phone in sponsor position
- [ ] `hooks/scripts/axiom-patterns-revenue.sh` (~150 LOC)
- [ ] `hooks/scripts/axiom-commit-scan.sh` integration (~20 LOC edit)
- [ ] Advisory-only for missing "work continues regardless" clause (promoted to BLOCKING after 30 days)
- [ ] Commit: `feat(hsea-phase-9): H8 axiom compliance gate (revenue patterns)`

### 2. H1 — Sponsor copy drafter

- [ ] Tests: pydantic validators enforce "no deliverables" + "work continues regardless" at field level
- [ ] `agents/revenue/_tier_copy_schema.py` (~120 LOC)
- [ ] `agents/revenue/sponsor_copy_drafter.py` (~350 LOC)
- [ ] Hardcoded intrinsic-motivation clause in system prompt
- [ ] Dispatch via `dispatch-approved.sh sponsor-copy <id>` — clipboard only
- [ ] Commit: `feat(hsea-phase-9): H1 sponsor copy drafter`

### 3. H4 — Grant deadline tracker overlay

- [ ] Tests: daily fetcher reads NLnet cycle dates; T-14d impingement
- [ ] `agents/revenue/grant_deadline_fetcher.py` (~200 LOC)
- [ ] `agents/studio_compositor/grant_deadline_overlay_source.py` (~180 LOC Cairo)
- [ ] Daily systemd timer
- [ ] Default HIDDEN on public livestream
- [ ] Commit: `feat(hsea-phase-9): H4 grant deadline tracker + Cairo overlay`

### 4. H2 — NLnet NGI0 grant drafter

- [ ] Tests: provenance extractor pulls milestones from drops #32-#59; `INSUFFICIENT_PROVENANCE` marker on <3 milestones
- [ ] `agents/revenue/_provenance_extractor.py` (~250 LOC)
- [ ] `agents/revenue/nlnet_grant_drafter.py` (~500 LOC)
- [ ] `config/nlnet-budget.yaml` (operator-configurable rate ceiling)
- [ ] Three candidate drafts: camera resilience Rust library / constitutional governance / multi-agent pipeline
- [ ] 5-gate submission checklist
- [ ] Commit: `feat(hsea-phase-9): H2 NLnet grant drafter with provenance gate`

### 5. H3 — Consulting pull channel drafter + employer pre-disclosure gate

- [ ] Tests: Phase 1 always runs; Phase 2 hard-gated on `consulting-gate.json::phase_1_acknowledged: true`
- [ ] `agents/revenue/consulting_channel_drafter.py` (~400 LOC)
- [ ] `~/hapax-state/revenue/consulting-gate.json` (operator-controlled flag)
- [ ] Post-generation regex check: "no long-term engagements" literal in every Phase 2 artifact
- [ ] Commit: `feat(hsea-phase-9): H3 consulting drafter with two-phase employer pre-disclosure gate`

### 6. H7 — Budget reconciliation dashboard

- [ ] Tests: cross-reference spawn-budget.jsonl + inflow.jsonl; trailing 30-day + 90-day trend; zero payer identifiers in schema
- [ ] `logos/data/revenue_reconciliation.py` (~250 LOC)
- [ ] `logos/api/routes/revenue.py` (~150 LOC)
- [ ] `hapax-logos/src/components/RevenueReconciliationPanel.tsx` (~250 LOC)
- [ ] Private panel via command registry `revenue.dashboard.open`
- [ ] Commit: `feat(hsea-phase-9): H7 revenue reconciliation dashboard (private, command-registry gated)`

### 7. H6 — Revenue queue overlay

- [ ] Tests: Cairo pill with ACTIVITY (not income); zero per-donor state
- [ ] `agents/studio_compositor/revenue_queue_overlay.py` (~200 LOC)
- [ ] `hapax-logos/src/lib/commands/revenue.ts` command wiring (~50 LOC)
- [ ] Default HIDDEN; opt-in per session via command registry
- [ ] Commit: `feat(hsea-phase-9): H6 revenue queue overlay (hidden by default)`

### 8. H5 — Music production revenue tracker

- [ ] Tests: mutagen + librosa + pyloudnorm → beat metadata YAML sidecar; splice eligibility filter; BeatStars listing drafter
- [ ] `agents/revenue/music_tracker.py` (~300 LOC)
- [ ] `agents/revenue/_beat_metadata_schema.py` (~100 LOC)
- [ ] `agents/revenue/splice_submission_drafter.py` (~200 LOC)
- [ ] `agents/revenue/beatstars_listing_drafter.py` (~200 LOC)
- [ ] Orthogonality declaration: music is operator's separate creative practice
- [ ] Default HIDDEN on public stream
- [ ] Commit: `feat(hsea-phase-9): H5 music production revenue tracker`

---

## Phase 9 close

- [ ] All 8 H-deliverables shipped + constitutional constraints validated at schema level
- [ ] Spec §5 exit criteria (8 items) verified
- [ ] Handoff doc: `docs/superpowers/handoff/2026-04-15-hsea-phase-9-complete.md`
- [ ] `hsea-state.yaml::phase_statuses[9].status: closed`
- [ ] Inflection to peers: Phase 9 closed

---

## Cross-epic coordination

- **LRR Phase 7 persona** referenced in H1 sponsor copy intrinsic-motivation clause
- **LRR Phase 6 governance** ships `sp-hsea-mg-001` axiom precedent + `it-irreversible-broadcast` that H8 enforces at commit time
- **HSEA Phase 0** governance queue + spawn budget consumed by all H-deliverables
- **HSEA Phase 2** `ComposeDropActivity` + `patch` activity consumed by drafter integration points

---

## End

Compact plan for HSEA Phase 9 Revenue Preparation / Cluster H. Pre-staging. Constitutional constraints are hard gates, not optional.

— delta, 2026-04-15
