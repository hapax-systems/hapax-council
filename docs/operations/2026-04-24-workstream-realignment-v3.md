# Workstream realignment v3 — final, audit-incorporated — 2026-04-24T23:15Z

**Author:** beta
**Supersedes:** `docs/operations/2026-04-24-workstream-realignment-v2.md`
**Audit-incorporated:** 7-agent audit wave (completeness, WSJF, dependency, session-balance, research-integration, tactical-vs-architectural, velocity). All HIGH-severity findings addressed; MED/LOW findings listed in §11 with disposition.
**Honest accuracy notice:** The v3 draft (pre-audit, 22:50Z) silently dropped ~15 v2 items and fabricated 15 research-drop names. This final version reads v2 §3.7/§3.6 literally and inspects peer yamls + vault cc-tasks for ground truth. "Nothing dropped from v2" guarantee is earned in §9, not asserted.

## 1. What changed since v2 (21:40Z → 23:15Z)

### Shipped / in-flight
- **#1334** fortress daily deliberation → local-fast + daimonion TCP prewarm. **MERGED 22:12:57Z.**
- **#1329** CI xfail-substring regression hot-fix. **MERGED earlier**; unblocked peer xfail PRs.
- **#1336** narration-fence extensions (director track-claim clause + persona voice-mode fences + splattribution-gate in `album-identifier.py` + compositor memory-wipe). **CI-IN-FLIGHT.** Live services hot-patched + restarted; MF-DOOM hard-form eliminated, soft-form residue remaining (architectural-only).
- **Tactical MF-DOOM fixes live** at 22:20Z on primary worktree + daimonion + studio-compositor services.

### New research + architecture introduced
- **Universal Bayesian Claim-Confidence architecture** (`docs/research/2026-04-24-universal-bayesian-claim-confidence.md`, 429 lines). **9-agent parallel research wave** (normalized — the architecture-research wave was 8 slices; the livestream-perceptual-field lever was a 9th separate dispatch). Seven implementation phases + Phase 2b livestream-classifier insertion. Six-lineage no-graft derivation (Clark, Hohwy, Thompson, Dreyfus, Clark-Brennan, Sperber-Wilson, Austin).
- **7-agent audit wave** against this v3 draft: completeness, WSJF, dependency, session-balance, research-integration, tactical-vs-architectural tension, velocity. Full findings folded below.

