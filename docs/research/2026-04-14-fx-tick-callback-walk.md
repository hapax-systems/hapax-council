# fx_tick_callback 30-fps main-loop work walk

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Drop #36 flagged `fx_tick_callback` as the
30 fps uniform-update tick on the GLib main loop but
didn't audit what it actually does per tick. This drop
walks the three subroutines (`tick_governance`,
`tick_modulator`, `tick_slot_pipeline`) and identifies
three modest findings.
**Register:** scientific, neutral
**Status:** investigation — 3 findings, all small. No
code changed.
**Companion:** drop #36 (threading + tick cadence), drop
#38 (SlotPipeline internals)

## Headline

**fx_tick_callback runs every 33 ms on the GLib main
loop and does three kinds of work:**

1. **`tick_governance`** — reads `_overlay_state` for
   activity/genre, calls `AtmosphericSelector.evaluate`
   for auto-preset selection, computes gestural offsets,
   applies them via `_on_graph_params_changed` per
   node. Potentially triggers a full preset load on the
   main loop if auto-governance picks a new target.
2. **`tick_modulator`** — builds a **~30-key signals
   dict from scratch every tick**, feeds it to the node
   graph modulator, iterates per-update calling
   `_on_graph_params_changed` per param.
3. **`tick_slot_pipeline`** — iterates **24 slots**,
   does a **string-contains check `f"u_{k}" in
   defn.glsl_source`** for each slot × 3 time_uniforms,
   and calls `_apply_glfeedback_uniforms` or
   `_set_uniforms` on every slot with a non-None
   assignment.

