---
date: 2026-05-07
status: proposed acceptance matrix
source_pr: "https://github.com/ryanklee/hapax-council/pull/2395"
source_task: test-gaps-2395-merged
scope: suggested tests and fixtures only
---

# Bachelard Amendment 8 Miniature Test Matrix

This note converts the merged Bachelard Amendment 8 design spec into a
phase-2 acceptance matrix. It does not claim implementation completion. The
source spec explicitly marks Amendment 8 as design-only and leaves
implementation to the downstream `bachelard-amendment-8-miniature-impl`
cc-task.

## Evidence

- PR #2395, `docs(reverie): Bachelard Amendment 8 - Phenomenology of Miniature design spec`, merged on 2026-05-03T15:09:28Z at `96d367863608647b548fb52f70c0129971055709`.
- `docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md:3` says the artifact is "design - spec only; implementation a separate downstream cc-task."
- `docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md:70` through `:76` define the miniature factor as a derived visual-chain signal from stance, gaze dwell, low motion, and high local visual complexity.
- `docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md:80` through `:100` define the no-new-WGSL modulation topology, helper location, ordering, and `/dev/shm/hapax-stimmung/miniature.json` signal read.
- `docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md:106` through `:130` define the Sierpinski, token-pole, and content-placement interactions.
- `docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md:133` through `:142` list anti-patterns: no downscale/viewport zoom-out, zoom tunneling, preset, affordance, strobe/flicker, or unbounded noise frequency.
- `docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md:158` through `:168` list the downstream implementation footprint and expected test surfaces.
- `docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md:172` through `:180` provides the downstream validation anchors.

## Findings

1. Factor derivation needs an all-predicates fixture.

   Suggested fixture: future `compute_miniature_factor()` tests should assert that
   factor becomes positive only when all source predicates are simultaneously
   true: `stance == "nominal"`, `ir_gaze_zone` is `center` or `near-center` for
   more than 5 seconds, `motion_score < 0.3`, and some component
   `max_novelty_score > 0.5`. Each missing predicate should independently force
   factor 0. A fake clock should cover the dwell threshold without sleeping.

2. Shared-signal handling needs a stale and malformed input fixture.

   Suggested fixture: the downstream reader for
   `/dev/shm/hapax-stimmung/miniature.json` should accept bounded numeric
   factors in `[0, 1]` and fail closed to 0 for missing, stale, non-numeric,
   negative, over-range, or malformed data. If a VLA publisher is added, its
   tests should prove it writes only this bounded derived state, not operator
   attention claims beyond the current input evidence.

3. Uniform modulation needs both baseline and factor-1 fixtures.

   Suggested fixture: `_apply_miniature_bias(uniforms, factor=0)` should be
   byte-identical or structurally identical to the pre-miniature baseline.
   `_apply_miniature_bias(..., factor=1)` should pin every named multiplier:
   intensity x1.20, tension x0.70, depth x1.0, coherence x1.0,
   spectral_color x1.30, temporal_distortion x1.0, degradation x0.90,
   pitch_displacement x1.10, diffusion x0.50, plus shader-topology deltas such
   as `noise.frequency` x2.5, `colorgrade.contrast` x1.4, and
   `colorgrade.saturation` x1.3.

4. Modulation ordering needs an integration fixture.

   Suggested fixture: the uniform writer should prove the order remains
   plan defaults plus chain deltas, mode tint, roundness, miniature, homage
   damping, then programme override. This should be tested with distinguishable
   inputs so a reorder changes the output. The fixture should also confirm
   miniature is a modulation pass, not a new WGSL node or preset path.

5. Roundness composition needs a non-cancellation fixture.

   Suggested fixture: when roundness and miniature are both active, depth should
   preserve roundness behavior while miniature contributes inner texture rather
   than canceling or sign-flipping depth. Pin the source-spec divergence:
   diffusion is damped by miniature, spectral color is amplified by miniature,
   and depth is unchanged by miniature alone.

6. Sierpinski subdivision needs a four-state fixture.

   Suggested fixture: compositor tests should pin default `[4]`, roundness-only
   `[2]`, miniature-only `[6]`, and both-active `[2, 6]`. The both-active case
   is the highest-value guard because it proves the outer roundness envelope and
   inner miniature texture can coexist.

7. Token pole precision needs a saturation non-regression fixture.

   Suggested fixture: under miniature, token-pole tick or sub-tick precision
   should increase while saturation remains unchanged. This prevents accidental
   reuse of roundness behavior, where saturation and tick cadence are damped.

8. Content placement needs a bounded splay fixture.

   Suggested fixture: the content placement or mixer layer should keep baseline
   placement for `miniature_factor <= 0.5`, then switch to four tight clustered
   slots for `miniature_factor > 0.5` with `per_slot_opacity = base_opacity /
   1.5`. The test should assert total visual weight remains bounded and that
   splay is not implemented as viewport downscale or zoom-out.

9. Anti-pattern regression needs static scans and runtime fixtures.

   Suggested fixture: add focused checks that reject literal downscale,
   viewport zoom-out, dolly/zoom-tunnel tricks, a `miniature` preset, a
   `miniature` affordance, blinking/strobe/flicker, and unbounded noise
   frequency. The source cap implies `noise.frequency` should not exceed
   default x2.5 when factor is bounded to 1.

10. Mode orthogonality and public-witness boundaries need fixtures.

   Suggested fixture: miniature should apply regardless of working mode
   (`research`, `rnd`, `fortress`) because it is a stance-bound register, not a
   mode. If any future public readback or telemetry describes miniature as
   active, tests should bind that claim to current VLA/SHM state and stale data
   should not be allowed to produce a false active-readback claim.

## Uncertainty

- `agents/reverie/content_layer.py` is named in the source spec as conditional:
  "if it exists; otherwise the slot-placement code in mixer." The exact test
  path should follow the downstream implementation surface rather than force a
  new module.
- The source document describes the VLA publisher and SHM reader but does not
  define timestamp, schema version, or stale-window semantics for
  `/dev/shm/hapax-stimmung/miniature.json`. A downstream implementer should
  define those before converting the stale-data fixture into a hard test.
- The factor shape is implied as a bounded scalar, but interpolation and dwell
  smoothing are not specified beyond the source predicates. Tests should pin
  fail-closed behavior first and leave smoothing precision to the implementation
  contract if it is added.

## Senior Intake

- Treat this as an acceptance matrix for the downstream implementation task,
  not as task closure or proof that Amendment 8 is implemented.
- The first implementation PR should include fixtures for derivation,
  `/dev/shm` signal handling, uniform multiplication/order, Sierpinski
  composition, token-pole precision, content splay, anti-pattern rejection, and
  no-false-grounding readback behavior.
- The matrix stays within the existing Hapax architecture: single-operator
  local state, Obsidian/cc-task work truth, `uv`-run tests, relay/claim
  coordination, and public-readback caution. It proposes tests and fixtures
  only; it does not bypass services, governance gates, or runtime authority.