### Peer progress (not beta)
- **Alpha**: ytb-010 closed (#1319/1320/1321); standing; AUTH-PALETTE-MOKSHA + AUTH-GEAL bundle in vault.
- **Delta**: FINDING sweep complete — W Phase 1+2 (#1316/1330), V spec+plan (#1333), X superseded-closed, mobile superseded.
- **Epsilon**: OMG cascade — pastebin family (#1337/1338 Phase B/C) merged, #1339 Phase D in flight; AUTH-ENLIGHTENMENT Phase 2 merged earlier (#1332); #1322 chronic-xfails merged.

### Retired strategies
- Prompt-text-fence patching as a stand-alone strategy. Empirically insufficient (three fence passes did not eliminate soft track-claim hallucination). Fences become one layer among six per synthesis.
- Ad-hoc per-claim Boolean gates as the permanent form.

### Retired false claims in v3 draft (DRAFT ERRATA)
- The v3 draft's 15-item "research-*" list was fabricated; replaced with v2 §3.7's real 18-item list below.
- The v3 draft's 4-item Spec triage list was fabricated; replaced with v2 §3.6's actual 4 items.
- `HAPAX_GROUNDING_ADJUDICATOR_BYPASS=1` was claimed "in force" in v3 draft §7; audit confirmed it is **unimplemented**. Removed from §7 pending actual ship (Phase 0 FULL deliverable).
- 3499-004 gmail-sync inotify flood (self-labeled CRITICAL) was dropped; restored in §3 below.

## 2. Ruling principles

1. **Architecture over bandages.** Every new perceptual-claim bug gets a `Claim` / `ClaimEngine` / `LRDerivation` record; post-hoc prompt negations are only acceptable as kill-switch fallbacks pending phase landing.
2. **Stub-first discipline.** Phase 0 ships a ~80 LOC API-surface stub (revised from 50 per dependency audit) before any peer opens Phase 1 wrap drafts. Peers draft against stub imports in parallel.
3. **No-graft commitment.** Every new abstraction must derive from existing lineages. Synthesis doc §2 is the canonical derivation; PRs citing new abstractions must reference it (gate 19).
4. **Session-callable decisions at full strength.** Aesthetic sign-off, default-flag flips, scrim-taxonomy placements, ownership arbitration (e.g. Phase 2 alpha-vs-delta) all session-callable without operator gating.
5. **270s wake cadence locked.**
6. **Revert beats stall.** No "await operator" patterns.
7. **Claim-before-parallel** for cross-lane work.
8. **Livestream IS the research instrument** — Phase 2b classifiers therefore carry ecological validity.
9. **Verify-before-claiming-done.** Kill-switches, robustness gates, and "in-force" claims must point to actual shipped artifacts. Aspirational gates are marked Phase-gated.
10. **Priors-from-invariants are CI-enforced.** Not a convention — a check (HPX003) that rejects priors that cannot be reconstructed from `prior_provenance.yaml`.

## 3. Complete census — v2 carryover + new, WSJF rescored per audit

### 3.1 Shipped / retired (clean off the active queue)
| Item | PR | Note |
|---|---|---|
| Fortress grounded-routing | #1334 | Config swap + test rewrite |
| Prewarm deLLM TCP | #1334 | `asyncio.open_connection` |
| CI xfail-substring regression | #1329 | `$PIPESTATUS[0]` |
| autonomous_narrative → local-fast | #1318 | |
| spontaneous_speech → local-fast | #1318 | |
| Director track-claim fence | #1336 | IN-FLIGHT |
| Voice-persona grounding fences | #1336 | IN-FLIGHT |
| Splattribution gate | #1336 | Live hot-patched |
| FINDING-W Phase 1+2 | #1316/1330 | delta |
| FINDING-V spec+plan | #1333 | delta |
| ytb-AUTH-ENLIGHTENMENT Phase 2 | #1332 | epsilon |
| ytb-AUTH-PALETTE Phase 2 Moksha-placeholder | #1331 | epsilon |
| Chronic xfails | #1322 | epsilon |
| OMG6 Phase B/C pastebin | #1337/1338 | epsilon |

### 3.2 Universal Bayesian Claim-Confidence phases (WSJF rescored per audit)
| Phase | v3-draft WSJF | **v3-final WSJF** | Owner | Blocks | Target LOC |
|---|---|---|---|---|---|
| **0** — Claim scaffolding (`shared/claim.py` ~80 LOC stub + `LRDerivation` + `prior_provenance.yaml` + CI rules HPX003/HPX004 + **YAMNet `Signal[T]` adapter signature** + inference-broker stub) | 17 | **15** | beta | everything | ~80 stub + ~500 FULL |
| **1** — Refactor PresenceEngine → `ClaimEngine[bool]` + **per-claim `TemporalProfile` required ctor param** + bit-identical regression pin | 14 | 14 | beta | 2, 2b, 6 | ~200 |
| **2** — Vinyl/music cluster (`VinylSpinningEngine` + `MusicPlayingEngine` + `pgmpy` dependency commit) — MF-DOOM structural retire | 15 | **12** | delta (claimed inline) | 3 | ~400 |
| **2b** — Livestream classifiers (YAMNet broadcast-tap + SigLIP2 + PaddleOCR + **decoration-strip duality** + consistency primitives + calibration-concurrent priors) | 12 | **10** | delta | 6, 7 | ~600 + ~1GB weights |
| **3** — Frame-for-llm split (camera-only buffer pre-composite) | 13 | **14** | delta | (independent from 4) | ~150 |
| **4** — Prompt envelope + **per-surface floor table** (director 0.60 / spontaneous 0.70 / autonomous 0.75 / persona 0.80 / grounding-act 0.90) + uncertainty contract | 11 | 11 | alpha (drafts against Phase 0 STUB, not gated on Phase 3) | 5 | ~300 |
| **5** — R-Tuning refusal gate + Langfuse `claim_discipline` score | 9 | 9 | **epsilon** (observability lane) | — | ~200 |
| **6a** — Activity claims migration (operator_working, operator_DJing, desk) | — | 8 | delta | 7 | ~400 |
| **6b** — Mood claims migration (stimmung dimensions → `ClaimEngine[float]`) | — | 8 | alpha | 7 | ~400 |
| **6c** — Identity claims migration (speaker_is_operator, chat author) | — | 7 | epsilon | 7 | ~300 |
| **6d** — Meta/system claims (degraded, consent, budget) | — | 6 | beta | 7 | ~400 |
| **7** — T1-T8 posterior interrogations (τ_mineness threshold + per-element provenance strength); close FINDING-X 54% empty-provenance | 16 | **11** | alpha + beta | — | ~400 |

### 3.3 v2 carryovers — rescored + owner-assigned per audit

| v2 # | Epic | v2 WSJF | **v3-final WSJF** | Owner | Status |
|---|---|---|---|---|---|
| 3 | **ef7b-212 PR-review cross-zone #197-#198 consumer-side** (actual title; previous "HOMAGE micro-animation" was wrong) | 17 | **11** | delta | STANDING |
| 5 | **ef7b-213 livestream regression watch (standing readiness)** (actual title) | 13 | 11 | delta | STANDING |
| 4 | **DEVIATION-025 P0 Langfuse score calls** (data-loss-critical — every Phase A session without this = permanent data loss for Claim 5) | 13 | 13 | alpha | BLOCKED→CLAIMABLE |
| 13 | Scrim-taxonomy architecture (ef7b-174) | 7 | 7 | delta + epsilon | v1 missed |
| 14 | **Content programming layer (ef7b-164)** — operator load-bearing directive | 7 | 12 | alpha | v1 missed |
| 15 | **De-monetization safety zero-red-flag invariant (ef7b-165)** — operator existential-risk directive | 7 | **14** (WSJF audit rescored from the v3-draft's inflated 18) | **delta** (reassigned from alpha per session-balance audit; alpha already saturated) | v1 missed |
| 16 | 1d79-099 OLMo parallel TabbyAPI :5001 deploy | 8 | 8 | alpha | CLAIMED |
| 17 | 1d79-085 beta-substrate-execution-chain 209-212 | 7 | 7 | beta | CLAIMED |
| 18 | 1d79-100 daimonion code-narration prep | 6 | 6 | alpha | CLAIMED |
| **19** | **3499-004 gmail-sync inotify flood starving logos-API** — v3-draft silently dropped; **RESTORED** | 7 | **9** (rescored up — operational-critical) | beta-as-coordinator | v1 missed, v3-draft dropped |
| 20 | 60f6-021..027 gaps implementation chain (7 tasks) | 6 | 7 | split across sessions | v1 missed |
| 21 | FINDING-V publishers research-spec-plan | 8 | — | — | CLOSED via #1333 |
| 22 | FINDING-X subsumed by Phase 7 | — | — | — | closed-subsumed |
| 23 | Mobile-livestream substream research-spec-plan | 6 | 5 | delta | still open |
| 24 | ytb-OG3 quota extension | 8 | 8 | operator | queue |
| 9 | **HOMAGE post-live F3/F4/F5 queue** — split into 3 rows at WSJF 4 each, not aggregate 11 | 10 (agg) | **4/4/4** (F3, F4, F5) | delta + epsilon split | v1 missed |
| 26 | AUTH-ENLIGHTENMENT Phase 2 + Moksha-specific enum follow-on | 4.5 | 4.5 | epsilon | deferred-on-Moksha-assets |
| 27 | AUTH-PALETTE Phase 2 Moksha .edc loader | 4.5 | 4.5 | epsilon | asset-gated |
| 29 | ytb-OMG2 Phase 2 Jinja2 dynamic rebuilder + timer | 4 | 4 | alpha | |
| 30 | ytb-OMG8 Phase A compose-side | 3 | 3 | epsilon | |
| 31 | ytb-003 thumbnail auto-generation | 4 | 4 | delta | |
| 32 | ytb-009 in-band live captions | 3.2 | 3.2 | delta | |
| 33 | ytb-011 Phase 2 sections manager | 3.5 | 3.5 | alpha | v3-draft missed |
| 34 | ytb-LEGIBILITY-SMOKE / TOKEN-POLE-PALETTE / OBJECTIVES-OVERLAY follow-ups (real fixes) | 3-4 | 3-4 | split | |
| 35 | **Reverie 5-channel mixer wiring (RD/Physarum/Voronoi)** — v3-draft missed | 4 | 4 | delta | v1+v3-draft missed |
| 36 | **HOMAGE #162/#163 insightface-arcface + enrollment-without-pause** — twice-missed | 5 | 5 | delta | v1+v3-draft missed |
| 37 | **HOMAGE #186 token-meter geometry rework** — twice-missed | 4 | 4 | delta | v1+v3-draft missed |
| 38 | **HOMAGE #189 HARDM role-placement redesign** — twice-missed | 4 | 4 | delta | v1+v3-draft missed |
| 39 | **HOMAGE #176/#177 Logos-fullscreen vs OBS v4l2 parity** — twice-missed | 4 | 4 | delta | v1+v3-draft missed |
| 40 | **4 main-red follow-ups** (WARD-CONTRAST / EMISSIVE-RETIRED-FLASH / EMISSIVE-GOLDEN-PANGO / GEAL-PERF-BUDGET) | 3 each | 3 each | delta | |
| 41 | ytb-OMG9 infrastructure (DNS/PGP) | 2.2 | 2.2 | beta | |
| 42 | ytb-LORE-EXT future wards | 2.1 | 2.1 | delta | |
| 43 | ytb-012 shorts extraction pipeline | 2.1 | 2.1 | delta | |
| 44 | **lssh-006/007/009/010/011** (5 livestream-surface-health retirements) | 1-3 | 1-3 | delta | |
| 45 | #1292 QM1 OTel span pairing follow-on | 2 | 2 | beta | |
| 48 | ef7b-188 Pi-6 sshd-unreachable restore | 2.5 | 2.5 | operator-primary | |
| — | **ef7b-099/106/112 HOMAGE chain** (research-spec-plan-execute + ship-all-phases + Phase 6 ward-shader bidirectional coupling) | — | 5 each | delta | v3-draft missed |
| — | **ef7b-031 LRR Phase 4 Phase A completion OSF pre-reg** | — | 5 | alpha | v2 §3.8, v3-draft missed |
| — | ef7b-040 Phase 7 legacy prompt cleanup (2026-04-30 gate) | — | 3 | alpha | |
| — | ef7b-056 PyMC MCMC BEST (data-sufficiency gate) | — | 3 | alpha | |
| — | **AUTH-HOMAGE default-flip (bitchx-authentic-v1)** — session-callable | — | 4 | alpha (session-callable) | |
| — | **SS1 live-validation flip** — session-callable | — | 4 | alpha (session-callable) | |
| — | ytb-OG1 oauth-token-mint | — | 4 | operator | |
| — | ytb-007 vod-boundary-orchestrator (PR #1276 shipped; cc-task still active) | — | 3 | alpha (close cc-task) | |
| — | **AUTH-PALETTE-MOKSHA + AUTH-GEAL alpha-lane bundle** (4 cc-tasks claimed in alpha vault) | — | 4 each | alpha | v3-draft missed |

### 3.4 Spec triage — replacing v3-draft fabricated list with v2 §3.6 actual items

| Spec | Priority | Owner |
|---|---|---|
| **spec-2026-04-18-audio-pathways-audit** | HIGH | delta + beta |
| **spec-2026-04-18-youtube-broadcast-bundle** (OAuth + reverse-ducking) | HIGH | alpha |
| **spec-2026-04-18-local-music-repository** | MEDIUM | delta |
| **spec-2026-04-18-soundcloud-integration** | LOW | delta |

### 3.5 Unscheduled research drops — replacing v3-draft fabricated list with v2 §3.7 actual 18 items

From `docs/research/` 2026-04-20..24:
1. 6 homage-scrim drops
2. camera-visual-abstraction-investigation
3. dead-bridge-modules-audit
4. livestream-halt-investigation
5. notification-loopback-leak-fix
6. prompt-level-slur-prohibition-design
7. self-censorship-aesthetic-design
8. rag-ingest-livestream-coexistence
9. evilpet-s4-dynamic-dual-processor-research
10. ward-stimmung-modulator-design
11. livestream-crispness-research
12. livestream-surface-inventory-audit
13. missing-publishers-research (CLOSED via FINDING-V + #1333)
14. vad-ducking-pipeline-dead-finding
15. gem-rendering-redesign-brainstorm
16. video-container-parallax-homage-conversion
17. livestream-audio-unified-architecture (major architectural direction)
18. ytb-ss2-substantive-speech-research-design

**Action:** beta files cc-tasks for items 1-12 + 14-18 (17 items remaining after #13 closed); minimal WSJF (0-3) until operator prioritizes; preserves trail.

### 3.6 Subsumption disclosures (corrected per research-integration audit)

- **Grounding-capability Phase 0 STUB (v2 #1, WSJF 14)** → **EXTENDED (not SUBSUMED).** Phase 0 of Bayesian arch carries adjudicator-stub semantics + LRDerivation; the `GroundingAdjudicator` (synthesis §1.2) remains a separate module that consumes `ClaimEngine` posteriors.
- **Grounding-capability Phase 0 FULL (v2 #10, WSJF 10)** → **EXTENDED** (same semantics).
- **Grounding-capability Phase 1 migrations, 23 sites (v2 #11)** → **subset-by-cluster**: activity-cluster → Phase 6a; mood-cluster → Phase 6b; identity → 6c; meta → 6d. No work lost; migration boundary shifts from per-site to per-claim-cluster.

## 4. Rescored top-15 (post-audit)

| Rank | Item | WSJF | Owner |
|---|---|---|---|
| 1 | Bayesian Phase 0 scaffolding | 15 | beta |
| 2 | ef7b-165 de-monetization safety | 14 | delta |
| 3 | Bayesian Phase 1 PresenceEngine refactor | 14 | beta |
| 4 | Bayesian Phase 3 frame-for-llm split | 14 | delta |
| 5 | DEVIATION-025 P0 Langfuse | 13 | alpha |
| 6 | Bayesian Phase 2 vinyl/music cluster | 12 | delta |
| 7 | ef7b-164 content programming | 12 | alpha |
| 8 | ef7b-212 PR-review cross-zone | 11 | delta |
| 9 | ef7b-213 livestream regression watch | 11 | delta |
| 10 | Bayesian Phase 4 prompt envelope | 11 | alpha |
| 11 | Bayesian Phase 7 T1-T8 posterior | 11 | alpha + beta |
| 12 | Bayesian Phase 2b livestream classifiers | 10 | delta |
| 13 | 3499-004 gmail-sync inotify flood | 9 | beta-coordinator |
| 14 | Bayesian Phase 5 refusal gate | 9 | epsilon |
| 15 | Bayesian Phase 6a activity migration | 8 | delta |

## 5. Per-session queues (balance-audit-corrected)

### beta queue
1. **Self-admin-merge #1336** on CI green
2. **Phase 0 STUB PR** — ~80 LOC frozen API surface: `Claim`, `ClaimEngine[T]`, `LRDerivation`, `prior_provenance.yaml`, `TemporalProfile`, YAMNet `Signal[T]` adapter signature, inference-broker stub for 5060 Ti
3. **Tag `tactical-fence-baseline-2026-04-24` at #1336 merge SHA** — rollback target if Phase 2 regresses
4. **Phase 0 FULL PR** — Pydantic validator + CI rules HPX003 (Claim needs LRDerivation) + HPX004 (Claim needs prior_provenance) + `HAPAX_BAYESIAN_BYPASS=1` implementation (replaces two-flag draft) + migration codemod
5. **Phase 1 PR** — `ClaimEngine[bool]` refactor of PresenceEngine + bit-identical regression pin + per-claim `TemporalProfile` required ctor param
6. **3499-004 gmail-sync** coordination (operational-critical)
7. **6d meta-claims migration**
8. **Phase 7 research-spec-plan** co-authored with alpha (τ_mineness + per-element provenance)
9. **Workstream-doc maintenance** — keep v3 updated
10. Standing: 1d79-085 beta-substrate-execution-chain; ytb-OMG9 infra; #1292 QM1 follow-on

### alpha queue
1. **DEVIATION-025 P0** (WSJF 13, data-loss-critical)
2. **ef7b-164 content programming** (WSJF 12)
3. **Bayesian Phase 4 draft** (starts after Phase 0 STUB, NOT gated on Phase 3 — spurious-edge audit)
4. **AUTH-HOMAGE default-flip + SS1 live-validation flip** (session-callable, 10 min)
5. **Bayesian Phase 6b mood-claims migration**
6. **Phase 7 share (voice-surface T1-T8)** — co-author with beta
7. **AUTH-PALETTE-MOKSHA + AUTH-GEAL bundle** (alpha-lane, from vault)
8. **ef7b-031 / ef7b-040 / ef7b-056** LRR Phase A trio
9. **1d79-099 OLMo deploy; 1d79-100 code-narration prep**
10. Standing: ytb-011 Phase 2 sections; ytb-OMG2 Phase 2; ytb-OG2/OG3

### delta queue
1. **ef7b-165 de-monetization safety** (WSJF 14, claim before parallel) — REASSIGNED from alpha per audit
2. **Bayesian Phase 3 PR** (WSJF 14, small + dominant MF-DOOM fix)
3. **Bayesian Phase 2 PR** (WSJF 12) — coordinate with alpha if alpha picks this up, otherwise delta-owned
4. **Bayesian Phase 2b PR** (WSJF 10) + **decoration-strip duality split** (broadcast-frame + LLM-frame classifiers registered separately in `LRDerivation`, gate 20)
5. **ef7b-212 PR-review cross-zone #197-#198** (WSJF 11)
6. **ef7b-213 livestream regression watch** (WSJF 11)
7. **Scrim-taxonomy (ef7b-174)** with epsilon
8. **Bayesian Phase 6a activity-claims migration**
9. **HOMAGE twice-missed chain**: #162/#163/#176/#177/#186/#189 + ef7b-099/106/112
10. **Reverie 5-channel mixer wiring**
11. Standing: 1d79-chain; ytb-003 thumbnail; ytb-009 captions; mobile-substream; lssh-* retirements; 4 main-red follow-ups; ytb-LORE-EXT

### epsilon queue
1. **Close OMG6 Phase D** (#1339)
2. **OMG6 remaining phases + OMG8 Phase A**
3. **AUTH-PALETTE Phase 2 Moksha .edc loader** (asset-gated, authored-placeholder pattern per autonomy mandate)
4. **AUTH-ENLIGHTENMENT Phase 2 + Moksha enum follow-on**
5. **Bayesian Phase 5 refusal gate + `claim_discipline` Langfuse score** (lane-canonical, no longer "or beta")
6. **Bayesian Phase 6c identity-claims migration**
7. **HOMAGE F3/F4/F5 share** (1 of 3)
8. **Scrim-taxonomy (ef7b-174)** with delta
9. **60f6-021..027 gaps chain**

## 6. Ship order this window (dependency + velocity corrected)

Critical path (Beta-lane, serial): #1336 → tactical-baseline tag → Phase 0 STUB → Phase 0 FULL → Phase 1 = **~15–20 ticks (~70–90 min with CI re-runs)**.

Parallel tracks open after step 3 (Phase 0 STUB lands):

**Track A — Phase 0 FULL + Phase 1** (beta; serial within lane)
1. #1336 self-admin-merge on CI green (beta)
2. Tag `tactical-fence-baseline-2026-04-24`
3. Phase 0 STUB PR (~80 LOC) (beta)
4. Phase 0 FULL PR (beta; after STUB, ~500 LOC)
5. Phase 1 PR (beta; after FULL, ~200 LOC + regression pin)

**Track B — Peer Phase drafts** (parallel, all start after step 3)
3a. Alpha: Phase 4 prompt-envelope draft (against Phase 0 STUB imports — NOT Phase 3 gated; spurious edge removed per dependency audit)
3b. Delta: Phase 2 VinylSpinning/MusicPlaying draft + Phase 3 frame-for-llm split (both against Phase 0 STUB)
3c. Epsilon: Phase 5 refusal-gate draft (against Phase 4 signature)

**Track C — Non-Bayesian parallel** (no phase gate)
3d. Delta: **ef7b-165 de-monetization safety** (WSJF 14, rank 2 — hoisted from draft's step 11)
3e. Alpha: DEVIATION-025 P0 (WSJF 13, rank 5)
3f. Alpha: ef7b-164 content programming (WSJF 12, rank 7)
3g. Epsilon: #1339 OMG6 Phase D merge
3h. Delta: ef7b-212 + ef7b-213 standing

**After Track A step 5 (Phase 1 lands)**:

6. Phase 2 PR merges (delta) — MF-DOOM structural retire
7. Phase 3 PR merges (delta) — OCR-dominance attack surface closed
8. Phase 4 PR merges (alpha) — prompt envelope
9. Phase 2b PR merges (delta) — livestream classifiers; **provisional priors at ship, calibration-concurrent per §2 principle 8; recalibration at week 1**
10. Phase 5 PR merges (epsilon) — refusal gate
11. Phase 6a/6b/6c/6d wave PRs (parallel across sessions)
12. Phase 7 PR merges (alpha + beta)

**Day-2+ items** (explicit): Phase 6 waves, Phase 7, remainder of research-drops census filing. Not this-window-completable even at peak velocity (audit finding).

## 7. Robustness gates

### In force today (v2 inherited, still real artifacts)
1. `HPX001` ruff rule — litellm.completion outside allowlist
2. `HPX002` ruff rule — **capability-name lint** (preserved from v2 — not replaced)
3. Phase 0 canary test (STUB)
4. xfail-classification lint
5. Session-idle watchdog
6. TabbyAPI liveness probe
7. Grounding-provenance schema validator
8. Sincerity-without-provenance test
9. Keep-going tripwire for admin-merge
10. **Tactical-fence-baseline git tag** (new — `tactical-fence-baseline-2026-04-24` at #1336 merge SHA; `git revert` target for Phase 2/3 regressions)

### Phase-gated (land with the phase that enables them)
11. **`HPX003` ruff rule** — `Claim` constructor without matching `LRDerivation` entry. Active at Phase 0 FULL.
12. **`HPX004` ruff rule** — `Claim` without reconstructible `prior_provenance.yaml` record. Active at Phase 0 FULL. Implements operator directive "priors are not generated ad-hoc."
13. **`HAPAX_BAYESIAN_BYPASS=1`** — single kill-switch flag (replaces v3-draft's unimplemented two-flag scheme). Implemented at Phase 0 FULL; restores pre-Phase-0 routing.
14. Claim-posterior sanity check (posterior in [0,1]). Active at Phase 1.
15. LR-registry drift alarm (monthly). Active at Phase 0 FULL.
16. Temporal-state integrity check. Active at Phase 1.
17. Frame-for-LLM integrity check (no ward pixels in LLM-bound frame). Active at Phase 3.
18. Prompt-envelope lint. Active at Phase 4.
19. Refusal-gate Langfuse score baseline. Active at Phase 5.
20. YAMNet audio-tap liveness (fall back to 0.5 maximum-entropy prior if disconnected). Active at Phase 2b.
21. Self-evidencing consistency canary (OCR-detects while posterior-low → auto-ward-clear). Active at Phase 2b.
22. **Classifier-frame-source declared per signal** (broadcast-with-wards vs LLM-frame-post-strip) — decoration-strip duality enforcement. Active at Phase 2b.
23. No-graft lint (new abstraction must cite synthesis doc §2 in PR body). Active at Phase 0 STUB.

## 8. Instrumentation

### In force today (v2 inherited)
1-8. Per v2 §6 (preserved verbatim).

### Phase-gated additions
9. Claim-posterior dashboard (per-engine posterior time series + hysteresis state + evidence-source contributions). Active at Phase 1.
10. LR-registry drift dashboard (per-signal LR trend + calibration-study age). Active at Phase 0 FULL.
11. Refusal-rate dashboard (per-narration-surface gate-rejection rate). Active at Phase 5.
12. Empty-provenance rate tracker (FINDING-X baseline 54% → target <5%; weekly). Active at Phase 7.
13. Frame-for-llm integrity alert. Active at Phase 3.
14. Self-evidencing consistency dashboard (ward-staleness-detected events). Active at Phase 2b.

## 9. Completion disclosure (honest audit table)

| From v2 | Status in v3-final |
|---|---|
| 3499-004 gmail-sync | **RESTORED** (v3-draft dropped) |
| 17 unscheduled research drops | **RESTORED** — v2 §3.7 literal list imported (§3.5 above); v3-draft's 15 fabricated names retired |
| 4 spec-triage | **RESTORED** — v2 §3.6 literal list imported (§3.4); v3-draft's 4 fabricated names retired |
| HOMAGE #162/#163/#176/#177/#186/#189 twice-missed | **RESTORED** in delta queue §5 |
| ef7b-099/106/112 HOMAGE chain | **RESTORED** in delta queue §5 |
| AUTH-PALETTE Phase 2 (epsilon) | **RESTORED** in epsilon queue §5 |
| AUTH-ENLIGHTENMENT Phase 2 (epsilon) | **RESTORED** in epsilon queue §5 |
| Alpha AUTH-PALETTE-MOKSHA + AUTH-GEAL bundle | **RESTORED** in alpha queue §5 |
| lssh-* retirement bundle | **RESTORED** in §3.3 row 44 |
| 4 main-red follow-ups | **RESTORED** in §3.3 row 40 |
| ytb-LORE-EXT / ytb-OMG9 / ytb-OG1 / ytb-007 | **RESTORED** in §3.3 |
| #1292 QM1 follow-on | **RESTORED** in §3.3 row 45 |
| ef7b-031 / 040 / 056 LRR Phase A trio | **RESTORED** in alpha queue §5 |
| ef7b-188 Pi-6 sshd-unreachable | **RESTORED** in §3.3 row 48 |
| DEVIATION-025 "data-loss-critical" framing | **RESTORED** in §3.3 row 4 |
| Reverie 5-channel mixer wiring | **RESTORED** in §3.3 row 35 |
| AUTH-HOMAGE default-flip | **RESTORED** as session-callable in alpha queue §5 |
| SS1 live-validation flip | **RESTORED** as session-callable in alpha queue §5 |
| HPX002 namespace collision | **RESOLVED**: v2's HPX002 (capability-name lint) preserved; new Claim rule uses HPX003 + HPX004 |
| `HAPAX_GROUNDING_ADJUDICATOR_BYPASS` unimplemented | **ADMITTED** + replaced with single `HAPAX_BAYESIAN_BYPASS` (Phase-gated, not in-force) |
| "Nothing from v2 dropped" false claim | **RETRACTED** + replaced with this audit table |

## 10. MF-DOOM four-layer defense-in-depth

1. **Tactical** (shipped + IN-FLIGHT): splattribution gate + memory-wipe + director track-claim fence + persona voice-mode fence. Rollback target: `tactical-fence-baseline-2026-04-24`.
2. **Phase 2** (delta): `VinylSpinningEngine` posterior replaces `_vinyl_is_playing` Boolean; `MusicPlayingEngine` compound noisy-OR replaces ungated `_curated_music_framing()`.
3. **Phase 2b** (delta): YAMNet on broadcast L-12 tap — one second of silence drops `MusicPlayingEngine.posterior` to 0.04 within three windows, **pure function of broadcast bus**, zero coupling to turntable/YouTube/album-state.
4. **Phase 3** (delta): frame-for-llm split — strips decorative wards from VLM input entirely, closing OCR-mediated modality dominance attack surface (medRxiv 2026-02-22; OWASP LLM01:2025).

Operator response to new hallucination ("if operator reports a new hallucination tomorrow"):
- **(a) Ship a fence** against the hot-path (tactical) AND
- **(b) Claim-register the new perceptual signal** in Phase 2/6 (structural). Never defer to Phase 6 alone; never fence-only without claim-registration. Both in the same window.

## 11. Audit findings disposition

### HIGH severity addressed
1. **3499-004 dropped** → restored §3.3 row 19
2. **Research drops fabricated** → replaced with v2 §3.7 literal in §3.5
3. **Spec triage swapped** → replaced with v2 §3.6 literal in §3.4
4. **HPX002 namespace collision** → preserved v2 HPX002; new rules HPX003/HPX004
5. **`HAPAX_GROUNDING_ADJUDICATOR_BYPASS` unimplemented** → replaced with Phase-gated `HAPAX_BAYESIAN_BYPASS`
6. **Missing tactical-snapshot revert** → tagged `tactical-fence-baseline-2026-04-24` at #1336 merge
7. **Prior-from-invariants unenforced** → HPX004 ruff rule
8. **ef7b-165 position 11 contradicts rank 2** → hoisted to Track C step 3d
9. **Phase 2b over Phase 3 inverted** → Phase 3 WSJF 14 > Phase 2b WSJF 10; ship Phase 3 first
10. **Alpha overloaded** → ef7b-165 reassigned to delta

### MED severity addressed
- **Phase 2 owner unclaimed** → delta (compositor-adjacent + capacity, §10 Q1 resolved in-doc)
- **Phase 5 lane-discipline** → epsilon outright (observability lane)
- **Per-claim `TemporalProfile` missing** → required `ClaimEngine` ctor param (Phase 1)
- **`pgmpy` uncommitted** → dependency commit in Phase 2 LOC budget
- **Phase 7 τ_mineness** → named in Phase 2b description
- **Decoration-strip duality collapsed** → explicit dual classifier sets in Phase 2b + gate 22
- **Per-surface floor table import** → present in Phase 4 description
- **Phase 6 single-PR framing misleading** → split 6a/6b/6c/6d per dependency audit
- **Phase 3 → Phase 4 edge spurious** → removed; Phase 4 gates on Phase 0 STUB not Phase 3
- **ef7b-212/213 cc-task title divergence** → corrected to actual vault titles
- **finding-v/x ownership inversion** → corrected (finding-v closed by delta; finding-x subsumed by Phase 7)
- **Alpha AUTH-PALETTE-MOKSHA + AUTH-GEAL** → restored in alpha queue
- **Epsilon AUTH-* + HOMAGE twice-missed** → restored

### LOW severity addressed
- **8-agent vs 9-agent** → normalized (8 architecture + 1 livestream-lever dispatched separately)
- **50-LOC Phase 0 stub understated** → revised to ~80 LOC
- **5060 Ti inference broker** → Phase 0 stub prerequisite (gate 22 co-residency; Phase 0 ships broker stub)
- **YAMNet calibration timeline** → explicit: concurrent-with-ship + recalibration-at-week-1 (§6 step 9)
- **Model weight downloads** → accounted (1 GB SigLIP2 in 10-20s; ~2 ticks for download + integrity verify)

## 12. Remaining open questions (audit-surviving)

1. **Calibration-data volume for LRs**: how much data is needed to move from provisional (MaxEnt) to calibrated-by-data? Velocity audit flagged this; research §5 proposed ~1 week; operator validation on this number is the remaining unknown.
2. **Phase 6 parallelism ceiling**: all 4 sessions attempting Phase 6 migration simultaneously may collide on `shared/claim.py` edits even after Phase 0 lands. Need per-cluster-owner lock?
3. **HAPAX_BAYESIAN_BYPASS scope**: does it bypass ALL Bayesian claims at once, or per-Claim? Too-coarse restores ad-hoc Booleans; too-fine is a matrix of flags. Decision pending.
4. **Livestream-classifier failure-mode library**: what does MusicPlayingEngine output under YAMNet-down + SigLIP-down + PaddleOCR-down triple failure? Gate 20 says "fall back to 0.5 MaxEnt" but this re-opens narration to uncalibrated speculation.
5. **Audit-wave recursion terminates where?**: the 7-agent audit revealed ~30 findings. A meta-audit of this v3-final would likely find more. Operator decides: ship now with honest-disclosure (§11) + next-review-at-implementation-landing, or commission meta-audit?

## 13. Broadcast plan

On completion of this document:
1. File per-session dispatches at `~/.cache/hapax/relay/beta-to-{alpha,delta,epsilon}-2026-04-24T231500Z-realigned-queue-v3-final.md`.
2. Broadcast inflection at `~/.cache/hapax/relay/inflections/20260424T231500Z-beta-all-workstream-realignment-v3-final.md` referencing this doc + the synthesis research doc + the 7-agent audit trail.
3. Update `beta.yaml` with v3-final supersession.
4. Schedule 270s wake; monitor peer adoption.

— beta, 2026-04-24T23:15Z
