---
date: 2026-04-20
author: cascade (Claude Opus 4.7, 1M context)
audience: alpha (execution) + operator
register: scientific, neutral
status: research + retirement plan — no code
branch: hotfix/fallback-layout-assignment
operator-directive-load-bearing: |
  "effect shuffle mode should be totally removed it's a crutch"
  (2026-04-20). Architectural thesis: effect-shuffle is the same
  anti-pattern class as the F1/F2 gates retired tonight — a random
  release-valve substituting for grounded recruitment. Shuffle masks
  the upstream collapse of the recruitment surface documented in
  `2026-04-19-preset-variety-design.md`.
related:
  - docs/research/2026-04-19-preset-variety-design.md (variety root-cause analysis, task #166)
  - docs/superpowers/plans/2026-04-20-preset-variety-plan.md (task #166 phases)
  - docs/research/2026-04-19-expert-system-blinding-audit.md (A6/A7 retirement precedent)
  - docs/research/2026-04-20-nebulous-scrim-design.md (scrim-texture-family reorganization, task #174)
  - agents/studio_compositor/random_mode.py (primary shuffle site)
  - agents/studio_compositor/preset_family_selector.py (family-biased pick, already partially replacing shuffle)
  - agents/studio_compositor/compositional_consumer.py (recent-recruitment.json writer)
  - shared/director_observability.py (hapax_random_mode_pick_total metric)
  - hapax-logos/src/components/graph/SequenceBar.tsx (UI shuffle button + generateRandomSequence)
memories:
  - feedback_no_expert_system_rules (load-bearing)
  - project_programmes_enable_grounding (load-bearing)
---

# Retire Effect Shuffle Mode — Research + Retirement Plan

## §0. Thesis and scope

Effect shuffle is a **crutch**. When the pipeline cannot confidently choose
a preset, shuffle release-valves the indecision with random noise. That
randomness creates the *appearance* of variety, which masks the
underlying collapse of the recruitment surface documented in
`docs/research/2026-04-19-preset-variety-design.md` §1: the director's
narrative is monoculture-locked on `calm-textural`, the Thompson
posterior is calcified around whichever family was recently active, and
the affordance catalog has structural sparseness. Shuffle hides all of
this by periodically re-rolling the dice.

This is the same anti-pattern class as the F1/F2 gates the operator
retired on 2026-04-19:

- **F1 (`camera.hero` variety gate)** — a hardcoded anti-repeat rule on
  camera dispatches. Refused legitimate re-selections; invisible to
  grounded recruitment.
- **F2 (`narrative-too-similar` / `_emit_micromove_fallback`)** — a
  Jaccard/shingle similarity gate that discarded LLM output and cycled
  through a hardcoded 7-tuple micromove table.
- **A7 (per blinding audit §3)** — the pre-existing call-out that
  `random_mode` is an expert-system rule of its own, substituting for
  recruitment rather than emerging from it.

Shuffle shares the architectural signature: a substitute output
mechanism that fires when the grounded mechanism produced nothing the
dispatcher considered usable. The fix is not to tune the shuffle; the
fix is to repair the grounded mechanism so shuffle has nothing to
substitute for.

Load-bearing memory constraints:

1. `feedback_no_expert_system_rules` — "behavior emerges from impingement
   → recruitment → role → persona; hardcoded cadence/threshold gates
   are bugs." Shuffle is such a gate: "when no family recruited for
   `_PRESET_BIAS_COOLDOWN_S` seconds, pick a random preset from a
   hardcoded neutral-ambient fallback, else uniform random across the
   whole corpus."
2. `project_programmes_enable_grounding` — "programmes expand the
   affordance surface; they don't replace grounded decisions with
   random ones." Shuffle is the literal anti-case: it replaces the
   grounded decision with an RNG roll.

Scope. This plan is research + sequencing. It authors no code. It
specifies telemetry, removal order, risk mitigations, operator-control
migration, and acceptance metrics. It depends on task #166 (preset
variety) landing first; shuffle cannot come out before the grounded
replacements are in, or variety collapses further.

## §1. Inventory — every effect-shuffle site in the stack

Seven shuffle / random-selection call sites across the compositor and
the Logos UI. Listed with trigger, mechanism, observability, and
coupling. Recent-activity counts are zero for all Python-side sites
(journal grep over the last 24h returns no `random_mode pick` lines)
because the `random_mode.run()` loop is not currently running as a
separate process — but the file exists, the control surface exists,
and the UI shuffle button is live. The inventory documents what MUST
be removed, independent of current in-flight activity.

| Site | File:lines | Trigger | Mechanism | Fires/24h | Coupled to |
|------|-----------|---------|-----------|-----------|------------|
| S1 | `agents/studio_compositor/random_mode.py:107-177` (`run()` loop) | `CONTROL_FILE` not "off" + `interval` sleep expired (default 30s) | 1) if `preset.bias` recruited within 20s → `pick_from_family(family)`; 2) else → `pick_from_family("neutral-ambient")`; 3) else fallback → `random.choice(choices)` with `chosen_via="uniform-fallback"` | 0 (loop idle) | S2, S4 |
| S2 | `agents/studio_compositor/random_mode.py:148-154` (`uniform-fallback` branch) | S1 path 1 + 2 both returned None (family map empty, or all filtered) | `random.choice([p for p in presets if p != last])` across the entire 27-preset corpus | 0 (S1 idle) | S1 |
| S3 | `agents/studio_compositor/preset_family_selector.py:199` (`pick_from_family`) | Called by S1 or by `pick_and_load_mutated` | `random.choice(non_repeat) if non_repeat else random.choice(candidates)` within the 6-preset family | 0 (S1 idle) | S1, S5 |
| S4 | `agents/studio_compositor/preset_family_selector.py:308` (`pick_with_scene_bias`) | Scene classifier provides a scene, called by S1 extension | `rng.choices(pool, weights=..., k=1)[0]` — still random within weighted pool | 0 (not wired yet) | S3 |
| S5 | `agents/studio_compositor/preset_family_selector.py:313-369` (`pick_and_load_mutated`) | Director's deterministic path that wants "a fresh preset from family X mutated" | Calls S3, then `mutate_preset(graph, rng=Random(seed), variance=0.15)` — the mutation adds parametric jitter on top of the random pick | 0 (director path partial) | S3 |
| S6 | `agents/studio_compositor/director_loop.py:876-896` (`_reload_slot_from_playlist`) | YouTube slot reload event | `random.choice(playlist)` — picks a playlist entry uniformly | Sporadic, slot-bound | Disjoint (video playlist, not preset) |
| S7 | `hapax-logos/src/components/graph/SequenceBar.tsx:140-195` (`generateRandomSequence`) + `:334-347` (`handleShuffle`) | User clicks the `shuffle` button in the Logos UI sequence bar | Build 8-12 chains of 2-3 randomly-selected presets with `.sort(() => Math.random() - 0.5)`, optionally auto-looping with `shuffleModeRef.current = true` re-randomization on loop | Manual, operator-bound | Disjoint (UI-only, bypasses affordance pipeline) |

