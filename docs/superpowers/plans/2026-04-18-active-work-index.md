# Active Work Index

**Purpose:** Living index of every in-flight workstream. Kept fresh — updated whenever status changes. This is the canonical "what is Hapax actually doing right now" document.

**Policy (operator, 2026-04-18):**
- Keep detailed plan documents on everything going forward.
- Keep them fresh and updated so as not to lose track of anything.
- Every new workstream starts with a plan doc in this index.

**Update cadence:** Every tick of the `/loop` dynamic mode. At minimum: when an item advances state (researched → spec → plan → in-PR → merged → active).

**Last updated:** 2026-04-21 (delta refresh — §1/§2 status markers synced with live task state; §8 added for 2026-04-19/-20/-21 workstreams; §7 change-log carries three new entries).

---

## Workstream Status Legend

- 🟢 **ACTIVE** — currently being implemented / PR open
- 🟡 **QUEUED** — spec + plan exist, awaiting execution slot
- 🔵 **SPEC** — spec exists, plan does not yet
- 🟣 **RESEARCH** — research done, provisionally approved, spec pending
- ⚫ **BLOCKED** — waiting on external dependency
- ✅ **DONE** — merged to main, service restarted, deployed
- 🔁 **ITERATION** — research done but needs operator iteration before spec

---

## 1. HOMAGE Epic

**Lead doc:** `docs/superpowers/specs/2026-04-18-homage-framework-design.md`
**Plan:** `docs/superpowers/plans/2026-04-18-homage-framework-plan.md`

| Phase | Status | Landed | PR |
|---|---|---|---|
| 1 — Spec + plan docs | ✅ | 2026-04-18 | #1049 |
| 2 — HomagePackage + BitchX data | ✅ | 2026-04-18 | #1050 |
| 3 — FSM + choreographer + 5 metrics | ✅ | 2026-04-18 | #1051 |
| 4 — 4 legibility surfaces → BitchX | ✅ | 2026-04-18 | #1052 |
| 5 — IntentFamily + catalog + dispatchers | ✅ | 2026-04-18 | #1053 |
| 11a — 6 hothouse wards (batch 1) | ✅ | 2026-04-18 | #1054 |
| 11b — 6 content wards (batch 2) | ✅ | 2026-04-18 | #1055 |
| 7 — Voice register enum + CPAL wiring | ✅ | 2026-04-18/19 | — |
| 8 — StructuralIntent.homage_rotation_mode | ✅ | 2026-04-19 | — |
| 9 — Research condition + PerceptualField.homage | ✅ | 2026-04-19 | — |
| 10 — Rehearsal + audit runbook (no PR) | ✅ | 2026-04-19 | — |
| 11c — 6 overlay-zone + reverie (batch 3) | ✅ | 2026-04-19 | — |
| 12 — Consent-safe variant + retirement + flag flip | ✅ | 2026-04-19/20 | — |
| 6 — Ward↔shader bidirectional coupling | 🟢 | partial | — |

**Next up:** Phase 6 ward↔shader bidirectional coupling remaining; umbrella hardening = audit bundle B7 (delta-owned — see §8).

---

## 2. HOMAGE Follow-On (Research Dossier Cascade)

