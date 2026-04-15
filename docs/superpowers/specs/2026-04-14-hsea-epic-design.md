# HAPAX SELF-EXECUTING AGENT (HSEA) — Epic Design

**Date:** 2026-04-14 CDT
**Author:** delta (research support role)
**Status:** DRAFT — awaiting operator sign-off before Phase 0 open
**Authority:** this document supersedes drops #58 and #59 as the build authority; the drops remain in the audit trail as thesis + audit artifacts
**Predecessor research:**
- drop #54 (v1 speculative Bayesian analysis)
- drop #55 (v2 single-axis grounded analysis)
- drop #56 (v3 novelty + platform value correction)
- drop #57 (tactical roadmap — operator executes)
- drop #58 (thesis: Hapax-executes-tactics-as-content)
- drop #59 (critical audit of drop #58 — identified ~55% correctness errors, 26% coverage gaps, 23 missed opportunities)

**Companion plan doc:** `docs/superpowers/plans/2026-04-14-hsea-epic-plan.md` (execution companion)

**Parallel epic:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` (LRR) — HSEA Phase 4 (code-drafting) depends on LRR Phase 1 (T1.3 PyMC 5 BEST port) having shipped.

---

## 0. Headline

> "Every tactic in drop #57 becomes an instance of the same generic pattern: Hapax detects a need → Hapax drafts a response → Hapax renders the drafting as stream content → operator approves in Obsidian → Hapax executes the approved action → result feeds back into the next detection cycle." — drop #58 §12

**HSEA operationalizes this pattern.** The epic ships ~2,820 LOC of shared primitives (Phase 0) followed by ~110 touch points across 9 clusters (Phases 1-12), each of which makes Hapax execute operator tactics as visible livestream content under constitutional governance. The constitutional axiom `management_governance` ("LLMs prepare, humans deliver") becomes the content-generating mechanism: Hapax's visible *preparation* is the stream content; the operator's discrete *delivery* is the governance ritual. What looks like friction becomes a pacing device.

The epic is corrected for drop #59's audit findings. Where drop #58 silently omitted a cluster (Revenue) or a class of work (Code-drafting for critical-path PRs), HSEA adds Clusters H (Revenue preparation) and I (Code drafting). Where drop #58 referenced infrastructure that did not exist (~55% file-reference error rate), HSEA Phase 0 explicitly builds that infrastructure as its first deliverable. Where drop #58 missed compositions from the unique Legomena infrastructure (biometric, studio, archival), HSEA Phase 5 adds the M-series touch points — the biometric + studio + archival-as-content triad.

**End-state:** Legomena Live is a 24/7 livestream where Hapax visibly drafts research drops, code patches, grant applications, sponsor copy, exemplar proposals, and constitutional decisions; narrates its own anomalies and recoveries; schedules itself on the operator's biometric ultradian rhythm; reads its own past reactions as content; and proposes changes to its own prompt for operator approval — all under an operator-controlled approval gate, with every consequential action routed through `~/Documents/Personal/00-inbox/` for operator delivery. The operator is the constitutional authority for a self-executing substrate.

**Cross-epic relationship (added by drop #62 fold-in).** HSEA does not own the research substrate, the persona spec, the governance amendments, the closed-loop wiring, the per-condition observability, or the substrate swap. Those are all LRR scope. HSEA's role is to (a) ship the shared content-execution primitives (governance queue, spawn budget, promote scripts), (b) ship the visibility surfaces that make LRR's work into stream content, and (c) ship the new work that LRR does not touch (clip mining, revenue preparation, M-series biometric/studio/archival, reflexive content). Drop #62 (`docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`) is the authoritative dependency map and the ownership declarations in §3 of drop #62 take precedence over any conflicting claim in this spec.

**Scope is closed.** This epic does not add requirements beyond drop #57 + drop #59's audit corrections. It sequences everything already captured into implementable phases with explicit dependencies, gates, and exit criteria.

---

## 1. Prior art + reconciled predecessors

This epic supersedes or absorbs:

| Document | Status | Relationship |
|---|---|---|
| drop #57 (tactical roadmap — operator-executes) | Preserved; reframed as input to HSEA | The 38 tactics in drop #57 become touch points that Hapax executes. HSEA phases cluster the tactics by execution pattern, not by tier. |
| drop #58 (thesis) | Preserved in audit trail | The architectural reframe (Hapax-executes-as-content) is HSEA's core thesis. Specific touch-point enumerations are reclustered and corrected per drop #59. |
| drop #59 (audit) | Preserved | Drop #59's 10 uncovered tactics + 23 missed opportunities + corrections to file/budget/posterior claims are all absorbed as HSEA scope items. |
| LRR epic (`docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md`) | Parallel, dependency-coupled; cross-mapped by drop #62 | HSEA is structurally a content-execution layer above LRR. LRR ships the substrate (registry, archive, governance, persona, observability, closed loop, substrate swap). HSEA reads all of LRR's outputs and renders them as visible drafting work routed through an operator-controlled approval queue. The two epics share five primitive families (frozen-files, condition_id, research-marker, research-registry CLI, stats.py BEST port); LRR owns all five and HSEA reads them. See `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §3 for the canonical ownership table and §5 for the unified 14-phase sequence (UP-0 through UP-13). |
| Camera 24/7 resilience epic | Shipped, reused | HSEA Phase 2 (self-monitoring) extends the existing recovery FSM with narration; does not rebuild it. |
| Compositor unification epic | Shipped, reused | All HSEA Cairo sources run on `CairoSourceRunner` (no streaming-thread work). |
| Reverie source registry completion epic | Shipped, reused | HSEA Phase 5 M5 (Reverie as cognitive write channel) builds on the existing 9 expressive dimensions. |

**Not merged here:** LRR remains a distinct epic. HSEA is an execution layer *on top of* LRR's research harness. Both run in parallel; both depend on shared primitives (frozen files, research registry, consent axioms).

---

## 2. Pre-epic verification findings (2026-04-14)

Drop #59's audit verified 22 specific claims from drop #58 against the codebase. Key findings informing HSEA scope:

**Missing primitives (Phase 0 work, corrected per drop #62 fold-in):**

HSEA Phase 0 ships:
- `shared/prom_query.py` — does not exist (HSEA owns, 0.1)
- `~/hapax-state/governance-queue.jsonl` — does not exist (HSEA owns, 0.2)
- `~/hapax-state/spawn-budget.jsonl` — does not exist (HSEA owns, 0.3)
- `scripts/promote-*.sh` + `_promote-common.sh` — do not exist (HSEA owns, 0.4)
- Axiom precedent YAML — does not exist (HSEA drafts 0.5; LRR Phase 6 (UP-8) ships in a joint `hapax-constitution` PR)
- `~/.cache/hapax/relay/hsea-state.yaml` — does not exist (HSEA owns, 0.6)

**LRR-owned primitives (HSEA READS these, does not duplicate):**
- `scripts/check-frozen-files.sh` / `.py` — **LRR Phase 1 (UP-1) owns.** HSEA Phase 0 adds a thin `--probe` wrapper ONLY after LRR Phase 1 merges.
- `~/hapax-state/research-registry/` — **LRR Phase 1 (UP-1) owns.** HSEA reads via standard filesystem interface.
- `/dev/shm/hapax-compositor/research-marker.json` — **LRR Phase 1 (UP-1) owns.** HSEA reads atomically.
- `scripts/research-registry.py` — **LRR Phase 1 (UP-1) owns.** HSEA does not extend the CLI; new subcommands go upstream to LRR.
- `condition_id` tagging (Qdrant + JSONL + Langfuse) — **LRR Phase 1 (UP-1) owns.** HSEA tags consume.
- `shared/exemplars.yaml` + `shared/antipatterns.yaml` — **HSEA Phase 0 ships the empty YAML shells; LRR Phase 7 (UP-9) populates them.**
- `stats.py` PyMC 5 BEST port — **LRR Phase 1 (UP-1 item 7) owns.** HSEA Phase 4 I1 drafter rescoped to narration-only.

**Not HSEA work (previously misattributed):**
- `agents/code_drafter/` — NOT a foundation primitive. Created in HSEA Phase 4 Cluster I, which is now **rescoped** (see §4 Phase 4) to narration-only drafters for I1-I5; only I6 (conditional) and I7 remain as code-generation drafters.
- `agents/revenue/` — HSEA Phase 9 Cluster H creates this; no change from original spec.

**Existing primitives (reused):**
- `agents/studio_compositor/director_loop.py::ACTIVITY_CAPABILITIES` — exists with 6 activities (`react`, `chat`, `vinyl`, `study`, `observe`, `silence`). HSEA adds 7+ new activities incrementally per phase.
- `agents/studio_compositor/overlay_zones.py` + `sierpinski_renderer.py` + `cairo_source.py` — Cairo source infrastructure is production-ready.
- `agents/studio_compositor/atomic_io.py::atomic_write_json` — atomic tmp+rename pattern, usable as-is.
- `agents/research.py` — existing pydantic-ai RAG agent (narrower than drop #58 implied; Phase 7 extends it).
- `scripts/research-registry.py::_write_marker` — condition_id flow works for reaction tagging.
- `agents/studio_compositor/chat_reactor.py` — PresetReactor with consent guardrail (caplog test enforced). HSEA Phase 2 reuses for audience preset-chain composition.
- `agents/hapax_daimonion/presence_engine.py` — Bayesian presence fusion. HSEA Phase 5 M1 consumes it.
- `hapax-watch` receiver + IR NoIR fleet + contact mic + album identifier — all live, all reusable.
- `shared/qdrant_schema.py` — 10 collections including `operator-corrections`, `axiom-precedents`, `stream-reactions` (2,758 entries), `documents`. HSEA Phase 5 consumes these.

**Constitutional state:**
- `axioms/registry.yaml` contains 5 constitutional axioms — all preserved without modification
- `axioms/implications/management-governance.yaml` — HSEA Phase 0 adds one implication (`mg-drafting-visibility-001`)
- `axioms/precedents/seed/` contains retroactive precedents; HSEA creates `axioms/precedents/hsea/` for epic-specific precedents
- `hooks/scripts/axiom-commit-scan.sh` — Phase 0 extends with HSEA-specific patterns (auto-delivery detection, revenue compliance)

**Research state:**
- `cond-phase-a-baseline-qwen-001` is the active research condition; frozen files include `conversation_pipeline.py`, `grounding_evaluator.py`, `persona.py`, `conversational_policy.py`
- `camera_pipeline.py` is NOT frozen (verified during drop #52 FDL-1 work)

**Budget state:**
- Current local inference cost is $0 (TabbyAPI Qwen3.5-9B)
- HSEA adds Claude Sonnet (`balanced`) + Claude Opus (`capable`, new alias) cloud calls
- Phase 0 spawn-budget ledger enforces default $5/day cap; operator can adjust

---

## 3. Guiding principles

Derived from drops #57, #58, #59 + operator pushback sequences:

**P-1: Hapax prepares, operator delivers — visibly.** Every consequential artifact routes through the governance queue. No code commits directly. No PR merges. No external posts. Hapax's preparation is stream content; the operator's delivery is off-stream ritual. This is the constitutional axiom operationalized, not violated.

**P-2: Shared primitives before touch points.** Phase 0 ships 6 load-bearing primitives. No Phase >0 opens until Phase 0 closes. The drop #58 error of treating unbuilt primitives as existing is the anti-pattern this principle prevents.

**P-3: Concrete-artifact anti-slop discipline universally.** Every reflexive, critical, or narrative touch point must cite a concrete artifact — reaction index, condition_id, PR number, drop filename, metric value, dimension state. Pure prose reflexivity is rejected at schema level. This single constraint is what separates Hapax's reflexive content from Neuro-sama-style "do you think I'll ever be real" slop.

**P-4: Carved exception for long-form research drafting.** The anti-slop rule in P-3 cannot apply to long-form research drafting where forward-looking synthesis is the point. Cluster A (research authoring) operates under a modified discipline: drafts must cite prior drops where applicable, must stay within scientific register, but may contain hypothesis and synthesis that pre-dates its own citation. Drop #59 flagged this tension; P-4 resolves it.

**P-5: Revenue is Hapax-preparable and constitutionally compatible.** Drop #58 silently omitted revenue; drop #59 identified this as the largest categorical gap. Cluster H ships revenue preparation work with hard workflow gates (employer pre-disclosure for consulting, intrinsic-motivation-preserving copy for sponsors, provenance-backed milestones for grants). Revenue is not the goal — break-even protection is — but it is Hapax-executable under constitutional constraint.

**P-6: Critical-path code changes are first-class Hapax-drafted artifacts.** Cluster I (Code Drafting) ships per-task drafters for every drop #57 critical-path item (T1.3 PyMC 5 BEST, T1.7 stimmung prior, T2.2 burst cadence, T2.6 8B pivot, T2.8 guardrail, T4.8 YouTube tee, T4.11 ritualized states). Hapax writes the code; operator reviews; `promote-patch.sh` applies.

**P-7: The biometric + studio + archival triad is the Legomena novelty surface.** Drop #59's top 5 missed opportunities all cluster here. Phase 5 ships the triad: biometric-driven proactive intervention (M1), retrieval-augmented operator memory (M2), studio creative-state composition (M3), long-horizon drift detection (M4), Reverie as cognitive write channel (M5). This is what makes Legomena unique; no other stream can do it.

**P-8: Budget discipline is constitutional.** The spawn-budget ledger (Phase 0 deliverable) is a hard kill-switch. Default $5/day global cap. Per-touch-point caps prevent runaway spawns. Opus-tier calls rate-limited to ≤3/day. Budget exhaustion is a visible stream event, not a silent failure.

**P-9: Frozen files are universal.** Every HSEA touch point that could commit code respects `scripts/check-frozen-files.py --probe`. Patches to frozen files require DEVIATION documents drafted inline. The research integrity commitment from LRR is preserved across all HSEA phases.

**P-10: Append-only research artifacts.** Research drops (drops #60+) are append-only. Hapax can draft new drops; Hapax can reference old drops; Hapax cannot edit old drops (except for errata appendices). This preserves the audit trail across drop-authoring cycles.

**P-11: Operator sustainability is the binding constraint.** The entire epic depends on the operator being willing to run it for months. Phase 5 M1 (biometric proactive intervention) and Phase 10 (reflexive stack) both explicitly serve operator sustainability. If the operator cannot sustain attention through Phases 0-12, HSEA does not ship.

**P-12: Visibility is content, not delivery.** The HSEA core insight: rendering Hapax's drafting on the livestream is not delivery of the drafted artifact; delivery is a distinct operator action. This principle is codified as axiom precedent `sp-hsea-mg-001` (Phase 0 deliverable).

---

## 4. Phase summary

| # | Phase | Goal | Clusters | Dependencies | Effort |
|---|---|---|---|---|---|
| **0** | Foundation primitives | Ship the 6 load-bearing primitives (prom_query, governance queue, spawn budget, promote scripts, axiom precedent, epic state file) | Foundation | — | ~2,820 LOC · 3.6 d |
| **1** | Visibility surfaces | Ship the 5 foundational Cairo surfaces (HUD, research state broadcaster, glass-box prompt, orchestration strip, governance queue overlay) | A·C·D·G partial | 0 | ~1,200 LOC · 2.5 d |
| **2** | Core director activities | Extend director loop with new activities: `draft`, `reflect`, `critique`, `patch`, `compose_drop`, `synthesize`, `exemplar_review`, `verification_run`. Ship `ReflectiveMomentScorer` gate. | A·B·F foundations | 0, 1 | ~2,500 LOC · 3 d |
| **3** | Research program orchestration | Cluster C full ship: research state broadcaster enrichment, voice session spectator event, attribution audit narration, Phase 4 PR drafter, OSF amendment drafter, publishable result composer | C | 0, 1, 2, LRR Phase 1 | ~2,800 LOC · 4 d |
| **4** | Code drafting cluster (Cluster I — RESCOPED per drop #62 §4) | Only I7 (T4.11 ritualized states) and I6 (T4.8 YouTube tee, if `rtmp_output.py` is not frozen) ship as code-generation drafters. I1–I5 are rescoped to **narration-only spectator drafters** that watch LRR phases land the actual code. I4 (8B pivot) is owned entirely by LRR UP-7 per the substrate-swap fold-in decision. | I (reduced scope) | 0, 1, 2, **LRR UP-1, UP-7, UP-9** | ~1,100 LOC · 2-3 d (down from 3,500 LOC · 5 d) |
| **5** | Biometric + studio + archival triad (M-series) | M1 biometric proactive intervention, M2 retrieval-augmented operator memory, M3 studio creative-state daemon, M4 long-horizon drift detector, M5 Reverie as cognitive write channel + supporting M-series | M-series (new) | 0, 1, 2 | ~3,200 LOC · 4.5 d |
| **6** | Content quality + clip mining | Cluster B: clipability scorer, exemplar auto-curation, anti-pattern detection, self-A/B prompt testing, clip-miner pipeline, music-aware self-observation | B | 0, 1, 2 | ~2,200 LOC · 3 d |
| **7** | Self-monitoring + catastrophic tail | Cluster D: anomaly narration, FSM recovery narration, recurring-pattern fix proposer, alert triage, postmortem auto-drafter, DMCA pre-check, consent face redaction narration, watchdog self-expansion | D | 0, 1, 2 | ~2,800 LOC · 3.5 d |
| **8** | Platform value curation | Cluster E: live RESEARCH.md, morning briefing ritual, stimmung-annotated git log, spin-off documentation drafter, option-value audit, studio session chronicle, weekly retrospective, governance audit trail, drops publication curator, monthly retrospective | E | 0, 1, 2 | ~2,400 LOC · 3 d |
| **9** | Revenue preparation (Cluster H — NEW) | H1 sponsor copy drafter, H2 NLnet grant drafter, H3 consulting channel drafter + employer gate, H4 deadline tracker overlay, H5 music production tracker, H6 revenue queue overlay, H7 reconciliation dashboard, H8 axiom compliance gate | H (new) | 0, 1, 2 | ~2,000 LOC · 3 d |
| **10** | Reflexive stack (Cluster F) | Reflexive layers F2 `reflect` through F14 meta-meta-reflexivity. Gated by F3 scorer (Phase 2). Always ships after B+E so clipability + platform value exist for reference | F | 0, 1, 2, 6, 8 | ~1,800 LOC · 2.5 d |
| **11** | Multi-agent research spawner (Cluster G) | G1 research_question affordance, G2 weekly self-analysis ritual, G3 live orchestration strip extension, G4-G14 spawn-based touch points. Requires Phase 0 budget ledger enforcing per-touch-point caps | G | 0, 1, 2, 3 | ~3,000 LOC · 4 d |
| **12** | Long-tail integration + handoff | Remaining touch points from drop #58's full inventory after de-dup (~30 items across A-G), session handoff automation, documentation drift sweeper, CI watch + merge queue triage | All | 0-11 | ~2,500 LOC · 3.5 d |

**Totals:** 13 phases · 9 clusters (A-I) + M-series · ~29,000 LOC · ~45 days serial implementation at single-operator velocity.

**Parallelism notes:**
- Phases 3-9 have no mutual dependencies beyond 0/1/2 and can be parallelized across alpha + beta worktrees (with branch discipline).
- Phase 4 (Code Drafting) depends on LRR Phase 1 (PyMC 5 BEST port) for its first per-task drafter (I1); the others are LRR-independent.
- Phases 10-11 sit last because they compound on earlier phases' infrastructure.

---

## 5. Phase specifications

### Phase 0 — Foundation Primitives

**Goal:** Ship the 6 load-bearing primitives without which no other phase can deliver.

**Deliverables:**

**0.1 Prometheus query client** (`shared/prom_query.py`)
- `PromQueryClient` with `instant(query)`, `range(query, start, end, step)`, `scalar(query)`
- `WatchedQuery` declarative abstraction with refresh tiers 0.5/1/2/5 Hz
- `WatchedQueryPool` shared thread pool: one worker per tier, max 4 concurrent loops
- Error handling: degraded-state flag, never raises to caller (Cairo render callbacks must not throw)
- Testability: `respx`-based HTTP mocking
- LOC: ~430 (implementation + tests)
- Serial time: 1 day

**0.2 Governance queue** (`~/hapax-state/governance-queue.jsonl` + `shared/governance_queue.py` + Cairo overlay)
- JSONL schema: `{id, title, type, drafted_at, location, status, approval_path, metadata, status_history}`
- Types enumeration: `research-drop | pr-draft | osf-amendment | axiom-precedent | revenue-draft | code-patch | fix-proposal | exemplar-proposal | antipattern-proposal | sprint-measure-update | distribution-draft`
- Status lifecycle: `drafted → reviewing → approved → executed → archived` OR `drafted → rejected → archived` OR `drafted → expired → archived`
- Concurrency: `fcntl.flock LOCK_EX` for append; `O_APPEND` + sub-PIPE_BUF line sizes for atomicity
- Obsidian inbox sync: drafters write approval path + `id:` frontmatter; inotify watcher updates queue on operator access/edit
- Cairo overlay: persistent badge showing pending count + oldest age + most recent title
- Reap: weekly timer moves archived entries to `~/hapax-state/governance-queue-archive.jsonl`
- LOC: ~720 (queue module + overlay source + inotify watcher + tests)
- Serial time: 1 day

**0.3 Spawn budget ledger** (`~/hapax-state/spawn-budget.jsonl` + caps file + ledger module)
- JSONL schema: one line per LLM call: `{timestamp, touch_point, spawn_id, model_tier, model_id, tokens_in, tokens_out, cost_usd, latency_ms, langfuse_trace_id, status}`
- Caps file: `~/hapax-state/spawn-budget-caps.yaml` (editable by operator): global daily $5, per-touch-point caps, concurrency limits
- Kill-switch interface: `check_can_spawn(touch_point) → BudgetDecision(allowed, reason, projected_cost, current_daily_usd, daily_cap_usd)`
- Cost source: authoritative from LiteLLM response headers + Langfuse `total_cost`; never estimated from tokens
- Budget-exhaustion behavior: publishes `budget_exhausted` impingement, overlay flips to red, daimonion narrates at salience 0.55
- Hysteresis: re-enable at 90% of cap (mostly triggers at UTC midnight)
- Cairo overlay: "today's spawn budget: 47% used, 12 spawns, top 3 categories"
- Integration: extends `mcp__hapax__cost` with per-touch-point attribution
- LOC: ~580 (ledger + overlay + tests)
- Serial time: 0.5 day

**0.4 Prepare/deliver inbox convention** (`scripts/promote-*.sh` + `_promote-common.sh`)
- Directory layout: `~/Documents/Personal/00-inbox/` (existing) + `/dev/shm/hapax-compositor/draft-buffer/<slug>/` (volatile)
- Frontmatter schema: `id`, `type`, `status`, `drafted_at`, `drafted_by`, `location`, `approval_method`, `notes`
- Scripts:
  - `promote-drop.sh` — research drops → `docs/research/<date>-<slug>.md`
  - `promote-patch.sh` — code patches via `git apply` (operator invokes only)
  - `promote-pr.sh` — `gh pr create --draft` only (never --draft=false, never merge)
  - `promote-axiom-precedent.sh` — precedent YAML → `axioms/precedents/hsea/`
  - `promote-exemplar.sh` — exemplar pool updates → `shared/exemplars.yaml`
  - `promote-antipattern.sh` — antipattern list updates → `shared/antipatterns.yaml`
  - `promote-revenue.sh` — revenue drafts → per-target deployment
  - `dispatch-approved.sh` — clipboard-copy for external platforms (never auto-posts)
- Safety gates in `_promote-common.sh`: frozen-files probe, ruff check, pytest smoke, consent scan, axiom scan, idempotency marker
- Operator override: `HAPAX_PROMOTE_SKIP_CHECKS=1` emergency bypass
- Tests: bats-core shell tests for each script + happy path + failure modes
- LOC: ~760 (scripts + common lib + bats tests)
- Serial time: 0.5 day

**0.5 Axiom precedent** (`axioms/precedents/hsea/management-governance-drafting-as-content.yaml`)
- Precedent ID: `sp-hsea-mg-001`
- Decision: drafting constitutes preparation (not delivery) IFF operator retains discrete revocable non-visual delivery authority
- Edge cases: livestream clip extraction, daimonion audible narration, drafts referencing individuals (falls back to existing mg-boundary rules), operator approving without reading, spawn-budget-exhaustion truncation
- New implication `mg-drafting-visibility-001` added to `axioms/implications/management-governance.yaml`
- Enforcement hook: extends `hooks/scripts/axiom-commit-scan.sh` with auto-delivery pattern detection
- LOC: ~220 (precedent YAML + implication + hook + tests)
- Serial time: 0.5 day

**0.6 Epic state file** (`~/.cache/hapax/relay/hsea-state.yaml`)
- Schema mirrors LRR state file: `current_phase`, `last_completed_phase`, `known_blockers`, `phase_statuses[*].{name, status, opened_at, closed_at, spec_path, plan_path, handoff_path, pr_url, branch_name, deliverables[*]}`
- Updates: phase open, deliverable transitions, blocker discovery, phase close
- Reads: `hooks/scripts/session-context.sh` surfaces `HSEA: Phase N · owner=<session> · health=<color>` at session start
- LOC: 110 (YAML)
- Serial time: 0.1 day

**Exit criteria:**
- All 6 deliverables merged to main
- Epic state file exists at `~/.cache/hapax/relay/hsea-state.yaml` with `phase_statuses[0].status: closed`
- Precedent referenced from `axioms/README.md`
- `session-context.sh` extension merged (surfaces HSEA state alongside LRR)
- One end-to-end smoke test: a stub drafter creates a governance queue entry, operator flips frontmatter to `approved`, `promote-drop.sh` executes cleanly
- Phase 0 handoff doc written at `docs/superpowers/handoff/YYYY-MM-DD-hsea-phase-0-complete.md`

### Phase 1 — Visibility Surfaces

**Goal:** Ship the 5 foundational Cairo overlay sources that make all subsequent HSEA work visible on stream.

**Deliverables:**

**1.1 HUD Cairo overlay (D1)**
- New `HudSource(CairoSource)` rendering compositor telemetry at 2Hz: uptime, fd_count bar, cameras healthy/total, per-role frame age, GPU util/VRAM, LLM p95, voice latency, chat authors, current condition_id
- Color-coded via design-language CSS custom properties (no hardcoded hex)
- Consumer of shared Prometheus poller (Phase 0)
- Top-left corner zone, low opacity baseline
- LOC: ~250

**1.2 Research state broadcaster (C1)**
- Persistent Cairo overlay top-right showing: active condition_id, current phase, scores today/target, time since last session, attribution integrity tier, next scheduled session
- Data sources: `research-marker.json`, `condition.yaml`, `~/hapax-state/research-integrity/heartbeat.json`
- Refresh 1Hz Cairo + Sierpinski card every 5 minutes
- LOC: ~200

**1.3 Glass-box prompt rendering (F1)**
- `prompt-glass` Cairo zone rendering current `_build_unified_prompt()` truncated to active section
- Shows: which of last-8 reactions are in context, which 9 dimensions are extreme, current condition_id
- Updates per tick (8s); not narrated
- Foundation for all F-series reflexive layers (without this, layers 2-7 are unfalsifiable narration)
- LOC: ~150

**1.4 Live orchestration strip (G3)**
- `OrchestrationStrip` Cairo source reading `/dev/shm/hapax-orchestration/active.jsonl`
- One line per active sub-agent: id, label, started_at, status, latency_estimate
- Horizontal swimlanes in lower content zone
- Sub-agents write heartbeats via new `hsea_spawn_heartbeat()` append-path (since `hapax_span` has no post-emit hook)
- LOC: ~200

**1.5 Governance queue overlay**
- Renders governance queue state as persistent pill: "2 proposals awaiting review · oldest 3h 14m"
- Color transitions: green (queue empty) → yellow (>24h oldest) → red (>72h oldest)
- Links via command-registry action `governance.queue.open` to Obsidian inbox
- LOC: ~150

**Exit criteria:**
- All 5 Cairo sources rendering in production compositor
- Operator can verify each overlay by running the compositor and observing
- Zone allocation in `overlay_zones.py::ZONES` updated with new zones
- Golden-image regression tests for each source (if existing compositor test harness supports)

### Phase 2 — Core Director Activities

**Goal:** Extend `ACTIVITY_CAPABILITIES` from 6 to 13+ activities, adding the infrastructure for all drafting + reflective + synthesis content.

**Deliverables:**

**2.1 `draft` activity (A1)**
- New activity mode for composing research drops live
- Each tick extends `/dev/shm/hapax-compositor/draft-buffer/<slug>.partial.md`
- `DraftStreamCairoSource` reveals text character-by-character (80-240 chars/sec tuned by stimmung intensity)
- LLM call via `balanced` tier with 1-shot exemplar from existing drops
- Buffer promotion via `promote-drop.sh <slug>`

**2.2 `reflect` activity (F2)**
- New activity reading last 8 reactions + stimmung trajectory + 9-dim state
- Schema requires `noticed: <reaction_index>` — solved via explicit reaction numbering in prompt context
- Anti-slop: reflect calls without concrete index rejected and re-rolled

**2.3 `critique` activity (B4)**
- Reads last 5-10 reactions and critiques pattern + names crutches by name
- Output schema: `{activity, react, noticed, intend}` — `noticed` and `intend` append to reactor log
- Gated by `ReflectiveMomentScorer` (2.7)

**2.4 `patch` activity (D5 — preview of Phase 4)**
- Foundational hook for Cluster I (Phase 4)
- In Phase 2 the activity is a stub that calls a placeholder "no patches available"
- Full implementation lands in Phase 4

**2.5 `compose_drop` activity (G4 foundation)**
- Synthesizes findings from ≥3 sub-agents into a drop draft
- Phase 2 ships the activity; Phase 7 wires the spawn pipeline that produces the findings

**2.6 `synthesize` activity (G9)**
- Takes multiple recent sub-agent findings and composes 30-word synthesis
- Cairo overlay caption; the most compact multi-agent consensus surface

**2.7 `ReflectiveMomentScorer` gate (F3)**
- Score = 0.3·pattern_density + 0.25·stance_specificity + 0.2·time_since_last_reflect/30min + 0.15·chat_quietness + 0.1·condition_change_recency
- Threshold 0.65; cooldown floor 12 ticks
- **Calibration task:** instrument the scorer with a 7-day metrics capture before enabling the gate; tune threshold if empirical frequency diverges from target 1-in-20 rate
- This addresses drop #59 Finding: "1 in 20" was an untested claim

**2.8 Activity taxonomy extension**
- `ACTIVITY_CAPABILITIES` grows from 6 → 13 (add: `draft`, `reflect`, `critique`, `patch`, `compose_drop`, `synthesize`, `exemplar_review`)
- Persona prompt updated to describe each new activity
- Response schema updated with new activity-specific fields
- Downstream consumers (reactor log writer, content scheduler, preset reactor) updated to comprehend new types

**Exit criteria:**
- Director loop successfully alternates between old + new activities in production
- Reactor log captures new activity types with schema validation
- ReflectiveMomentScorer instrumented; calibration data captured
- Regression tests for each new activity against a mocked LLM fixture

### Phase 3 — Research Program Orchestration (Cluster C)

**Goal:** Automate the LRR research program flow end-to-end with Hapax as the preparer at every stage.

**Deliverables** (detailed in drop #58 §3 Cluster C):
- C2 voice grounding session spectator event (`/voice-session` skill)
- C3 attribution audit narration daemon
- C4 Phase 4 PR drafting (reads beta worktree commits, drafts PR body)
- C5 PyMC 5 BEST verification live (depends on LRR Phase 1 merge)
- C6 triple-session ritualized cadence (systemd timers + director activity unlock)
- C7 OSF pre-registration amendment drafter
- C8 8B pivot scheduled spectator event
- C9 confound decomposition teach-in
- C10 research drop auto-generation from milestones
- C11 publishable result composer (Phase A results drop with 5 hard gates)
- C12 research integrity heartbeat (extends C1 with per-second refresh)

**LRR coupling:**
- C5 requires LRR Phase 1 (PyMC 5 BEST) merged
- C6 requires LRR Phase 4 (condition_id plumbing) merged
- C11 requires LRR Phase 4 complete + attribution audit green

**Exit criteria:**
- At least one voice grounding session successfully orchestrated end-to-end through C2
- Attribution audit timer (C3) running and catching at least one simulated fault
- First research drop auto-generated via C10 from a real milestone event

### Phase 4 — Code Drafting Cluster (Cluster I — NEW)

**Goal:** Ship per-task drafters for every drop #57 critical-path code change.

**New alias:** `capable → claude-opus-4-6` added to `shared/config.py` and `agents/_config.py`. The existing `reasoning` alias (local Qwen) is preserved; `capable` is the Opus escalation path.

**Deliverables:**

**4.1 Base code drafter** (`agents/code_drafter/__init__.py`)
- Pydantic-ai agent with `output_type=CodePatch(files: list[FileDiff], test_plan, rationale, risk_assessment, risk_factors, rollback_plan, blocked_by, unblocks)`
- `DrafterDeps(target_task, source_files, conventions, frozen_file_list, line_cap)`
- `build_agent(tier: "balanced" | "capable")` factory
- System prompt including project conventions + explicit "NEVER write git/rm/sudo/curl|sh" constraint
- LOC: ~280

**4.2 Staging infrastructure** (`agents/code_drafter/_staging.py`, `_gates.py`, `_escalation.py`, `_diff.py`, `_conventions.py`)
- `stage_patch()` atomically writes to `~/hapax-state/staged-patches/<ulid>/`
- `run_gates()` runs destructive-regex check, line cap, frozen-files probe (via new `check-frozen-files.py --probe` mode)
- Per-task line caps stored in `config/code_drafter.yaml`
- Opus rate limiter: ≤3/day tracked in `~/hapax-state/opus-drafter-counter.jsonl`
- LOC: ~600 total

**4.3 Per-task drafter subclasses** (per drop #62 §4 + §10 Q3 rescoping, operator-ratified 2026-04-15): 2 code-generation drafters + 5 narration-only spectator drafters. Every former I-drafter whose target file is either LRR-owned or in the active condition's frozen-files manifest has been demoted to narration-only; it watches LRR land the canonical code and drafts a stream-content research drop summarizing the landing, rather than generating the code itself. Net LOC on this cluster: ~1,100 (down from ~3,500 pre-rescoping). See drop #62 `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §8 for the ownership map and the drop #47 DR-7 PR #828 for the PresetInput retirement that closed the source-registry-binding path most of these drafters would have had to touch.

**Code-generation drafters** (write real source patches, route through `promote-patch.sh` + operator inbox):

- **I6 `t4_8_youtube_tee`** — Tee branch for `rtmp_output.py` for backup ingest. Tier: `balanced`. Line cap: 200. **Conditional:** `rtmp_output.py` must NOT be in the active condition's frozen-files manifest at drafter open time. If frozen, I6 demotes to narration-only and the code work moves to a DEVIATION-gated LRR PR.
- **I7 `t4_11_ritualized_states`** — Four ritualized director states (Midnight/Wake/Crate/Last Call) with time-of-day gating. Tier: `balanced`. Line cap: 500. Targets `agents/director_loop/_ritual_states.py` (new file; no frozen-file touch). Survives the rescoping unchanged — drop #62 §8 notes this is the only I-drafter that writes genuinely new HSEA code rather than duplicating LRR work.

**Spectator narrator drafters** (watch LRR phases land the code; draft a research drop summarizing; route through `promote-drop.sh` + operator inbox):

- **I1 `t1_3_pymc5_best_narrator`** — Watches LRR UP-1 (research registry foundation) for PyMC 5 BEST port commits (LRR Phase 1 item 7). Drafts a research drop summarizing the port at landing time. Tier: `balanced`. Line cap: 150 (research drop text). Depends on: LRR UP-1 merged. Original code-generation scope owned by LRR Phase 1, not HSEA.
- **I2 `t1_7_stimmung_prior_narrator`** — Watches LRR UP-11 (LRR Phase 9 closed-loop wiring) for stimmung-gated activity prior commits. Drafts a research drop with the wiring diagram + before/after stimmung traces. Tier: `balanced`. Line cap: 150. Depends on: LRR UP-11 merged.
- **I3 `t2_2_burst_cadence_narrator`** — Watches LRR UP-11 (LRR Phase 9 + Phase 10 PERCEPTION_INTERVAL tuning) for burst/rest cadence state machine commits. Drafts a research drop with state-diagram + cadence histograms. Tier: `balanced`. Line cap: 150. Depends on: LRR UP-11 merged.
- **I4 `t2_6_hermes_8b_pivot_narrator`** — Watches LRR UP-7a (unified Phase 5a, 8B parallel pivot per drop #62 §4 Option C ratification 2026-04-15) for TabbyAPI config + LiteLLM route + conversation_pipeline dispatch landings. Drafts a research drop covering the pivot rationale (drop #56 v3 consent-latency axiom), the fork rationale (drop #62 §4 Option C), the pre-staged scaffolding (PR #826 systemd + LiteLLM drafts), and the activation sequence. Tier: `balanced`. Line cap: 300 (this is the largest narrator drop — substrate swap narrates the full arc from #54 through #62 through operator activation). Depends on: LRR UP-7a merged.
- **I5 `t2_8_guardrail_narrator`** — Watches LRR UP-7a DEVIATION-037 landing (the guardrail bundles into the 8B pivot DEVIATION per drop #62 §10 Q2 ratification 2026-04-15) for `conversation_pipeline.py` validator commits. Drafts a research drop with the validator taxonomy + fixture coverage + first operator-observed violations. Tier: `balanced`. Line cap: 200. Depends on: LRR UP-7a merged + DEVIATION-037 filed.

**4.4 `promote-patch.sh` + `reject-patch.sh`**
- Re-runs final ruff + pytest + frozen-files check + destructive regex
- Applies via `git apply`, stages, commits with Claude-attributed message
- Optional `--pr` flag creates draft PR via `gh pr create --draft`
- Rejection archives bundle to `~/hapax-state/staged-patches/archive/` with reason file

**4.5 Director `patch` activity full implementation**
- Picks task from `config/patch_priorities.yaml`
- Invokes drafter subprocess, streams diff text to Sierpinski slot character-by-character
- Daimonion narrates milestones at salience 0.45
- On approval detection (inotify on inbox frontmatter), re-narrates with commit SHA

**4.6 Mandatory `code_review.py` integration**
- Every staged patch automatically goes through `code_review.agent.run()` before reaching operator inbox
- Review output written to `review_notes.md`
- Operator sees Hapax's self-review before Hapax's work (closes the loop)

**Exit criteria (rescoped per drop #62 §10 Q3):**
- Both code-generation drafters (I6 conditional on `rtmp_output.py` not frozen, I7) produce valid CodePatch outputs against real source files
- All 5 narration-only spectator drafters (I1/I2/I3/I4/I5) produce valid research drop outputs that cite the underlying LRR phase commits by SHA
- At least 1 code patch (from I6 or I7) has gone through the full draft→review→approve→promote cycle successfully
- At least 2 narrator drops have gone through the full draft→review→approve→promote-drop cycle successfully
- `check-frozen-files.py --probe` mode merged (LRR Phase 1 item 4 dependency)
- `capable` alias registered in config
- Opus daily cap enforced by at least one mock test

### Phase 5 — Biometric + Studio + Archival Triad (M-series — NEW)

**Goal:** Ship the top 5 missed opportunities from drop #59 — the unique-to-Legomena novelty surface that no other stream can produce.

**Deliverables:**

**5.1 M1 biometric-driven proactive intervention loop**
- Real-time HUD strip showing operator HRV trend (24h window), sleep-debt score, hours-at-desk, IR-presence streak
- When HRV trends down >X% over 2h AND desk-streak >3h AND no break detected → daimonion prompt at low salience: "HRV trended down 14% in 2h. Want a 20-min break nudge?"
- **Response is operator-private, never on stream**
- Consumes: hapax-watch biometrics, IR presence engine, contact mic activity
- Constitutional: sustains operator commitment which is the binding constraint on everything

**5.2 M2 retrieval-augmented operator memory in voice**
- Before daimonion generates a fresh answer to an operator voice question, it queries Qdrant across `documents` + `stream-reactions` + chronicle + research drops via the operator's narrative as embed query
- If high-similarity prior answer exists (cosine > 0.85), surfaces it first: "You asked about FDL-1 yesterday. Drop #52 traces it to camera_pipeline.stop(). That answer hasn't changed."
- Cited drop + condition_id renders briefly in Sierpinski slot
- Closes the cognitive-prosthetic gap drop #58 identified but never implemented

**5.3 M3 studio creative-state composition daemon**
- Fusion daemon: contact mic BPM/gesture + MIDI clock + stimmung SEEKING + Qdrant beat-archive
- When operator is making something at BPM 94 × 20 min × nothing recorded × similar prior session exists → soft daimonion suggestion
- Visible to stream as "studio scaffold active" pill
- Content kept operator-private (creative work is not public content)
- **Unique to Legomena** — no other AI livestream serves a working hip-hop producer

**5.4 M4 long-horizon stream-reactions drift detector**
- Weekly job reads all 2,758 stream-reactions from Qdrant over 18 months
- PCA over reaction vectors, per-week centroid + dispersion
- Detects drift events: "Slum Village reactions drift from analytical to elegiac framing in last 6 weeks"
- Renders drift trajectory as Sierpinski content slot with cited reaction indices
- **Longest-horizon self-observation the data supports** — no other stream has 2,758 indexed reactions to itself

**5.5 M5 Reverie wgpu as cognitive state write channel**
- Reverie's 9 GPU expressive dimensions become structured write surface (not just input from mood)
- New affordance `gpu_state_signal` with registry of (cognitive event → 9-dim transform) mappings
- Events: frozen-files block, drift detection, anomaly resolution, research integrity flip, condition transition
- Viewers learn to read the pipeline like sheet music
- **Closes the cross-modal write gap** drop #58 never identifies

**5.6 Supporting M-series touch points:**
- M6 accountability ledger surfacing
- M7 cross-reference drops ↔ reactions
- M8 audience-driven preset chain composition (aggregate-only)
- M9 album-identifier editorial expansion
- M10 ultradian rhythm ceremony rescheduling (by HRV not clock)
- M13 spawn-budget heatmap as content
- M15 daimonion-narrated commit walkthrough
- M16 IR-fleet-driven proxemic Reverie response
- M18 vault daily-note → prompt context bridge
- M21 operator-correction live filter (Qdrant NN block)
- M22 operator-absent dream-sequence content
- M23 axiom near-violation narration

**Exit criteria:**
- M1 triggers on simulated HRV drop and produces a daimonion impingement
- M2 retrieval works against real operator voice query
- M3 state machine runs through full session without consent violations
- M4 produces at least one drift detection from 90 days of reaction history
- M5 affordance registry wired to at least 3 event types

### Phase 6 — Content Quality + Clip Mining (Cluster B)

**Goal:** Ship the content quality feedback loop — clipability scoring, exemplar curation, anti-patterns, self-A/B testing, clip mining.

**Deliverables** (detailed in drop #58 §3 Cluster B):
- B1 clipability scorer
- B2 exemplar auto-curation (weekly ceremony)
- B3 live anti-pattern detection (grep filter + LLM critic + rewriter)
- B4 `critique` activity (Phase 2 foundation extended)
- B5 self-A/B testing director prompt variants
- B6 condition-boundary retrospection
- B7 self-prompt-engineering proposals (operator-approved)
- B8 music-aware self-observation ("Dilla discipline")
- B10 clip-miner visible decision
- B11 operator-collaboration ceremony

### Phase 7 — Self-Monitoring + Catastrophic Tail (Cluster D)

**Goal:** Ship the anomaly narration + self-healing + catastrophic tail mitigation.

**Deliverables** (detailed in drop #58 §3 Cluster D):
- D2 threshold-crossed anomaly narration
- D3 FSM step-by-step recovery narration
- D4 recurring-pattern detection → fix proposal (extends Phase 4's code drafter infrastructure)
- D6 alert triage on stream
- D8 postmortem auto-drafting
- D9 pre-flight checklist narration
- D10 watchdog self-expansion proposal
- D11 DMCA/Content ID pre-check
- D12 consent face redaction narration
- D13 mobo swap scheduled event

### Phase 8 — Platform Value Curation (Cluster E)

**Goal:** Ship the live RESEARCH.md, morning briefing ritual, stimmung git log, spin-offs, retrospectives.

**Deliverables** (detailed in drop #58 §3 Cluster E):
- E1 live RESEARCH.md maintenance
- E2 morning briefing ritual
- E3 stimmung-annotated git log ticker
- E4 spin-off documentation drafter
- E5 architectural option-value audit narration
- E6 documentation freshness auto-check
- E7 studio session chronicle
- E8 weekly retrospective
- E9 public agent registry rendering
- E10 constitutional governance audit trail
- E11 drops publication pipeline curator
- E12 beat archive integration
- E13 monthly retrospective (long-form)
- E14 platform value posterior (operator-private)

### Phase 9 — Revenue Preparation (Cluster H — NEW)

**Goal:** Ship the 8 revenue preparation touch points drop #58 silently omitted.

**Deliverables:**

**9.1 H1 sponsor copy drafter** (`agents/revenue/sponsor_copy_drafter.py`)
- Pydantic-ai agent with pydantic validators enforcing "no deliverables" clause and "work continues regardless" thank-you framing
- Output schema with `TierCopy` validation at field level
- Drafts tier descriptions (≤$25), GitHub/Ko-fi/Nostr profile copy, FAQ, thank-you variants
- Hardcoded intrinsic-motivation clause in system prompt
- Operator reviews in Obsidian, dispatches via `dispatch-approved.sh sponsor-copy <id>` (clipboard only, never auto-posts)

**9.2 H2 NLnet NGI0 grant drafter** (`agents/revenue/nlnet_grant_drafter.py`)
- Pydantic-ai agent, `reasoning` tier draft-1, `balanced` polish, `capable` optional final
- Three candidate drafts: (a) camera 24/7 resilience as Rust library, (b) constitutional governance framework, (c) multi-agent research pipeline
- **Provenance-backed milestones only** — extracts from drops #32-#59, never invents
- If fewer than 3 provenance-backed milestones exist, emits `INSUFFICIENT_PROVENANCE` marker instead of hallucinating
- Budget derivation: labor-only, rate ceiling 20% of operator day-job rate (configurable)
- Submission checklist with 5 gates
- NLnet cycle: 1st of every even month (continuous review)

**9.3 H3 consulting pull channel drafter + employer pre-disclosure gate** (`agents/revenue/consulting_channel_drafter.py`)
- **Two-phase workflow with hard gate:**
  - Phase 1: Employer pre-disclosure email draft (always runs)
  - Phase 2: Public consulting artifacts (only runs after operator flips `consulting-gate.json: phase_1_acknowledged: true`)
- Engagement types: short-form, medium-form; long-form explicitly out of scope
- Outputs: one-line footer, rate card, contract boilerplate skeleton, pitch response template
- Post-generation regex check: every artifact must contain literal string "no long-term engagements"

**9.4 H4 grant deadline tracker overlay** (`agents/revenue/grant_deadline_fetcher.py` + Cairo source)
- Deterministic fetcher on daily timer reads public NLnet cycle dates
- Cairo overlay zone showing next cycle countdown + current candidate status
- T-14 days trigger: writes impingement, DMN pipeline recruits H2 drafter
- Public livestream visibility: default hidden (revenue preparation is private)

**9.5 H5 music production revenue tracker** (`agents/revenue/music_tracker.py`)
- **Orthogonality declaration:** music revenue is operator's separate creative practice, outside Hapax constitutional constraints
- Beat metadata extraction via `mutagen` + `librosa` + `pyloudnorm` → YAML sidecar per beat
- Splice submission workflow (eligibility filter + candidate packs)
- BeatStars listing drafter
- Optional Sierpinski slot "splice pack X queued" (gated off public stream by default)

**9.6 H6 revenue queue overlay** (`agents/studio_compositor/revenue_queue_overlay.py`)
- Cairo overlay showing revenue preparation activity (not income): "NLnet draft 78% · sponsor copy staged · T+14d"
- **Zero per-donor state** — shows Hapax's preparation work, not operator's revenue
- Default hidden on public livestream; opt-in per session via command registry

**9.7 H7 budget reconciliation dashboard** (`logos/data/revenue_reconciliation.py` + `logos/api/routes/revenue.py`)
- Cross-references `spawn-budget.jsonl` + operator-maintained `~/hapax-state/revenue/inflow.jsonl`
- Trailing 30-day spend vs inflow, rolling delta vs $210/month floor, 90-day trend
- Private panel in hapax-logos, reachable via command registry only
- **Zero payer identifiers in schema** — operator transcribes bank statements manually
- No nagging/pressure language — cognitive prosthetic not goal tracker

**9.8 H8 axiom compliance gate** (`hooks/scripts/axiom-patterns-revenue.sh`)
- Extension to `axiom-commit-scan.sh` with revenue-specific patterns
- Rejects: `\bdonors?\b`, `\bsubscribers?\b`, `\bguarantee\b`, `\bpromise\b`, email/phone patterns in sponsor position
- Advisory-only for missing "work continues regardless" clause (promoted to blocking after 30 days)

**Exit criteria:**
- Sponsor copy draft produced with all constitutional constraints validated at schema level
- NLnet application draft for one candidate with at least 3 provenance-backed milestones
- Consulting pre-disclosure email draft produced; Phase 2 artifacts locked until operator acknowledges
- Deadline tracker running with real NLnet cycle data
- Music beat metadata extracted for at least 5 operator beats
- Revenue reconciliation dashboard accessible via command registry

### Phase 10 — Reflexive Stack (Cluster F)

**Goal:** Ship F2-F14 reflexive layers, gated by F3 scorer from Phase 2.

**Deliverables** (detailed in drop #58 §3 Cluster F):
- F2 `reflect` activity (Phase 2 foundation extended)
- F4 research-harness narration (condition transitions)
- F5 viewer-awareness ambient (aggregate only)
- F6 Bayesian-loop self-reference (once per stream max, cites specific tactic)
- F7 architectural narration (cites PR numbers + service names)
- F8 reading own research drops
- F9 temporal self-comparison via Qdrant
- F10 meta-reflexive override (Qdrant NN anti-cliche) — **ships with or before F2 per drop #59 fix**
- F11 stimmung self-narration
- F12 counterfactual substrate self-reference
- F13 operator-Hapax dialogue cameo
- F14 meta-meta-reflexivity (hard-rate-limited ≤3/stream)

### Phase 11 — Multi-Agent Spawner (Cluster G)

**Goal:** Ship the G-series spawning infrastructure with budget enforcement.

**Deliverables** (detailed in drop #58 §3 Cluster G):
- G1 `research_question` affordance (via `AffordancePipeline`)
- G2 weekly self-analysis ritual (Sunday 04:00 timer)
- G4 drop draft from sub-agent consensus
- G5 tactical re-evaluation on 30-day clock
- G6 voice session parallel scoring
- G7 anomaly analyst spawn
- G8 constitutional decision proxy
- G10 long-running research sessions with checkpoints
- G11 live Langfuse telemetry slot
- G13 emergency analyst (Tier-1)
- G14 multi-agent consensus demonstration

### Phase 12 — Long-tail Integration + Handoff

**Goal:** Complete remaining touch points + ship session handoff automation + documentation drift sweeper + CI watch.

**Deliverables:**
- All remaining touch points from the de-duplicated ~65-item inventory
- Session handoff doc drafter (second-order gap from drop #59)
- CI watch + merge queue triager (second-order gap)
- Documentation drift sweeper (README + CLAUDE.md + spec doc drift)
- Final epic close handoff at `docs/superpowers/handoff/YYYY-MM-DD-hsea-phase-12-complete.md`

**Exit criteria:**
- `~/.cache/hapax/relay/hsea-state.yaml::overall_health == green`
- All 110 touch points either shipped or explicitly deferred with rationale
- Handoff doc describes total LOC shipped, touch points deployed, known open items, recommended next-epic directions

---

## 6. Constitutional axiom precedent (Phase 0 deliverable 0.5)

**Precedent ID:** `sp-hsea-mg-001`
**File:** `axioms/precedents/hsea/management-governance-drafting-as-content.yaml`

**PR vehicle (added by drop #62 fold-in):** This precedent ships in the same `hapax-constitution` PR as LRR Phase 6's `it-irreversible-broadcast` implication, `su-privacy-001` clarification, and `corporate_boundary` clarification. HSEA Phase 0 deliverable 0.5 drafts the YAML; LRR Phase 6 (UP-8) opens the single PR that bundles both epics' constitutional amendments. Operator review is one cycle covering all pieces, not two. This eliminates the risk of partial constitutional state between the two epics.

**Precedent text:**

> **Situation.** The HSEA epic proposes that Hapax draft research drops, code patches, PR bodies, revenue copy, OSF amendments, and other consequential artifacts, and that the drafting process itself be rendered as livestream content (via Cairo overlays, Sierpinski slots, and daimonion voice narration). The question: does rendering Hapax's drafting on a public livestream constitute "delivery" of the drafted artifact, such that the artifact would violate the `management_governance` separation of preparation (LLM) from delivery (operator)?
>
> **Decision.** Drafting constitutes preparation (not delivery) IFF the operator retains a discrete, revocable, non-visual delivery authority for the underlying artifact. The visibility of the drafting process on the livestream is not equivalent to delivery of the artifact; delivery is a distinct operator action that occurs after drafting and that the operator can decline without consequence. Specifically: a research drop is delivered when the operator runs `promote-drop.sh` and the git commit lands; a PR is delivered when the operator runs `promote-pr.sh` and `gh pr create` succeeds; a revenue draft is delivered when the operator pastes from the clipboard into the external platform. In each case, the governance queue entry must transition `drafted → approved → executed` before delivery is complete, and the operator holds sole authority over the `approved → executed` transition. The livestream is a content surface that witnesses drafting; it is not a delivery surface.
>
> **Edge cases:**
> 1. **Livestream clip extraction** — derivative content about Hapax's drafting, not delivery. Source draft remains in drafted status.
> 2. **Audible daimonion narration** — still preparation. Operator can mute daimonion, overlay, or entire stream and still choose not to approve.
> 3. **Draft references individuals** — falls back to `mg-boundary-001` / `mg-boundary-002` directly. Drafts with feedback language about individuals are T0 violations, blocked at draft time.
> 4. **Operator approves without reading** — preserves the axiom. Responsibility for reading-before-approving belongs to the operator.
> 5. **Budget-exhaustion truncation** — truncated draft is still a draft. Status remains `drafted`.

**New implication added to `axioms/implications/management-governance.yaml`:**

```yaml
- id: mg-drafting-visibility-001
  tier: T1
  text: >
    Rendering an LLM-drafting process on a visible surface (livestream
    overlay, daimonion voice narration, Sierpinski slot) is preparation,
    not delivery, provided the operator retains sole authority over the
    drafted → approved → executed transition via operator-invoked
    promotion scripts. No Hapax process may transition a governance
    queue entry to executed without operator invocation.
  enforcement: review
  canon: purposivist
  mode: compatibility
  level: subsystem
  precedent_ids:
    - sp-hsea-mg-001
```

**Enforcement extensions** in `hooks/scripts/axiom-patterns.sh`:
- `check_hsea_auto_delivery()` — blocks commits adding `gh pr merge`, `gh pr create --draft=false`, `requests.post.*twitter|bluesky`, etc.
- `check_hsea_executed_transition()` — blocks commits where non-promote-script files call `governance_queue.update_status(..., "executed")`

---

## 7. Cluster taxonomy

HSEA defines 9 clusters + M-series:

| Cluster | Name | Touch points | Phase |
|---|---|---|---|
| **A** | Real-time research author/publisher | A1-A13 (12 original + A13 per-community array from drop #59) | 2, 3, 8 |
| **B** | Self-observing content tuner + clip-miner | B1-B13 | 6 |
| **C** | Research program orchestrator | C1-C14 (12 original + C13 voice-session extensions + C14 substrate-swap orchestrator) | 3 |
| **D** | Self-monitoring uptime engineer | D1-D14 (13 original + D14 routine-PR drafter cluster) | 7 |
| **E** | Platform value curator | E1-E16 (14 original + E15 sprint progress narrator + E16 documentation drift sweeper) | 8 |
| **F** | Self-reflexive narrator + meta-content | F1-F14 | 10 |
| **G** | Multi-agent research spawner | G1-G16 (14 original + G15 CI-watch triager + G16 session handoff drafter) | 11 |
| **H** (new) | Revenue preparation | H1-H8 | 9 |
| **I** (new) | Code drafting for critical path | I1-I7 + I-base infrastructure | 4 |
| **M-series** (new) | Missed opportunities | M1-M23 | 5, 6, 7, 8 (distributed) |

**De-duplication note:** drop #58 listed 92 touch points; drop #59 audit called out ~65 unique after dedup. HSEA explicit count: **~140 touch points** after adding H (8), I (7 + base), M-series (23), and the 14 drop #59 "additions to existing clusters" across A/C/D/E/G. Not all are load-bearing; Phase 12 defers the long tail.

---

## 8. Execution invariants

Adapted from LRR epic's invariants pattern:

- **Cross-epic dependency check (added by drop #62 fold-in).** Any HSEA phase that depends on an LRR phase output (per drop #62 §3 ownership table) MUST verify the LRR phase has reached `closed` status in `lrr-state.yaml` before opening. The shared `~/.cache/hapax/relay/research-stream-state.yaml` index file is the canonical lookup for cross-epic dependencies. Session-context.sh surfaces a unified status line on onboarding: `LRR: phase N (owner) | HSEA: phase M (owner) | UP: X,Y active`.
- **One active phase at a time.** `~/.cache/hapax/relay/hsea-state.yaml::current_phase` is the single source of truth. Sessions check this file first, then check `research-stream-state.yaml` for blocking dependencies.
- **Phase N opens only after Phase N-1 is closed.** Exceptions: Phases 5-9 have no mutual dependencies beyond 0/1/2 and can parallelize across worktrees.
- **Each phase is its own branch + PR** (or sequence of PRs per deliverable). Branch name: `feat/hsea-phase-N-<slug>`.
- **Every phase writes a handoff doc** at `docs/superpowers/handoff/YYYY-MM-DD-hsea-phase-N-complete.md` on close.
- **Frozen files are enforced universally** via Phase 0 `check-frozen-files.py --probe` extension.
- **Budget ledger enforces all spawns** via Phase 0 kill-switch. Daily cap $5 default, operator-adjustable.
- **Governance queue is append-only** — never delete entries, only archive.
- **Drafting never auto-commits** — every consequential artifact routes through operator-invoked `promote-*.sh`.
- **Every phase that modifies existing code respects the active research condition's `frozen_files` list.**

---

## 9. Exit criteria (epic-level)

HSEA epic closes when:

1. All 13 phases have `status: closed` in hsea-state.yaml
2. Phase 12 handoff doc written and committed
3. ~140 touch points either shipped or explicitly deferred with rationale
4. Constitutional axiom precedent `sp-hsea-mg-001` merged to `axioms/precedents/hsea/`
5. `~/.cache/hapax/relay/hsea-state.yaml::overall_health == green` sustained for ≥7 days
6. At least one end-to-end workflow demonstrated live: Hapax drafts research drop → operator approves → promote-drop.sh commits → drop appears in `docs/research/`
7. At least one code patch drafted and promoted end-to-end (any of I1-I7)
8. At least one governance queue entry transitioned `drafted → approved → executed → archived`
9. At least one revenue draft produced under all constitutional constraints
10. Audit of final state confirms <10% file-reference error rate (vs drop #58's ~55%)

---

## 10. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phase 0 primitives take >5 days | Medium | High | Scope Phase 0 tightly; ship minimum viable versions first, extend later |
| Frozen-files probe mode has edge cases | Medium | Medium | Write explicit test fixtures for each case; gate Phase 4 on verified probe coverage |
| Operator review fatigue at ~10 inbox items/day | High | High | Phase 5 M1 biometric intervention + ultradian scheduling; cap daily drafter activity via budget ledger |
| Spawn budget runaway mid-tick | Medium | High | Hard kill-switch before spawn; hysteretic re-enable at 90% cap; Opus rate limit ≤3/day |
| Reflexive content degenerates to slop | High | Medium | §3 concrete-artifact anti-slop discipline; F10 Qdrant NN anti-cliche; F3 scorer calibration period |
| Cluster I patches break production | Medium | High | Mandatory `code_review.py` pass before operator inbox; `promote-patch.sh` re-runs all gates; rollback plan per patch |
| Revenue tactics create obligation creep | Medium | High | Phase 0 axiom precedent + Phase 9 H3 consulting gate + pydantic validators enforcing no-deliverable clauses |
| LRR Phase 1 delays Phase 4 I1 (PyMC port) | Medium | Medium | Other I-drafters (I2-I7) don't depend on LRR; ship them first; I1 waits |
| Mobo swap (scheduled) breaks compositor | Medium | High | Phase 7 D13 scheduled spectator event includes pre/post validation; FDL-1 already shipped |
| Operator decides HSEA is too much | High | Fatal | Phase 0 standalone value demonstrates the concept; operator can deploy Phase 0 only and defer the rest |

---

## 11. Appendix: deferred items explicitly out of scope

These are in the drop #58 / drop #59 inventory but deferred to post-HSEA or to parallel epics:

- **Platform diversification to Twitch** (drop #57 T5.2) — out of scope; operational, not Hapax-executable
- **Hardware cascade isolation via cgroup edits** (drop #57 T5.1) — operator-manual work
- **Conference speaking circuit** (drop #57 T5.x) — fully operator-driven
- **Sprint tracking + goal updates via `agents/sprint_tracker.py`** — E15 is a Phase 8 touch point but depends on vault schema stabilization first
- **Obsidian plugin extensions** — belongs in `obsidian-hapax` epic, not HSEA
- **Substrate swap execution** (LRR Phase 5) — LRR epic owns this; HSEA supports via C7-C9

---

## 12. End

This document is the authoritative build authority for the Hapax Self-Executing Agent epic. It supersedes drops #58 and #59 for build purposes while preserving them in the audit trail. The epic's companion execution plan lives at `docs/superpowers/plans/2026-04-14-hsea-epic-plan.md`.

**Pre-epic-open checklist for the first session:**

1. Read this document in full
2. Read the companion plan doc
3. Verify hsea-state.yaml does not exist yet (creation is Phase 0 deliverable 0.6)
4. Check that FDL-1 is deployed + compositor healthy (Phase 0 needs it running)
5. Check LRR Phase 4 status (Phase 4 I1 depends on LRR Phase 1)
6. Open Phase 0 by creating `feat/hsea-phase-0-foundation-primitives` branch
7. Ship deliverables in sequence 0.6 → 0.1 → 0.3 → 0.2 → 0.4 → 0.5 per agent recommendation

**Total session estimate:** 22-35 sessions across 4-8 weeks, time-gated by Phase 5 M1 biometric data collection + Phase 11 G2 weekly ritual observation.

— delta