Trigger condition notes:

- **S1** is the primary grounded-but-still-shuffling site. The 2026-04-18
  rewrite removed the uniform-random across-corpus default, replacing
  it with `pick_from_family("neutral-ambient")` — but that fallback is
  itself a hardcoded expert-system substitution per blinding-audit A7.
- **S2** fires only when `FAMILY_PRESETS` is empty or every family
  member is filtered out. In practice, this is dead code; the branch
  and its `chosen_via="uniform-fallback"` metric exist specifically to
  alert if it ever fires non-zero.
- **S3** is not shuffle in the shuffle-mode sense — it is the
  within-family pick, using `random.choice` because family members are
  by construction equivalent under the current semantic model. #166
  Phases 3 and 6 replace this `random.choice` with a scored pick.
- **S4** is unwired; when wired, its weights come from `SCENE_TAG_BIAS`
  — a hardcoded expert-system table. Shuffle AND latent rule.
- **S5** wraps S3 with parametric mutation (seeded jitter). Mutation is
  a tunable dial, not a blanket replacement.
- **S6** is a video-playlist shuffle in the director's slot-reload path.
  Out of scope for this retirement pending §8 Q1, but listed for
  completeness.
- **S7** is the UI-side shuffle button — the only site where shuffle is
  a user gesture rather than an automatic fallback. It bypasses the
  affordance pipeline entirely, writing direct to the mutation bus.