**Lead doc:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` (this dossier)

**Policy:** Each research item gets its own spec stub, then its own plan doc, then its own PR(s). **Synergy pass deferred to last.**

### Rendering / Compositor Wards

| Task | Status | Spec stub | Plan | PR |
|---|---|---|---|---|
| #121 HARDM | ✅ | [design](../specs/2026-04-18-hardm-dot-matrix-design.md) | — | merged |
| #122 DEGRADED-STREAM | 🟢 PARTIAL | [design](../specs/2026-04-18-degraded-stream-design.md) | [plan](2026-04-18-degraded-stream-plan.md) | `e9f633ae1` controller; ward + auto-trigger missing — delta MVP queued §8 |
| #123 Chat ambient ward | ✅ | [design](../specs/2026-04-18-chat-ambient-ward-design.md) | — | merged |
| #127 SPLATTRIBUTION | ✅ | [design](../specs/2026-04-18-splattribution-design.md) | — | merged |
| #128 Preset variety | ✅ | [design](../specs/2026-04-18-preset-variety-expansion-design.md) | [plan](2026-04-20-preset-variety-plan.md) | merged |
| #132 Operator sidechat | ✅ | [design](../specs/2026-04-18-operator-sidechat-design.md) | — | merged |
| #135 Camera naming | ✅ | [design](../specs/2026-04-18-camera-naming-classification-design.md) | — | merged |
| #136 Follow-mode | ✅ | [design](../specs/2026-04-18-follow-mode-design.md) | — | merged |
| #124 Reverie preservation | ✅ | [design](../specs/2026-04-18-reverie-substrate-preservation-design.md) | — | merged |
| #125 Token pole HOMAGE | ✅ | [design](../specs/2026-04-18-token-pole-homage-migration-design.md) | — | merged |
| #126 Pango text repository | ✅ | — | — | merged |
| #159 Vinyl image ward | ✅ | [design](../specs/2026-04-18-vinyl-image-homage-ward-design.md) | — | merged |
| #191 GEM ward | 🟡 QUEUED | — | [plan](2026-04-21-gem-ward-activation-plan.md) | — (operator ratified 2026-04-21 as 15th HOMAGE ward; delta §8 item 3) |
| #180 chat-keywords ward | 🟡 QUEUED | design at `docs/research/2026-04-20-chat-keywords-ward-design.md` | — | — (16th ward candidate) |

### Perception → Representation

| Task | Status | Spec stub | Plan | PR |
|---|---|---|---|---|
| #129 Facial obscuring (HARD) | ✅ | [design](../specs/2026-04-18-facial-obscuring-hard-req-design.md) | [plan](2026-04-18-facial-obscuring-plan.md) | merged |
| #135 Camera naming | ✅ | [design](../specs/2026-04-18-camera-naming-classification-design.md) | — | merged |
| #136 Follow-mode | ✅ | [design](../specs/2026-04-18-follow-mode-design.md) | — | merged |

### Audio I/O + Mic

| Task | Status | Spec stub | Plan | PR |
|---|---|---|---|---|
| #133 Rode Wireless Pro | ✅ | [design](../specs/2026-04-18-rode-wireless-integration-design.md) | — | merged |
| #134 Audio pathways audit | ✅ | [design](../specs/2026-04-18-audio-pathways-audit-design.md) | [plan](2026-04-20-audio-pathways-audit-plan.md) | merged (superseded by §8 EvilPet-S4 dual-processor epic for future work) |

### Music + Content Sources

| Task | Status | Spec stub | Plan | PR |
|---|---|---|---|---|
| #127 SPLATTRIBUTION | ✅ | [design](../specs/2026-04-18-splattribution-design.md) | — | merged |
| #130 Local music repository | ✅ | [design](../specs/2026-04-18-local-music-repository-design.md) | [plan](2026-04-20-local-music-repository-plan.md) | merged |
| #131 SoundCloud integration | ✅ | [design](../specs/2026-04-18-soundcloud-integration-design.md) | — | merged |

### Operator ↔ Hapax Sidechannel

| Task | Status | Spec stub | Plan | PR |
|---|---|---|---|---|
| #132 Operator sidechat | ✅ | [design](../specs/2026-04-18-operator-sidechat-design.md) | — | merged |

### Synergy Pass

| Task | Status | Doc |
|---|---|---|
| Cross-cutting synergy analysis | 🟡 (DEFERRED to after all 16 stubs) | — |

---

### CVS Large-Scope Redesigns (specs landed)

| Task | Title | Spec | Status |
|---|---|---|---|
| #140-143 | Control-surface bundle (Stream Deck + KDEConnect + vinyl rate + IR cadence) | [design](../specs/2026-04-18-control-surface-bundle-design.md) | 🔵 SPEC |
| #144 + #145 | YouTube broadcast bundle (description auto-update + reverse ducking) | [design](../specs/2026-04-18-youtube-broadcast-bundle-design.md) | 🔵 SPEC |
| #146 | Token pole reward mechanic | [design](../specs/2026-04-18-token-pole-reward-mechanic-design.md) | 🔵 SPEC |
| #149 | Audio reactivity contract | [design](../specs/2026-04-18-audio-reactivity-contract-design.md) | 🔵 SPEC |
| #150 | Vision integration | [design](../specs/2026-04-18-vision-integration-design.md) | 🔵 SPEC |
| #151 | Cross-agent audit dormant policy | [design](../specs/2026-04-18-heterogeneous-agent-audit-design.md) | 🔵 SPEC |
| #155 | Anti-personification linter | [design](../specs/2026-04-18-anti-personification-linter-design.md) | 🔵 SPEC |
| #156 | Role derivation research template | [design](../specs/2026-04-18-role-derivation-research-template-design.md) | 🔵 SPEC |
| #157 | Non-destructive overlay layer | [design](../specs/2026-04-18-non-destructive-overlay-design.md) | 🔵 SPEC |

### Fix-PRs Shipped in PR #1056 (2026-04-18 cascade)

| Task | Title | Status |
|---|---|---|
| #158 | Director "do nothing" invariant | ✅ SHIPPED — schema `min_length=1` + parser fallbacks + regression test |
| #152 | Session-naming identity (`hapax-whoami` + cwd fallback) | ✅ SHIPPED — 10-line session-context.sh fix |
| #148 | Reactivity sync gap (snapshot-before-decay) | ✅ SHIPPED — `AudioCapture.get_signals` order fix |
| #142 PR A | Vinyl rate-aware audio restoration (ACTIVE BUG) | ✅ SHIPPED — `shared/vinyl_rate.py` + album-identifier fix |

### Operator Calls Made 2026-04-18 ("make the calls yourself")

- **#142 Handytrax preset default:** 0.741× (45-on-33). Operator overrides via `/dev/shm/hapax-compositor/vinyl-playback-rate.txt`.
- **#159 image source:** cover-DB (MusicBrainz + Discogs) PRIMARY, IR capture FALLBACK; palette-quant to mIRC-16.
- **#159 warp source:** switch workstation daemon to Pi-side pre-warped `/album.jpg`.
- **#129 operator face:** obscure on every egress (incl. local OBS V4L2).
- **#129 SCRFD dropout:** fail-closed for broadcast, last-known for local preview.
- **#129 archival recordings:** obscure applied (operator can flag override).
- **#121 HARDM cell mapping:** JSON config (externalized).
- **#121 TTS fidelity:** 16-band Kokoro envelope (matches grid).
- **#132 sidechat narrative leak:** default silent; operator opt-in flag.
- **#134 AEC:** WebRTC method; Kokoro TTS merged into reference signal.

---

## 3. Context-Void Sweep Recoveries (2026-04-18)

**Source:** [`docs/superpowers/research/2026-04-18-context-void-sweep.md`](../research/2026-04-18-context-void-sweep.md)
**Swept:** 4 most recent transcripts covering 2026-03-25 through 2026-04-18.
**Found:** 19 dropped operator commitments / directives. All now tracked.

### Priority banding

**HIGH (governance-critical or active leak):**
| Task | Title | Status |
|---|---|---|
| #155 CVS #16 | Anti-personification persona constraint | 🟣 INVESTIGATE |
| #158 CVS #19 | Director "do nothing interesting" invariant regression | 🟣 SPEC-READY |
| #147 CVS #8 | Token-pole qualifier research (healthy/non-manipulative) | 🟣 RESEARCH |
| ~~#154 CVS #15~~ | ~~Hookify glob noise~~ | ⛔ DROPPED 2026-04-18 (already resolved per operator) |

**MEDIUM (capability gap / operator-flagged value):**
| Task | Title | Status |
|---|---|---|
| #150 CVS #11 | Video/image classification underused in livestream | 🟣 SCOPE |
| #144 CVS #5 | YT description auto-update from shared links ("powerful reuseable") | 🟣 SPEC |
| #146 CVS #7 | Token pole reward mechanic (emoji spew + chat tokens) | 🟣 SPEC |
| #156 CVS #17 | Role derivation methodology (general-case + Hapax-specific) | 🟣 RESEARCH |
| #157 CVS #18 | Non-destructive overlay effects layer | 🟣 SPEC |
| #140 CVS #1 | Stream Deck control surface | 🟣 SPEC |
| #141 CVS #2 | KDEConnect interim control path | 🟣 SPEC |
| #142 CVS #3 | Vinyl half-speed toggle + correction | 🟣 SPEC |

**INVESTIGATE FIRST (may be covered; verify before specc-ing):**
| Task | Title | Cross-reference |
|---|---|---|
| #143 CVS #4 | ARCloud integration + IR cadence | #127 SPLATTRIBUTION |
| #145 CVS #6 | 24c ducking for YT/React | #134 audio pathways + PR #778 |
| #148 CVS #9 | Reactivity sync/granularity gap | #74-78 A+ livestream + #91 sim runs |
| #149 CVS #10 | 24c global reactivity contract | #134 audio pathways |
| #153 CVS #14 | Worktree cap workflow | workspace CLAUDE.md policy |
| #152 CVS #13 | Session naming enforcement | hook ecosystem |

**META / GLOBAL CLAUDE.md:**
| Task | Title | Destination |
|---|---|---|
| #151 CVS #12 | Cross-agent audit preparedness (Gemini) | Global CLAUDE.md directive |

---

## 4. Standing Tasks Not Part of HOMAGE

| ID | Title | Status | Notes |
|---|---|---|---|
| #40 | Phase 7 legacy prompt cleanup PR | 🟡 (overdue) | Post-validation cleanup; blocked only by execution slot |
| #56 | Phase 4 PyMC MCMC BEST analysis | ⚫ | Data-sufficiency gated (livestream accumulation) |
| hapax-constitution#46 | Operator merge + registry.yaml patch | ✅ | Closed per task #58 |

---

## 5. Context-Void Sweep

**Launched:** 2026-04-18
**Completed:** 2026-04-18 (~4.7 min wall time)
**Agent:** general-purpose sweeping 4 most recent transcripts (152M + 106M + 88M + 112M)
**Output (permanent):** [`docs/superpowers/research/2026-04-18-context-void-sweep.md`](../research/2026-04-18-context-void-sweep.md)

**Result:** 19 dropped commitments recovered, triaged to §3 above. Tasks #140–#158 created. Task #138 (triage) complete.

---

## 6. Plan-Doc Freshness Policy

Every spec stub and plan under `docs/superpowers/{specs,plans}/` MUST:
1. Carry a `**Status:**` line at the top updated when the doc's phase changes.
2. Carry a `**Last updated:**` date on every substantive edit.
3. Link back to this active-work index so the graph is traversable from either end.

If a doc goes stale (no update in 14 days while its status is ACTIVE or QUEUED), it is flagged for rescue in the next tick.

---

## 7. Change Log

- **2026-04-18** — Index created. HOMAGE epic through Phase 11b merged. Research dossier with 16 findings provisionally approved. Context-void sweep dispatched.
- **2026-04-18 (later)** — Spec stubs written for #129 (facial obscuring), #122 (DEGRADED-STREAM), #134 (audio pathways). Tasks #137/138/139 created for index maintenance + sweep triage + deferred synergy analysis.
- **2026-04-18 (later)** — Context-void sweep returned. 19 dropped commitments recovered as tasks #140–#158. Index §3 added with HIGH/MEDIUM/INVESTIGATE/META priority banding.
- **2026-04-18 (final)** — All 19 CVS research agents returned. Findings in [`cvs-research-dossier.md`](../research/2026-04-18-cvs-research-dossier.md) §2. **Active regressions surfaced:** #158 director no-op 25% live, #142 album-identifier 2× hardcoded, #155 anti-personification violations, #152 session-naming, #154 hookify parser. Next tick: fix-PRs on actives + spec stubs on large-scope redesigns.
- **2026-04-19** — HOMAGE umbrella Phases 7–10 + 11c + 12 shipped. GEM ward designed at `docs/research/2026-04-19-gem-ward-design.md` (task #191 new). Voice-modulation Phase 1 plan authored.
- **2026-04-20** — Heavy-shipping day. Specs + research: HOMAGE ward umbrella (50K-line spec + 84K-line plan), EvilPet-S4 routing permutations research (62K lines), CBIP cultural-lineage + 5-family enhancement research, CBIP Phase 0 tint fix (PR #1112), 3h audit remediation plan with 10 B1-B10 bundles (alpha+delta split), D-31 unplanned-specs triage (19 specs classified), chat-keywords ward design (task #180), vitruvian enhancement, mode-d-voice-tier mutex, voice-tier 7-tier ladder, unified audio architecture, dual-FX routing. Shipped: B1 voice-gate wire (alpha), B2 YT backflow + loudnorm (alpha), B3 programme partials (alpha), B5 pin-check systemd (joint), B9 Evil Pet Grafana (alpha), B4 audio-infra drift PR (delta).
- **2026-04-21 (early)** — Operator reports livestream bypassing Evil Pet. Delta diagnoses filter-chain drift (AUX10/11 raw PC on broadcast sum); opens PR #1115 (dual-processor epic): research + spec + plan + Phase A1 drift fix (live) + A2 runbook + A3 notification isolation (live) + A4 state-surface audit CLI (live) + A5 YT→S-4 bridge (live, dormant until S-4 plugs) + audit-doc rescue from stash + B8 runtime-safety test rescue. 44 pipewire tests + 6 gain-discipline tests pass locally.
- **2026-04-21 (mid)** — Delta researched OQ-1 (HOMAGE 15th ward) and OQ-3 (CBIP) historical operator directives after operator flagged potential dropped research in alpha's workstream. OQ-1: the 15th ward is **GEM** (operator-designed 2026-04-19), not captions/vitruvian. OQ-3: PR #1112 deterministic tint is Phase 0 only; 5 enhancement families + 3 new effect-graph nodes + recognizability test harness still to ship. Audit dossiers at `~/.cache/hapax/relay/audit/oq{1,3}-*.md`. Alpha subsequently authored `docs/superpowers/specs/2026-04-21-cbip-phase-1-design.md` and `docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md` in response.
- **2026-04-21 (late)** — Delta added Phase B4 (S-4 scene library, 10 scenes) + B5 (dual-engine pairings) + B3 policy core (state + 3-layer policy, 22 tests) + B6 UC1–UC10 integration tests (18 tests) + C1 ramp formula + C2 utterance-boundary sticky tracker (14 tests). PR #1115 reaches 9 commits, 61 audio-router tests. Operator: "Consider everything ratified and move forward." + "Get a pathway towards degradation mode prioritized." Delta Degraded-Stream MVP queued as next post-merge item per `~/.cache/hapax/relay/delta-priority-pathway-2026-04-21.md`. Active-work-index refreshed (this commit): §1/§2 status markers synced; §8 added for 2026-04-19/-20/-21 epics.

---

## 8. 2026-04-21 Epics (post-ratification workstreams)

### 8.1 EvilPet-S4 Dual-Processor Dynamic Routing (delta)

**Research:** `docs/research/2026-04-21-evilpet-s4-dynamic-dual-processor-research.md` (77K lines, 12 topology classes, 10 use-cases, control-law layer).
**Spec:** `docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md` (supersedes 2026-04-20-evilpet-s4-routing-design for dual-engine scope).
**Plan:** `docs/superpowers/plans/2026-04-21-evilpet-s4-dynamic-dual-processor-plan.md` (16 tasks, 3 phases).
**PR:** #1115 (9 commits — spec + plan + research + Phase A1/A2/A3/A4/A5 + audit doc rescue + B8/B4/B5/B3/B6/C1/C2).

| Phase | Status | Notes |
|---|---|---|
| Research + spec + plan | ✅ | In PR #1115 |
| A1 filter-chain drift fix | 🟢 LIVE | Deployed 2026-04-21 04:30Z |
| A2 hardware-loop runbook | ✅ | In PR #1115 |
| A3 notification-sink isolation | 🟢 LIVE | Deployed 2026-04-21 04:45Z |
| A4 state-surface audit CLI | 🟢 LIVE | Symlinked to `~/.local/bin/hapax-audio-state-audit` |
| A5 YT→S-4 bridge | 🟢 LIVE | Dormant until S-4 USB enumerates |
| B3 router policy (state + 3-layer) | ✅ | 22 tests in PR #1115 |
| B4 S-4 scene library (10 scenes) | ✅ | In PR #1115 |
| B5 dual-engine pairings | ✅ | In PR #1115 |
| B6 UC1–UC10 integration tests | ✅ | 18 tests in PR #1115 |
| B8 S-4 runtime-safety test | ✅ | In PR #1115 |
| C1 ramp formula | ✅ | 7 tests in PR #1115 |
| C2 utterance-boundary sticky | ✅ | 14 tests in PR #1115 |
| C3 observability closure | 🟡 | Queued — delta §8.5 item 5 |
| C4 dry-run preview | 🟡 | Queued — delta §8.5 item 8 |
| C5 WARD pre-render gate | 🟡 | Queued — delta §8.5 item 9 |
| B1 S-4 USB enumeration | ⚫ | Operator plug-in gated |
| B2 S-4 MIDI lane | ⚫ | Operator plug-in gated |
| Full `dynamic_router.py` tick loop | ⚫ | B1/B2 gated |

### 8.2 CBIP Phase 1 (delta — B10 re-scope; alpha-authored spec)

**Research:** `docs/research/2026-04-20-cbip-vinyl-enhancement-research.md` (5 enhancement families + test harness) + `docs/research/2026-04-20-cbip-1-name-cultural-lineage.md` (chess-boxing 4-move hermeneutic).
**Spec:** `docs/superpowers/specs/2026-04-21-cbip-phase-1-design.md` (alpha-authored 2026-04-21 after OQ-3 audit; Palette Lineage + Poster Print + 3 effect nodes + test harness + operator override + Ring-2 pre-render).
**Plan:** ⚠️ **MISSING** — delta §8.5 item 6 authors this next.
**PR:** none yet.
**Status:** 🔵 SPEC.

### 8.3 GEM Ward Activation (alpha-plan; operator-ratified as 15th ward)

**Research:** `docs/research/2026-04-19-gem-ward-design.md`.
**Plan:** `docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md` (alpha-authored 2026-04-21).
**PR:** none yet.
**Status:** 🟡 QUEUED — delta §8.5 item 3.
**Context:** Operator-ratified 2026-04-21 as the 15th HOMAGE ward; captions retires in same geometry `(40, 820, 1840, 240)`.

### 8.4 Degraded-Stream MVP (delta — complete the #122 ship)

**Spec:** `docs/superpowers/specs/2026-04-18-degraded-stream-design.md`.
**Plan:** `docs/superpowers/plans/2026-04-18-degraded-stream-plan.md` (10 tasks, 63 checkboxes, 0 done).
**Current ship:** controller `agents/studio_compositor/degraded_mode.py` (commit `e9f633ae1`) + HARDM publisher bridge (`a07d600bc`). Missing: BitchX netsplit ward, auto-trigger hooks, systemd ExecStartPre/Post, compositor main-loop dispatch, observability, Grafana alert. §2 status flipped 🔵 SPEC → 🟢 PARTIAL.
**PR:** none yet for MVP.
**Status:** 🟡 QUEUED — delta §8.5 item 2 (prioritized per operator 2026-04-21 directive).

### 8.5 Delta Priority Pathway (2026-04-21 post-ratification)

Full ordered queue: `~/.cache/hapax/relay/delta-priority-pathway-2026-04-21.md`.

1. PR #1115 merges (CI)
2. **Degraded-Stream MVP** (infrastructure — prioritized)
3. GEM ward activation (per 2026-04-21 plan)
4. B7 HOMAGE umbrella hardening (task #226, unblocked once 15-ward registry stable)
5. EvilPet-S4 Phase C3 observability
6. **CBIP Phase 1 plan** (doc-only) — closes §8.2 plan gap
7. CBIP Phase 1 implementation (multi-PR epic)
8. EvilPet-S4 Phase C4 dry-run preview
9. EvilPet-S4 Phase C5 WARD pre-render gate
10. EvilPet-S4 B1/B2 (operator S-4 plug-in gated)
11. Full `dynamic_router.py` tick loop

### 8.6 Alpha Track

- **B3 programme completion** (task #223) — alpha active; ProgrammeManager lifecycle + JSONL log + named abort predicates. Tracked via audit-remediation bundle B3.
- **Remaining wiring audits** (tasks #171, #172) — alpha pending.
- **CBIP Phase 1 spec** authored 2026-04-21 (see §8.2).
- **GEM activation plan** authored 2026-04-21 (see §8.3).