All three run serially on the main thread per tick. A
slow preset load in `tick_governance` blocks the 33 ms
schedule, which (per drop #36 finding 3) causes
reactive-scheduling drift across all main-loop work.

## 1. Per-tick work breakdown

### 1.1 tick_governance — possible main-loop preset load

`agents/studio_compositor/fx_tick.py:9-55`:

```python
def tick_governance(compositor, t) -> None:
    if compositor._graph_runtime is None or not hasattr(compositor, "_atmospheric_selector"):
        return

    # User override hold: 10 minutes after user-initiated preset switch
    hold_until = getattr(compositor, "_user_preset_hold_until", 0.0)
    if time.monotonic() < hold_until:
        return

    from agents.effect_graph.visual_governance import (
        compute_gestural_offsets,
        energy_level_from_activity,
    )
    from .effects import get_available_preset_names, try_graph_preset

    gov_data = compositor._overlay_state._data
    energy_level = energy_level_from_activity(gov_data.desk_activity)
    stance = "nominal"
    available = get_available_preset_names()
    target = compositor._atmospheric_selector.evaluate(
        stance=stance,
        energy_level=energy_level,
        available_presets=available,
        genre=gov_data.music_genre,
    )
    if target and target != getattr(compositor, "_current_preset_name", None):
        if try_graph_preset(compositor, target):
            compositor._current_preset_name = target
    ...
```

**Finding 1 — `try_graph_preset` runs on the main loop.**
When `AtmosphericSelector.evaluate` returns a preset
name different from the current one, `try_graph_preset`
loads + applies the new preset **on the main loop**.
That involves reading a JSON file from disk, parsing,
constructing an EffectGraph, calling `graph_runtime.load_graph`
which propagates through to the SlotPipeline's
`activate_plan` (drop #38) which re-sets up to 24
fragment shaders.

**Worst case** (new preset with many nodes different
from current): ~5-20 ms of work on the main loop.
Drop #38's diff check (shipped in drop #5 era) limits
the shader recompiles to ONLY nodes that actually
changed, but the preset file read + parse + plan
construction still runs synchronously.

**Mitigation in place**: `_user_preset_hold_until` is a
10-minute timeout after user-initiated preset switches
(`fx-request.txt` path in `state_reader_loop`). During
that hold, governance doesn't fire. So governance-
triggered loads are rate-limited by how often user
overrides happen.

**Additional mitigation in place**: governance only
fires when the target differs from current. Most ticks
are no-ops.

**Finding 1 is a latent risk, not a current hot spot.**
Measurement is needed to know how often governance
actually triggers a load in practice.

**Optional ring 2 fix**: move `try_graph_preset` off
the main loop via `GLib.idle_add` — fire-and-forget
from the governance tick, let the load happen on the
next idle iteration. Won't block the 33 ms schedule
even if a load is slow.

### 1.2 tick_modulator — per-tick 30-key dict construction

`agents/studio_compositor/fx_tick.py:58-146`:

```python
def tick_modulator(compositor, t, energy, b) -> None:
    if compositor._graph_runtime is None:
        return
    modulator = compositor._graph_runtime.modulator
    if not modulator.bindings:
        return

    signals = {"audio_rms": energy, "audio_beat": b, "time": t}
    data = compositor._overlay_state._data
    if data.flow_score > 0:
        signals["flow_score"] = data.flow_score
    # ... ~30 total signal keys built from overlay_state + cached_audio ...

    updates = modulator.tick(signals)
    for (node_id, param), value in updates.items():
        compositor._on_graph_params_changed(node_id, {param: value})
```

**~30 potential signal keys per tick:**
- 3 time/audio base: `audio_rms`, `audio_beat`, `time`
- 3 stimmung-dependent (conditional): `flow_score`,
  `stimmung_valence`, `stimmung_arousal`
- ~14 audio keys from `_cached_audio`: `mixer_energy`,
  `mixer_beat`, `mixer_bass`, `mixer_mid`, `mixer_high`,
  `beat_pulse`, `onset_kick`, `onset_snare`, `onset_hat`,
  `sidechain_kick`, `spectral_centroid`, `spectral_flatness`,
  `spectral_rolloff`, `zero_crossing_rate`
- 8 mel bands: `mel_sub_bass`, `mel_bass`, `mel_low_mid`,
  `mel_mid`, `mel_upper_mid`, `mel_presence`,
  `mel_brilliance`, `mel_air`
- 3-6 desk + beat-derived: `desk_energy`,
  `desk_onset_rate`, `desk_centroid`, `beat_phase`,
  `bar_phase`, `beat_pulse` (fallback)
- 3 biometric: `heart_rate`, `stress`, `perlin_drift`

**Finding 2 — dict allocation churn**: Python allocates
a fresh 30-key dict every tick. At 30 fps that's ~900
dict allocations per second + ~27000 key insertions.
Python dict allocator handles this easily (~50 ns per
key), so actual cost is **~1.3 ms/sec** ≈ 0.1% of one
core. Absolutely trivial.

**But the subsequent `modulator.tick(signals)` call**
iterates the modulator's binding list and returns an
`updates` dict. For each update, `_on_graph_params_changed`
dispatches to the slot_pipeline's `update_node_uniforms`.
The cost scales with `len(modulator.bindings)` — if
every binding updates, there's one uniform set per
binding per tick.

**Observability gap**: there's no metric for how many
updates actually fire per tick, and no measurement of
the per-tick modulator cost. Could be 0 or could be
hundreds of uniform sets per tick.

**Optional fix**: reuse a pre-allocated signals dict
and `.clear() + .update()` it per tick. Saves the 30
key insertions. Sub-microsecond savings. **Not worth
shipping unless profiling shows modulator cost is
meaningful.**

### 1.3 tick_slot_pipeline — 24-slot string-contains
scan per tick

`agents/studio_compositor/fx_tick.py:149-173`:

```python
def tick_slot_pipeline(compositor, t) -> None:
    if not compositor._slot_pipeline:
        return

    time_uniforms = {"time": t % 600.0, "width": 1920.0, "height": 1080.0}
    for i, node_type in enumerate(compositor._slot_pipeline.slot_assignments):
        if node_type is None:
            continue
        defn = (
            compositor._slot_pipeline._registry.get(node_type)
            if compositor._slot_pipeline._registry
            else None
        )
        if defn and defn.glsl_source:
            implicit = {k: v for k, v in time_uniforms.items() if f"u_{k}" in defn.glsl_source}
            if implicit:
                compositor._slot_pipeline._slot_base_params[i].update(implicit)
                if compositor._slot_pipeline._slot_is_temporal[i]:
                    compositor._slot_pipeline._apply_glfeedback_uniforms(i)
                else:
                    compositor._slot_pipeline._set_uniforms(i, ...)
```

**For each of 24 slots** (well, for each slot where
`node_type is not None` — typically 5-9 from drop #38
presets):

1. Look up the registry definition
2. For each of 3 `time_uniforms` keys (`time`, `width`,
   `height`): run `f"u_{k}" in defn.glsl_source`
   (Python string-contains check against the entire
   GLSL source, typically ~500-2000 chars)
3. If any implicit keys matched, call
   `_slot_base_params[i].update(implicit)` and then
   `_apply_glfeedback_uniforms(i)` (which walks the
   param dict and calls a glfeedback property set per
   param)

**Finding 3 — per-tick string-contains scan is
wasteful.** The set of implicit keys that each shader
uses is determined at shader-compile time, not at
tick time. Scanning the GLSL source for `u_time`,
`u_width`, `u_height` on every frame is pure waste.

**Fix**: precompute the implicit-keys set per shader at
plan-activation time (in `SlotPipeline.activate_plan`)
and cache it on `_slot_implicit_keys[i]`. The tick
then looks up the cached set and skips the scan.

```python
# In activate_plan:
self._slot_implicit_keys[i] = {
    k for k in ("time", "width", "height")
    if f"u_{k}" in step.shader_source
}

# In tick_slot_pipeline:
implicit_keys = compositor._slot_pipeline._slot_implicit_keys[i]
if implicit_keys:
    implicit = {k: time_uniforms[k] for k in implicit_keys}
    ...
```

**Savings**: 24 slots × 3 string scans × 30 fps = **2160
substring scans per second** eliminated. At ~1000 chars
each, that's ~2.2 MB/sec of string comparison work. CPU
cost is ~1-5% of one core on Python's string backend.

Not huge but free to fix. And this is **every tick**
on the main loop — the exact thing drop #36 finding 3
flagged as priority-pinning-worthy.

## 2. Ring summary

### Ring 1 — modest cleanups

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **FXT-1** | Precompute per-slot implicit-keys set at plan-activation | `agents/effect_graph/pipeline.py:activate_plan` + `fx_tick.py:tick_slot_pipeline` | ~10 | ~2160 string scans/sec eliminated; frees 1-5% of one core on the main loop |
| **FXT-2** | Reuse pre-allocated signals dict in `tick_modulator` | `fx_tick.py:tick_modulator` | ~5 | ~1 ms/sec allocation churn eliminated (trivial) |

**Risk profile**: zero for both. Pure refactors.

### Ring 2 — latent risk mitigation

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **FXT-3** | Wrap `try_graph_preset` in governance tick with `GLib.idle_add` | `fx_tick.py:tick_governance` | ~5 | Governance-triggered preset loads no longer block the 33 ms schedule |

**Risk profile**: low. Adds one tick of latency on
governance preset switches (which are already
rate-limited by the 10-min user-override hold).

### Ring 3 — observability

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **FXT-4** | Per-sub-function latency histograms (`tick_governance_ms`, `tick_modulator_ms`, `tick_slot_pipeline_ms`) | `fx_tick.py` + `metrics.py` | ~30 | Per-tick cost distribution becomes scrape-visible; pairs with drop #36 finding 5 |
| **FXT-5** | Counter for how many updates `tick_modulator` produces per tick | `fx_tick.py` | ~5 | Quantifies drop #41 Ring 2 BT-4's expected benefit |

## 3. Cross-drop context

All three findings are incremental tuning on a path
that is **not currently a measured hot spot**. The
fx_tick_callback cost is unmetered (drop #36 finding 5),
so we don't know how much headroom is here.

**Ring 1 FXT-1 is the only free win worth shipping
on its own** — it's a clear unnecessary per-tick
operation. Everything else should wait for measurement
via FXT-4 (Ring 3).

**The bigger fx_tick_callback issue is still drop #36
finding 3**: the callback is reactive-scheduled at
default priority. THR-1 in drop #36 (upgrade to
PRIORITY_HIGH) remains the highest-leverage fx_tick
fix. This drop's findings are all smaller optimizations
within the callback.

## 4. Cross-references

- `agents/studio_compositor/fx_chain.py:643-700` —
  `fx_tick_callback` entry point
- `agents/studio_compositor/fx_tick.py:9-55` —
  `tick_governance`
- `agents/studio_compositor/fx_tick.py:58-146` —
  `tick_modulator`
- `agents/studio_compositor/fx_tick.py:149-173` —
  `tick_slot_pipeline`
- `agents/effect_graph/pipeline.py:148-220` —
  `SlotPipeline.activate_plan` (where FXT-1's
  precomputation would live)
- Drop #5 — glfeedback diff check (prevents repeat
  shader compilation, already shipped)
- Drop #36 — threading + tick cadence (flagged
  fx_tick_callback as reactive-scheduled)
