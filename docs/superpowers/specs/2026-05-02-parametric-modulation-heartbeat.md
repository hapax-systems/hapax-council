# Parametric Modulation Heartbeat — Spec

**Date:** 2026-05-02
**Author:** alpha
**Status:** Active
**Supersedes (in spirit, not in code-revert):** PR #2239 preset-bias-heartbeat-fallback

## Operator directive (verbatim)

From `~/.claude/projects/-home-hapax-projects/memory/feedback_no_presets_use_parametric_modulation.md`, recorded 2026-05-02T22:13Z:

> "Already going to push back on 'presets' — we should be relying on
> constrained algorithmic parametric modulation and combination and
> chaining of effects at the node graph level. Presets are dumb. Be
> smart about this."

## Architecture

Variance enters the Reverie shader pipeline through three orthogonal channels:

1. **The visual chain (`agents/visual_chain.py`)** writes per-frame
   `{node_id}.{param_name}` deltas to `/dev/shm/hapax-imagination/uniforms.json`
   in response to grounded perceptual + stimmung signals. This is the
   "real grounded variance" channel.
2. **The imagination loop (`agents/imagination_loop.py`)** publishes
   the 9 expressive dimensions per fragment, mapped to the GPU uniform
   buffer. This is the cognitive channel.
3. **The parametric modulation heartbeat (this spec)** walks the
   per-node parameter space within constraint envelopes when channels
   1 + 2 are quiescent. This is the substrate-fallback channel.

All three write to the **same** `uniforms.json` surface; the Reverie
mixer (`agents/reverie/_uniforms.py::write_uniforms`) merges
`base + delta` per tick. Last-writer-wins per key per frame — chain +
imagination dominate when active because they tick faster than the
heartbeat's 30s cadence.

### Constraint envelopes (`shared/parameter_envelopes.py`)

Each envelope encodes:

- `node_id` + `param_name` (canonical
  `{node_id}.{param_name}` key matching the uniforms.json schema)
- `min_value` + `max_value` (inclusive bounds — clipped per tick)
- `smoothness` (max `|delta|` per tick — the smoothness invariant)
- `joint_constraints` (tuple of `JointConstraint` instances — aesthetic
  invariants involving this and another parameter)

The envelope is the **spec**; the walk is the behavior. Walking within
an envelope produces continuous, bounded, aesthetically-invariant
modulation. There are no "preset values" in the envelope — only
ranges.

### Joint constraints

Aesthetic invariants per the operator directive's worked example
("intensity × degradation must not both peak — would clip to noise"):

| Invariant | `joint_max` | Rationale |
|---|---|---|
| `content.intensity` × `post.sediment_strength` | 0.55 | Both peaking clips pipeline to visual noise |
| `fb.decay` × `fb.rotate` | 0.30 | Both peaking produces dizzying smear |
| `rd.feed_rate` × `rd.kill_rate` | 0.06 | Both peaking leaves the Gray-Scott structured basin |

When the walker breaches a joint constraint, both parameters are scaled
proportionally back into the constraint surface — symmetric, no
privileging of either. Operator can audit joint constraints over time
through journal logs (every clip emits an `INFO` line).

### Parameter walk algorithm

Per-tick step (`agents/parametric_modulation_heartbeat/heartbeat.py::ParameterWalker.tick`):

```
for each envelope:
    target = lfo_target(envelope, t)        # sin wave with per-key phase
    noise  = gauss(0, perturbation × range) # Gaussian perturbation
    stepped = envelope.clip_step(prev, target + noise)  # smoothness + range
    values[envelope.key] = stepped

apply_joint_constraints()                   # symmetric scale-down on breach
return detect_boundaries()                  # values within 5% of min/max
```

**LFO** is deterministic per-key (hash-based phase offset), so the walk
is reproducible if you replay the wall clock. **Perturbation** is
zero-mean Gaussian with std proportional to envelope range — small
enough to keep the walk smooth, large enough to break LFO periodicity.

### Boundary-crossing transitions

When a parameter walks within 5% of its envelope's `min` or `max`, a
`BoundaryEvent` is emitted. The heartbeat then records a transition
primitive request in `recent-recruitment.json` under one of the five
canonical chain operations:

- `transition.fade.smooth`
- `transition.cut.hard`
- `transition.netsplit.burst`
- `transition.ticker.scroll`
- `transition.dither.noise`

