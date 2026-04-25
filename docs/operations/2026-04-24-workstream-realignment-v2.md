# Workstream Realignment v2 — Audit-Incorporated

**Author:** beta
**Date:** 2026-04-24T21:40Z
**Supersedes:** `2026-04-24-workstream-realignment.md` (v1)
**Based on:** 5 independent audit agents (coherence / WSJF / completeness / robustness / missed-opportunities) on v1.
**Operator aim:** *"faster flow; nothing gets lost; entire plan accounted for."*

## 0. Why v2

v1 had **~60 items unaccounted for** per completeness audit. v1 had **false serialization** (Phase 0 blocks Phase 1) per missed-opportunity audit. v1 had **single-point-of-failure keystone** without kill-switch per robustness audit. v1 had **HIGH-severity coherence defect** (fortress deferred on false Phase-0 dependency) per coherence audit. v1 had **WSJF scoring outliers** per scoring audit. v2 corrects all.

## 1. State snapshot (2026-04-24T21:40Z)

Today's shipped: 33 feature merges. Main green. CI speed ~5-8min; **but note**: #1318 CI script has xfail-substring regression fixed by #1329 in-flight (trivial hot-fix; my own regression).

In-flight: #1316 delta render_stage (admin-merge-eligible); #1320→1321 ytb-010 fully closed; #1322 epsilon xfails (blocked by #1329); #1323-1328 dependabot (5 build-dep bumps, some failing on xfail regression); #1329 beta hot-fix.

## 2. Absolute rules (re-asserted)

1. **No operator-approval waits.** Aesthetic signoffs, LORE-MVP flag flips, HOMAGE default-flips, SS1 live-validation — **session-callable** per `feedback_no_operator_approval_waits`. v1 hedged on this; v2 reassigns.
2. **Revert > stall.** Per `feedback_never_stall_revert_acceptable`.
3. **270s ScheduleWakeup.** Cache-warm.
4. **Claim-before-parallel-work** for out-of-lane/cross-cutting.
5. **Every move grounded or outsourced-by-grounding.** T1-T8 operative (`feedback_grounding_act_operative_definition`).
6. **No session retirement until LRR complete** (`feedback_no_retirement_until_lrr_complete`).

## 3. Epic catalog — full census, WSJF rescored

### 3.1 CRITICAL (13+) — top-of-stack

