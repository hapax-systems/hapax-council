# Synergy Analysis — First Pass (2026-04-18)

**Status:** First-pass analysis across 25 landed specs + 35 research items (16 HOMAGE follow-on + 19 CVS). Second pass deferred until HOMAGE epic Phase 12 ships.

**Scope sources:**
- `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` (16 findings, tasks #121–#136)
- `docs/superpowers/research/2026-04-18-cvs-research-dossier.md` (19 findings, tasks #140–#158)
- `docs/superpowers/research/2026-04-18-context-void-sweep.md` (operator quote provenance)
- 25 spec files under `docs/superpowers/specs/2026-04-18-*-design.md`
- Active-work index `docs/superpowers/plans/2026-04-18-active-work-index.md`

**Methodology:** Dossiers read end-to-end; specs spot-checked for consolidation/dependency evidence. Each claim below cites a spec path + anchor or item number.

---

## 1. Executive Summary

The 2026-04-18 cascade is not 35 independent workstreams — it is a single architectural shape surfacing as overlapping tickets. Three forces produced it: (1) the HOMAGE epic reaching Phase 11b exposed what wasn't yet a `HomageTransitionalSource`; (2) a context-void sweep caught 19 dropped operator commitments from 2026-03-25 through 2026-04-06, most of which were already half-implemented and needing integration rather than design; (3) an audit pass (Phase 7 persona, director no-op, anti-personification) surfaced live invariant violations. The four fix-PRs already landed on PR #1056 (#158, #152, #148, #142-A) are evidence that the cascade started as active-regression triage, not feature work.

**Top three cross-cutting themes:**
1. **Consent/privacy as pixel-level and state-level floor** — #129 facial obscure, #132 sidechat redaction, #123/#146 aggregate-only chat, #155 anti-personification, #147 ethical rubric, #151 heterogeneous audit policy. All inherit the `chat_reactor.py` caplog precedent (no per-author state, no persistence, no author in logs).
2. **Control-surface and rate-as-first-class-data convergence** — #140/#141/#142/#143 share one command registry + one `/dev/shm` file-bus (control-surface-bundle-design.md §2). #142 `vinyl_playback_rate: float`, #143 `album-cadence.json`, #148 30 fps→93 fps sync gap, #149 `AudioReactivitySource` protocol, #150 three-priority vision routing — all are "treat rate/cadence/signal as parameterizable first-class data, not boolean or hardcoded." The old code kept these as booleans or hardcoded constants; the cascade uniformly floats them.
3. **BitchX palette + Px437 typography as shared aesthetic backbone** — #121 HARDM, #122 DEGRADED, #123 chat, #124 reverie tint, #125 token pole, #146 token pole glyphs, #157 non-destructive tag, #159 vinyl image. Every HOMAGE follow-on ward consumes `HomagePackage.palette` + `_BITCHX_GRAMMAR.line_start_marker` + `Px437 IBM VGA 8×16`. This is the real unifier across the rendering subsystem.

**Top five critical-path items (ordered):**
1. **#129 facial obscuring** — live privacy leak today via `content_injector` → Reverie → `pip-ur`. Ship before any other rendering change touches the compositor.
2. **#155 anti-personification linter (warn-only)** — governance-critical, surfaces the two live violations (`conversational_policy._OPERATOR_STYLE`, `conversation_pipeline` LOCAL prompts), blocks #126 Pango text repo.
3. **#134 audio pathways audit + echo cancellation** — unblocks #133 Rode, #132 sidechat mic path, #145 24c-side ducking; closes phantom-VAD loop today.
4. **Control-surface bundle #140+#141+#142+#143** — one spec already consolidated these; PR A of #140 unblocks #142-C, #143 cadence, #145 mirror. Vinyl rate float is the upstream of fingerprinting, BPM, director prompts, reactivity.
5. **#150 vision integration Phase 1 (scene → preset-family)** — unblocks #121 HARDM cells 16–239, closes "hero is empty room" bug (`per_camera_person_count` gate), feeds #136 follow-mode. One-of-seventeen signal consumption today is architecturally wrong; Phase 1 alone fixes the largest gap.

The landscape shape: HOMAGE epic is 8/14 phases complete and running; the 25 landed specs are the surface area that emerges from the other 6 phases plus the CVS recoveries. The second-pass synergy analysis (post-Phase 12) will reason about *integrated* shapes; this first pass identifies which items collapse, which are already load-bearing for others, and what gaps the collisions reveal.

---

## 2. Cross-Cutting Themes

### Theme A — Consent / Privacy Invariants (load-bearing, 9 items)

**Participants:** #129 (facial obscure), #132 (sidechat redaction), #123 (chat ambient ward — aggregate only), #126 (Pango text repo axiom gate), #146 (token pole — no per-author state), #147 (ethical rubric — negative-defined positivity), #151 (heterogeneous agent audit policy), #155 (anti-personification linter), #156 (role `is_not:` fields).

**Observation:** Every consent/privacy item inherits the same precedent — `chat_reactor.PresetReactor`'s caplog discipline at `chat_reactor.py:254` (preset name only, never author, never body). This precedent is cited verbatim in:
- `2026-04-18-chat-ambient-ward-design.md` §1 (redaction invariant)
- `2026-04-18-token-pole-reward-mechanic-design.md` §3 (7 ethical principles, rule 1)
- `2026-04-18-operator-sidechat-design.md` §1 (redaction invariant)
- cvs-research-147.md §7 (enforcement template reference)

**Consolidation opportunity:** Extract `shared/consent_discipline.py` with three reusable primitives: (a) `aggregate_only_decorator` (asserts no string values in log records), (b) `author_handle_redactor` (regex + embedding-distance operator detector), (c) `pixel_floor_applier` (SCRFD + Kalman + fail-closed rect, currently only in #129). These three plus the existing caplog test pattern would cover all 9 items.

**Load-bearing observation:** The axiom `it-irreversible-broadcast` T0 is the pixel-level invariant; `interpersonal_transparency` is the state-level invariant; `corporate_boundary` is the storage invariant. The three form a layered fence, and every cascade item fits one of the three layers. #129 is the pixel fence; #123/#146/#155 are the state fence; #132 is the storage fence.

**Consolidation estimate:** ~400 LOC of shared primitives, ~6 fewer ad-hoc test patterns, one authoritative doc per fence layer instead of three precedent chains.

---

### Theme B — Control-Surface Backbone (4 items already consolidated)

**Participants:** #140 Stream Deck, #141 KDEConnect, #142 vinyl rate, #143 IR cadence.

**Observation:** The operator already recognized this synergy — `2026-04-18-control-surface-bundle-design.md` consolidates all four into one spec. §2 of that spec identifies the two shared substrates: logos-api `:8051` command registry + `/dev/shm/hapax-compositor/*.txt` file-bus. The four items expose the same verbs through different surfaces (deck keys / phone shortcuts / UI buttons) and share four backend endpoints (`/studio/vinyl-playback-rate`, `/api/album/cadence`, `/api/album/reid`, `studio.*` registry entries).

**Load-bearing observation:** The relay-vs-direct-HTTP decision in §2 of the bundle spec (Stream Deck adapter POSTs directly to `:8051` for backend commands, bypassing Tauri `:8052` relay) is a correctness constraint, not a performance one. If backend commands went through Tauri, the Stream Deck would die when the Logos window closed. This architectural split is new and should be made a general rule, not per-surface.

**Consolidation opportunity:** Already done in the bundle spec. One follow-on: extract `scripts/hapax-ctl` as a reusable client that any control surface (Stream Deck adapter, KDEConnect runcommand, future voice shortcuts via #132) imports — not duplicates. The bundle spec §3.2 and §3.1 both describe the same POST shape; a `hapax_ctl.client` library would be ~80 LOC saved across three adapter codebases.

---

### Theme C — Rate / Cadence / Signal as First-Class Data (6 items)

**Participants:** #142 (vinyl playback rate), #143 (IR capture cadence), #148 (reactivity sync 30→60 Hz or peak-hold), #149 (audio reactivity protocol with `rate` + `chunk` fields), #134 (AEC + topology — rate-aware), #150 (scene → family mapping parameterized).

**Observation:** Each of these fixes a place where the old code kept a rate/cadence as a hardcoded number or boolean. The cascade's uniform move is to float them:

| Item | Old (hardcoded) | New (parameterized) |
|---|---|---|
| #142 | `vinyl-mode.txt` boolean + `asetrate=88200` 2× restore | `vinyl-playback-rate.txt` float + `asetrate = 44100/rate` |
| #143 | 5 s / 15–30 s hardcoded in album-identifier.py | `album-cadence.json` presets + force-refresh endpoint |
| #148 | `fx_tick` 30 fps polling 93 fps DSP | wall-clock peak-hold in `get_signals` or 60 Hz tick |
| #149 | `mixer_master` hardcoded as reactivity source | `AudioReactivitySource` protocol with `rate`/`chunk`/`channel_role` |
| #134 | AEC claimed but not running | `module-echo-cancel` pass with explicit ref signal |
| #150 | 11 classifiers write; 1 signal read | `scene_family_router.py` + `config/scene-family-map.yaml` mapping |

**Load-bearing observation:** Every one of these surfaces a **downstream correctness bug** when the hardcoded value is wrong. #142: ACRCloud lookup fails at 0.741× because audio arrives at 1.48×. #143: Gemini Flash gets stale frames if operator paused deck. #148: operator perceives "own pulse" latency. #149: 7 of 8 24c inputs can't drive shaders. #134: phantom VAD from YouTube crossfeed creates ducking oscillation. #150: director punts (#158) because signals don't reach it.

**Consolidation opportunity:** A `shared/cadence.py` module with a `CadenceState` pydantic model + `/dev/shm` file-bus conventions (atomic tmp+rename, missing = default, operator-override via touch) would give all 6 items one writer/reader discipline. The audio reactivity contract (#149 §4.1) already has the right shape — lift it generally.

**Secondary observation:** #148 is a prerequisite for #149 (Phase A extract) per the CVS dossier sequencing. Do #148 first or the 24c reactivity contract multiplies a broken cadence.

---

### Theme D — BitchX Package Palette as Shared Aesthetic (8 items)

**Participants:** #121 HARDM, #122 DEGRADED, #123 chat ambient, #124 reverie tint, #125 token pole HOMAGE, #146 token pole reward glyphs, #157 non-destructive overlay, #159 vinyl image ward.

**Observation:** All eight consume `HomagePackage.palette` (mIRC-16), `_BITCHX_GRAMMAR.line_start_marker`, `_BITCHX_TYPOGRAPHY.primary_font_family` (`Px437 IBM VGA 8×16`), and `raster_cell_required: True`. Each spec cites `apply_package_grammar(cr, package)` or `package.resolve_colour(...)`. #124 uses pattern (b) "exempt Reverie from choreography" + pattern (d) "consume custom[4]" — palette still reaches Reverie via the coupling slot.

**Load-bearing observation:** The HOMAGE Phase 11c migration for Cairo sources would be mechanical if not for #124 (reverie substrate exemption) and #157 (the `content_layer` WGSL node is inside the shader graph, not a Cairo source). These two edge cases drive the need for the `HomageSubstrateSource` marker trait (#124 §3) and the `destructive_taxonomy.json` + `non_destructive_overlay` tag (#157 §4).

**Consolidation opportunity:** The five-PiP-FX dict in `album_overlay.py` deletion pattern (#159 §5.2) is repeated in spirit across #123 (replace `ChatKeywordLegendCairoSource`), #125 (replace SVG-esque token pole fill), #121 (geometry-invariant + palette-variant). Extract a `PackageCairoSource` mixin that: (a) reads active package on each paint, (b) maps palette roles to cairo set_source_rgba calls, (c) asserts `refuses_anti_patterns` at render time (no rounded rect, no fade). ~150 LOC shared across 5+ wards.

**Caveat:** This is mostly a "HOMAGE Phase 11c implementation discipline" theme, not a new abstraction. The marker trait + tag mechanism already captures it. Flag for second-pass: check if any ward after Phase 11c is still hardcoding palette.

---

### Theme E — Perception → Compositor Consumption Gaps (4 items)

**Participants:** #135 (camera naming), #136 (follow-mode), #150 (vision integration), #121 (HARDM cells 16–239).

**Observation:** Today the livestream director branches on exactly one RGB-vision signal (`visual.detected_action == "away"`, per vision-integration-design §2.2). Sixteen produced signals + entire `SceneInventory` API are unconsumed. The four items describe different consumers of the same signal pool:

```
perception-state.json (writer, 1 Hz)
  ├─ visual.per_camera_scenes    ──► #135 (authored labels) ──► #136 follow-mode activity tag
  │                               ──► #150 Phase 1 (scene→family)
  │                               ──► #121 HARDM cells 16–239 (scene-signal expansion)
  ├─ visual.top_emotion          ──► VLA stimmung (existing)  ──► #150 (unused for composition)
  ├─ visual.hand_gesture         ──► #150 Phase 2 (object→ward)
  ├─ visual.gaze_direction       ──► #136 follow-mode activity tag
  ├─ visual.per_camera_person_count ──► #150 Phase 1 hero-gate
  └─ visual.operator_confirmed    ──► #136 operator-detected filter
```

**Load-bearing observation:** #135 is a hard prerequisite for #136 (follow-mode references camera roles by stable name) and for #150 Phase 1 (scene→family depends on per-camera scene labels, not global). Both specs cite #135 as blocker. HARDM (#121) §3 reserves cells 16–239 for "scene-signal / aux-signal expansion from task #150" — so #121 depends on #135 + #150 Phase 1 for meaningful content in 88% of its cells.

**Consolidation opportunity:** A single `agents/studio_compositor/perception_router.py` module that owns the mapping from `PerceptualField.visual` to compositional impingements, with #135 YAML as its label vocabulary, #136 as a stance filter, #150 as its phased rollout. One module, four items' worth of glue code.

**Savings:** ~200 LOC of per-consumer routing scattered across `twitch_director.py`, `compositional_consumer.py`, `objective_hero_switcher.py`, and a new `scene_family_router.py`.

---

### Theme F — Attribution Backflow (5 items, emergent abstraction)

**Participants:** #127 SPLATTRIBUTION (vinyl detection), #144 YouTube description auto-update, #146 token pole reward, #159 vinyl image ward (cover-DB), #123 chat ambient ward (DOI detection, future).

**Observation:** The YouTube description bundle spec (§2.4) already surfaced the abstraction — `AttributionSource` protocol:

```python
class AttributionSource(Protocol):
    kind: Literal["yt-react", "splattribution", "citation", "homage", "vinyl", "objective", "condition"]
    url: str
    title: str
    author: str | None
    timestamp: datetime
```

…with 7 candidate producers already in-repo. #127 writes `music-attribution.txt`, #159 writes `album-cover.png` + attribution text, #146 reads chat T5/T6 classifications, #144 extracts URLs from chat, #123 (future) resolves DOIs. All five terminate at the same substrate — some form of public-record attribution.

**Load-bearing observation:** `youtube-broadcast-bundle-design.md` §2.4 calls this "what the operator meant by 'powerful reusable'" — the operator flagged it at 2026-04-06 and the cascade vindicates the flag. One protocol, many producers, one syncer = real consolidation, not gold-plating.

**Consolidation opportunity:** Land the `AttributionSource` protocol + `youtube_description_syncer.register(source)` API as part of #144's first PR. Then #127, #159, #146 each register as sources in their respective PRs (1-line change each). #123's DOI resolver registers when it lands.

**Savings:** Each individual spec would otherwise author its own description-writer path. Shared protocol: ~60 LOC; per-source registration: ~10 LOC each vs ~40 LOC each of bespoke YouTube integration.

---

### Theme G — Ethical / Governance Axioms as Code (4 items, tightly coupled)

**Participants:** #147 qualifier rubric (negative-defined positive, Shannon-surprise for interesting, embedding distance for contributive), #155 anti-personification linter, #156 role derivation methodology, #151 heterogeneous audit policy.

**Observation:** Three of these (#147, #155, #156) are not features — they are **enforcement mechanisms** for architectural axioms. #147 encodes "measure structure not quality" as deterministic chat-tier arithmetic. #155 encodes "no inner life claims" as regex + AST deny-list. #156 encodes "roles derive from literature, not declaration" as a template + CI gate. #151 is a dormant wrapper for when heterogeneous agents activate.

**Load-bearing observation:** The four items form a **governance stack**: #151 is agent-level (who authored this?), #156 is role-level (what function does this agent embody?), #155 is prompt-level (can we speak about inner life?), #147 is output-level (can the rubric even judge "quality"?). All four are negative-defined (what is forbidden) with positive carve-outs.

**Contradiction with #156 vs #155:** Role derivation (#156) requires per-cadence decision schedules that could slip into personification if authored carelessly ("the host feels the room" → invalid). #155's linter would catch this. The two are mutually reinforcing but need to run in order — #156 templates must be lint-clean before they become canonical, which is why #155 Stage 6 explicitly imports the linter into #126 Pango text repo gate.

**Consolidation opportunity:** A single `docs/superpowers/governance-as-code-index.md` that maps each axiom (`interpersonal_transparency`, `management_governance`, `corporate_boundary`, `single_user`) to its enforcement mechanisms across the four items + existing hooks. Not new code, but a navigational document that makes the stack visible.

---

### Theme H — Substrate Preservation + Fallback Modes (3 items, minor pattern)

**Participants:** #124 (Reverie never recedes — `HomageSubstrateSource` marker), #122 (DEGRADED-STREAM mode — all wards recede to safe fallback during rebuild), #132 (operator sidechat — default silent, never leaks to public).

**Observation:** Three items each carve out a "floor" that is invariant against the default dynamic:
- #124: Reverie is floor under HOMAGE choreography (never absent)
- #122: DEGRADED overrides all other wards (absent until rebuild completes)
- #132: sidechat responses exist but never escape private sink (absent to public egress)

**Load-bearing observation:** Each is an "exemption from the main FSM," and each uses a different mechanism: marker trait (#124), flag file (#122), intent-family veto (#132). The patterns don't collapse cleanly — they solve different problems (substrate persistence vs deploy safety vs channel isolation).

**Verdict:** Minor pattern. Each item needs its own mechanism; the shared observation is that the HOMAGE FSM is not universal and three explicit carve-outs exist. Call out in second-pass for operator to decide whether a general "exempt" trait with typed reasons (`substrate | deploy_safety | channel_isolation`) is worth the abstraction cost.

---

## 3. Dependency Graph

### Hard blocks (A must ship before B)

- **#135 → #136** (follow-mode references camera roles by stable name)
- **#135 → #150 Phase 1** (scene→family depends on per-camera scene labels)
- **#135 + #150 Phase 1 → #121** (HARDM cells 16–239 reserved for scene signals)
- **#134 → #133** (Rode integration fallback chain needs echo_cancel_capture)
- **#134 → #132 mic path** (sidechat mic uses post-AEC source)
- **#134 channel-doc correction → #149** (audio reactivity spec §3 depends on #134 correcting Cortado=FL, mixer_master=FR)
- **#148 → #149 Phase A** (fx_tick sync fix must land before extracting MelFFTReactivitySource; otherwise contract multiplies broken cadence across all sources)
- **#147 rubric → #146** (token pole reward mechanic imports rubric verbatim as input constraint)
- **#155 linter (warn-only) → #126 Pango text repo** (text repo's axiom gate consumes the linter; dossier: "spec will sharpen the gate first")
- **#155 Stages 2-4 (refactors) → #155 Stage 5 (fail-loud)** (linter can't block until existing 2 violations cleaned)
- **HOMAGE Phase 6 (ward↔shader coupling) → #121 HARDM** (cell 12 reads `uniforms.custom[4].shader_feedback_key`)
- **HOMAGE Phase 11c → #124 reverie marker trait** (phase needs the trait to exempt reverie from migration)
- **HOMAGE Phase 11c → #125 token pole migration** (pole inherits HomageTransitionalSource within 11c scope)
- **HOMAGE Phase 12 → synergy-second-pass** (explicit precondition in both dossiers)
- **#127 vinyl_playing gate → #159 ward FSM** (ward entry/exit gates on the derived boolean)
- **#127 → #130** (local music repo activates when vinyl_playing==False)
- **#130 → #131** (SoundCloud falls back to local repo on API unavailable)
- **OAuth consent for `youtube.force-ssl` → #144** (operator runs `scripts/youtube-auth.py` once; everything else silent-skips until then)
- **#142 PR A → #142 PR B, PR C** (float signal is the substrate; reactivity + control surfaces consume it)
- **#140 PR A → #140 PR B** (registry entries must exist before adapter deployment verifies them)
- **#140 → #142 PR C, #143 PR B** (control surfaces for vinyl rate + IR cadence ride on Stream Deck)
- **#140 → #141** (KDEConnect runcommand entries mirror `config/streamdeck.yaml`)

### Soft dependencies (A benefits B)

- **#150 Phase 1 → #158 follow-up** (director punts partly because perception signals don't reach it; vision routing reduces punt pressure)
- **#157 non-destructive tag → #128 preset variety** (#128 Phase 1 parametric mutation targets the `non_destructive_overlay` pool created by #157)
- **#132 sidechat → Rode #133** (sidechat mic input benefits from wireless freedom)
- **#121 HARDM → #150 Phase 1** (HARDM cells would be more useful with scene-family signals; mutually reinforcing but not hard)
- **#122 DEGRADED → HOMAGE Phase 10 runbook** (rehearsal/audit benefits from having a known-safe fallback mode to rehearse against)
- **#146 ledger transparency → #147 anti-addiction principle** (deterministic payout mutually reinforces "no per-author state")
- **#159 cover-DB → #144 AttributionSource** (cover-DB metadata is a natural attribution source for the YT description)

### Chicken-and-egg / co-evolution

- **#155 ↔ #156** — role derivation templates must be lint-clean (depends on #155); linter's `is_not:` check (#155 Stage 4) depends on role registry fields added by #156 Phase C. Ship #155 warn-only first + #156 Phase A template, then #156 Phase C adds `is_not:` fields which enable #155 Stage 4 test.
- **#121 HARDM ↔ #150 vision** — HARDM cells 16–239 reserved for vision signals; vision routing Phase 1 has no obvious UI surface until HARDM exists. Ship both in the same epic window.
- **#142 float rate ↔ #127 SPLATTRIBUTION** — SPLATTRIBUTION's `vinyl_playing` derivation adds rate-bounds check (`0.85 ≤ rate ≤ 1.15`, splattribution-design.md §5) that depends on #142 publishing the rate. #142 PR A writes the rate; #127 reads it; they must ship in that order or the gate degrades open.
- **HOMAGE Phase 6 ↔ HOMAGE Phase 9** — ward↔shader coupling (Phase 6) and `PerceptualField.homage` (Phase 9) both write to `custom[4]`; coordination needed.

### Visual summary

```
                         ┌──────────────────────┐
                         │ OAuth consent (ops)   │
                         └──────────┬───────────┘
                                    ▼
     #155 linter (warn) ────► #126 Pango ────► #144 YT desc ──► AttributionSource
           │                                          ▲
           ▼                                          │
     #155 refactors ──► #155 fail-loud               │
           │                                          │
           ▼                                          │
     #156 template                                    │
           │                                          │
           ▼                                          │
     #156 registry                                    │
                                                      │
     #134 AEC ──► #133 Rode ──► #132 sidechat         │
       │                                              │
       ▼                                              │
     #149 contract (after #148 sync fix)              │
                                                      │
     #140 deck ─► #141 KDE ─► #142-C ─► #143 cadence  │
       ▲                                              │
       │                                              │
     #142-A rate ──► #142-B reactivity                │
           │                                          │
           ▼                                          │
     #127 vinyl_playing ──► #130 local music ─► #131 SC
           │
           ▼
     #159 vinyl image ward
           │
           ▼
 HOMAGE Phase 11c ──► #124 reverie + #125 token pole migration
       │
       ▼
 HOMAGE Phase 12 ──► SECOND-PASS SYNERGY

     #135 cameras ─► #136 follow ──────┐
           └─► #150 Phase 1 ──► #121 HARDM ◄─ HOMAGE Phase 6 (coupling)
                    └─► #158 relief (soft)
```

---

## 4. Consolidation Opportunities

### CO-1: Extract `shared/consent_discipline.py` (primitives for Theme A)

**Items:** #123, #129, #132, #146, #147, #155.

**Abstraction:**
- `@aggregate_only` decorator — asserts log record has no string-valued fields matching author/body patterns (promotes `chat_reactor.py:254` caplog pattern to reusable)
- `AuthorHandleHasher` — salted hash per session, never persisted, `unique_authors_60s` counting only
- `PixelObscureApplier` — SCRFD + Kalman + fail-closed, parameterized by detector cadence + obscure technique + policy (ALWAYS_OBSCURE vs OBSCURE_NON_OPERATOR)

**Savings:** ~400 LOC duplication across `chat_reactor.py`, `chat_signals.py`, `chat_ambient_ward` (new), `OperatorSideChatPanel` backend, `token_pole_reward_accumulator` (new), `facial_obscure_filter` (new). One authoritative regression test in `tests/shared/test_consent_discipline.py` replaces 5+ scattered caplog tests.

**Cost:** Minor — existing code keeps working, new consumers import the primitives. One PR, ~1 day.

---

### CO-2: Collapse #140, #141, #142, #143 (already done)

**Items:** Four CVS items into `2026-04-18-control-surface-bundle-design.md`.

**Evidence:** Spec §2 identifies shared substrates (command registry + file-bus); §3 lays out 8 PRs sized appropriately. §4 interaction matrix shows single writer/reader discipline.

**Savings:** 4 per-item specs with duplicated context collapse to one spec with cross-referenced sections. Estimated: 2× LOC reduction in design docs, one test harness for fake-relay pattern (`tests/scripts/test_hapax_ctl.py`) serves both #140 and #141.

---

### CO-3: Merge #125 and #146 into a single "token pole epic"

**Items:** #125 (HOMAGE grammar migration) and #146 (reward mechanic redirect).

**Rationale:** Both touch `token_pole.py` and `token-ledger.json`. #125 preserves geometry + swaps palette. #146 redesigns the driver (LLM-spend → chat-contribution) and adds glyph spew. Shipping them serially means two refactors of the same module, two test passes, two palette-consumer audits. Shipping jointly means one refactor with the new palette wired in from the start.

**Proposed:** One plan doc, two phased PRs (#125 first as it preserves behavior; #146 second as it redesigns driver).

**Savings:** ~1 refactor pass, 1 test file, clearer git history.

---

### CO-4: `shared/cadence.py` for Theme C

**Items:** #142, #143, #148, #149 (not #134 or #150 — those are specific domain integrations).

**Abstraction:** `CadenceState` pydantic model + file-bus conventions (atomic tmp+rename, missing = default). `CadenceReader` for consumers, `CadenceWriter` for logos-api endpoints.

**Savings:** ~150 LOC across 4 items; one consistent file-bus discipline.

**Caveat:** Soft win; each item can ship independently. Lift to shared if a 5th cadence-like signal appears.

---

### CO-5: `AttributionSource` protocol (Theme F)

**Items:** #127, #144, #146, #159, and future #123 DOI.

**Abstraction:** Protocol + `youtube_description_syncer.register(source)` API, already specified in youtube-broadcast-bundle §2.4.

**Savings:** Per-source registration ~10 LOC vs ~40 LOC of bespoke YT integration. ~150 LOC total across 5 items.

**Cost:** Protocol ~60 LOC + one test. Land with #144 PR.

---

### CO-6: `agents/studio_compositor/perception_router.py` (Theme E)

**Items:** #135, #136, #150, part of #121.

**Abstraction:** Single module owning `PerceptualField.visual` → compositional impingements mapping. Consumes #135 YAML, applies #136 stance filter, implements #150 Phase 1/2/3 routing.

**Savings:** ~200 LOC scattered across `twitch_director.py`, `compositional_consumer.py`, `objective_hero_switcher.py`, and the proposed new `scene_family_router.py`.

**Cost:** Requires #135 spec to land first. Then one PR replacing scattered routing with the module.

---

### CO-7: `PackageCairoSource` mixin (Theme D, minor)

**Items:** #121, #123, #125, #157, #159 ward renderers.

**Abstraction:** Mixin with `apply_package_grammar(cr)` + `assert_refuses_anti_patterns()` + `map_palette_role(role)`.

**Savings:** ~150 LOC across 5 ward renderers.

**Cost:** Small. Land as part of HOMAGE Phase 11c discipline.

---

## 5. Tensions / Contradictions

### T-1: #156 role derivation vs #155 anti-personification (low tension, resolvable)

**Nature:** #156 demands per-cadence function catalogs authored from practitioner literature ("host notices the room energy" — tempting personification). #155's linter forbids inner-life framing.

**Resolution:** #155 Stage 6 explicitly gates #126 text repo on the linter; extend to #156 templates. Author templates with architectural-fact framing ("livestream-host monitors audience-engagement rate") rather than experiential ("host feels the room"). The allow-list carve-out for "SEEKING-stance translation commentary" (linter §2.2) already handles the common case.

**Second-pass check:** Does #156 Phase A literature survey drift into personification language? Verify when Phase A ships.

---

### T-2: #132 sidechat "narrative silent by default" vs "operator opt-in to let it inform public narrative"

**Nature:** Two operator intents pull opposite ways — privacy of side-channel vs wanting Hapax to learn from private context.

**Resolution:** Already resolved in operator calls (2026-04-18): default silent, explicit opt-in flag. spec-stub §2 codifies.

**Second-pass check:** Is there an audit trail when operator flips the flag? If Hapax inferred from side-chat and then spoke publicly, is the provenance traceable? Likely needs a Prometheus counter or chronicle entry.

---

### T-3: #129 facial obscure "per-camera at capture" vs #150 vision routing "reads raw camera JPEGs"

**Nature:** #129 §3.1 says "obscuring runs on each per-camera source *before* the JPEG hits `/dev/shm`" — safety floor covers downstream tees. But vision classifiers in `perception-state.json` writer consume raw (un-obscured) frames internally for detection, and some detectors (SCRFD, emotion) operate on face crops. If obscure runs before vision, SCRFD has nothing to detect; if after, the director LLM call leaks.

**Resolution:** Likely a two-lane split — detection pipeline consumes un-obscured frames *in-process* (never written to `/dev/shm`), broadcast tees consume obscured frames. #129 §3.1 hints at this (per-camera at capture) but doesn't explicitly separate the two lanes.

**Second-pass check:** Verify `_perception_state_writer.py` doesn't serialize raw crops to disk. Confirm the director multimodal LLM calls consume the obscured `/dev/shm/*.jpg`, not an upstream un-obscured source.

---

### T-4: #124 "Reverie never recedes" vs #122 DEGRADED-STREAM "all wards recede"

**Nature:** DEGRADED says "all other wards transition to `absent`" during rebuild. Reverie is exempt from HOMAGE FSM entirely (#124 pattern (b)). What happens to Reverie during rebuild?

**Resolution:** #122 §3.2 is ambiguous. Reverie is not a ward (per #124); it's substrate. DEGRADED should override the final compositor output (single centered text ward over a fade-to-safe background), but whether Reverie's wgpu blit continues under the fade is undefined. Likely correct: Reverie keeps rendering, DEGRADED overlay occludes it.

**Second-pass check:** DEGRADED implementation must coordinate with Reverie — either alpha over or explicit suspend. Clarify when #124 lands, before #122.

---

### T-5: #142 "vinyl_playback_rate" semantics vs #127 "vinyl_playing" gate

**Nature:** #127 derives `vinyl_playing` from MIDI transport state. #142 publishes `vinyl_playback_rate: float` from operator-set preset. These are orthogonal — deck could be "playing" at any rate, or "stopped" at rate 1.0.

**Resolution:** splattribution-design §5 integrates by ANDing: `vinyl_playing &= 0.85 ≤ rate ≤ 1.15`. Rate-bounds gate ensures hand-braked / slip-cued deck isn't misattributed. This is correct but imposes coupling — #127 reads #142's file-bus output.

**Second-pass check:** If #127 ships before #142, the rate-bounds gate is missing and SPLATTRIBUTION degrades open (current behavior). If #142 rate bounds are too tight, normal 33⅓±10% pitch fluctuation falsely fails gate. Tune threshold band during #142 PR A.

---

### T-6: #146 "chat-contribution drives pole" vs #147 "#147 T5 rule is credit-farming surface"

**Nature:** #147 rubric imported into #146, but #147 research §integration notes that "current T5 rule (any research keyword bumps tier) is a credit-farming surface." If #146 v1 uses T5 as-is, viewers farm by spamming research vocabulary.

**Resolution:** #146 spec §4 notes "Don't block v1 on this. Qualifier v2 should require structural linkage to active research condition." So v1 ships with known-gameable T5 rule; v2 tightens.

**Second-pass check:** Monitor T5 classification distribution during first 2 hours of stream with #146 active. If viewers rapidly farm, v2 lands sooner.

---

### T-7: Schema docstring contradiction (#158 resolved but check other schemas)

**Background:** #158 found `DirectorIntent` schema docstring said "Zero impingements means the director chose to reinforce the prior state" — directly contradicting operator directive. Fixed with `min_length=1`.

**Concern:** Same pattern may exist elsewhere. Schemas authored when "do nothing" was valid, never updated when directive changed.

**Second-pass check:** Grep `shared/*.py` + `agents/**/*_intent.py` for docstrings endorsing empty-list semantics. Flag any schema where empty list is "legal silence."

---

## 6. Critical Path

Ordered by downstream unlock count + fix-live-regression + governance weight:

### CP-1: #129 facial obscuring (HIGHEST — live privacy leak)

- Live leak today: `content_injector` → Reverie → `pip-ur` has no obscure stage.
- Touches every egress path; delay risks broadcast incident.
- Dependencies: none.
- Unlocks: safe further compositor work; unblocks #122, #124 FSM decisions without privacy overhead.
- **Ship week 1.**

### CP-2: #155 anti-personification linter (warn-only) + Stage 2 refactors

- Two live governance violations (`conversational_policy._OPERATOR_STYLE`, `conversation_pipeline` LOCAL prompts).
- Warn-only mode surfaces them without blocking.
- Stage 2 refactors clean them up.
- Unlocks: #126 Pango text repo, #156 role template lint discipline.
- Dependencies: none for warn-only; refactor reviews for Stage 2.
- **Ship weeks 1–2.**

### CP-3: #134 audio pathways audit + AEC

- Fixes live phantom-VAD loop today (YouTube crossfeed → ducking oscillation).
- Corrects stale channel docs (FL/FR swap) — blocks #149 sequencing.
- Unlocks: #133 Rode, #132 sidechat mic, #145 24c ducking reverse direction, #149 reactivity contract.
- Dependencies: none.
- **Ship week 2.**

### CP-4: Control-surface bundle (#140 PR A + PR B + #141 + #142 PR A)

- #142 PR A fixes ACTIVE BUG (already landed per active-work-index: `shared/vinyl_rate.py` + album-identifier fix).
- #140 + #141 unblock #142 PR C, #143 PR B, #145 control surfaces.
- Dependencies: #142 PR A landed; Stream Deck hardware already plugged.
- **Ship week 2.**

### CP-5: #135 camera naming + #150 Phase 1 scene→family

- Unblocks #136 follow-mode, #121 HARDM cells 16–239.
- #150 Phase 1 reduces director no-op pressure (#158 mechanical fix landed, but #150 addresses root cause).
- Dependencies: #135 before #150 Phase 1.
- Closes "hero is empty room" bug (one-line `per_camera_person_count` gate).
- **Ship weeks 2–3.**

### CP-6: #148 sync fix (if not landed) + #149 Phase A extract

- #148 landed per active-work-index ("snapshot-before-decay" in `AudioCapture.get_signals`).
- #149 Phase A is refactor without behavior change — extract `MelFFTReactivitySource`.
- Unlocks: #149 Phase B (desk as second reactive source), closes Sprint 3 F2 dead-alias debt.
- Dependencies: #148 landed + #134 channel-doc correction.
- **Ship week 3.**

### CP-7: HOMAGE Phase 6 + #124 marker trait + #125 migration + #121 HARDM

- Phase 6 is HOMAGE epic's next-up (ward↔shader coupling).
- #124 marker trait unblocks Phase 11c.
- #125 and #121 are Phase 11c-adjacent migrations.
- HARDM needs Phase 6 (custom[4] read) + #150 Phase 1 (scene signal content).
- Dependencies: #129 first (compositor safety), #150 Phase 1.
- **Ship weeks 3–4.**

---

## 7. Re-Banding Recommendations

### Promote

- **#155 anti-personification linter (warn-only)** — was MEDIUM in dossier priority, operator flagged "tender and fragile"; 2 live violations; blocks #126. **→ HIGH.**
- **#134 audio pathways audit** — was dossier row 2; phantom-VAD is a live production bug affecting stream quality daily; unblocks 4 other items. **→ HIGH+.**
- **#150 Phase 1 (scene→family + person-count hero-gate)** — was MEDIUM in active-work-index; one-line fix kills "hero is empty room" bug flagged in viewer-experience audit; unblocks #121 HARDM cells 16–239. **→ HIGH.**

### Demote

- **#131 SoundCloud integration** — dossier already LOW; credential issuance is external + operator-action; good fit for "when it lands it lands." **Confirm LOW.**
- **#128 preset variety expansion** — pairs with #157 but is not urgent; #157 creates the tag pool, #128 populates it. Can wait until after Critical Path items. **→ MEDIUM-LOW.**
- **#125 token pole HOMAGE migration** — was LOW in dossier priority; correctly LOW; pairs with #146 (CO-3), not time-sensitive. **Confirm LOW.**

### Defer

- **#156 role derivation methodology** — was MEDIUM in dossier; requires Phase A literature survey + Phase B Hapax adjustment before any runtime impact. Not a gate on anything shipping. **Defer to after Critical Path; worked example first, schema extension later.**
- **#151 heterogeneous audit policy** — dossier already notes "dormant"; no Gemini session active; Claude-only steady state. Land the doc + advisory hook when convenient; no urgency. **Defer.**

### Keep as-is

- **#129 facial obscuring** — already HIGHEST; correct.
- **#158 director no-op** — FIXED, shipped in PR #1056. Not a re-banding question.
- **#142** — PR A shipped; PR B + C follow naturally.

---

## 8. Gaps / Absences

### G-1: No spec for the "AttributionSource" abstraction itself

**Surfaced by:** Theme F consolidation. #144 spec §2.4 names it but treats it as implementation detail of #144 PR.

**Gap:** If #127, #146, #159 each ship before #144 sees production, they'll each author ad-hoc attribution paths. No spec owns the protocol.

**Recommendation:** Either extend #144 spec with an explicit §2.4a protocol-design section OR write a tiny `attribution-backflow-protocol-design.md` stub (< 50 lines). The operator flagged "powerful reusable" — that's the signal to make the abstraction first-class.

---

### G-2: No audit trail for #132 sidechat → public narrative opt-in

**Surfaced by:** Tension T-2 + consent/privacy theme.

**Gap:** When operator flips "consider side-chat as context" flag, there's no audit mechanism tracking which public narratives were informed by private sidechat. Retroactively, operator cannot answer "did Hapax speak about something I only discussed privately?"

**Recommendation:** Second-pass question. Possibly a Prometheus counter + chronicle entry ("narrative turn N influenced by sidechat turn M"). Non-trivial; may warrant its own spec.

---

### G-3: No unified fallback mode coordination doc

**Surfaced by:** Tension T-4 + Theme H (substrate preservation).

**Gap:** #122 DEGRADED, #124 Reverie-exempt, #132 sidechat-private all define "exemption from default dynamic" with different mechanisms. No doc explains the precedence order when multiple exemptions collide (e.g., rebuild fires during active sidechat + operator-present vision routing).

**Recommendation:** Low-priority for first-pass; flag for second-pass after Phase 12 when the full HOMAGE FSM is stable and the collisions can be tested.

---

### G-4: `scripts/hapax-ctl` library not explicitly extracted

**Surfaced by:** CO-2 (control-surface bundle) + CO-1 (consent primitives).

**Gap:** `hapax-ctl` is scripted in the bundle spec §3.2 (KDEConnect relay client) and implicitly duplicated in Stream Deck adapter (#140). A `hapax_ctl` Python library isn't carved out.

**Recommendation:** During #140 PR A, extract the dispatch path into `shared/hapax_ctl/client.py` from the start, not as follow-up. Saves one refactor.

---

### G-5: No spec for "operator-override semantics" on file-bus

**Surfaced by:** Theme C (rate/cadence as first-class data).

**Gap:** `/dev/shm/hapax-compositor/*.txt` is used as a file-bus for many signals (vinyl-playback-rate, album-cadence, degraded flag, attention-bid dismissal). No spec governs the conventions:
- Who owns write rights?
- Is `touch` by operator a legitimate override signal?
- What's the staleness cutoff?
- Atomic tmp+rename or direct write?

**Recommendation:** Write a short `file-bus-conventions.md` during the control-surface-bundle implementation. Cite in all specs that touch the bus.

---

### G-6: Missing contradiction-audit tool for schema docstrings

**Surfaced by:** Tension T-7 (follow-up to #158).

**Gap:** #158 surfaced that `DirectorIntent` schema docstring contradicted operator directive. No tool exists to audit pydantic schema docstrings against stated axioms.

**Recommendation:** Low-priority, but noteworthy. Could be a superpowers:axiom-check extension.

---

### G-7: No spec for "when is a scene label operator-curated vs model-proposed?"

**Surfaced by:** #135 camera naming vs #150 vision integration.

**Gap:** #135 replaces hardcoded `_SCENE_LABELS` list with operator-curated YAML. But SigLIP-2 is zero-shot; if the operator's label doesn't match what the camera sees, zero-shot returns low confidence. No spec governs fallback: does the model propose new labels? Does the operator curate in reaction to stream events? Is there a review cycle?

**Recommendation:** Second-pass question. For first pass, #135 ships as operator-authored-only; label curation workflow is its own item for a future cascade.

---

### G-8: No spec for Stream Deck + KDEConnect LED feedback / bidirectional state

**Surfaced by:** #140 §3.1 bullet "LED feedback and SIGHUP rescan deferred (follow-ups)."

**Gap:** Stream Deck keys with LED feedback would show live state (vinyl rate active, stream mode, degraded-stream flag). KDEConnect runcommand is one-shot, no state readback. The command registry emits events (per CLAUDE.md "every action... is a registered command with typed args and observable events") but control surfaces don't subscribe.

**Recommendation:** Follow-up spec after #140 PR B ships. Bidirectional state is not blocking; it's a polish layer.

---

## 9. Operator Decisions Still Needed

After 10 operator calls made 2026-04-18 (listed in active-work-index §2), the following cross-cutting decisions remain:

### OD-1: AttributionSource abstraction — lift to first-class protocol now or after #144 proves it?

**Context:** Theme F + G-1. Operator flagged "powerful reusable" at 2026-04-06. Cascade vindicates the flag. Decision: extract protocol in #144 PR (CO-5) or defer.

**Recommendation to operator:** Extract now. Protocol is small; deferral risks divergence across #127, #146, #159.

---

### OD-2: `shared/consent_discipline.py` — do primitives, or keep precedent per-item?

**Context:** Theme A + CO-1. Precedent pattern (`chat_reactor.py:254`) is inherited verbatim across 5+ items. Decision: extract, or trust each item to inherit correctly.

**Recommendation to operator:** Extract when the third consumer ships (after #123 or #146 PR 1). Premature extraction can also constrain.

---

### OD-3: #132 sidechat audit trail — Prometheus counter or chronicle entry, or neither?

**Context:** Tension T-2 + G-2. When operator flips opt-in flag, is there traceability?

**Recommendation to operator:** Minimum: Prometheus counter `sidechat_context_influenced_narrative_total`. Maximum: chronicle entry with structural-linkage (narrative turn N ← sidechat turn M). Ask operator at #132 implementation time.

---

### OD-4: #135 camera label curation workflow

**Context:** G-7. Operator-authored YAML is the input; what's the update cycle?

**Recommendation to operator:** Defer the workflow question; ship #135 with ops-manual-curate-only posture. Revisit when live scene-label-misses exceed threshold.

---

### OD-5: Ward precedence during fallback mode collisions

**Context:** Tension T-4, G-3. DEGRADED + active sidechat + vision routing are three simultaneous carve-outs.

**Recommendation to operator:** Defer to second-pass. Phase 12 will expose collisions.

---

### OD-6: #131 SoundCloud timing

**Context:** Re-banding — keep LOW, contingent on credential issuance.

**Recommendation to operator:** No decision needed now; ship #130 first, revisit when credentials arrive.

---

### OD-7: HOMAGE Phase 11c Reverie coordination with #122 DEGRADED

**Context:** Tension T-4. Does Reverie blit continue under DEGRADED overlay?

**Recommendation to operator:** Default to "yes, Reverie blits; DEGRADED is alpha-over." Confirm at #122 implementation (before Phase 11c) to avoid rework.

---

## 10. Second-Pass Triggers

The second-pass synergy analysis runs when any of these conditions fires:

### S-1: HOMAGE Epic Phase 12 shipped (primary trigger)

Phase 12 is the consent-safe variant + retirement + flag flip. After flag flip, the full HOMAGE surface is stable and second-pass can reason about the integrated shape rather than mid-flight. Both dossiers explicitly defer to this point.

### S-2: Operator adds >5 new research items or directives

Cascade is 35 items today. If operator surfaces another batch at similar magnitude, re-banding and dependency graph will drift; refresh before the new batch tries to land.

### S-3: Implementation surfaces unexpected cross-cutting blockers

Examples (any single one):
- `AttributionSource` protocol turns out to need session-bound auth (breaks CO-5 assumption)
- #129 SCRFD at 5 Hz is insufficient for the per-camera cadence (invalidates Theme E assumptions)
- #148 sync fix doesn't eliminate "own pulse" perception (suggests the issue is not purely cadence-driven)
- #155 linter discovers >10 additional live violations (scope blows up Theme G)

### S-4: Live regression count exceeds 2 simultaneous governance-critical issues

Today: #129 is a live leak, #155 has 2 violations, #158 was live but landed. If the count rises (new governance issue surfaces), pause feature work and re-run synergy pass on the regression cluster specifically.

### S-5: Three or more items in one theme ship, revealing the shape is different than predicted

Example: if #127, #146, and #159 all ship before #144, and their attribution-path implementations diverge, Theme F prediction was wrong; abstract the diff, not the pre-ship assumption.

### S-6: Any ship of #156 Phase A (first role general-case literature survey)

#156 is methodology-changing for all future role work. Its first concrete output (likely `livestream-host` general-case survey) will surface whether the template catches or misses personification drift — a Theme G check.

---

## Change Log

- **2026-04-18** — First-pass synergy analysis authored. 35 items classified into 8 themes, 7 consolidation opportunities, 7 tensions, 7 critical-path items, 8 gaps, 7 open operator decisions. Second-pass trigger conditions defined.

**Echo:** `docs/superpowers/research/2026-04-18-synergy-analysis-first-pass.md` (repo: `hapax-council--cascade-2026-04-18`)