These are **chain operations**, not preset picks (per the operator
directive: "the 5 transition primitives are right; the 27 preset
families are the wrong unit"). The director-loop's
`preset_recruitment_consumer` reads the same surface and dispatches
the primitive against the live chain.

The recruitment entry carries:

- `kind: "transition_primitive"` (NOT `kind: "preset.bias"` — that was
  PR #2239's anti-pattern)
- `source: "parametric-modulation-heartbeat"` (observability marker)
- `triggered_by: "{envelope_key}"` (journal correlation)

Per-key cooldown (60s default) prevents a parameter hovering near a
boundary from flooding the recruitment surface with one transition per
tick.

### Affordance-driven chain mutation

The walker observes the recruited affordance set from
`recent-recruitment.json` (the same surface the imagination loop's
recruited affordances land on). When the affordance set shifts, the
walker treats this as a signal to mutate the chain — but the mutation
itself happens through the existing `AffordancePipeline` →
`maybe_rebuild` path. The walker never touches `presets/` directly.

Per CLAUDE.md § Unified Semantic Recruitment: "The chain mutates because
affordances are recruited/dismissed, not because a preset was picked."

## Why presets are wrong (anti-pattern catalog)

Per `feedback_no_expert_system_rules` ("behavior emerges from
impingement→recruitment→role→persona; hardcoded cadence/threshold gates
are bugs") and the cumulative `feedback_no_presets_use_parametric_modulation`:

- **Presets are hardcoded snapshots.** Sampling from a preset library is
  the same expert-system anti-pattern as cadence gates. Variance must
  emerge from the underlying generative substrate, not from a curated
  library of frozen states.
- **PR #2239's preset-bias heartbeat** was the wrong unit. It uniform-samples
  from 27 frozen "preset families" when LLM recruitment stalls. The
  audit's framing — "24/27 family-mapped presets dormant" — was operator-correct
  as a description, but reinforced the dumb-preset model as a target.
- **The correct target** is parameter-space modulation + chain composition.
  The 5 transition primitives are right because they're chain operations;
  the 27 preset families are wrong because they're snapshots.

## Composition with PR #2239

The preset-bias heartbeat module (`agents/preset_bias_heartbeat/`) is
**not deleted in this PR** for revert-safety per the cc-task
constraints. Both units may run alongside during the transition window;
operator disables the preset unit post-merge by stopping the systemd
unit:

```sh
systemctl --user stop hapax-preset-bias-heartbeat.service
systemctl --user disable hapax-preset-bias-heartbeat.service
```

Once the operator has validated the parametric heartbeat in livestream
operation, the preset unit module + service file can be deleted in a
follow-up PR.

## Migration path for `presets/`

The `presets/` directory remains as **starting-point reference** only —
operator may consult preset JSONs to seed envelope `(min, max)` values
when authoring new envelopes. **No code path samples from `presets/`**
(regression test `TestNoPresetCoupling::test_no_presets_directory_read`
enforces this for the heartbeat module).

Future work (out of scope for this PR):

- Migrate `presets/` JSONs to envelope deltas in
  `shared/parameter_envelopes.py` — the envelope BECOMES the spec, the
  preset is retired.
- Director vocabulary expansion = NEW chain-operation moves + NEW
  parameter-modulation moves, NOT new presets.

## Verification

Operator runs:

```sh
# Verify the heartbeat is running.
systemctl --user status hapax-parametric-modulation-heartbeat.service

# Verify per-frame parameter modulation is reaching the GPU.
# Shows live parameter changes — smooth modulation, not stepwise jumps.
watch -n 1 'jq "{noise_amp: .[\"noise.amplitude\"], color_brightness: .[\"color.brightness\"], rd_feed: .[\"rd.feed_rate\"]}" /dev/shm/hapax-imagination/uniforms.json'

# Verify boundary-crossing transition primitives are landing in the
# recruitment surface (parametric-walk source, NOT preset bias).
jq '.families | to_entries | map(select(.value.source == "parametric-modulation-heartbeat"))' /dev/shm/hapax-compositor/recent-recruitment.json
```

The parametric modulation heartbeat is correctly active when:

1. `uniforms.json` parameters drift smoothly across consecutive snapshots
   (no instantaneous large jumps).
2. `recent-recruitment.json` shows `transition.*` entries with
   `source: "parametric-modulation-heartbeat"` over time.
3. Joint constraints hold: `(content.intensity + post.sediment_strength) / 2 ≤ 0.55`
   in every observed snapshot.

## References

- cc-task: `~/Documents/Personal/20-projects/hapax-cc-tasks/active/parametric-modulation-heartbeat.md`
- Operator directive: `~/.claude/projects/-home-hapax-projects/memory/feedback_no_presets_use_parametric_modulation.md`
- Anti-pattern: `~/.claude/projects/-home-hapax-projects/memory/feedback_no_expert_system_rules.md`
- Substrate: CLAUDE.md § Reverie Vocabulary Integrity (per-node `params_buffer`)
- Composition mechanism: CLAUDE.md § Unified Semantic Recruitment (chain composition through affordance recruitment)
- Superseded: PR #2239 `alpha/preset-bias-heartbeat-fallback` (`agents/preset_bias_heartbeat/`)
- Built on: PR #2244 imagination_loop pydantic-ai fix (real grounded variance now flows)
- Built on: PR #2246 camera-classifications fill (semantic camera selection now works)
