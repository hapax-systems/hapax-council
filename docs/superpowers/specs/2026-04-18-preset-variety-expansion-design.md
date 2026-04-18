# Preset + Composite Variety Expansion

**Date:** 2026-04-18
**Source:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § Rendering → #128
**Status:** Provisionally approved (operator policy 2026-04-18)
**Pairs with:** #157 non-destructive overlay (tag-pool consumer); #146 token-pole (mutation-as-reward).

---

## 1. Goal

Expand the livestream surface's expressive output **at the curation layer** by 3–5× without touching shaders. The shader layer already has headroom: 56 WGSL nodes, 4 content slots, Reverie's 8-pass permanent graph, arbitrary user-preset depth up to ~9 nodes. The bottleneck is human-curated preset authoring — ~30 `.json` files in `presets/`, each a single point in a large parametric space that the current director only traverses as discrete jumps.

Success shape: the stream never looks like it is cycling a 30-item playlist. Same family stance recruited twice in 10 minutes produces visibly different surfaces.

## 2. Current Constraint

- **Corpus:** 30 presets in `presets/` (counted 2026-04-18). Of these, 5 are family-fallback neutrals, the rest are aesthetic singletons.
- **Family taxonomy:** `agents/studio_compositor/preset_family_selector.py::FAMILY_PRESETS` — 5 families (`audio-reactive`, `calm-textural`, `glitch-dense`, `warm-minimal`, `neutral-ambient`). Each family has 3–6 presets. `pick_from_family()` avoids back-to-back repeats but otherwise picks uniformly within the narrow list.
- **Director binding:** Director recruits `fx.family.<family>` capability → consumer calls `pick_from_family()` → one preset name → loader instantiates the JSON verbatim. No mutation layer.
- **Content slots:** `content_slot_0..3` declared on nodes with `requires_content_slots: true` (shader registry), but only `content_layer` and `sierpinski_content` read them. Three of four slots are structurally cold.
- **Temporal modulation:** Present in shader params (e.g. breath rate, drift amplitude) but not exposed to the director. Presets are evaluated as static parameter bundles.

Net: the stance → preset map is **deterministic modulo last-pick memory**. Family entropy is bounded above by `log2(family_size) ≈ 2.5 bits`.

## 3. Phase 1 — Parametric Mutation (no new shaders)

Apply bounded jitter to each preset's numeric parameters at recruitment time.

**Mechanism:**
- New module `agents/studio_compositor/preset_mutator.py` exposes `mutate(preset_dict, variance=0.15, seed=None) -> dict`.
- Walks `passes[].params`; for every numeric param with a declared range in the shader registry's `ParamDef`, samples `param * (1 + N(0, variance))`, clipped to `[min, max]`.
- Non-numeric params (enum strings, slot bindings) pass through untouched.
- Temporal params (breath.rate, drift.phase_seed) get a separate, wider variance (25%) to produce perceptually distinct re-draws.
- Caller wraps `pick_from_family()`:
  ```
  preset_name = pick_from_family(family)
  raw = load_preset(preset_name)
  mutated = mutate(raw, variance=0.15, seed=stance_tick)
  write_graph_mutation(mutated)
  ```

**Budget:** Adds one dict walk + RNG sampling per preset swap (~ms). No GPU or registry changes.

**Expected variety gain:** each base preset → effectively N distinct renditions per session (operator-unobservable that they share a parent). Raises family entropy from `log2(family_size)` toward `log2(family_size) + log2(N)` where N is the perceptually-distinguishable mutation count per base (~4–8 empirically).

## 4. Phase 2 — Temporal-Modulation Knobs

Expose time-varying modulation of preset parameters as first-class director intent.

