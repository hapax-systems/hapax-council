# Delta WSJF Reorganization — 2026-04-20

**Author:** delta (post-VRAM-incident triage cycle); state-update + operator-decisions pass by alpha 2026-04-20T17:30Z (HEAD `12ac429d8`).
**Date:** 2026-04-20
**Audience:** next delta session (entry point)
**Register:** Engineering prioritization decision; concise; cite-or-it-didn't-happen.

> **STATE UPDATE 2026-04-20T17:30Z (alpha):** 8 READY items shipped between original authorship and now (D-03, D-13, D-14, D-19, D-20, D-21, D-22, D-23). D-17 partial (CLI shipped, director_loop residue pending). D-24 partial (2-of-11 sub-items). Audit's "0 callers" claim for `quiet_frame` is now stale; `music_policy` claim is technically stale (1 metric ref) but functionally accurate. AUDIT §8.4 systemd-state-divergence claim is partially incorrect — `rag-ingest.service` was never deleted from repo (only the .timer); script `c11d8d2be` is still useful general tooling. **All §10 operator questions RESOLVED by alpha per "make best decision and unblock yourself" directive (see §10).** New item D-25 (OQ-01 neon palette node, WSJF 6.3) inserted. OQ-02 (Nebulous Scrim three-bound invariant) promoted to research-to-plan triage outside WSJF.
>
> **STATE UPDATE 2026-04-20T19:30Z (alpha — chain closure burst):** Per operator directive *"keep moving, no other session"* — full quiet_frame dead-bridge chain shipped end-to-end in 4 commits: D-27 (`1fb58b0b7`) egress audit wire → D-26 (`866b66499`) Programme plumb → D-18 (`3ea6074e9`) music_policy CPAL proof-of-wiring → D-17 (`1e3d2fa4a`) quiet_frame subscriber. Audit's "shipped infrastructure with no consumer" finding is now CLOSED — every governance module has at least one production caller. ~750 LOC, 35+ new tests, 0 regressions across 318 governance + pipeline tests. Remaining: D-01 cross-zone PR review (alpha PR not yet opened), D-02 standing readiness, D-08 + D-15 research dispatches, D-24 9-of-11 mechanical residue, D-26a + D-18b + D-27b follow-ons (NEW, lower-priority). All hardware/firmware-blocked items unchanged.
>
> **STATE UPDATE 2026-04-20T20:30Z (alpha — OQ-02 Phase 1 + cleanup burst):** Operator GO received for OQ-02 Phase 1 enforcement; all 3 oracles + B2 tracker SHIPPED — `fddcdd978` (B2 oracle scrim_translucency, 25 tests), `d8347a293` (B1 oracle anti_recognition, 19 tests, fail-CLOSED everywhere), `7a9a6c09d` (B2 tracker, 24 tests, observe-only by default), `1b21435d5` (B3 oracle anti_visualizer, 35 tests inc. Hypothesis property). Director watchdog Phase 2 SHIPPED `3522ee8ec`. D-01 Phase 3b consumer half SHIPPED `ce427c3a3`. Latent micromove DirectorIntent.stance bug FIXED `68cb2b9fa`. 4 beta orphans cherry-picked (`5757cdc31`/`2903e4205`/`b90c79980`/`6d9e8cc00`); PR #819 closed; beta-phase-4-bootstrap deleted. D-24 §10.4 SHIPPED `676e94bda` — D-24 bundle FULLY closed (11/11). Total-workstream gap audit SHIPPED `7a9a6c09d` (~58 items / 30 tracked / 17 misses). **THIS DOCUMENT'S §5/§7/§10 ARE STALE** per audit §4 confirmed drift — only §3 master table is authoritative. D-09 (Music policy Path B) is CLOSED in §3 but still appeared in §7 BLOCKED table; resolved here. Four invisible-but-existing plans now allocated D-NN slots in §3 (D-28 through D-31).
**Source documents (all citations resolve to these):**

- `docs/superpowers/handoff/2026-04-20-delta-pre-compaction-commitments.md` (PRE-COMPACT)
- `docs/research/2026-04-20-delta-queue-flow-organization.md` (FLOW)
- `docs/superpowers/research-to-plan-triage-2026-04-20.md` (TRIAGE)
- `docs/superpowers/handoff/2026-04-20-delta-queue-cleared-handoff.md` (CAPSTONE)
- `docs/superpowers/handoff/2026-04-20-delta-l6-retargets-operator-runbook.md` (L6-RUNBOOK)
- `docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md` (DEMONET-PLAN)
- `~/.cache/hapax/relay/delta.yaml` (DELTA-YAML; refreshed 2026-04-20T15:13Z post-VRAM-fix)
- `~/.cache/hapax/relay/delta-to-alpha-research-triage-20260420.md` (TRIAGE-RELAY)
- `~/.cache/hapax/relay/delta-to-alpha-rag-ingest-livestream-optimization-20260420.md` (RAG-RESEARCH)
- `docs/research/2026-04-20-six-hour-audit.md` (AUDIT) — woven 2026-04-20 d33be1a6e+ pass; produced D-17 through D-24

---

## §1. TL;DR

**Top 5 unshipped by WSJF (post state-update; highest = ship first):**

| Rank | Item | WSJF | State |
|---|---|---|---|
| 1 | Cross-zone PR review pickup for #197/#198 (alpha consumer side) | **17.0** | READY |
| 2 | Investigate operator-reported livestream regressions (standing readiness) | **13.0** | READY |
| 3 | OQ-01 neon palette node (D-25, NEW) | **6.3** | READY |
| 4 | Wire `quiet_frame` director_loop residue (D-17b) | **7.0** | READY (cross-zone-authorized) |
| 5 | Wire `music_policy` CPAL+compositor (D-18) | **7.0** | READY (cross-zone-authorized) |

**Ship-readiness distribution (25 items, post state-update):**

- **SHIPPED post-weave:** 8 (D-03, D-13, D-14, D-19, D-20, D-21, D-22, D-23) + partials D-17a CLI, D-24 2-of-11.
- **READY remaining:** 7 (D-01, D-02, D-15-when-alpha-returns, D-17 director_loop residue, D-18, D-24 9-of-11 residue, D-25 NEW).
- **NEEDS_CLARIFICATION:** 0 (all RESOLVED by alpha per §10).
- **NEEDS_RESEARCH:** 1 (D-08 — D-15 dispatched).
- **BLOCKED:** 6 (D-04 hardware, D-06 manual op, D-09 op decision-now-resolved-stay-Path-A so RESOLVED, D-10 hardware, D-11 firmware, D-12 strict-serial after D-05/D-13/D-14 → all shipped → D-12 now READY post-decision-on-prompt-strategy).

**Headline:** delta exited the prior session with the queue genuinely cleared (CAPSTONE §1 lines 11–33 lists 35 ships; PRE-COMPACT §3 line 50 confirms working-tree clean on `main`). The VRAM emergency closed cleanly (`8816040eb` shipped per DELTA-YAML lines 20–28; rag-ingest now drip-only inotify, 370 MB RSS, zero GPU). The 2026-04-20 six-hour audit (commit `d33be1a6e`) surfaced 14 net-new actionable findings (HIGH ×2, MEDIUM ×6 clustered, LOW ×11 bundled). The 3 most-urgent audit findings (speech_lexicon WIP, rag-ingest handoff doc, and Ring 2 Phase 1 commit) were resolved out-of-band by alpha (`9fad053b5`, `f89012131`, `d6a4d4753`); the residue is woven below as D-17 through D-24. Remaining work is dominated by (a) wiring two truly-dead governance modules (`quiet_frame`, `music_policy`) into production callers, and (b) a fast spec/doc-drift cleanup bundle that ranks #3 by WSJF.

---

## §2. Methodology

### §2.1 WSJF rubric

`WSJF = (Business Value + Time Criticality + Risk Reduction) / Job Size`

Components scored on Fibonacci-like 1-3-5-8-13. Source: `feedback_systematic_plans` (workspace MEMORY index) + standard SAFe WSJF.

| Dim | 13 | 8 | 5 | 3 | 1 |
|---|---|---|---|---|---|
| **Business Value** | unblocks operator's most-named gate | improves broadcast quality / workflow significantly | improves delta-zone subsystem | optimization / observability | nice-to-have |
| **Time Criticality** | go-live blocker decaying daily | stream-affecting, decays days | quality compounding weeks | decoupled | research-only |
| **Risk Reduction** | unblocks ≥3 downstream / fixes recurring failure | unblocks 1-2 items | enables future capability | isolated improvement | none |
| **Job Size** | 1=≤30min, 3=~1hr, 5=2-4hr, 8=4-8hr, 13=multi-day |

### §2.2 Spec-readiness states

- **READY:** acceptance criteria + named files + test plan exist; agent could ship without asking
- **NEEDS_CLARIFICATION:** direction clear; one operator/peer question unblocks
- **NEEDS_RESEARCH:** no spec yet; needs research dispatch first
- **BLOCKED:** waiting on operator decision, hardware, or peer agent (not a delta-side problem)

### §2.3 Sources scanned