| # | Epic | WSJF | Owner | Status | Rationale |
|---|---|---|---|---|---|
| 1 | **Grounding-capability-recruitment Phase 0 STUB** (stub signatures of `shared/grounding.py` + `shared/grounding_adjudicator.py`; ~50 LOC; ships FIRST to unblock parallel Phase 1 drafts) | **14.0** | beta | NEW | Compiles axiom violations into unwritability; unblocks 3 peer lanes via stubs. Rescored from v1's 11.0 per WSJF audit. |
| 2 | **CI xfail-substring regression hot-fix** (#1329) | **14.0** | beta | IN-FLIGHT | Blocks every xfail-bearing PR + dependabots. |
| 3 | **ef7b-212 PR-review cross-zone #197-#198 consumer-side** | **17.0** | delta | STANDING | v1 missed entirely. Highest-WSJF standing item. |
| 4 | **DEVIATION-025 P0 Langfuse score calls** (conversation_pipeline salience breakdown) | **13.0** | alpha | BLOCKED→CLAIMABLE | v1 missed entirely. Data-loss-critical: "Every Phase A session without this = permanent data loss for Claim 5." |
| 5 | **ef7b-213 livestream regression watch** (standing readiness) | **13.0** | delta | STANDING | v1 missed entirely. Continuous concern. |

### 3.2 HIGH (10-12) — top queue actionable

| # | Epic | WSJF | Owner | Status |
|---|---|---|---|---|
| 6 | **Chronic xfails PR** (#1322 landing when #1329 unblocks) | 10.0 | epsilon | IN-FLIGHT |
| 7 | **ytb-OG2 dual-format broadcast verification** | 11.0 (rescored from 16) | operator | QUEUE |
| 8 | **LRR Phase A validation continuation** (Shaikh RIFTS; Phase 7 doc-persona condition `cond-phase-a-persona-doc-qwen-001`; ≥8 livestream sessions; currently at 2) | 10.0 | alpha (research) + beta (observability) | ONGOING |
| 9 | **HOMAGE post-live F3/F4/F5 queue** (from `project_homage_go_live_directive`: F3=silence.*, F4=director-micromove capability registry, F5=speech_production recruitment path) | 10.0 | delta + epsilon split | **v1 missed entirely** |
| 10 | **Grounding-capability-recruitment Phase 0 FULL** (Pydantic validator + ruff HPX001 + classify_description + CapabilityRecord extension) | 10.0 | beta | POST-STUB |
| 11 | **Grounding-capability-recruitment Phase 1 migrations (23 sites)** | 8.0 per-slice × 23 | distributed | STUBBABLE-PARALLEL |

### 3.3 MEDIUM (6-10)

| # | Epic | WSJF | Owner |
|---|---|---|---|
| 12 | **Fortress `model_daily` cloud violation — immediate config swap to `local-fast`** (same shape as autonomous_narrative fix) | **6.0** (rescored from 2 — this is a live axiom violation, trivially fixed) | beta **NOW, not Phase-0-gated** |
| 13 | **Scrim-taxonomy architecture (ef7b-174 nebulous scrim)** | 7.0 | delta + epsilon | **v1 missed** |
| 14 | **Content programming layer above director-loop (ef7b-164)** | 7.0 | alpha | **v1 missed — operator load-bearing directive** |
| 15 | **De-monetization safety zero-red-flag invariant (ef7b-165)** | 7.0 | delta | **v1 missed — operator existential-risk directive** |
| 16 | **1d79-099 OLMo parallel TabbyAPI :5001 deploy** (LRR Phase 5 scenario-2) | 8.0 | alpha | CLAIMED but no owner surface in v1 |
| 17 | **1d79-085 beta-substrate-execution-chain 209-212** | 7.0 | beta | CLAIMED but no owner surface in v1 |
| 18 | **1d79-100 daimonion code-narration prep** | 6.0 | alpha | CLAIMED |
| 19 | **3499-004 gmail-sync inotify flood starving logos-api** | 7.0 | beta-as-coordinator (needs assignment) | **v1 missed — self-labeled CRITICAL** |
| 20 | **60f6-021..027 gaps implementation chain** (7 tasks: plan 1-6 + research 7-10 + implement 1-6 + implement 7-10 + observability + PR-everything) | 6.0 (chain) | split across sessions | **v1 missed entirely** |
| 21 | **FINDING-V publishers research-spec-plan** | 8.0 | delta |
| 22 | **FINDING-X subsumed** by Phase 1 (marked `subsumed=true`, removed from active score) | — | — |
| 23 | **Mobile-livestream substream research-spec-plan** | 6.0 | delta |
| 24 | **ytb-OG3 quota extension filing** | 8.0 | operator |

### 3.4 MEDIUM-LOW (3-6)

| # | Epic | WSJF | Owner |
|---|---|---|---|
| 25 | **ytb-010 Phase 3 Mastodon** — SHIPPED (#1321) | done | — |
| 26 | **AUTH-ENLIGHTENMENT Phase 2 + Moksha-specific enum follow-on** | 4.5 | epsilon |
| 27 | **AUTH-PALETTE Phase 2** (asset-gated; authored-placeholders per autonomy mandate OK) | 4.5 | epsilon |
| 28 | **ytb-OMG6 Phase B** (programme/axiom/research publishers) | 5.0 | epsilon |
| 29 | **ytb-OMG2 Phase 2** (Jinja2 dynamic rebuilder + timer) | 4.0 (rescored up — unblocks iteration) | alpha |
| 30 | **ytb-OMG8 Phase A compose-side** | 3.0 | epsilon |
| 31 | **ytb-003 thumbnail auto-generation** | 4.0 | delta |
| 32 | **ytb-009 in-band live captions** | 3.2 | delta |
| 33 | **ytb-011 Phase 2 sections manager** | 3.5 | alpha |
| 34 | **ytb-LEGIBILITY-SMOKE / TOKEN-POLE-PALETTE / OBJECTIVES-OVERLAY follow-ups** (3 cc-tasks from #1322 xfails; real-fix work) | 3.0-4.0 | split | **v1 captured xfails; v2 captures real-fix debt** |
| 35 | **Reverie 5-channel mixer wiring (RD/Physarum/Voronoi)** | 4.0 | delta | **v1 missed — active project per memory** |
| 36 | **HOMAGE #162/#163 insightface-arcface + enrollment-without-pause** | 5.0 | delta | **v1 missed (go-live directive queue)** |
| 37 | **HOMAGE #186 token-meter geometry rework (navel→cranium linear)** | 4.0 | delta | **v1 missed** |
| 38 | **HOMAGE #189 HARDM role-placement redesign** | 4.0 | delta | **v1 missed** |
| 39 | **HOMAGE #176/#177 Logos-fullscreen output quality vs OBS v4l2 parity** | 4.0 | delta | **v1 missed** |
| 40 | **4 main-red follow-ups** (ytb-WARD-CONTRAST / EMISSIVE-RETIRED-FLASH / EMISSIVE-GOLDEN-PANGO / ytb-GEAL-PERF-BUDGET) | 3.0 each | delta |

### 3.5 LOW (1-3)

| # | Epic | WSJF | Owner |
|---|---|---|---|
| 41 | **ytb-OMG9 infrastructure automation** | 2.2 | beta |
| 42 | **ytb-LORE-EXT future wards** | 2.1 | delta |
| 43 | **ytb-012 shorts extraction pipeline** | 2.1 | delta |
| 44 | **lssh-006/007/009/010/011** (5 livestream-surface-health retirements) | 1-3 each | delta |
| 45 | **#1292 QM1 OTel span pairing follow-on** | 2.0 | beta |
| 46 | **#1318 CI timeout removal (post-stability)** | 1.5 | beta |
| 47 | **Conversation-pipeline prewarm deLLM → TCP ping** | 3.0 (rescored up — axiom-closure + tiny job) | beta **NOW, not deferred** |
| 48 | **ef7b-188 Pi-6 sshd-unreachable restore** (physical-operator action but can be investigated session-side) | 2.5 | operator-primary |

### 3.6 Spec-triage (needs-plan) — **v1 missed entirely**

| # | Epic | Priority | Owner |
|---|---|---|---|
| 49 | **spec-2026-04-18-audio-pathways-audit** | HIGH | delta/beta |
| 50 | **spec-2026-04-18-youtube-broadcast-bundle** (OAuth + reverse-ducking) | HIGH | alpha |
| 51 | **spec-2026-04-18-local-music-repository** | MEDIUM | delta |
| 52 | **spec-2026-04-18-soundcloud-integration** | LOW | delta |

### 3.7 Research drops unscheduled — **v1 missed**

From `docs/research/` 2026-04-20..24:
- 6 homage-scrim drops
- camera-visual-abstraction-investigation
- dead-bridge-modules-audit
- livestream-halt-investigation
- notification-loopback-leak-fix
- prompt-level-slur-prohibition-design
- self-censorship-aesthetic-design
- rag-ingest-livestream-coexistence
- evilpet-s4-dynamic-dual-processor-research + ward-stimmung-modulator-design
- livestream-crispness-research + livestream-surface-inventory-audit
- missing-publishers-research
- vad-ducking-pipeline-dead-finding
- gem-rendering-redesign-brainstorm
- video-container-parallax-homage-conversion
- livestream-audio-unified-architecture (major architectural direction)
- ytb-ss2-substantive-speech-research-design (design landed today)

**Action:** beta files ~15 cc-tasks from these research drops, scores minimal WSJF (0-3) until operator prioritizes; preserves trail.

### 3.8 Bayesian validation + LRR Phase A present-state

- **14/28 measures complete on Day 26** (schedule started Day 1 = 2026-03-30; 5 days over 21-day schedule).
- **1 Blocked** + **5 Skipped** + **5 pending gates** — each needs individual remediation.
- **Current session count: 2** (need ≥8 for MCMC BEST data-sufficiency; next trigger ~2026-05-10).
- **ef7b-031 LRR Phase 4 Phase A completion OSF pre-reg** (claimed; continues)
- **ef7b-040 Phase 7 legacy prompt cleanup PR** (earliest 2026-04-30; 6 days out)
- **ef7b-056 PyMC MCMC BEST analysis at data-sufficiency gate** (trigger-gated)

**Action:** alpha owns Phase A research-direction; beta owns observability/data-loss-prevention (DEVIATION-025 P0).

## 4. Grounding-act audit (updated with v2 fixes)

| # | Surface | v1 state | v2 action |
|---|---|---|---|
| 1 | director_loop LLM | local-fast ✓ | wrap in adjudicator (Phase 1 via stub) |
| 2 | structural_director | local-fast ✓ | wrap in adjudicator (Phase 1 via stub) |
| 3 | conversation_pipeline main turn | cloud (engineering tension) | wrap in adjudicator; local uplift via OLMo Phase 5 |
| 4 | conversation_pipeline spontaneous speech | FIXED #1318 | wrap in adjudicator |
| 5 | autonomous_narrative compose | FIXED #1318 | wrap in adjudicator |
| 6 | **fortress deliberation** | ❌ violation ("defer Phase 0") | **FIX NOW: beta ships 1-line `model_daily="balanced"→"local-fast"` (or fortress-specific grounded route); adjudicator wrap later.** |
| 7 | logos/chat_agent + logos/interview | cloud (engineering tension) | wrap in adjudicator; local uplift |
| 8 | **conversation_pipeline prewarm** | mechanical (1-token LLM) | **FIX NOW: beta ships TCP ping replacement** |
| 9 | metadata_composer | cloud (work, legitimate) | wrap in adjudicator (Phase 1 via stub) |
| 10 | knowledge/query + dev_story/query | cloud (work, legitimate) | wrap in adjudicator |
| 11 | eval_grounding offline judge | cloud (work, legitimate) | wrap in adjudicator |
| 12 | vision tool | outsourced-by-grounding ✓ | wrap with provenance-chain |
| 13 | Imagen | outsourced-by-grounding ✓ | wrap with provenance-chain |

**Violation count after v2 Immediate fixes: 0 direct violations, 2 engineering tensions (conv-pipeline + logos chat — resolved by local uplift, not route-swap).**

## 5. Per-session realignment (v2)

### 5.1 beta (KEYSTONE)

Immediate:
1. **#1329 CI hot-fix merge** (in-flight)
2. **Fortress grounded-routing fix** (1-line, same pattern as spontaneous_speech) — ship NOW
3. **Prewarm deLLM → TCP ping** — ship NOW (15 min)
4. **Grounding Phase 0 STUB** (~50 LOC: frozen API surface for GroundingProfile + GroundingAdjudicator skeleton) — ship to unblock peer Phase 1 drafts

Short:
5. **Grounding Phase 0 FULL** (Pydantic validator + ruff HPX001 + classify_description + kill-switch `HAPAX_GROUNDING_ADJUDICATOR_BYPASS=1` env flag + migration codemod `scripts/migrate-litellm-to-adjudicator.py`)
6. **3499-004 gmail-sync inotify flood** investigate + fix

Ongoing:
7. LRR Phase A observability (DEVIATION-025 P0 coordination with alpha; instrumentation dashboards; alerts)
8. Peer audit + coordination
9. Workstream doc maintenance
10. Filing cc-tasks from unscheduled research drops (§3.7)

### 5.2 alpha

Immediate:
1. **DEVIATION-025 P0 Langfuse score calls** (data-loss-critical for LRR Phase A Claim 5) — ship NOW
2. **ytb-011 Phase 2 sections manager** (follow-on to #1317)

Short:
3. **Content programming layer (ef7b-164)** — operator load-bearing directive
4. **Grounding Phase 1: conversation_pipeline wrap** (draft PR against beta's Phase 0 stub; merges when stub lands)
5. **1d79-099 OLMo parallel TabbyAPI :5001 deploy** (LRR Phase 5 scenario-2)

Ongoing:
6. SS2 cycle 2 trigger
7. spec-2026-04-18-youtube-broadcast-bundle (HIGH)
8. 1d79-100 daimonion code-narration prep

### 5.3 delta

Immediate:
1. **Admin-merge #1316** (fallback: if blocked by hook, beta admin-merges on delta's behalf per keep-going tripwire)
2. **#1316 default-layout retag follow-on**
3. **ef7b-212 PR-review cross-zone #197-#198** (WSJF 17.0, standing)
4. **ef7b-213 livestream regression watch** (WSJF 13.0, standing)

Short:
5. **Grounding Phase 1: director_loop + structural_director wrap** (draft PR against stub)
6. **De-monetization safety (ef7b-165)** — operator existential-risk directive
7. **Scrim-taxonomy architecture (ef7b-174)** — operator aesthetic framework
8. **HOMAGE F3/F4/F5 post-live queue** (split with epsilon)

Medium:
9. **FINDING-V publishers research-spec-plan**
10. **HOMAGE #162/#163/#186/#189 visual redesigns**
11. **Reverie 5-channel mixer wiring**

### 5.4 epsilon

Immediate:
1. **#1322 chronic xfails** lands when #1329 unblocks

Short:
2. **AUTH-PALETTE Phase 2** (authored-placeholders per autonomy mandate)
3. **AUTH-HOMAGE default-flip** (bitchx-authentic-v1 as default; session-callable per autonomy mandate)
4. **Grounding Phase 1: metadata_composer + knowledge/query wrap** (draft PR against stub)
5. **HOMAGE F3/F4/F5 post-live queue** (split with delta)

Medium:
6. **AUTH-ENLIGHTENMENT Phase 2 + Moksha-enum follow-on**
7. **ytb-OMG6 Phase B + OMG8 Phase A**
8. **SS1 live-validation flip** (session-callable per autonomy mandate; was in v1 operator-queue)

## 6. Flow-maximization principles (v2)

1. **Stub-first Phase 0.** Beta ships API-surface stubs in a ~50 LOC PR #1; peers draft Phase 1 wraps against imports immediately; CI red until stub impl lands in Phase 0 FULL, then all green in one merge wave. Eliminates v1's false serialization.
2. **Kill-switch env flag.** `HAPAX_GROUNDING_ADJUDICATOR_BYPASS=1` makes adjudicator a pass-through to current routing; emergency rollback without reverting the PR chain.
3. **Keep-going tripwire.** If session's entire queue blocks on a common dependency, session files priority-boost against dep-owner; or, if dep-owner also blocked, beta executes on owner's behalf within 30 min.
4. **Claim-before-parallel.** Unchanged.
5. **270s cadence.** Unchanged.
6. **Autonomy-mandate at full strength.** SS1/LORE/AUTH-HOMAGE default flips session-callable TODAY, not operator-queue.
7. **Revert > stall.** Unchanged.

## 7. Robustness surfaces (NEW — per robustness audit)

Explicit mechanical gates:

1. **Phase 0 kill-switch env flag** `HAPAX_GROUNDING_ADJUDICATOR_BYPASS=1` — adjudicator pass-through fallback.
2. **Phase 0 schema canary test** — dedicated CI job validates scaffolding signatures on fixture PR before Phase 1 dispatch.
3. **Capability-name lint HPX002** — rejects `call_llm_*`, `*_sonnet`, `*_haiku`, non-Gibson-verb names.
4. **`GroundingProfile` default-check unit test** — asserts every `CapabilityRecord` extension supplies a non-default profile.
5. **Xfail-classification lint** — requires `reason="first_seen=<sha>, classification=(regression|chronic|never-worked)"` on every xfail.
6. **Session-idle watchdog** — if all remaining queue items share blocking dependency, alert.
7. **CI timeout headroom gauge** — 95th percentile PR duration vs 15m ceiling; alert at 80%.
8. **TabbyAPI stream-liveness probe** — 30s external ping simulating director_loop grounding-act.
9. **cc-claim flock atomicity** — replace rename-only with `flock(2)` for races <1ms.
10. **Diff-disjointness pre-admin-merge assertion** — static check xfailed tests don't import PR-modified symbols.

## 8. Instrumentation (NEW — per missed-opportunity audit)

Synthesis §6 specified 8 metrics; none in v1. v2 schedules:

1. **Grafana panel for `hapax_director_ungrounded_total` + `hapax_capability_ungrounded_total{class}`** — beta ships dashboard JSON alongside Phase 0.
2. **Prometheus alert rule** `hapax_capability_ungrounded_total{class="action"} > 0` — beta adds 3-line PrometheusRule alongside Phase 0.
3. **Weekly neurosis-index report** — beta relay-bump every Monday reports current empty-provenance rate; target trajectory 54% → 0 within 30 days of Phase 1 completion.
4. **CI AST-count assertion** — Phase 2 addition: `pytest -k test_litellm_allowlist` fails if `litellm.(a)completion` outside adjudicator.
5. **Capability count tracker** — `pytest -k test_capability_count` pinned at baseline; targets 91 → 113.
6. **`grounded_emission_rate` gauge** — exposures per second with non-empty grounding_provenance; alert on >50% drop in 60s during stream.
7. **`hapax_youtube_shorts_published_total`** — closes OG2 verification loop.
8. **`% PRs near timeout ceiling` gauge** — 80% of 900s = 12min early warning.

## 9. Not-lost ledger (census mode — per completeness audit)

Full vault census: **57 cc-tasks active + 7 claimed + 30+ offered**. This v2 enumerates every offered/claimed item in §3 across §3.1-§3.5. §3.6 adds 4 spec-triage. §3.7 files 15 research-drop follow-ups. §3.8 enumerates LRR Phase A state. §4 enumerates all 13 grounding-act surfaces.

**Residual gaps** (acknowledged, not actioned yet):
- project_reverie / project_reverie_autonomy / project_reverie_adaptive phase tracking
- project_session_conductor follow-up
- project_unified_recruitment phase tracking
- SCM Eigenform / PCT / DEUTS / Arbiter-namespace gaps
- project_rig_migration (stream-ready trigger)
- DF workstream follow-ups

**Action:** beta files these as `project_*_followup` cc-tasks during next 270s cycle; ~20 min of filing; preserves complete trail.

## 10. Session disposition summary (v2)

| Session | Immediate (0-1h) | Short (1-4h) | Medium (4-24h) | Epic |
|---|---|---|---|---|
| **beta** | #1329 + fortress fix + prewarm fix + Phase 0 STUB | Phase 0 FULL + kill-switch + dashboards | Phase 0 adjudicator wrap coordination | LRR observability keystone |
| **alpha** | DEVIATION-025 + ytb-011 Phase 2 | Content programming + Phase 1 conv-pipeline draft | OLMo deploy + SS2 cycle 2 | LRR Phase 5 |
| **delta** | #1316 merge + ef7b-212/213 review | De-monetization + scrim-taxonomy + HOMAGE F3-F5 | Phase 1 director draft + HOMAGE redesigns | FINDING-V |
| **epsilon** | #1322 lands | AUTH-PALETTE + AUTH-HOMAGE flip + Phase 1 work-class draft | HOMAGE F3-F5 + Phase 2 follow-ons | Authentic-asset closure |

**Every session has ≥4 items across every horizon.** **No single dependency blocks >1 session** (stub-first Phase 0 eliminates the v1 cascade).

— beta, 2026-04-24T21:40Z