**Mechanism:**
- Extend `CompositionalImpingement` (or the family capability's recruitment payload) with optional `temporal_modulation: {rate, depth, shape}`:
  - `rate` — Hz, 0.05–2.0. How fast the modulation oscillates.
  - `depth` — 0.0–1.0. Multiplier on jitter amplitude.
  - `shape` — enum: `sine | triangle | sample_hold | noise`.
- `preset_mutator.py` grows a `temporal_wrap()` that emits a time-varying param override stream into `uniforms.json` per-frame, keyed `{node_id}.{param}`.
- Director maps stance dimensions onto knobs (example binding): `tension → rate`, `intensity → depth`, stance category → `shape`.
- Operator-facing default: `rate=0.2, depth=0.3, shape=sine` when not specified.

**Dependencies:** Phase 1 mutator infrastructure; the existing per-node `params_buffer` bridge (council CLAUDE.md § Reverie Vocabulary Integrity path #2 — already live).

**Variety gain:** parametric mutation becomes time-evolving instead of frozen-per-swap; same preset visibly breathes differently under different stances.

## 5. Phase 3 — Multi-Family Stance Fan-Out

A single stance maps to N family-indexed presets composited simultaneously, not 1.

**Mechanism:**
- Extend `FAMILY_PRESETS` schema so a stance can recruit a **family tuple** `(primary, secondary, tertiary?)` with weights `(w_p, w_s, w_t)`, `sum ≤ 1`.
- `content_slot_1..3` (currently cold) become the destination for secondary/tertiary family picks. Primary still drives the main chain.
- Loader pseudocode:
  ```
  primary   = pick_from_family(primary_family)
  secondary = pick_from_family(secondary_family, available=slot_compatible_presets())
  # slot 1 ← secondary preset's dominant output texture
  # slot 2..3 reserved for #157 non-destructive overlay pool
  ```
- Requires marking a subset of presets as "slot-embeddable" (single-output, no feedback dependency) — add `"slot_embeddable": true` to preset JSON; default false for safety.

**Dependencies:** Phases 1–2 stable. Pairs with #157 (non-destructive overlay) — #157 populates slots 2–3 with ambient tag content; Phase 3 here claims slot 1 for cross-family composite.

**Variety gain:** `family_count × family_size` combinatorial surface for any given stance (≈ 150 base combinations at current corpus size), multiplied by Phase 1 mutation.

## 6. Pairing With #157 (Non-Destructive Overlay)

#157's `non_destructive_overlay` tag pool is the natural consumer of the idle content slots this spec opens up. Phase 3 claims slot 1 for cross-family compositing; slots 2–3 remain free for #157's ambient-text / token-pole / album-art overlays. Slot accounting goes in a shared registry (`shared/content_slot_registry.py`, new) to prevent Phase 3 and #157 from stomping on each other.

## 7. File-Level Plan

| Phase | Files | Nature |
|---|---|---|
| 1 | `agents/studio_compositor/preset_mutator.py` (new) | Pure function, unit-testable |
| 1 | `agents/studio_compositor/preset_family_selector.py` | Add `mutate=True` kwarg to `pick_from_family` |
| 1 | `tests/studio_compositor/test_preset_mutator.py` (new) | Property tests: bounds, determinism under seed |
| 2 | `shared/compositional_affordances.py` | Extend `fx.family.*` recruitment payload with `temporal_modulation` |
| 2 | `agents/studio_compositor/preset_mutator.py` | Add `temporal_wrap` producing per-frame overrides |
| 2 | `agents/effect_graph/modulator.py` | Consume temporal overrides into `uniforms.json` |
| 2 | `tests/studio_compositor/test_temporal_modulation.py` (new) | Shape correctness per enum |
| 3 | `agents/studio_compositor/preset_family_selector.py` | Family-tuple schema + weighted pick |
| 3 | `presets/*.json` | Add `slot_embeddable` flag to safe subset |
| 3 | `shared/content_slot_registry.py` (new) | Slot-owner registry; shared with #157 |
| 3 | `agents/studio_compositor/compositor.py` | Wire secondary/tertiary preset into slot 1 |

## 8. Test Strategy

- **Unit:** `test_preset_mutator.py` — bounds, clipping, determinism under seed, non-numeric param passthrough.
- **Variety entropy metric:** new script `scripts/measure_preset_variety.py` — runs director-sim for N stance ticks, hashes the resulting mutated-preset parameter vectors, reports Shannon entropy of the hash distribution. Run before + after each phase.
- **Director-sim family-entropy comparison:** existing director-sim harness (see `tests/studio_compositor/`) gets a `--compare-baseline` flag; emits per-family entropy delta table. Phase 1 target: +1.5 bits family-wide. Phase 3 target: +3.0 bits.
- **Stream smoke:** 30-minute livestream in `research` mode post-deploy; operator confirms no visibly identical renditions of the same base preset.
- **Budget regression:** `BudgetTracker` must not show per-frame cost delta > 5% attributable to mutator.

## 9. Open Questions

1. **Mutation cache:** Should mutated presets be memoized (stance, tick) → dict, or recomputed each swap? Memo saves ~ms but loses time-varying gain; defer until Phase 2 lands.
2. **Aesthetic guardrails:** A 15% variance on all numeric params may produce invalid configurations (e.g. feedback_preset with feedback amount near 1.0 + jitter → blowup). Registry's declared `ParamDef.max` should hard-clip, but preset authors may have tuned values below numerical stability ceilings. Add a `safe_range` override per preset? Punt to Phase 1 post-deploy observation.
3. **Director intent schema:** does `temporal_modulation` belong on the recruitment capability payload or on a separate modulation-intent channel? Latter decouples recruitment from modulation but adds a second message path. Defer until Phase 2 design pass.
4. **Phase 3 fan-out ratio:** is 3-family fan-out a single hop too far — does it perceptually muddy the stance? Gate Phase 3 on Phase 2 operator feedback.

## 10. Related Specs

- **#157 non-destructive overlay** (pending spec stub) — slot-pool consumer; coordinates via `shared/content_slot_registry.py`.
- **#146 token pole** — mutation as spendable reward artifact; operator-earned mutations could become rarer / wider-variance as token-pole incentive.
- **`docs/superpowers/specs/2026-03-25-effect-node-graph-design.md`** — shader registry + ParamDef ranges that gate Phase 1 clipping.
- **`docs/superpowers/specs/2026-03-26-effect-graph-phase2-design.md`** — per-node params_buffer bridge that Phase 2 rides on.
- **`docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md`** — surface-kind contracts Phase 3 must respect when populating content slots.