PRE-COMPACT §4–§9 (in-flight, queued, operator-gated, shipped-with-followup); FLOW §3.1–§4.4 (dependency graph + size estimates); TRIAGE §1 + §3 (delta-zone unqueued); CAPSTONE §3–§5 (#202 pickup spec); DELTA-YAML lines 51–66 (`operator_gated_items_prescope` + `next_delta_session_priorities`); TRIAGE-RELAY lines 27–45 (alpha-zone gap list, adjacent for cross-zone scoring).

### §2.4 Anchor: operator's go-live gates

Per directive: Gate 1 monetization (delta-owned via #202), Gate 2 vinyl Mode D (shipped per FLOW §3 line 84), Gate 3 DEGRADATION (alpha-owned, shipped per directive). Gate 1 → Time Criticality 13 for any item directly advancing it.

---

## §3. Master scored table

Every remaining delta-zone item, scored. Sequenced by WSJF descending within each readiness state.

| ID | Item | Source | BV | TC | RR | JS | WSJF | State | Deps |
|---|---|---|---|---|---|---|---|---|---|
| **D-01** | Cross-zone PR review pickup for #197/#198 (alpha consumer side) | PRE-COMPACT §4.4 line 91; DELTA-YAML line 63; CAPSTONE §1 row #197+#198 | 8 | 13 | 13 | 2 | **17.0** | READY | alpha opens PR |
| **D-02** | Investigate operator-reported livestream regressions (standing readiness) | DELTA-YAML line 64; PRE-COMPACT §4.5 lines 97–102 | 13 | 13 | 13 | 3 | **13.0** | READY | operator surfaces issue |
| **D-03** | Audio-topology Phase 5 verify-sweep against current live graph | PRE-COMPACT §9.3 lines 232–240; FLOW §3 lines 88–94 | 5 | 5 | 5 | 2 | **8.0** | **SHIPPED `b0a02940e`** | — |
| **D-04** | L6 retargets apply (5 configs) | L6-RUNBOOK §1–§2; PRE-COMPACT §5.2 + §7 line 191; DELTA-YAML line 54 | 8 | 8 | 5 | 3 | **7.6** | BLOCKED-hardware | Rode WP on ch 1 + AUX 1 confirm (not alpha-decidable) |
| **D-05** | #202 Ring 2 classifier Phase 1 | CAPSTONE §3 lines 58–145; PRE-COMPACT §4.2 lines 72–83; DELTA-YAML lines 45–50 | 13 | 13 | 8 | 8 | **5.4** | **SHIPPED `d6a4d4753`** | — |
| **D-06** | LADSPA loudnorm operator-apply step | PRE-COMPACT §5.5 lines 136–138; DELTA-YAML line 58 | 5 | 5 | 3 | 3 | **4.3** | BLOCKED-operator | `cp` + pipewire restart (manual op) |
| **D-07** | Vinyl-broadcast signal-chain software wiring | TRIAGE §1 row 10; FLOW §3.2 line 145; TRIAGE §3 row 36 | 5 | 5 | 3 | 5 | **2.6** | READY | DECIDED §10: verify-only |
| **D-08** | Audio-normalization-ducking-strategy plan stub | TRIAGE §1 row 8; FLOW §10.3 line 390 | 3 | 3 | 5 | 3 | **3.7** | NEEDS_RESEARCH | LADSPA topology survey |
| **D-09** | Music policy Path B runtime switch | PRE-COMPACT §5.3 lines 128–130; DELTA-YAML line 56 | 3 | 3 | 1 | 1 | **7.0** | **CLOSED — DECIDED §10: stay Path A** | — |
| **D-10** | Evil Pet `.evl` SD card preset parser (Phase 1) | PRE-COMPACT §5.4 lines 132–134; DELTA-YAML line 57; FLOW §3 lines 109–113 | 3 | 3 | 3 | 5 | **1.8** | BLOCKED-hardware | factory `.evl` file |
| **D-11** | Dual-FX Phase 6 (S-4 firmware activation) | PRE-COMPACT §9.4 lines 246–247; FLOW §6 line 240 | 5 | 3 | 3 | 5 | **2.2** | BLOCKED-firmware | flash S-4 OS 2.1.4 |
| **D-12** | #202 Phase 2 (classifier-side opt-in negotiation) | PRE-COMPACT §5.1 lines 110–114; DEMONET-PLAN §3.1; DECIDED §10: 4 distinct prompts | 8 | 8 | 5 | 5 | **4.2** | READY | reconcile with `ring2_gate_helper.py` (`3de317399`) |
| **D-13** | #202 Phase 3 (integrate verdict into `MonetizationRiskGate.assess()`) | PRE-COMPACT §5.1 line 113; DEMONET-PLAN §3.1 | 13 | 8 | 8 | 5 | **5.8** | **SHIPPED `896d8a52f`** | — |
| **D-14** | #202 Phase 4 (classifier-degraded fail-closed integration tests) | PRE-COMPACT §5.1 line 114; CAPSTONE §3.what's-pre-wired item 1 | 8 | 5 | 5 | 3 | **6.0** | **SHIPPED `9db8fb8fd`** (ClassifierDegradedController) | — |
| **D-15** | rag-ingest livestream-compatible redesign (followup to VRAM fix) | DELTA-YAML lines 30–38; RAG-RESEARCH (relay drop) | 8 | 5 | 8 | 8 | **2.6** | NEEDS_RESEARCH | alpha returns spec+plan |
| **D-16** | Ring 2 prompt design — per `SurfaceKind` | CAPSTONE §3.scope bullets 1–5; DEMONET-PLAN research §6 ref; DECIDED §10: 4 distinct prompts | 8 | 8 | 5 | 5 | **4.2** | READY | feeds D-12 |
| **D-17** | Wire `quiet_frame` into production caller | AUDIT §7.1; §11 remediation row 4 | 8 | 8 | 5 | 3 | **7.0** | **SHIPPED `1e3d2fa4a`** (subscriber pattern via `_assess_listeners` API; cooldown-bounded; off-by-default via `HAPAX_QUIET_FRAME_AUTO=1`). CLI half shipped earlier `31d32a29c`. | — |
| **D-18** | Wire `music_policy` into CPAL audio loop / compositor mute path | AUDIT §7.1; §11 remediation rows 1–6 | 8 | 8 | 5 | 3 | **7.0** | **SHIPPED `3ea6074e9`** (proof-of-wiring with NullMusicDetector default; production-mute deferred to D-18b once a real detector exists) | — |
| **D-19** | Concurrency hardening bundle | AUDIT §8.1, §8.2, §12.2 | 5 | 3 | 5 | 2 | **6.5** | **SHIPPED `840a643ae`** | — |
| **D-20** | Crash-safety/atomic-write bundle | AUDIT §8.3, §10.1, §9.1 | 5 | 3 | 5 | 3 | **4.3** | **SHIPPED `a6ef02fbe`** | — |
| **D-21** | Repo-vs-systemd state divergence reconciler | AUDIT §8.4 (claim partially incorrect — `.service` was never deleted, only `.timer`) | 5 | 5 | 5 | 3 | **5.0** | **SHIPPED `c11d8d2be`** (general-purpose tooling regardless) | — |
| **D-22** | Spec/doc drift bundle | AUDIT §6.2, §4.2 + §5.2, §11.2 | 5 | 3 | 3 | 1 | **11.0** | **SHIPPED** sub-1+2 `50251d8fe`, sub-3 `16fb210` (dotfiles) | — |
| **D-23** | Detector fail-closed + egress timer + Prometheus | AUDIT §9.2, §7.2, §11.1, §11.5 | 5 | 5 | 3 | 3 | **4.3** | **SHIPPED `12ac429d8`** | — |
| **D-24** | Audit-cleanup bundle (11 LOW-severity items) | AUDIT §6.1, §6.3, §8.5, §8.6, §9.3, §9.4, §10.3, §10.4, §11.3, §11.4, §11.6 | 3 | 1 | 3 | 5 | **1.4** | **PARTIAL** `4e0ee68ed` (§10.3 NaN guard + §8.5 redactor); 9 sub-items remain | — |
| **D-25** | **NEW** OQ-01 neon GPU palette node — fix white-edge degeneracy in `presets/neon.json` via new `palette_remap` node + brightness ceiling | alpha.yaml `operator_queue_adds_20260420` OQ-01; verified `agents/shaders/nodes/edge_detect.frag:31-36`; CPU reference `agents/studio_fx/effects/neon.py` | 8 | 8 | 3 | 3 | **6.3** | **SHIPPED `863509ac9`** | — |
| **D-26** | Phase 5 wire: replace `programme=None` at `shared/affordance_pipeline.py:434` with live active-programme lookup | Audit by alpha 2026-04-20T18:30Z verified `affordance_pipeline.py:430-431` is the explicit Phase-5 stub; `Programme.monetization_opt_ins` already shipped in `shared/programme.py:336` | 13 | 8 | 13 | 5 | **6.8** | **SHIPPED `866b66499`** (TTL-cached active-programme lookup; None is legitimate cached value; store-read failures fall back to None) | — |
| **D-27** | Egress audit wire: call `MonetizationEgressAudit.default_writer().record(...)` from `MonetizationRiskGate.assess()` per demonet plan §Phase 6 | Demonet plan lines 389-405 | 8 | 5 | 8 | 3 | **7.0** | **SHIPPED `1fb58b0b7`** (single chokepoint at `_record_and_return()`; sampling per spec; HAPAX_DEMONET_AUDIT=0 disables) | — |
| **D-26a** | **NEW** Programme validation rules (Hapax-authored fails-on-non-empty `monetization_opt_ins`, operator-authored allowed up to MAX_OPT_INS=3) per demonet plan §Phase 5 (lines 354-358) | Pedantry not behavior — gate already correctly handles missing/empty opt_ins; validation is hygiene-only | 3 | 1 | 3 | 3 | **2.3** | READY | none |
| **D-18b** | **NEW** Production-mute integration: wire `decision.should_mute` into ProductionStream so true-positive music detection actually mutes Hapax TTS | D-18 ships proof-of-wiring; behavior change deferred until a real (non-Null) detector exists | 8 | 3 | 5 | 5 | **3.2** | NEEDS_RESEARCH | requires real music detector first; see `shared/governance/music_policy.py:71-86` |
| **D-27b** | **NEW** Egress audit async-write queue per plan §Phase 6 lines 405-408 (sync write under recruitment hot path is acceptable but not optimal under sustained load) | Plan spec calls for "atomic append via single-writer queue + background thread" | 5 | 1 | 3 | 5 | **1.8** | NEEDS_RESEARCH | benchmark sync vs queued under livestream load |
| **D-28** | **NEW (gap audit NEW-1)** Programme-layer plan execution: `docs/superpowers/plans/2026-04-NN-programme-layer-plan.md` (task #164, 12 phases) is spec'd but invisible to WSJF — the exemplar of the operator's near-miss. Read plan + allocate per-phase D-NN sub-slots OR file a single tracking row | Gap audit NEW-1; near-miss exemplar | 13 | 5 | 13 | 13 | **2.4** | NEEDS_RESEARCH | read plan to know phase shape; many phases may be already-shipped or duplicated by D-26 work |
| **D-29** | **NEW (gap audit NEW-3)** HOMAGE Ward umbrella plan from `docs/research/2026-04-20-homage-ward-umbrella-research.md` + `docs/superpowers/specs/2026-04-20-homage-ward-umbrella-design.md` — research exists, design spec exists, NO plan. Umbrella supersedes CBIP + Vitruvian as standalone specs (those become 1-2 page annexes). **Sequenced after HSEA Phase 0** per delta sister-epic memo | Gap audit NEW-3; delta umbrella research | 8 | 5 | 8 | 13 | **1.6** | BLOCKED-after-HSEA | requires HSEA Phase 0 governance ledger |
| **D-30** | **NEW (gap audit P0)** CC-task Obsidian SSOT plan from `docs/superpowers/specs/2026-04-20-cc-task-obsidian-ssot-design.md` — STRUCTURAL FIX for systemic misses #1 + #3 ("plans live but queue does not refer back" + "operator queues fragment across surfaces"). Single canonical task-tracking surface in Obsidian replaces WSJF-D-NN + alpha.yaml-OQ-NN + scattered task #NN fragmentation | Gap audit P0 #1 | 13 | 8 | 13 | 8 | **4.3** | NEEDS_CLARIFICATION | operator: prioritize this OR ship more domain features first? |
| **D-31** | **NEW (gap audit NEW-10)** 8-spec spec-burst from 2026-04-18 has no plans — audio-pathways-audit, audio-reactivity-contract, camera-naming, heterogeneous-agent-audit, local-music-repository, splattribution, non-destructive-overlay, operator-sidechat. Single-day backlog of unplanned specs. Triage pass needed: which are still relevant, which superseded, which need plans | Gap audit NEW-10 | 5 | 3 | 8 | 13 | **1.2** | NEEDS_RESEARCH | triage all 8 specs for current relevance |

**Score sanity check:** D-01 dominates because the body of work is tiny (review + maybe a clarifying patch) and it converts two already-shipped delta-side commits (`0dbaa1321` per CAPSTONE §1 row #197+#198) into deployed behavior. D-02 is high because *any* livestream regression is by definition gate-decay-affecting per `feedback_consent_latency_obligation` and `feedback_show_dont_tell_director` (memory index). D-05 (Ring 2 P1) is the heaviest standalone delta-shippable but the JS=8 divisor + the clarification gate keeps it below the small-ticket items. **D-22 lands at #3** because three coordinated documentation fixes (≤30 min total) eliminate ongoing reader-confusion at the spec/code/CLAUDE.md interface — high BV+TC over a JS=1 divisor produces a high WSJF. **D-17/D-18 tie at 7.0** with D-09 because wiring a shipped-but-dead governance module into a production caller is functionally equivalent to closing a Gate 1 sub-gap (per `feedback_grounding_exhaustive` memory: a module with 0 callers is indistinguishable from a dead bridge).

---

## §3.5 Audit-derived items (2026-04-20 d33be1a6e weave)

The 2026-04-20 six-hour audit (`docs/research/2026-04-20-six-hour-audit.md`, commit `d33be1a6e`) enumerated 25 findings across 8 axes (HIGH ×5, MEDIUM ×11, LOW ×9). This sub-section traces every audit finding to its disposition in the queue.

**Resolved out-of-band before weave (do not re-add):**

| Audit ref | Finding | Resolution commit |
|---|---|---|
| AUDIT §4.1 / §10.2 | Ring 2 Phase 1 uncommitted (4 files in working tree, including `ring2_classifier.py` modified-not-staged) | `d6a4d4753` (feat(demonet): Ring 2 Phase 1 — real per-surface LLM + 500-sample bench) |
| AUDIT §5.2 | Broken doc reference in `8816040eb` to missing rag-ingest handoff | `f89012131` (docs: backfill rag-ingest livestream-research handoff doc) |
| (operator WIP rescue, audit-adjacent) | speech_lexicon work-in-progress at risk of loss | `9fad053b5` (feat(speech): canonical pronunciation lexicon — operator WIP rescue) |
| AUDIT §5.1 | `eb1657358` capstone "queue cleared" claim under-delivered (now superseded by actual ship of D-05/D-13) | implicit; capstone narrative is historical |
| AUDIT §7.1 (ring2_classifier 0 callers) | Subset of dead-bridge finding | `896d8a52f` (feat(demonet): Ring 2 classifier integration into MonetizationRiskGate.assess()) |

**Newly-added items (D-17 through D-24):**

| New ID | Audit refs | Severity | Cluster type | Cross-zone? |
|---|---|---|---|---|
| D-17 | §7.1 (quiet_frame), §11 remediation row 4 | HIGH | individual (named module + named CLI fix) | no (delta governance zone) |
| D-18 | §7.1 (music_policy), §11 remediation rows 1–6 | HIGH | individual (named module + named call sites) | no (delta governance zone, but touches CPAL audio loop owned by alpha — flag for cross-zone review pre-merge) |
| D-19 | §8.1, §8.2, §12.2 | MEDIUM ×2 | concurrency theme (both are stateful-dataclass-without-lock variants of same anti-pattern) | no |
| D-20 | §8.3, §10.1, §9.1 | MEDIUM ×3 | crash-safety / state-cleanup theme (atomic-write window + monotonic state growth + transactional prune) | no |
| D-21 | §8.4 | MEDIUM | individual (systemd reconciler is a discrete new script) | no (delta sysadmin/governance overlap) |
| D-22 | §4.2, §6.2, §11.2 | MEDIUM ×3 | doc/spec drift theme (all three are documentation-only edits with no code change) | no (DEMONET-PLAN is delta-owned; workspace CLAUDE.md is shared but operator-decided edit) |
| D-23 | §7.2, §9.2, §11.1, §11.5 | MEDIUM ×4 | observability/robustness theme (all are "module shipped without operational instrumentation" variants) | no |
| D-24 | §6.1, §6.3, §8.5, §8.6, §9.3, §9.4, §10.3, §10.4, §11.3, §11.4, §11.6 | LOW ×11 | catch-all bundle (mechanical low-risk consistency / hardening / future-proofing; per WSJF guidance LOW items bundle into a single low-WSJF READY ticket) | no |

**Findings explicitly NOT promoted to queue items:**

| Audit ref | Reason |
|---|---|
| §12.1 (skeleton-then-defer anti-pattern) | Process-pattern observation, not a queue item; recorded here as a delta-self-discipline note. The fix is "future skeletons must include at least one production caller" — addressed structurally by D-17 / D-18 closure. |
| §12.3 (atomic-rename usage correct everywhere) | Positive finding; no action. |
| §12.5 (Co-Authored-By consistency) | Positive finding; no action. |
| §13 remediation rows 1, 3 | Already resolved above. |
| §13 remediation rows 2, 5 | Wired via D-13 (`896d8a52f`) and D-03 (`b0a02940e`); no further action. |

**Cross-references:** every audit finding section number above appears in at least one D-NN row's "Source" column in §3 master table, providing bidirectional traceability.

---

## §4. READY queue (rank-ordered, ship without further triage)

### §4.1 D-01 — Cross-zone PR review pickup for #197/#198 (WSJF 17.0)

**Action:** Watch `gh pr list --search 'voice-tier OR mode-d OR engine_session'` for alpha consumer-side PRs landing the work scoped in `~/.cache/hapax/relay/delta-to-alpha-cross-zone-handoff-20260420.md` (lines 18–60 voice_tier_3b; lines 62–103 mode_d_mutex_p3, both per PRE-COMPACT §6.1–§6.2). When PRs open, review for:

- `VoiceTierImpingement.try_from(imp)` correctly handles all 7 tier values (T0–T6) per PRE-COMPACT §9.1 line 215
- `engine_session()` consumer keyword matches the producer constant `VOICE_TIER_IMPINGEMENT_SOURCE` (PRE-COMPACT §6.1 line 145)
- Prometheus counter labels match the lazy-registered names `hapax_evil_pet_engine_acquires_total`, `hapax_evil_pet_engine_contention_total` (PRE-COMPACT §6.2 line 152)

**Acceptance:** approve or request changes; ship clarifying patches if alpha asks.

**Files to touch (likely none, possibly `shared/impingements.py` clarifier):** `agents/studio_compositor/director_loop.py` (alpha-owned, review only); `tests/studio_compositor/test_voice_tier_consumer.py` (alpha-owned, review only).

### §4.2 D-02 — Investigate operator-reported livestream regressions (WSJF 13.0)

**Action:** standing readiness — when operator surfaces a regression, dispatch `superpowers:systematic-debugging` per global CLAUDE.md "Proactive Plugin Usage" table. Apply `feedback_show_dont_tell_director.md` (memory index) and `feedback_never_drop_speech.md` as governance anchors during diagnosis.

**Acceptance:** root cause identified + fix shipped or dispatched, with citation back to the operator's surface message.

**Files to touch:** depends on regression. Most likely surfaces: `agents/hapax_daimonion/cpal_runner.py`, `agents/studio_compositor/director_loop.py`, `config/pipewire/voice-fx-*.conf`.

### §4.3 D-03 — Audio-topology Phase 5 verify sweep (WSJF 8.0)

**Action:** Phase 5 watchdog shipped (`138de264f` per PRE-COMPACT §9.3 line 237). Sweep is a verification pass: run `hapax-audio-topology verify` against current live graph, confirm exit 0 against the actual L6 + Cortado + Studio 24c topology after the operator's recent hardware moves. If non-zero, file follow-up; if zero, mark family closed in `delta.yaml`.

**Acceptance:** `hapax-audio-topology verify` exits 0 with current graph snapshot saved to `~/hapax-state/audio-topology/snapshot-20260420.json`.

**Files to touch:** none (read-only verify); maybe `delta.yaml` to mark family closed.

**Note:** FLOW §11 hour-3 (lines 421–430) was the original spec for this; that work is shipped, this is the verify-it-still-holds pass.

### §4.4 D-15 (when alpha returns spec) — rag-ingest livestream-compatible redesign

Currently NEEDS_RESEARCH; will re-rank as READY when alpha returns the spec dispatched in DELTA-YAML lines 30–38 / RAG-RESEARCH relay drop. Pre-scoping notes for the moment alpha returns:

- Embedder selection (CPU-only vs GPU-with-fortress-mode-gating)
- Docling vs alternatives (markdown-only direct-chunker bypass)
- Backfill semantics (retry-queue vs full-rescan cadence)
- Pacing primitive (existing examples: `shared/pacing.py`, none yet?)
- Observability (Prometheus + JSONL per existing patterns, see `shared.governance.monetization_egress_audit` PRE-COMPACT §9.5 line 254)
- Fortress-mode gating (read `~/.cache/hapax/working-mode`)

### §4.5 D-22 — Audit doc/spec-drift bundle (WSJF 11.0)

**Action:** Three coordinated documentation-only fixes from the 2026-04-20 audit. All three are mechanical edits that resolve reader-confusion at the spec/code/CLAUDE.md interface; no code touched.

1. **DEMONET-PLAN §0.1 path reconcile.** AUDIT §6.2 — plan prescribes `~/hapax-state/programmes/egress-audit/<date>/<hour>.jsonl`; shipped writer (`shared/governance/monetization_egress_audit.py:47`) uses flat `~/hapax-state/demonet-egress-audit.jsonl`. Decide: (a) update the plan to record the flat path actually shipped, OR (b) refactor the writer to nest-by-date (rotate hook already exists; this is a path-format change). Default to (a) — the flat path is operationally simpler and rotation is timer-driven, not directory-driven.
2. **DEMONET-PLAN §0.4 attribution update.** AUDIT §4.2 + §5.2 — `f893ddfbc` unilaterally resolved Path A vs Path B per "unblock yourself" directive, but plan still names it as a blocking operator-input gate. Update plan §0.4 to record "Path A (mute-and-transcript) was delta-defaulted on 2026-04-20 per `f893ddfbc`; operator may override to Path B per D-09."
3. **Workspace CLAUDE.md `Shared Infrastructure` rag-ingest GPU-isolated bullet.** AUDIT §11.2 — `8816040eb` cites the workspace CLAUDE.md GPU-isolation pattern but the doc still enumerates only ollama. Add a one-line bullet: "rag-ingest also runs CPU-only via `CUDA_VISIBLE_DEVICES=""` per `systemd/overrides/rag-ingest.service.d/gpu-isolate.conf`." Edit goes via dotfiles (`~/dotfiles/workspace-CLAUDE.md`), not `~/projects/CLAUDE.md`.

**Acceptance:** all three docs reflect the 2026-04-20 reality; `git diff` shows exactly three files modified.

**Files to touch:** `docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md` (§0.1 + §0.4); `~/dotfiles/workspace-CLAUDE.md` (Shared Infrastructure section).

### §4.6 D-17 — Wire `quiet_frame` into production caller (WSJF 7.0) — PARTIAL + SPEC-MISMATCH

**STATE 2026-04-20T17:30Z:** AUDIT §7.1 partially closed by `31d32a29c` (CLI shipped). `Grep quiet_frame` returns 2 production sites (CLI + module). Director_loop wire pending; **AUTHORIZED §10.9 as alpha-PR**. Idempotency: `activate_quiet_frame()` is dedup-safe per D-20 (`a6ef02fbe`); deactivate-when-not-active returns gracefully per CLI exit-code 1 contract.

**STATE 2026-04-20T18:00Z (alpha investigation):** ATTEMPTED to ship director_loop wire; FOUND ARCHITECTURAL MISMATCH. AUDIT spec assumed `agents/studio_compositor/director_loop.py` knows about MonetizationRiskGate — verified incorrect: director_loop has zero references to monetization_safety / risk_gate. The gate is called via `shared/governance/ring2_gate_helper.ring2_assess()` from `shared/affordance_pipeline.py::AffordancePipeline.select()`. Director makes broadcast/composition decisions but does not directly consult the risk gate.

**Re-spec required.** Two architecturally-clean wire options:

1. **Observer hook in ring2_gate_helper.** Wrap `ring2_assess()` so when `RiskAssessment.allowed=False`, fire `activate_quiet_frame(reason=f"risk-gate blocked {capability}")`. Requires transition-detection (HISTORY) for de-activation: track BLOCKED→ALLOWED edges. Module-level state with lock.

2. **Subscribe via monetization_egress_audit.** The audit already records every gate decision. Add a side-effect hook: when audit records a BLOCKED record, also activate quiet_frame (with cooldown). Cleanest separation per gate's "no I/O in hot path" docstring (`monetization_safety.py:130-132`). Same transition-detection requirement.

**STATE 2026-04-20T18:30Z (alpha consumer audit):** A research subagent verified the full dead-bridge chain. **D-17 has TWO upstream prerequisites that are themselves dead bridges:**

- **D-26 (Phase 5 wire):** `shared/affordance_pipeline.py:434` hard-codes `programme=None`. The TODO at `affordance_pipeline.py:430-431` is explicit — Phase 5 is unimplemented. Even if quiet_frame activates, the pipeline never sees it. Demonet plan §Phase 5 specifies 150-250 LOC + 6 tests for proper wire including the Programme `monetization_opt_ins` field + validation rules.
- **D-27 (egress audit wire):** `MonetizationEgressAudit.default_writer().record(...)` is shipped + tested but never called from `MonetizationRiskGate.assess()`. Option 2 above (subscribe via audit) is dead until D-27 ships. Demonet plan §Phase 6 specifies the wire.

Additional dead bridges discovered (not D-17-blockers, but in the same governance chain):
- `ring2_gate_helper.ring2_assess()` (`shared/governance/ring2_gate_helper.py:105`) has 0 production callers — only test imports.
- `resolve_tier(... programme_band_prior=)` (`shared/voice_tier.py:417`) has 0 production callers — `QUIET_FRAME_TIER_BAND=(0,2)` is inert.
- `tests/governance/test_quiet_frame.py::TestGateIntegration` is a **fake-verification** test — passes the freshly-activated quiet_frame Programme to the gate by hand, never proves the production pipeline does. Test would still pass even if no consumer existed (which is the actual state).

**Why a wire wasn't shipped this turn:** Phase 5 is 150-250 LOC; Phase 6 is comparable scope. Shipping an upstream activator (D-17) into a chain where every downstream link is dead would create the illusion of a working safety hold — worse than no hold per `feedback_grounding_exhaustive` ("a module with 0 callers is indistinguishable from a dead bridge"). Demonet plan's Phase 5 stub was already documenting this honestly; the audit just made it visible at the call site.

**Files to NOT touch this iteration:** `agents/studio_compositor/director_loop.py` (architectural mismatch); pick a re-spec'd entry point above only after **D-26 AND D-27** ship.

**Sequencing:** D-27 (audit wire) → D-26 (Phase 5 plumb) → D-18 (CPAL music_policy wire) → D-17 (this item, Option 2 audit subscriber).

**Action:** AUDIT §7.1 — `shared/governance/quiet_frame.py` ships with zero production callers. Wire two entry points:

1. **CLI `scripts/hapax-quiet-frame`** — operator-invokable, exposes `activate_quiet_frame()` + `deactivate_quiet_frame()` per AUDIT §11 remediation row 4. Add a `[scripts]` entry in `pyproject.toml` so it lands on `$PATH`.
2. **Pre-monetization-window programmatic call.** Audit recommends a call site in the broadcast-loop's pre-monetization-window logic. Suitable site: `agents/studio_compositor/director_loop.py` — when monetization-risk-gate transitions to `BLOCKED`, also `activate_quiet_frame()` with the current programme id; on transition back to `ALLOWED`, `deactivate_quiet_frame()`.

**Acceptance:** `Grep quiet_frame|QUIET_FRAME|activate_quiet_frame` returns ≥2 production import sites outside tests/docs (currently 0); `hapax-quiet-frame --help` works; one new test in `tests/studio_compositor/test_director_loop_quiet_frame.py` verifies the transition-driven activation.

**Files to touch:** `scripts/hapax-quiet-frame` (new), `pyproject.toml` ([scripts] section), `agents/studio_compositor/director_loop.py`, `tests/studio_compositor/test_director_loop_quiet_frame.py` (new).

**Cross-zone flag:** director_loop is alpha-touched. Coordinate via relay before merging to avoid mid-flight conflict; or scope D-17 to CLI-only and let alpha wire the director_loop call site as a follow-up.

### §4.7 D-18 — Wire `music_policy` into CPAL audio loop / compositor mute path (WSJF 7.0)

**Action:** AUDIT §7.1 — `shared/governance/music_policy.py` ships with zero production callers. Wire `default_policy().evaluate(audio_window)` into:

1. **CPAL audio capture loop** — `agents/hapax_daimonion/cpal_runner.py` (or the captured-audio buffer that feeds it). On every N-second window of captured audio, call `policy.evaluate(window)`; if `MusicAction.MUTE`, gate the output stream; if `MusicAction.RECORD_TRANSCRIPT`, log transcript per Path A.
2. **Studio compositor mute path** — when `policy.evaluate()` returns a mute decision, the studio compositor needs to also mute its own broadcast audio (not just CPAL). Use the existing impingement bus or a direct call into `agents/studio_compositor/audio_mute.py` (file may need to be created if no abstraction exists).

**Acceptance (uplifted 2026-04-20T17:30Z):**
(a) `Grep music_policy|MusicPolicy` returns ≥3 production import sites (currently 1: `shared/governance/demonet_metrics.py:18,71` metric-only ref);
(b) reference music sample at `tests/governance/fixtures/music_30s.wav` triggers `MusicAction.MUTE` within 5s of playback start, captured by `tests/governance/test_music_policy_cpal_integration.py::test_known_music_sample_mutes`;
(c) reference speech sample at `tests/governance/fixtures/speech_30s.wav` triggers no mute over 30s;
(d) Prometheus counter `hapax_demonet_music_policy_mutes_total` increments on each mute decision (counter shipped per `12ac429d8`);
(e) escape hatch: `HAPAX_MUSIC_POLICY_DISABLED=1` env-var bypass for incident response.

**Call site (specified):** wire at `CpalRunner.process_audio_window()` (the captured-audio-buffer entrypoint), NOT the raw stream callback — windowing semantics already exist there.

**Files to touch:** `agents/hapax_daimonion/cpal_runner.py`, possibly `agents/studio_compositor/audio_mute.py` (new), `tests/governance/test_music_policy_cpal_integration.py` (new), `tests/governance/fixtures/{music,speech}_30s.wav` (new fixtures — generate with sox or pull from existing test audio archive).

**Cross-zone flag:** CPAL is alpha's `feedback_grounding_critical` zone; coordinate via relay before merging. Per `feedback_no_stale_branches`, scope to a small PR and ship within one session-window or split into D-18a (CPAL wire) + D-18b (compositor wire).

**Dependencies:** D-19 should ship before D-18 in the ideal sequence — wiring music_policy without first adding the lock fixes the unsynchronized state issue under live concurrent CPAL+director_loop access. If D-18 ships first, document "single-thread caller" in MusicPolicy docstring as an interim contract.

### §4.8 D-19 — Concurrency hardening bundle (WSJF 6.5)

**Action:** Two coordinated lock additions; both are 5-line patches. Per AUDIT §12.2 cross-cutting pattern observation: stateful dataclasses without explicit lock contracts are a recurring anti-pattern in this window's governance modules.

1. **`_DEFAULT_WRITER` TOCTOU.** AUDIT §8.1 / `monetization_egress_audit.py:201-205` — wrap lazy init in module-level `threading.Lock` or use `functools.cache`. The latter is one line and idiomatic.
2. **`MusicPolicy._path_b_window_opened_at` lock.** AUDIT §8.2 / `music_policy.py:117-180` — add `_lock: threading.Lock = field(default_factory=threading.Lock)` and guard the read-then-write on the Path B branch.

**Acceptance:** both modules pass `pytest -k 'concurrent' tests/governance/` (add a thread-fuzzing test if not present); existing tests still green.

**Files to touch:** `shared/governance/monetization_egress_audit.py`, `shared/governance/music_policy.py`, `tests/governance/test_concurrent_default_writer.py` (new), `tests/governance/test_music_policy_concurrent_evaluate.py` (new).

### §4.9 D-21 — Repo-vs-systemd state divergence (WSJF 5.0)

**Action:** AUDIT §8.4 — `8816040eb` deleted `rag-ingest.timer` from the repo, but `systemctl --user list-unit-files | grep rag-ingest` still shows `rag-ingest.service linked enabled` (verified live during this weave: 2026-04-20). The repo-vs-systemd state divergence is identical-shape to the workspace `Subagent Git Safety` lost-work hazard, but for systemd state.

Ship `scripts/hapax-systemd-reconcile.sh` that:
1. Lists all `linked` user units under `~/.config/systemd/user/`.
2. Cross-references against `systemd/units/*.{service,timer,path,socket}` in the council repo.
3. For each linked unit absent from the repo: `systemctl --user disable --now <unit>` and unlink (with `--dry-run` default; `--apply` to act).
4. Emit a ntfy summary on completion.

Schedule via existing `claude-md-audit.timer` precedent — daily oneshot.

**Acceptance:** running `scripts/hapax-systemd-reconcile.sh --apply` disables rag-ingest.timer (the audit's specific case); idempotent on second invocation.

**Files to touch:** `scripts/hapax-systemd-reconcile.sh` (new), `systemd/units/hapax-systemd-reconcile.{service,timer}` (new), `tests/scripts/test_hapax_systemd_reconcile.py` (new).

### §4.10 D-20 — Crash-safety / atomic-write bundle (WSJF 4.3)

**Action:** Three small patches addressing AUDIT §8.3, §9.1, §10.1 — all are state-cleanup / atomic-write hygiene defects in the new governance / programme modules.

1. **`ProgrammePlanStore` `.tmp` orphan cleanup.** AUDIT §8.3 / `programme_store.py:189-196` — add `_cleanup_tmp()` startup hook that unlinks any `*.tmp` siblings of `self.path` left over from prior crashes. Alternatively, filter `.tmp` files in `all()`.
2. **`quiet_frame.activate_quiet_frame` no-op `if/else` collapse.** AUDIT §10.1 / `quiet_frame.py:130-145` — both branches call `st.add(programme)`. Collapse to a single `st.add(programme)`. Then add a `compact()` method on `ProgrammePlanStore` (or rely on dedup-at-read) so the store doesn't grow monotonically on every reactivation.
3. **`prune_old_archives` crash-safety.** AUDIT §9.1 / `monetization_egress_audit.py` prune loop — log start/end of prune so a crash mid-loop is visible; or move matched files to a quarantine dir then `shutil.rmtree`.

**Acceptance:** new tests verify `.tmp` cleanup-after-simulated-crash; quiet_frame reactivation doesn't grow the store; prune logs show start+end timestamps.

**Files to touch:** `shared/programme_store.py`, `shared/governance/quiet_frame.py`, `shared/governance/monetization_egress_audit.py`, plus three new test files.

### §4.11 D-23 — Detector exception fail-closed + egress-audit timer + Prometheus counters (WSJF 4.3)

**Action:** Robustness/observability bundle covering AUDIT §7.2, §9.2, §11.1, §11.5.

1. **Wrap `MusicPolicy.evaluate()` detector call.** AUDIT §9.2 — `self.detector.detect(audio_window)` raises propagate to broadcast loop. Wrap in try/except → `MusicDetectionResult(detected=False, source="error")` so the loop never crashes on a flaky detector.
2. **Ship egress-audit systemd timer.** AUDIT §7.2 — `bee082804` deferred the timer for daily rotate+prune. Without it, the 30-day retention promise is unenforced. Add `systemd/units/hapax-egress-audit-rotate.{service,timer}` calling `python -m shared.governance.monetization_egress_audit rotate`. ~10 LOC.
3. **Add `hapax_demonet_*` Prometheus counters across 8 new modules.** AUDIT §11.1 — at minimum `hapax_demonet_egress_records_total{risk,allowed}`, `hapax_classifier_unavailable_total{reason}`, `hapax_programme_store_active_count`, `hapax_quiet_frame_activations_total`, `hapax_music_policy_decisions_total{action}`. Per the existing `127.0.0.1:9482` Prometheus pattern.
4. **Optional `audit_writer` param on `classify_with_fallback`.** AUDIT §11.5 — composition hook: every fail-closed event becomes a `classifier_unavailable` egress record.

**Acceptance:** Grafana dashboard `dashboards/hapax-demonet.json` (new) shows live counts after a smoketest; `MusicPolicy` integration test with a raising detector passes; rotate timer fires per `systemctl --user list-timers`.

**Files to touch:** `shared/governance/music_policy.py`, `shared/governance/classifier_degradation.py`, `shared/governance/monetization_egress_audit.py`, `shared/governance/quiet_frame.py`, `shared/governance/ring2_classifier.py`, `shared/programme_store.py`, `systemd/units/hapax-egress-audit-rotate.{service,timer}` (new), `dashboards/hapax-demonet.json` (new), plus tests.

### §4.12 D-24 — Audit-cleanup bundle (WSJF 1.4)

**Action:** Catch-all bundle of 11 LOW-severity audit findings. Mechanical, low-risk, no operator question. Ship as a single PR; each item is independently revertable.

1. AUDIT §6.1 — `default_*` factory naming consistency: pick noun (`default_writer`, `default_policy`, `default_store`) or verb across `quiet_frame` family.
2. AUDIT §6.3 — tests-location convention: all `programme_store` consumers' tests live in `tests/governance/`, but `test_programme_store.py` itself is in `tests/shared/`. Decide one home.
3. AUDIT §8.5 — promote `_redact_points` import-failure from log+continue to raise (operator-decided per audit row 15; default to raise for fail-CLOSED).
4. AUDIT §8.6 — add a loud docstring warning to `classify_with_fallback` that timeout enforcement is post-hoc, not preemptive (until Phase 1+ classifier honors timeout itself).
5. AUDIT §9.3 — `unicodedata.normalize('NFKD', ...)` before lowercasing in `verify_vinyl_chain` substring matching.
6. AUDIT §9.4 — emit `warning` in `ProgrammePlanStore` if `self.path.stat().st_size > 1_000_000`.
7. AUDIT §10.3 — `if not math.isfinite(lufs): return None` guard in `_loudness_to_band`.
8. AUDIT §10.4 — optional `verify_port=True` flag on `recall_preset` to ping the MIDI port before issuing the burst.
9. AUDIT §11.3 — extract `_BASE_SCENE` from `shared/evil_pet_presets.py` to a shared constant; have `scripts/evil-pet-configure-base.py §3.8` import it.
10. AUDIT §11.4 — add `hapax-audio-topology verify --profile vinyl` subcommand wrapping `vinyl_chain_verify.verify_vinyl_chain` (overlaps with D-18 for a different module, but vinyl_chain_verify also has 0 callers per AUDIT §7.1).
11. AUDIT §11.6 — Hypothesis property-based tests for `aggregate_mix_quality` (algebraic over min-of-floats) and `_parse_verdict` (JSON-shape parser).

**Acceptance:** all 11 sub-items shipped; `pytest tests/ -q` green; `Grep` confirms naming consistency.

**Files to touch:** spans most new modules from this audit window; scope is wide but each diff is small.

---

## §5. NEEDS_CLARIFICATION queue (one question per item)

### §5.1 D-05 — Ring 2 classifier Phase 1 (WSJF 5.4)

**Sharpening question for operator:**

> For the 500-sample benchmark labelling (`benchmarks/demonet-ring2-500.jsonl`) — do you want me to (a) **synthesize** 500 samples from the existing `~/hapax-state/programmes/egress-audit/` JSONL, presenting them in a CLI for you to bucket none/low/medium/high; or (b) **generate** 500 fresh from the catalog × programme cross-product, then bucket? Synthesizing from real history calibrates against actual production traffic; synthetic gives full coverage but no production weighting. (Spec source: CAPSTONE §3 lines 58–73; PRE-COMPACT §4.2 lines 72–83.)

**Once answered:**

- Spec is locked. Implementation per CAPSTONE §3 "Recommended Phase 3 shape" (lines 113–145) with prompts sourced from `docs/research/2026-04-19-demonetization-safety-design.md` §6 (PRE-COMPACT §4.2 line 80).
- Estimated 400–600 LOC across `shared/governance/ring2_classifier.py` + `tests/governance/test_ring2_classifier.py` + `scripts/benchmark-ring2-classifier.py` + `benchmarks/demonet-ring2-500.jsonl`.

### §5.2 D-07 — Vinyl-broadcast signal-chain software wiring (WSJF 2.6)

**Sharpening question for operator:**

> The hardware signal chain is documented in `docs/research/2026-04-20-vinyl-broadcast-signal-chain-topology.md`. The software side I'd wire is one PipeWire conf + one verify test per channel-mapping. Confirm: for the "vinyl" path on the L6 ch 5–6 stereo input, the software writes (a) **a separate `hapax-vinyl-capture` filter-chain** mirroring `hapax-l6-evilpet-capture.conf`, or (b) **just a verify-only check** asserting the existing `pw-cat` consumers in `agents/studio_compositor/` see ch 5–6 stereo? (Source: TRIAGE §1 row 10; L6-RUNBOOK §1 lines 24–26.)

### §5.3 D-16 — Ring 2 per-`SurfaceKind` prompt design (WSJF 4.2)

**Sharpening question for operator:**

> Per-surface false-positive tolerance differs structurally — TTS false-positive cost is high (operator-audible re-recruitment); ward overlay FP cost is low (just visual swap). Per `SurfaceKind` (TTS / captions / overlay / ward), do I (a) **share a single base prompt** with surface-specific risk-tolerance constants; or (b) **author 4 distinct prompts** with per-surface few-shot exemplars? (a) is cheaper; (b) is more accurate per-surface. (Spec source: CAPSTONE §3 scope bullet 5; DEMONET-PLAN cross-ref to research §6.)

**Note:** D-16 is upstream of D-05 — answering it is a prerequisite for the Phase 1 prompt-author phase. Recommend operator answer §5.1 + §5.3 in one round.

---

## §6. NEEDS_RESEARCH queue (proposed dispatch brief per item)

### §6.1 D-08 — Audio-normalization ducking strategy (WSJF 3.7)

**Status per TRIAGE §1 row 8:** "Blocked. Unblock LADSPA syntax research first; then plan."

**LADSPA syntax research already shipped** as `docs/research/2026-04-20-ladspa-pipewire-syntax.md` per PRE-COMPACT §5.5 line 137. So D-08 is unblocked structurally — what's needed now is the *integration* research.

**Proposed dispatch brief (10–15 min subagent, research only):**

```yaml
to: research-subagent
mode: shared-directory (per global CLAUDE.md Subagent Git Safety #2)
deliverable: docs/research/2026-04-21-audio-normalization-ducking-integration.md
scope: |
  Given:
    - LADSPA syntax research shipped (docs/research/2026-04-20-ladspa-pipewire-syntax.md)
    - voice-fx-loudnorm.conf shipped (config/pipewire/voice-fx-loudnorm.conf)
    - Existing voice-fx chain (config/pipewire/voice-fx-chain.conf)
    - L6 multitrack topology per L6-RUNBOOK
  Produce a 1-page integration plan covering:
    - Where the ducking gate lives (pre-mix vs per-source)
    - How TTS-active signal reaches the ducker (impingement? direct sub-callback?)
    - 3-utterance smoketest acceptance criteria
    - Whether audio-topology.yaml needs a new node-kind
constraints: research only, no code, no plan-stub commits
```

**Acceptance for D-08 itself (uplifted 2026-04-20T17:30Z):** research doc exists at `docs/research/2026-04-21-audio-normalization-ducking-integration.md` AND a follow-up plan stub (≤1 page) is filed at `docs/superpowers/plans/2026-04-21-audio-normalization-ducking-plan.md` enumerating concrete LOC-sized PR(s). If research returns "no integration possible", plan stub records the negative finding and D-08 closes with no follow-on.

### §6.2 D-15 — rag-ingest livestream-compatible redesign

Already dispatched per DELTA-YAML lines 30–38 + RAG-RESEARCH relay drop. Re-promotes to READY (D-01 shape) when alpha returns the spec+plan.

**Watch for:** `gh pr list --search 'rag-ingest'` and inbox for `~/.cache/hapax/relay/alpha-to-delta-rag-ingest-*.md`.

---

## §7. BLOCKED queue (what's blocking + when expected to unblock)

| ID | Item | Blocker | Unblock condition |
|---|---|---|---|
| D-04 | L6 retargets apply | hardware patching | operator patches Rode Wireless Pro on L6 ch 1 + confirms AUX 1 routing per L6-RUNBOOK §1 lines 28–32 |
| D-06 | LADSPA loudnorm operator-apply | manual `cp` + pipewire restart | one-time operator step per PRE-COMPACT §5.5 line 138 |
| ~~D-09~~ | ~~Music policy Path B switch~~ | ~~operator decision~~ | **CLOSED 2026-04-20T17:30Z (§10.5 RESOLVED — stay Path A); also see §3 master table** |
| D-10 | Evil Pet `.evl` parser Phase 1 | physical SD card | operator delivers factory `.evl` per DELTA-YAML line 57 (note: CC-burst pack at `a19e8389f` already ships **without** `.evl` reverse — `.evl` is purely additive per CAPSTONE §1 row #194) |
| D-11 | Dual-FX Phase 6 (S-4 firmware) | firmware flash | operator flashes S-4 OS 2.1.4 per PRE-COMPACT §9.4 line 247 |
| ~~D-12~~ | ~~#202 Phase 2~~ | ~~strict-serial after Phase 1~~ | **READY 2026-04-20T17:30Z** — D-05 shipped `d6a4d4753`; per §10.2 RESOLVED with 4-distinct-prompt strategy. See §3 master table. |
| ~~D-13~~ | ~~#202 Phase 3~~ | ~~strict-serial after Phase 2~~ | **SHIPPED `896d8a52f`** (see §3 master table) |
| ~~D-14~~ | ~~#202 Phase 4~~ | ~~strict-serial after Phase 3~~ | **SHIPPED `9db8fb8fd`** (see §3 master table) |

**Note on serial chain D-05 → D-12 → D-13 → D-14:** This is the longest delta-only chain remaining (FLOW §4.1 line 154). Estimated total 1300–2000 LOC across 4 phases. Each phase has its own infrastructure pre-wired per CAPSTONE §3.what's-pre-wired (`classifier_degradation`, `monetization_egress_audit`, `monetization_safety`, `quiet_frame`).

---

## §8. Recommended sequencing

**Note (post-audit-weave 2026-04-20 d33be1a6e+):** D-05 / D-13 / D-03 have shipped out-of-band (`d6a4d4753`, `896d8a52f`, `b0a02940e`); the sequencing below has been re-walked to reflect that and the 8 new audit-derived items.

### §8.1 Next 4 hours (T+0 → T+240) — POST STATE-UPDATE 2026-04-20T17:30Z

**Goal:** ship D-25 (alpha-zone, operator-raised neon defect), then clear the cross-zone-authorized governance wires (D-17 residue, D-18) and the D-24 9-of-11 residue.

- **T+00 to T+60** — **D-25 (WSJF 6.3, alpha-shipping)** — new `palette_remap` shader node + `presets/neon.json` rewire + brightness ceiling 1.1→0.85 + smoketest fixture. Covered by alpha in this turn; delta does NOT pick up.
- **T+60 to T+120** — **D-17 director_loop residue (WSJF 7.0)** — alpha-PR per §10.9. Wire `activate_quiet_frame()` / `deactivate_quiet_frame()` into `agents/studio_compositor/director_loop.py` on monetization-risk-gate transition BLOCKED↔ALLOWED. Idempotent per D-20 dedup-add.
- **T+120 to T+240** — **D-18 (WSJF 7.0)** — wire `music_policy.default_policy().evaluate(audio_window)` into `CpalRunner.process_audio_window()` (the captured-audio-buffer entry per §4.7 uplift). Cross-zone-authorized.

### §8.2 Next 8 hours (T+240 → T+480)

- **T+240 to T+330** — **D-12 (WSJF 4.2)** — #202 Phase 2 classifier-side opt-in negotiation. Per §10.2 decision: 4 distinct prompts. Reconcile with `ring2_gate_helper.py` (`3de317399`).
- **T+330 to T+390** — **D-07 (WSJF 2.6)** — vinyl-broadcast verify-only per §10.4. Tiny — `verify_l6_ch_5_6_consumers()` + test.
- **T+390 to T+480** — **D-24 9-of-11 residue (WSJF 1.4)** — remaining sub-items per §3 row D-24 PARTIAL. Mechanical, low-risk; ship as background while monitoring D-01 / D-15.

### §8.3 Next 16 hours (T+480 → T+960)

- D-15 implementation if alpha returned spec.
- D-08 dispatch audio-normalization integration research subagent per §6.1.
- D-02 standing readiness — proactive sweep of `~/hapax-state/livestream-events/`.
- Revisit BLOCKED items D-04 / D-06 / D-10 / D-11 — operator may have signalled.

### §8.2 Next 8 hours (T+240 → T+480)

**Goal:** wire the two truly-dead governance modules (D-17, D-18) into production callers and finish observability/robustness pass.

- **T+240 to T+330** — **D-17 (WSJF 7.0)** — wire `quiet_frame` (CLI + director_loop transition trigger). 90 min budget includes the cross-zone relay coordination.
- **T+330 to T+450** — **D-18 (WSJF 7.0)** — wire `music_policy` into CPAL audio loop (split into D-18a CPAL + D-18b compositor if scope creeps). Cross-zone with alpha; ship D-18a first, leave D-18b on the relay if alpha is mid-PR.
- **T+450 to T+480** — **D-23 (WSJF 4.3)** — robustness/observability bundle: detector try/except, egress-audit timer, Prometheus counters. Each sub-item independent; ship in one PR if time permits, else split.

### §8.3 Next 16 hours (T+480 → T+960)

- D-12 Phase 2 (#202 classifier-side opt-in negotiation) — assumes operator answered §5.1+§5.3. Per FLOW §4.4 line 178 ~250–350 LOC.
- D-14 Phase 4 (#202 degradation integration tests) — strict-serial after D-12. Small, smoothing pass.
- **D-24 (WSJF 1.4)** — audit-cleanup bundle (11 LOW-severity items). Use this as a "background while monitoring" task; ships as a single wide-scope-but-small-diff PR.
- After full Ring 2 chain: revisit BLOCKED items D-04 / D-06 / D-09 — reasonable chance operator has signalled by then.

### §8.4 Sequencing rationale changes (vs pre-audit-weave §8)

| Pre-weave assumption | Post-weave reality | Sequencing impact |
|---|---|---|
| D-03 audio-topology verify is the second-fastest READY item | D-03 shipped `b0a02940e`; D-22 doc-bundle now slot-2 (T+15) | T+15 to T+45 reassigned to D-22 |
| D-05 Ring 2 Phase 1 is the single big-ticket; needs operator answer | D-05 shipped `d6a4d4753`; only Phase 2/4 left (D-12, D-14) | §8.2 freed to wire D-17/D-18 dead modules instead |
| D-13 strict-serial after D-12 | D-13 shipped `896d8a52f` (out of strict-serial order, with own integration) | §8.3 freed to focus on D-24 cleanup + remaining BLOCKED revisits |
| READY queue size = 4 | READY queue size = 12 (4 + 8 audit-derived) | §8.1 now front-loads small-WSJF items D-22/D-19/D-21 instead of waiting on cross-zone polls |

---

## §9. Cross-zone coordination items (alpha-touches; coordination cost factor)

| ID | Item | Alpha-side scope | Cost-mult |
|---|---|---|---|
| D-01 | Cross-zone consumer PR review | review only; alpha owns the actual consumer code | 1.0 (no cost; ball is in alpha's court) |
| D-15 | rag-ingest research return | alpha returns spec; delta implements | 1.5 (round-trip latency) |

**Coordination cost factor applied:** all WSJF scores in §3 already include the round-trip cost in Job Size for items requiring alpha return. Items where the ball is purely in alpha's court (D-01) have JS=2 (review-only); items where delta reads a spec then implements (D-15) have JS=8 reflecting both legs.

**Cross-zone risk:** TRIAGE-RELAY lines 27–45 enumerates 11 alpha-zone unqueued items (HOMAGE-SCRIM family is the largest cluster). Delta does not own these; cited here only so the next session knows alpha has its own large unplanned backlog and shouldn't expect fast pickup of D-15-style returns.

---

## §10. RESOLVED — alpha-decided 2026-04-20T17:30Z

Per operator directive *"do not wait for my decisions, make best decision and unblock yourself"* — all 9 pending decisions made by alpha. Each decision is recorded with rationale so delta can reverse if context changes.

### §10.1 Ring 2 sample-set strategy (was D-05 unblock) — MOOT

D-05 shipped `d6a4d4753`. Verify in implementation which path was taken; no decision required.

### §10.2 Ring 2 per-`SurfaceKind` prompt strategy — DECIDED: 4 distinct prompts

**Choice:** (b) — 4 distinct prompts with surface-specific exemplars.

**Rationale:** TTS false-positive cost is high (audible re-recruitment, breaks operator's flow); ward overlay FP cost is low. The precision benefit of distinct prompts dominates the (small) authoring cost. Memory `feedback_grounding_exhaustive` says: be precise. Memory `feedback_director_grounding` says: don't trade accuracy for speed in director-grade work — this is director-adjacent.

**Effect:** D-12 + D-16 now READY. D-12 implementation should author 4 prompt files at `shared/governance/ring2_prompts/{tts,captions,overlay,ward}.md` with 3 few-shot exemplars each.

### §10.3 L6 retargets readiness — DEFERRED (hardware-physical)

Cannot decide for operator — requires physical patch + audible verification. D-04 stays BLOCKED-hardware.

### §10.4 Vinyl-broadcast wiring shape — DECIDED: verify-only

**Choice:** (b) — verify-only assertion against existing consumers.

**Rationale:** Smaller surface area, reversible, fewer moving parts, no new pipewire conf to maintain. Default-after-24h was already verify-only per §5.2. Easier to escalate to filter-chain later if measurement shows a need.

**Effect:** D-07 now READY. Implementation: add `verify_l6_ch_5_6_consumers()` to `shared/audio_topology/verifiers.py` (or wherever L6 verifies live), assert ch 5-6 stereo input is consumed by ≥1 named consumer in `agents/studio_compositor/`. New test at `tests/audio_topology/test_l6_vinyl_consumers.py`.

### §10.5 Music policy Path B — DECIDED: stay Path A

**Choice:** stay on Path A (mute + transcript), shipped default.

**Rationale:** Path A is shipped, working, has audit hooks (`12ac429d8` Prometheus counters). Path B (≤30s clip windower) adds complexity without clear win. If operator later wants Path B, the runtime switch already exists per `shared/governance/music_policy.py`.

**Effect:** D-09 CLOSED.

### §10.6 OQ-01 neon palette confirmation — DECIDED: synthwave + 0.3 Hz

**Choice:** synthwave 12-color palette + 0.3 Hz cycle, matching CPU `agents/studio_fx/effects/neon.py:_SYNTHWAVE_PALETTE` verbatim.

**Rationale:** CPU path is the established target visual; matching it eliminates GPU-vs-CPU divergence and converges on the operator-validated aesthetic.

**Effect:** D-25 READY for alpha to ship in this turn.

### §10.7 OQ-02 promotion — DECIDED: PROMOTE NOW

**Choice:** promote OQ-02 to research-to-plan triage candidate immediately.

**Rationale:** Three-bound governance is foundational for all future scrim work. Better to start the planning epic in parallel with WSJF cleanup than to serialize. OQ-01 ship establishes the brightness-ceiling pattern that OQ-02 generalizes.

**Effect:** Triage doc to be created at `docs/research/2026-04-20-nebulous-scrim-three-bound-invariants-triage.md`.

### §10.8 OQ-02 face-obscure ordering — DECIDED: BEFORE scrim

**Choice:** face-obscure runs at camera producer layer BEFORE scrim compositor.

**Rationale:** Matches existing pipeline architecture (`agents/studio_compositor/face_obscure_integration.py` runs at camera producer per CLAUDE.md § Unified Semantic Recruitment). Matches nebulous-scrim-design §10 Q1 own proposal. Stronger answer per OQ-02 spec skeleton item 6: "face-obscure before scrim AND every scrim effect proven safe under all combinations on ALL three bounds."

**Effect:** Resolves nebulous-scrim-design §10 Q1. Recorded in alpha.yaml OQ-02 `operator_decisions_2026_04_20`.

### §10.9 D-17 director_loop wire ownership — DECIDED: alpha-PR with delta-review

**Choice:** alpha ships director_loop wire as a small alpha-PR, delta reviews if active.

**Rationale:** `agents/studio_compositor/director_loop.py` is alpha-zone per trio-delivery split. Delta authored the spec; alpha owns the implementation surface. Small wire (~50 LOC), low blast radius. Cross-zone coordination cost minimized by alpha-side ship.

**Effect:** D-17 director_loop residue is alpha-shippable; delta does not block on this.

---

## §11. Citation index (verification trail)

This document cites the following sources at the line/section ranges given. Total 32 distinct citation locations.

1. PRE-COMPACT §3 line 50 — working-tree-clean confirmation
2. PRE-COMPACT §4.2 lines 72–83 — #202 Phase 1 spec
3. PRE-COMPACT §4.4 line 91 — #197/#198 review pickup
4. PRE-COMPACT §4.5 lines 97–102 — livestream regression standing readiness
5. PRE-COMPACT §5.1 lines 110–114 — #202 Phase 2/3/4
6. PRE-COMPACT §5.2 + §7 line 191 — L6 retargets
7. PRE-COMPACT §5.3 lines 128–130 — music policy
8. PRE-COMPACT §5.4 lines 132–134 — Evil Pet `.evl`
9. PRE-COMPACT §5.5 lines 136–138 — LADSPA loudnorm
10. PRE-COMPACT §6.1 lines 145–148 — voice-tier 3b cross-zone
11. PRE-COMPACT §6.2 lines 150–154 — Mode D × voice-tier mutex 3 cross-zone
12. PRE-COMPACT §9.1 line 215 — voice-tier 7-tier catalog
13. PRE-COMPACT §9.3 lines 232–240 — audio-topology Phases 1–6
14. PRE-COMPACT §9.4 lines 246–247 — dual-FX Phase 6
15. PRE-COMPACT §9.5 line 254 — egress audit reference
16. FLOW §3 lines 88–94 — audio-topology dependency graph
17. FLOW §3 line 84 — Mode D shipped (Gate 2)
18. FLOW §3.2 line 145 — vinyl-broadcast software wiring
19. FLOW §4.1 line 154 — longest delta-only chain
20. FLOW §4.4 line 178 — Phase 2 size estimate
21. FLOW §6 line 240 — dual-FX Phase 6 operator gate
22. FLOW §10.3 line 390 — audio-norm research blockage history
23. FLOW §11 hour-3 lines 421–430 — audio-topology verify-sweep
24. TRIAGE §1 row 8 — audio-normalization-ducking blocked-then-unblocked
25. TRIAGE §1 row 10 — vinyl-broadcast software wiring
26. TRIAGE §3 row 36 — vinyl-broadcast signal-chain (operator-authored hardware)
27. TRIAGE-RELAY lines 27–45 — alpha-zone gap list
28. CAPSTONE §1 lines 11–33 — 35-ship table (post-resume + pre-crash)
29. CAPSTONE §3 lines 58–73 — #202 scope per plan §3
30. CAPSTONE §3 lines 113–145 — Recommended Phase 3 shape skeleton
31. DELTA-YAML lines 20–28 — VRAM fix shipped (`8816040eb`)
32. DELTA-YAML lines 30–38 — rag-ingest research dispatch to alpha
33. DELTA-YAML lines 51–66 — operator-gated items + next-session priorities
34. L6-RUNBOOK §1 lines 24–32 — pre-condition + pending operator confirms
35. DEMONET-PLAN §0.1 lines 38–62 — three-rings architecture (Phase 2/3/4 anchor)

---

## §12. Successor session entry checklist — POST STATE-UPDATE 2026-04-20T17:30Z

1. **Read this file first.** It is the front-of-queue.
2. Read PRE-COMPACT (full file) for exhaustive prior-state. Read AUDIT (`docs/research/2026-04-20-six-hour-audit.md`) for the d33be1a6e weave context.
3. **All §10 operator questions are RESOLVED** — no waiting on operator. If operator overrides any §10 decision, update §10 then re-sequence §8.
4. `gh pr list --search 'voice-tier OR mode-d OR engine_session OR rag-ingest'` — check for alpha returns on D-01 / D-15.
5. **First action:** D-25 (alpha-zone) is alpha's responsibility this turn — confirm shipped before starting downstream items. If not shipped, escalate via relay; do NOT pick up (alpha-zone).
6. **Second action:** D-12 (#202 Phase 2) — shipped per §10.2 decision (4 distinct prompts at `shared/governance/ring2_prompts/{tts,captions,overlay,ward}.md`). Reconcile with `ring2_gate_helper.py` (`3de317399`).
7. **Third action:** D-18 (`music_policy` CPAL wire) — cross-zone-authorized; spec uplift in §4.7 with concrete acceptance + call site (`CpalRunner.process_audio_window()`).
8. **Fourth action:** D-07 (vinyl-broadcast) — verify-only per §10.4. ~30 min.
9. **Fifth action:** D-24 9-of-11 residue (mechanical LOW-severity bundle).
10. Background-task: D-15 implementation when alpha returns spec.
11. Refresh `delta.yaml` `next_delta_session_priorities` from this document's READY queue.

---

*End of WSJF reorganization (audit-woven 2026-04-20 d33be1a6e; state-updated + decisions-resolved 2026-04-20T17:30Z by alpha at HEAD `12ac429d8`). Next delta session executes READY queue rank-ordered: D-12 → D-18 → D-07 → D-24-residue → D-15 (when ready) → D-08-dispatch.*