S1 reads `recent-recruitment.json`, populated by
`compositional_consumer.dispatch_preset_bias` (`compositional_consumer.py:232-245`).
The writer is correct; retirement removes the READER and its fallback.

## §2. Why shuffle exists — historical + architectural root

`git log --follow` on `random_mode.py` surfaces a trajectory from pure
chaos toward grounded recruitment:

- **2026-04-05** (`a042190f6`, `2c92cfd2a`) — 50-LOC origin. Pure
  uniform-random across the corpus, 30s interval, `CONTROL_FILE`
  toggle, 12-step brightness fade. No design doc, no precondition.
- **2026-04-17** (`14147f1eb`) — first architectural move: read
  `recent-recruitment.json`, defer to recruited family when active,
  uniform-random only when no recruitment was recent.
- **2026-04-18** (`019e01849`, `ed8737d89`) — introduces `FAMILY_PRESETS`,
  replaces uniform-random fallback with `pick_from_family("neutral-ambient")`,
  demotes `random.choice(choices)` to a `chosen_via="uniform-fallback"`
  terminal branch, adds `hapax_random_mode_pick_total` metric.

The trajectory is the right direction — each commit tightens toward
grounded recruitment. But its terminus is still a rule-based dispatcher:
"if recruited, use the family; else use `neutral-ambient`; else uniform."
Each clause is correct per its local invariant; the composition is an
expert-system cascade. The operator's 2026-04-20 directive closes the
trajectory by retiring all three clauses.

**Architectural root causes shuffle is papering over**, each matched to
the task #166 phase that actually fixes it:

| Root cause | What shuffle hides | Task #166 phase that fixes it |
|------------|--------------------|-------------------------------|
| Narrative monoculture — the director LLM writes `calm-textural` on every tick (12+ consecutive samples over 4h per preset-variety §1) | Without shuffle, the pipeline would rigidly hold one family. Shuffle fakes variety by rerolling. | **Phase 2** — unblock narrative prompt template bias |
| Thompson posterior calcification — active families accrue base-level advantage with no time-decay; dormant families stay dormant | Recently-dominant family wins forever; shuffle provides the only escape path | **Phase 4** — Thompson posterior decay on non-recruitment |
| Affordance-catalog sparseness — some families may have fewer Qdrant-registered members than `FAMILY_PRESETS` membership suggests | Cosine retrieval returns same top-1 every tick; shuffle is the only width | **Phase 5** — affordance-catalog closure audit |
| No recency-aware scoring — pipeline has no signal for "we just applied this" | Same-family / same-preset runs accumulate with no pushback; shuffle is the only pushback | **Phase 3** — `recency_distance` as scoring input |
| No perceptual-distance signal — no impingement fires when last-N applications cluster | Pipeline cannot KNOW the stream is locked in a register; shuffle's randomness is the only externally-visible variety | **Phase 6** — `content.too-similar-recently` impingement |

Each shuffle site emerged as a local patch for one of these root causes.
S1 papered-over narrative monoculture and Thompson calcification. S4
papered-over scene-variance. S5 papered-over preset monotony within
an active family. S7 papered-over the entire pipeline's perceived
rigidity — the user wanted a manual escape hatch. Repairing the root
cause retires the patch.

## §3. Replacements — grounded mechanisms already designed

Task #166 (`docs/superpowers/plans/2026-04-20-preset-variety-plan.md`)
specifies the full architectural replacement. Cross-referencing
phase-by-phase:

1. **Recency-distance scoring** (#166 Phase 3 §3.1). Adds
   `_RecencyTracker` over a rolling N=10 capability embedding window,
   folds `W_RECENCY × (1 - max_cosine_sim)` into the scoring formula
   at weight 0.10. Renormalized weights: `0.45/0.18/0.09/0.18/0.10`.
   Replacement for: the "avoid back-to-back preset" non-repeat memory
   in `_LAST_PICK` (S3). After Phase 3, variety emerges from the score
   itself; the `_LAST_PICK` memo can be deleted.
2. **Thompson posterior decay** (#166 Phase 4). `ActivationState.decay_unused(gamma_unused=0.999)`
   pulls dormant `ts_alpha` / `ts_beta` toward Beta(2,1) on every
   `select()` call to non-recruited candidates. Replacement for: the
   "shuffle as escape valve" semantics of S1's `uniform-fallback` and
   `neutral-ambient` branches. After Phase 4, dormant capabilities
   re-enter the exploration frontier automatically.
3. **Affordance-catalog closure** (#166 Phase 5). Script audits every
   `preset.bias.<family>` capability in Qdrant vs `FAMILY_PRESETS` vs
   `presets/*.json`; remediates gaps. Replacement for: the silent
   shrinkage of the candidate set when families are under-registered
   (e.g., `thermal` fragment-compile failure silently shrinks
   `warm-minimal`). After Phase 5, shuffle has no structural excuse —
   the pool is full.
4. **Programme-owned palette ranges** (#166 Phase 8, gated on task #164).
   Per-programme `ProgrammeAesthetics.palette_bias` tilts the scoring
   field. Replacement for: the `neutral-ambient` hardcoded fallback.
   After Phase 8, "what family is the system currently biased toward?"
   is a PROGRAMME property, not a constant in `random_mode.py`.
5. **Perceptual-distance impingement** (#166 Phase 6). When last-10
   embeddings cluster at ≥0.85 cosine similarity, emit
   `content.too-similar-recently`; pipeline can recruit a registered
   `novelty.shift` capability. Replacement for: shuffle's "operator
   notices things are samey" feedback path. After Phase 6,
   anti-repetition is a PERCEPTION signal feeding the pipeline, not a
   RULE filtering the output.
6. **Narrative prompt unblock** (#166 Phase 2). Audits the director
   prompt for literal `calm-textural` defaults; removes any expert-
   system-rule smuggle at the prompt level. Replacement for: the
   upstream cause of shuffle's original motivation. After Phase 2,
   the family distribution at the top of the pipeline stops
   collapsing to a single token.

These five phases replace shuffle COMPLETELY. Shuffle was solving five
problems at once, poorly; each of these solves one problem, correctly.
The composition is not "shuffle replaced by another rule" — it is
"shuffle's five local symptoms each repaired at their causal layer."

## §4. Retirement order (sequencing)

Shuffle cannot be removed before the replacements are in. Removing S1
today would leave a 20-second recruitment window followed by indefinite
stasis — narrative monoculture then holds the single family for hours.
Variety collapses further, not less.

**Preconditions (blocking)** — must ship before retirement starts:

- [P-1] #166 Phase 2 — narrative prompt unblock. Narrative-family
  diversity ≥2 tokens in any 20-min window.
- [P-2] #166 Phase 3 — recency-distance scoring folded into
  `AffordancePipeline.select()`.
- [P-3] #166 Phase 4 — Thompson posterior decay on non-recruitment.
- [P-4] #166 Phase 5 — affordance-catalog closure; every family has
  ≥3 registered members.

Retirement phase R3 starts only after all four are live on `main` and
observable (Shannon entropy ≥1.0, no regression).

**Retirement phases**:

- **R1 — Instrument.** Add per-site label on
  `hapax_random_mode_pick_total` (or new
  `hapax_effect_shuffle_fires_total{site}`): S1-family,
  S1-fallback=neutral-ambient, S2-uniform-fallback, S3-within-family,
  S4-scene-bias, S5-mutated, S6-playlist, S7-ui-shuffle. Observational
  only; no behavior change.
- **R2 — Baseline.** 24h live window of fires/hour per site. Expected:
  S1-family + S3 dominant, S1-fallback nonzero during silence gaps,
  S2 zero, S4/S5/S6 sporadic, S7 operator-initiated.
- **R3 — Retire S2 (`uniform-fallback`).** Delete
  `random_mode.py:148-154`. Zero current activity; pure deletion. If
  `pick` is None after both `pick_from_family` paths, loop sleeps and
  retries.
- **R4 — Retire S1's `neutral-ambient` fallback.** Delete
  `random_mode.py:143-145`. When no family was recruited in the
  cooldown window, loop SKIPS this iteration — recruitment either
  fires or does not, absence is valid data. Highest-risk removal;
  watch post-deploy entropy.
- **R5 — Delete the `random_mode` loop.** Delete `random_mode.py`;
  migrate `MUTATION_FILE`, `PRESET_DIR`, `get_preset_names`,
  `load_preset_graph` to a new `agents/studio_compositor/preset_corpus.py`
  (pure I/O helpers, no loop). Delete `CONTROL_FILE`,
  `/dev/shm/hapax-compositor/random-mode.txt`,
  `hapax_random_mode_pick_total`, `emit_random_mode_pick`.
  `preset_family_selector.py` stays — still the correct within-family
  picker for the director's deterministic path.
- **R6 — Retire the UI shuffle (S7).** Replace `handleShuffle` with
  programme-switch dropdown routing through the Logos command
  registry → #166 Phase 8 programme layer. Delete
  `generateRandomSequence`, `shuffleModeRef`, `handleShuffle`, the
  shuffle button. Keep `saveSequence` / `loadSequence` — those are
  operator-authored sequences, not shuffle.
- **R7 — Scrim-family reorganisation** (§6, gated on task #174).
  `FAMILY_PRESETS` rewritten from
  `{audio-reactive, calm-textural, glitch-dense, warm-minimal,
  neutral-ambient}` to
  `{gauzy-quiet, moiré-crackle, warm-haze, dissolving, clarity-peak,
  rain-streak}`. Category-theoretic coda making shuffle's replacement
  conceptually natural.
- **R8 — CI regression pin.** Grep check blocks reintroduction:
  `rg '\brandom_mode\b|\bshuffle_mode\b|generateRandomSequence|handleShuffle'
  agents/ shared/ hapax-logos/src/ logos/` must return zero hits.
  Import check: `random_mode` not importable.

## §5. Risk table

| Phase | Risk | Mitigation |
|-------|------|------------|
| R3 | S2 firing under edge case (filtered-empty family map) | #166 Phase 5 preconditions guarantee catalog closure |
| R4 | Recruitment-less windows produce long stasis | Stasis IS information; accelerate #166 Phase 4 gamma or Phase 6 threshold, do NOT restore shuffle |
| R4 | #166 Phase 4 Thompson decay too slow to break monopoly | Feature flag `HAPAX_AFFORDANCE_THOMPSON_DECAY` tightens gamma at runtime |
| R4 | #166 Phase 6 perceptual-distance impingement not firing | Phase 9 re-measurement reports impingement count; tighten 0.85 threshold if zero |
| R5 | Downstream imports break | Migrate helpers to `preset_corpus.py` in same commit as deletion |
| R5 | Grafana alert on old metric going silent | Update dashboard: `hapax_effect_shuffle_fires_total == 0` is the SUCCESS signal |
| R6 | Operator muscle-memory on shuffle button | Programme-dropdown replacement lands in same release |
| R7 | Scrim relabel races retirement | Gate R7 on #174 completion; R5 ships with old labels intact |
| R8 | False-positive CI grep on doc mentions | Scope grep to `agents/**`, `shared/**`, `hapax-logos/src/**`, `logos/**`; exclude `docs/**` |

**Operator-visible regressions mid-retirement.** Between R4 and R5,
silence gaps hold a preset instead of cycling — correct, but may read
as static. The right response is to tune #166's decay/impingement, not
to restore shuffle. R3 and R4 are revertible commits; if #166 Phase 5
surfaces catalog gaps post-retirement, revert the single commit,
remediate, then re-retire.

**Success signals**:

- `hapax_effect_shuffle_fires_total{site="*"}` → 0 over any 1h window
  post-R5 (the loudest signal — shuffle literally cannot fire).
- `hapax_preset_family_histogram` Shannon entropy ≥1.5 over 60-min
  windows — variety emergent, not shuffled.
- `hapax_affordance_recency_distance_mean` ≥0.4 — typical applied
  preset is perceptually distant from recent 10.
- `content.too-similar-recently` impingement count >0 — pipeline is
  SEEING clustering and acting on it.

## §6. Coupling with task #174 (scrim reorganisation)

Task #174 (`docs/research/2026-04-20-nebulous-scrim-design.md`)
reorganises the preset taxonomy around a scrim-texture-family axis.
Six scrim-profile programmes each with a distinct scrim character
(§7 of the scrim design): Listening → `gauzy-quiet`, Hothouse →
`moiré-crackle`, Vinyl showcase → `warm-haze`, Wind-down →
`dissolving`, Research → `clarity-peak`, Interlude → `rain-streak`.

These scrim-texture-families REPLACE the current `{audio-reactive,
calm-textural, glitch-dense, warm-minimal, neutral-ambient}` map. The
shift is STRUCTURAL — arbitrary aesthetic labels disappear, each preset
declares its scrim-texture membership instead.

Under scrim, shuffle-across-labels becomes categorically nonsensical.
`{audio-reactive, calm-textural}` are interchangeable flavour tokens
with no semantic reason to choose between them other than operator
preference — shuffle substitutes randomness for that absent reason.
`{gauzy-quiet, moiré-crackle}` are semantically distinct — one is the
listening-programme fabric, the other the hothouse-programme fabric.
Switching is a PROGRAMME change; randomizing between them during a
Listening programme would visibly violate the programme's envelope.

This is the scrim's architectural gift: it makes shuffle's REPLACEMENT
natural. Programme biases scrim-texture-family; pipeline recruits
within the programme's favoured family; cross-programme rotation
provides 5-10× the variety shuffle faked.

Sequencing. R7 (relabel) happens AFTER #174 ships its scrim-texture
enumeration in `preset_family_selector.py`. R5 (delete `random_mode.py`)
can ship INDEPENDENTLY — S1 reads whatever family string is written to
`recent-recruitment.json`; the specific enum doesn't matter for
deletion. Cross-references: `2026-04-20-nebulous-scrim-design.md` §3
(technique vocabulary), §5 (scrim-as-substrate framing), §7 (programme
× scrim-texture mapping folded into `FAMILY_PRESETS` at R7).

## §7. Operator-control surfaces

Current shuffle-adjacent control surfaces the operator has:

1. **`/dev/shm/hapax-compositor/random-mode.txt`** — file-based
   on/off toggle for the S1 loop. Retired at R5 (whole file + its
   reader deleted).
2. **Logos UI `shuffle` button** (`SequenceBar.tsx:433-449`) — clicks
   generate a random sequence, set auto-looping, start playback.
   Retired at R6.
3. **Chat `shuffle` keyword** — not currently wired (the chat reactor
   keyword index is built from preset filenames; `shuffle` is not a
   preset). No retirement needed.
4. **Stream Deck bindings** — audited `agents/stream_deck/commands/`;
   the only command file is `vinyl.py`. No shuffle binding. No
   retirement needed.
5. **Keyboard shortcuts** (`hapax-logos/src/lib/keyboardAdapter.ts`) —
   `grep shuffle` returns no hits. No shuffle binding. No retirement
   needed.

Replacement surface for the UI: a `programme.switch` dropdown OR a
`programme.cycle` button that advances through the programme list. Both
dispatch through the Logos command registry
(`hapax-logos/src/lib/commandRegistry.ts`) to the programme layer (task
#164). The operator's muscle memory — "I want the visuals to feel
different right now" — is preserved, but the grounded mechanism is a
programme change, which is stronger than shuffle (it moves scrim-texture,
ward emphasis, cadence, AND colour register together) and grounded (it
expresses a decision about what the stream IS right now).

R6 implementation note: the existing `saveSequence` / `loadSequence`
infrastructure stays. Operator-authored sequences are creative
expressions, not shuffle. A saved sequence named "chill-listen-1" that
the operator plays intentionally is a programme-like gesture — it
differs from shuffle in that the operator decided its contents.

## §8. Open questions for operator

1. **S6 playlist shuffle** (`director_loop._reload_slot_from_playlist`).
   YouTube slot reload uses `random.choice(playlist)`. Same crutch, or
   a legitimate "playlist shuffle is semantic" gesture? Default
   answer: leave it pending explicit direction.
2. **Intentional chaos as capability.** Is shuffle-as-game ever
   wanted (end-of-stream playful moment, guest reveal, chat-requested
   chaos)? If YES, it becomes a registered affordance
   `expression.chaos.shuffle` with a Gibson-verb description that
   recruitment chooses when grounded — NOT a default fallback. If NO,
   S7 retires outright.
3. **UI muscle memory.** Does the operator click the `SequenceBar.tsx`
   shuffle button often? If yes, the R6 programme-dropdown ships as
   priority replacement. If rarely, R6 is a simple deletion.
4. **Shuffle as debug probe.** During the #166 phase-landing window,
   useful to keep a comparison shuffle temporarily? If yes, it lives
   in `scripts/` not production, retires at R5.

## §9. Integration sequencing (6 phases)

All phases commit to `hotfix/fallback-layout-assignment`. Each phase is
a single subagent dispatch.

**Phase 1 — Instrumentation + baseline (R1 + R2).** Rename
`hapax_random_mode_pick_total` → `hapax_effect_shuffle_fires_total`,
add `site` label (S1-family, S1-fallback, S2-uniform, S3, S4, S5, S6,
S7). Call-site updates across `random_mode.py`,
`preset_family_selector.py`, `director_loop.py`; a
`POST /api/studio/effects/shuffle-event` endpoint handles the S7 UI
event. Author `scripts/measure-shuffle-baseline.py`; commit baseline
JSON to `docs/research/shuffle-baseline-2026-04-20.json`. Size: S.

**Phase 2 — Precondition gate-check.** No code change; author
`scripts/gate-shuffle-retirement.py` validating #166 Phases 2/3/4/5
have landed on `main` and passed their Phase 9 gates: Shannon entropy
≥1.0 in last 60 min, no `calm-textural` in control flow,
`_RecencyTracker` + `ActivationState.decay_unused` present,
affordance-catalog audit report with zero <3-member families. Gate
PASS unblocks Phase 3. Size: S.

**Phase 3 — Retire S2.** Delete `random_mode.py:148-154` +
uniform-fallback test assertions. No operator-visible change. Size: S.

**Phase 4 — Retire S1 `neutral-ambient` fallback.** Delete
`random_mode.py:143-145`. When no family recruited, loop sleeps and
produces no mutation. Update `test_closed_loop_wiring.py`. Watch
`hapax_preset_family_histogram` entropy; if regression, investigate
#166 decay/impingement — do NOT restore shuffle. Size: S.

**Phase 5 — Delete `random_mode.py` + migrate helpers.** Three atomic
commits:
- 5a: Create `preset_corpus.py` with the I/O helpers; update
  `chat_reactor.py` import.
- 5b: Delete `random_mode.py`, `/dev/shm/hapax-compositor/random-mode.txt`,
  `emit_random_mode_pick`; update Prometheus dashboard.
- 5c: Delete S7 UI shuffle (`generateRandomSequence`, `shuffleModeRef`,
  `handleShuffle`, shuffle button). Replace with programme-dropdown if
  task #164 shipped; otherwise TODO comment.

Size: M.

**Phase 6 — Post-retirement observation + scrim relabel (R7).** 60-min
operator-read acceptance: entropy ≥1.5, `hapax_effect_shuffle_fires_total{site!="S6-playlist"} == 0`,
subjective "3 of 5 families without feeling random." R7 scrim-family
relabel as follow-up PR gated on task #174 landing. Size: S + M.

---

## §10. Critical-path summary

Critical path: #166 Phases 2/3/4/5 land and pass Phase 9 acceptance →
this plan's Phase 1 instruments sites and captures 24h baseline →
Phase 2 gate-checks the preconditions → Phases 3–5 delete shuffle in
three ordered steps → Phase 6 observes and integrates with #174 scrim
reorganisation.

Shuffle retires not because it is wrong (it is often pleasant) but
because in a system that claims to ground every expression in
perception, recruitment, role, and persona, a randomised fallback is a
category error — ungrounded by construction. The pipeline either has a
reason to change the preset, or it does not. Absence of reason is
information, not anxiety to release-valve.
