# HSEA Phase 9 — Revenue Preparation (Cluster H) — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction; HSEA execution remains alpha/beta workstream)
**Status:** DRAFT pre-staging — awaiting UP-12 parallel cluster basket opening + operator review for revenue-handling constraints
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 9 (detailed H1-H8)
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-9-revenue-preparation-plan.md`
**Branch target:** `feat/hsea-phase-9-revenue-preparation`
**Cross-epic authority:** drop #62 §5 UP-12 parallelizable cluster basket + §10 Q6 (Cluster H timing, operator ratified UP-12 week 4-6 per 05:35Z)
**Unified phase mapping:** UP-12 sibling — ~2,800 LOC across 8 H-deliverables

---

## 1. Phase goal

Ship the **8 revenue preparation touch points** that drop #58 silently omitted: sponsor copy drafter, NLnet grant drafter, consulting pull channel + employer pre-disclosure gate, grant deadline tracker, music production revenue tracker, revenue queue overlay, budget reconciliation dashboard, and axiom compliance gate for revenue-specific patterns.

**Key constitutional constraint:** Hapax prepares revenue artifacts; **operator delivers**. Every H-deliverable produces drafts + staging + audit; none auto-posts or auto-submits anything. The `sp-hsea-mg-001` axiom precedent from HSEA Phase 0 0.5 ("drafting constitutes preparation, not delivery") is the foundational rule; H-cluster is the operational test of that rule at scale.

**What this phase is:** sponsor copy drafter + NLnet drafter + consulting gate + deadline tracker + music revenue tracker + revenue queue overlay + budget reconciliation + axiom compliance gate.

**What this phase is NOT:** does NOT auto-post sponsorships, does NOT auto-submit grant applications, does NOT execute consulting contracts, does NOT process payments, does NOT track individual donors (zero per-payer state per the "thermometer not scoreboard" commitment from LRR Phase 7 persona spec).

---

## 2. Dependencies + preconditions

1. **LRR UP-0 + UP-1 closed.**
2. **LRR UP-8 (governance finalization) closed** — Cluster H writes require the `sp-hsea-mg-001` precedent landed + `corporate_boundary` axiom formalized
3. **HSEA UP-2 closed** — governance queue + spawn budget + axiom precedent draft all consumed
4. **HSEA UP-10 closed** — `ComposeDropActivity` base for drafters
5. **LRR UP-9 (persona) closed** — the "intrinsic motivation" clause in H1 sponsor copy references the persona's engagement commitments (thermometer not scoreboard, fixed transparent relationship, recursion is the feature, don't reward sentiment)
6. **Employer pre-disclosure gate (H3) MUST complete Phase 1 before Phase 2 unlocks** — this is a constitutional hard gate
7. **Operator review bandwidth for revenue artifacts** — H1-H8 all produce drafts that go to operator inbox; operator reviews + approves before anything ships to the world

---

## 3. Deliverables (8 H-items)

### 3.1 H1 — Sponsor copy drafter

**Scope (per epic spec §5 Phase 9 9.1):**
- `agents/revenue/sponsor_copy_drafter.py` — pydantic-ai agent
- Pydantic validators enforce "no deliverables" clause + "work continues regardless" thank-you framing at field level
- `TierCopy` output type with per-tier validation
- Drafts: tier descriptions (≤$25 to keep relationships anonymous), GitHub Sponsors profile copy, Ko-fi profile copy, Nostr profile copy, FAQ, thank-you variant library
- **Hardcoded intrinsic-motivation clause in system prompt** — operator cannot override via input
- Operator reviews in Obsidian inbox; dispatches via `dispatch-approved.sh sponsor-copy <id>` — clipboard only, never auto-posts
- **Target files:** `agents/revenue/sponsor_copy_drafter.py` (~350 LOC), `agents/revenue/_tier_copy_schema.py` (~120 LOC pydantic schema + validators), tests (~250 LOC)
- **Size:** ~720 LOC

### 3.2 H2 — NLnet NGI0 grant drafter

**Scope (per epic spec §5 Phase 9 9.2):**
- `agents/revenue/nlnet_grant_drafter.py` — pydantic-ai agent, `reasoning` tier for draft-1, `balanced` for polish, `capable` (Opus) for optional final pass
- Three candidate drafts (operator selects which to pursue):
  (a) camera 24/7 resilience as Rust library
  (b) constitutional governance framework
  (c) multi-agent research pipeline
- **Provenance-backed milestones only** — extracts claimed milestones from research drops #32-#59; NEVER invents or extrapolates
- If fewer than 3 provenance-backed milestones exist for a candidate, emits `INSUFFICIENT_PROVENANCE` marker instead of hallucinating
- Budget derivation: labor-only, rate ceiling 20% of operator day-job rate (configurable in `config/nlnet-budget.yaml`)
- Submission checklist with 5 gates (provenance verified, budget under ceiling, narrative includes failure modes, artifact links live, FSF-compatible license statement)
- NLnet cycle: 1st of every even month (continuous review); deadline tracker (H4) fires T-14d alert
- **Target files:** `agents/revenue/nlnet_grant_drafter.py` (~500 LOC), `agents/revenue/_provenance_extractor.py` (~250 LOC), `config/nlnet-budget.yaml`, tests (~350 LOC)
- **Size:** ~1,100 LOC

### 3.3 H3 — Consulting pull channel drafter + employer pre-disclosure gate

**Scope (per epic spec §5 Phase 9 9.3):**
- **Two-phase workflow with hard gate:**
  - **Phase 1 (always runs):** drafts an employer pre-disclosure email for the operator to send to their day-job employer BEFORE any consulting artifacts go public. Content: proposed consulting scope, conflict-of-interest framing, hours expectation, approval request.
  - **Phase 2 (ONLY runs after operator flips `consulting-gate.json::phase_1_acknowledged: true`):** drafts public consulting artifacts — one-line footer, rate card, contract boilerplate skeleton, pitch response template
- Engagement types supported: short-form (days), medium-form (weeks); **long-form (months) explicitly OUT OF SCOPE** — constitutional constraint protects the day-job boundary
- **Post-generation regex check:** every Phase 2 artifact must contain the literal string `"no long-term engagements"` (or equivalent; validated at field level)
- **Target files:** `agents/revenue/consulting_channel_drafter.py` (~400 LOC with phase 1 + phase 2 gate logic), `~/hapax-state/revenue/consulting-gate.json` (operator-controlled flag), tests (~300 LOC)
- **Size:** ~700 LOC

### 3.4 H4 — Grant deadline tracker overlay

**Scope (per epic spec §5 Phase 9 9.4):**
- `agents/revenue/grant_deadline_fetcher.py` — deterministic fetcher on daily timer, reads public NLnet cycle dates
- Cairo overlay zone showing next cycle countdown + current candidate status
- T-14 days trigger: writes impingement, DMN pipeline recruits H2 drafter (if not already triggered)
- Public livestream visibility: **default HIDDEN** (revenue preparation is private content)
- **Target files:** `agents/revenue/grant_deadline_fetcher.py` (~200 LOC), `agents/studio_compositor/grant_deadline_overlay_source.py` (~180 LOC Cairo), `systemd/user/hapax-grant-deadline-fetcher.timer` (daily), tests (~150 LOC)
- **Size:** ~530 LOC

### 3.5 H5 — Music production revenue tracker

**Scope (per epic spec §5 Phase 9 9.5):**
- **Orthogonality declaration:** music revenue is operator's SEPARATE creative practice, outside Hapax constitutional constraints. Hapax tracks preparation + distribution, not the creative work itself.
- Beat metadata extraction via `mutagen` (file metadata) + `librosa` (audio analysis) + `pyloudnorm` (loudness normalization check) → YAML sidecar per beat
- Splice submission workflow: eligibility filter (loudness + duration + format) + candidate packs
- BeatStars listing drafter (same review-then-dispatch pattern)
- Optional Sierpinski slot "splice pack X queued" — **gated off public stream by default**
- **Target files:** `agents/revenue/music_tracker.py` (~300 LOC), `agents/revenue/_beat_metadata_schema.py` (~100 LOC), `agents/revenue/splice_submission_drafter.py` (~200 LOC), `agents/revenue/beatstars_listing_drafter.py` (~200 LOC), tests (~300 LOC)
- **Size:** ~1,100 LOC

### 3.6 H6 — Revenue queue overlay

**Scope (per epic spec §5 Phase 9 9.6):**
- `agents/studio_compositor/revenue_queue_overlay.py` — Cairo overlay showing revenue preparation ACTIVITY (not income)
- Example: `"NLnet draft 78% · sponsor copy staged · T+14d"`
- **Zero per-donor state** — shows Hapax's preparation work, not operator's revenue
- Default hidden on public livestream; opt-in per session via command registry `revenue.overlay.show`
- **Target files:** `agents/studio_compositor/revenue_queue_overlay.py` (~200 LOC), `hapax-logos/src/lib/commands/revenue.ts` (~50 LOC command wiring), tests (~120 LOC)
- **Size:** ~370 LOC

### 3.7 H7 — Budget reconciliation dashboard

**Scope (per epic spec §5 Phase 9 9.7):**
- `logos/data/revenue_reconciliation.py` + `logos/api/routes/revenue.py`
- Cross-references `~/hapax-state/spawn-budget.jsonl` (HSEA Phase 0 0.3) + operator-maintained `~/hapax-state/revenue/inflow.jsonl` (operator transcribes bank statements manually)
- Trailing 30-day spend vs inflow, rolling delta vs operator-configured floor (e.g., $210/month), 90-day trend
- Private panel in hapax-logos, reachable via command registry `revenue.dashboard.open` only
- **Zero payer identifiers in schema** — operator's responsibility to transcribe bank statements in a non-identifying format
- **No nagging/pressure language** — cognitive prosthetic not goal tracker
- **Target files:** `logos/data/revenue_reconciliation.py` (~250 LOC), `logos/api/routes/revenue.py` (~150 LOC), `hapax-logos/src/components/RevenueReconciliationPanel.tsx` (~250 LOC), tests (~200 LOC)
- **Size:** ~850 LOC

### 3.8 H8 — Axiom compliance gate (revenue patterns extension)

**Scope (per epic spec §5 Phase 9 9.8):**
- `hooks/scripts/axiom-patterns-revenue.sh` — extension to `axiom-commit-scan.sh` with revenue-specific patterns
- Rejects (commit blocks):
  - `\bdonors?\b` — implies per-donor tracking
  - `\bsubscribers?\b` — implies subscription relationship
  - `\bguarantee\b` + `\bpromise\b` — implies commitment language
  - Email/phone patterns in sponsor-position context
- Advisory-only (warning, not blocking) for missing "work continues regardless" clause — **promoted to BLOCKING after 30 days** (gives operator time to author sponsor copy with the clause before strict enforcement)
- **Target files:** `hooks/scripts/axiom-patterns-revenue.sh` (~150 LOC), `hooks/scripts/axiom-commit-scan.sh` integration (~20 LOC edit), tests (~100 LOC bats)
- **Size:** ~270 LOC

---

## 4. Phase-specific decisions

1. **H3 employer pre-disclosure is a HARD GATE** — Phase 2 public consulting artifacts are gated behind `consulting-gate.json::phase_1_acknowledged: true`. This is a constitutional constraint protecting the operator's day-job. No override.

2. **H5 music revenue is ORTHOGONAL** — music creative work is outside Hapax constitutional scope. Hapax tracks preparation + distribution, not the music itself.

3. **H1 + H2 + H6 + H7 are all operator-private by default.** Public livestream visibility requires explicit operator opt-in per session via command registry.

4. **H2 provenance-backed milestones only** — if fewer than 3 exist for a grant candidate, emit `INSUFFICIENT_PROVENANCE` marker. This is a research-integrity constraint preventing grant-driven hallucination.

5. **Drop #62 §10 Q6 ratification** — Cluster H timing accepted at UP-12 week 4-6 cadence. No acceleration.

6. **Substrate-agnostic.** All H-deliverables work on any LLM; no §14 reframing.

---

## 5. Exit criteria

1. **H1 sponsor copy draft** produced with all constitutional constraints validated at schema level
2. **H2 NLnet application draft** for one candidate with at least 3 provenance-backed milestones
3. **H3 consulting pre-disclosure email draft** produced; Phase 2 artifacts locked until operator acknowledges
4. **H4 deadline tracker** running with real NLnet cycle data
5. **H5 music beat metadata** extracted for at least 5 operator beats
6. **H6 revenue queue overlay** registered + hidden by default
7. **H7 revenue reconciliation dashboard** accessible via command registry
8. **H8 axiom compliance gate** rejects `\bdonors?\b` + similar patterns in a test commit
9. `hsea-state.yaml::phase_statuses[9].status == closed`
10. Phase 9 handoff doc written

---

## 6. Risks + mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| H1 sponsor copy leaks per-donor tracking language | Constitutional violation | H8 axiom compliance gate catches at commit time; pydantic validators catch at generation time |
| H2 NLnet drafter hallucinates milestones | Research integrity violation | `INSUFFICIENT_PROVENANCE` marker + provenance extractor cross-reference |
| H3 Phase 2 artifacts drafted before operator acknowledges Phase 1 | Day-job conflict of interest | Hard gate on `consulting-gate.json` flag; no code path bypasses |
| H5 music tracker leaks operator creative work to public stream | Privacy violation | Sierpinski slot default-hidden; per-session opt-in only |
| H7 dashboard encodes payer identity by mistake | Consent violation | Schema has zero payer identifier fields; operator transcribes anonymized |
| H8 axiom gate false-positives on legitimate commits | Development friction | Pattern tuning + override via explicit `HAPAX_REVENUE_GATE_SKIP=1` for specific cases |
| Operator review bandwidth overwhelmed by 8 drafts | Queue backup | Spawn budget caps per-drafter ≤1/day; operator controls cadence |
| H1 + H6 on same livestream session cause collision | Visual contention | H6 default-hidden; opt-in only |

---

## 7. Open questions

1. **H2 NLnet budget ceiling** default — epic spec says "20% of operator day-job rate"; actual rate operator-configured
2. **H3 Phase 1 email recipient address** — operator-specified
3. **H5 splice submission eligibility** — operator-tuned thresholds (loudness, duration, format)
4. **H6 revenue overlay default visibility** — confirmed HIDDEN per constitutional constraint; operator can override per session
5. **H7 monthly floor** — $210/month default per epic spec; operator-configured
6. **H8 advisory → blocking promotion timeline** — 30 days default; operator can extend if sponsor copy not ready

---

## 8. Plan

`docs/superpowers/plans/2026-04-15-hsea-phase-9-revenue-preparation-plan.md`. Execution order:
1. H8 axiom compliance gate (first — enforce constraints BEFORE drafters generate content)
2. H1 sponsor copy drafter
3. H4 deadline tracker + overlay (unblocks H2 timing)
4. H2 NLnet drafter (complex)
5. H3 consulting two-phase drafter
6. H7 reconciliation dashboard
7. H6 revenue queue overlay
8. H5 music revenue tracker (operator-private; ships last or parallel)

---

## 9. End

Pre-staging spec for HSEA Phase 9 Revenue Preparation / Cluster H. 8 H-deliverables implementing the "Hapax prepares, operator delivers" pattern for revenue artifacts. Substrate-agnostic.

Fourteenth complete extraction in delta's pre-staging queue this session.

— delta, 2026-04-15