- Drop #38 — SlotPipeline 24-slot architecture
- Drop #41 BT-4 — per-source budget_ms wiring (related
  observability gap)

## 5. End of systematic walk

**This drop brings the cam-pipeline + compositor
orchestration audit to 43 drops** (from drop #28
through this one, plus pre-compaction #1-#27).

**Hot-path coverage is complete.** Every element in
the streaming-thread critical path from `v4l2src` to
`v4l2sink` has been audited:

- Producer (drops #28-30, #37)
- Consumer chain + cudacompositor (drop #35)
- fx chain (drops #30, #38, #39, #40, #43)
- Output tee + sinks (drops #32, #33)
- Bus message handling (drop #33)
- USB hardware (drops #2, #27, #34)
- Python orchestration (drops #36, #41, #43)

**Background-thread coverage is complete**:
- Cairo source runners (drop #36)
- BudgetTracker wiring (drop #41)
- Individual cairo sources (drop #42 sierpinski,
  drop #41 overlay_zones)

**What's left unaudited** — none of it is in the
hot path:
- `state_reader_loop` thread (low-impact; 6-8 stat
  calls per tick for file polling)
- `LayoutAutoSaver` / `LayoutFileWatcher` (control
  plane; already flagged in drop #36 Ring 2 THR-4)
- Individual Cairo sources for dead layout entries
  (drop #41 finding 1 — `token_pole`, `album`,
  `stream_overlay` never start)
- Audio capture pw-cat subprocess (drop #36 touched
  on this but didn't deep-dive)
- `effect_graph/visual_governance.py` internals
  (`AtmosphericSelector`, `compute_gestural_offsets`)

**Recommendation**: stop the systematic walk here.
Further drops on control-plane or background-thread
minutiae would have diminishing returns. The
highest-leverage remaining work is **shipping the
fixes from the existing drops** — drop #31 Ring 1,
drop #35 COMP-1/COMP-2, drop #41 BT-1 (biggest
remaining wiring gap), drop #42 SIERP-4 — rather
than finding more research areas.
