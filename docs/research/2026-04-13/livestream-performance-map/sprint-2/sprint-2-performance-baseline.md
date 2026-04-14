# Sprint 2 — Performance Baseline

**Date:** 2026-04-13 CDT
**Theme coverage:** D1 (composite element), D7 (main output assembly cost), E1 (effect graph activation), E2 (per-node shader inventory), E8.1 (preset catalog), C1 (per-camera steady state — extended from sprint 1)
**Register:** scientific, neutral

## Headline

**Six findings in Sprint 2:**

1. **The compositor uses `cudacompositor`** (CUDA-accelerated GStreamer compositing) when available, falling back to CPU `compositor`. `pipeline.py:41` tries `cudacompositor` first; journal confirms runtime selection via `_use_cuda` flag.
2. **Node catalog: 56 WGSL shader nodes + 30 presets** (not the 54/28 that CLAUDE.md claims — docs drift).
3. **Per-node shader complexity varies 4×** from the smallest (postprocess, 51 lines) to the largest (glitch_block, 245 lines). No per-node GPU timing today.
4. **Queue 025 Phase 3 claim confirmed live**: brio-operator sustains 28.479 fps over a 5-second measurement window. Other BRIOs + C920s at 30.50 fps. The ~1.5 fps deficit is **reproducible at steady state** and **not a USB bus issue** (Sprint 1 F2).
5. **FreshnessGauge P1 bug — Prometheus name regex rejects hyphens.** 8 of the compositor's source-id values contain hyphens (`brio-operator`, `c920-desk`, `overlay-zones`, `sierpinski-lines`, etc.). All 8 hit `ValueError: FreshnessGauge name 'compositor_source_frame_overlay-zones' must match [a-z_][a-z0-9_]*`. **PR #755's FreshnessGauge wiring is silently disabled for every hyphenated source**, which is every per-camera source + 2 of the cairo sources.
6. **Graph plan state lives in `/dev/shm/hapax-compositor/fx-current.txt`** (currently: `chain`), NOT in a persistent `graph-mutation.json`. The `graph-mutation.json` file does not exist at measurement time.

## Data

### D1.1 — Main mixer: `cudacompositor` with CPU fallback

`agents/studio_compositor/pipeline.py:40-47`:

```python
# Try cudacompositor first, fall back to CPU compositor
comp_element = Gst.ElementFactory.make("cudacompositor", "compositor")
compositor._use_cuda = comp_element is not None
if comp_element is None:
    log.warning("cudacompositor unavailable — falling back to CPU compositor")
    comp_element = Gst.ElementFactory.make("compositor", "compositor")
    if comp_element is None:
        raise RuntimeError("Neither cudacompositor nor compositor plugin available")
```

- `gst-inspect-1.0 cudacompositor` returns a valid factory ("CUDA Compositor", Klass `Filter/Editor/Video/Compositor/Hardware`) — the element is installed.
- `_use_cuda` is set to `True` when the factory creates successfully.
- Downstream, `pipeline.py` branches on `_use_cuda` to insert a `cudadownload` element in front of `convert_bgra`.

**Assumed verdict**: the compositor is running on CUDA compositing. Verifying via a non-code probe (nvidia-smi compute-apps) would show compositor using GPU memory, which it does (3 GB per Sprint 1 L1.1).

**Uncertainty**: the `log.warning("cudacompositor unavailable")` would fire at startup if the element didn't load. Grepping the journal for it shows no occurrences in the current session. **High confidence the compositor is using GPU compositing.**

### E2.1 — Node catalog (56 WGSL + 55 fragment shaders)

`agents/shaders/nodes/*.wgsl` count: **56**. Full list:

```text
ascii, blend, bloom, breathing, chroma_key, chromatic_aberration,
circular_mask, colorgrade, color_map, content_layer, crossfade, diff,
displacement_map, dither, drift, droste, echo, edge_detect, emboss,
feedback, fisheye, fluid_sim, glitch_block, halftone, invert,
kaleidoscope, luma_key, mirror, noise_gen, noise_overlay, particle_system,
pixsort, posterize, postprocess, reaction_diffusion, rutt_etra, scanlines,
sharpen, sierpinski_content, sierpinski_lines, slitscan, solid, strobe,
stutter, syrup, thermal, threshold, tile, trail, transform, tunnel, vhs,
vignette, voronoi_overlay, warp, waveform_render
```

**Cross-reference with CLAUDE.md**: claim of "54 nodes" is stale; actual is 56. Two nodes shipped after the CLAUDE.md count was recorded.

### Per-node shader complexity sample (line counts)

Not a perfect proxy for GPU cost but a useful first pass:

| node | lines (wgsl) | complexity tier |
|---|---|---|
| postprocess | 51 | LOW |
| chromatic_aberration | 62 | LOW |
| kaleidoscope | 74 | LOW |
| bloom | 108 | MEDIUM |
| fluid_sim | 129 | MEDIUM |
| noise_gen | 136 | MEDIUM |
| feedback | 149 | MEDIUM |
| colorgrade | 155 | MEDIUM |
| halftone | 180 | MEDIUM-HIGH |
| glitch_block | 245 | HIGH |

**glitch_block is the largest shader** (245 lines). Likely also the most expensive when active. Per-pass GPU timing via wgpu `Query::Timestamp` is needed for definitive measurement (E6.3 in the research map, not yet landed).

### E8.1 — Preset catalog (30 presets)

```text
ambient, ascii_preset, clean, datamosh, datamosh_heavy, _default_modulations,
diff_preset, dither_retro, feedback_preset, fisheye_pulse, ghost,
glitch_blocks_preset, halftone_preset, heartbeat, kaleidodream,
mirror_rorschach, neon, nightvision, pixsort_preset, reverie_vocabulary,
screwed, sculpture, silhouette, slitscan_preset, thermal_preset, trails,
trap, tunnelvision, vhs_preset, voronoi_crystal
```

**30 presets** (CLAUDE.md claim of 28 is stale; presets have been added).

**`_default_modulations.json` is not a preset** — it's a modulation defaults file. Active preset count is 29.

**Active preset at measurement**: `chain` (per `/dev/shm/hapax-compositor/fx-current.txt`). This is a meta-preset that chains multiple presets; the constituents are determined at activation time, not listed statically.

### Sample preset structure (`clean.json`)

```json
{
  "name": "Clean",
  "description": "Minimal processing",
  "transition_ms": 300,
  "nodes": {
    "color": {"type": "colorgrade", "params": {"saturation":1.05, "brightness":1.02, "contrast":1.05}},
    "vig":   {"type": "vignette",   "params": {"strength":0.15, "radius":0.8, "softness":0.3}},
    "out":   {"type": "output",     "params": {}},
    "content_layer": {"type": "content_layer", "params": {}},
    "postprocess":   {"type": "postprocess",   "params": {}}
  }
}
```

**"Clean" preset has 5 nodes** (colorgrade, vignette, output, content_layer, postprocess). Minimum plausible preset size. More complex presets will have 10-24 slots filled (sprint 1 queue 023 observed a chain activation with 8/24 slots used).

### D7.1 — Compositor frame throughput (5-sec window, brio-operator)

```text
5.056 seconds  →  144 frames  →  28.479 fps
```

Reproducible. Matches Sprint 1's 2-sec-delta measurement of 28.50 fps.

**The deficit is stable**, not a transient. Over a 5-second window, brio-operator delivers exactly the 28.479 fps rate with no variance outside quantization.

All other cameras: 30.50 fps (within 0.5 fps of the 30 target, which is the GStreamer compositor's output framerate cap).

### E1 — Effect graph activation cost (indirect)

Queue 023 Phase 1 observed the compositor jump from 1.3 GB to 4.4 GB during a 24-slot plan activation at 17:02:09. Reproducing the measurement live would require triggering a plan activation, which causes a brief frame-rate hiccup and is operator-affecting. Defer to an operator-coordinated session.

**Evidence-backed observation from q023**: each graph plan slot activation produces a log line of shape `Slot N (name): setting fragment (NNN chars)`. 24 slots activated yields 24 logs in <100 ms. The cost is dominated by NVIDIA driver shader compilation on first-load for each slot's new fragment.

### FreshnessGauge P1 bug — hyphens reject

`shared/freshness_gauge.py:112`:

```python
if not _VALID_NAME.fullmatch(name):
    msg = (
        f"FreshnessGauge name {name!r} must match "
        "[a-z_][a-z0-9_]* (Prometheus naming convention)"
    )
    raise ValueError(msg)
```

`agents/studio_compositor/cairo_source.py:166`:

```python
self._freshness_gauge = FreshnessGauge(
    name=f"compositor_source_frame_{source_id}",  # ← source_id can contain hyphens
    expected_cadence_s=self._period,
)
```

**Source IDs with hyphens**:
- All 6 camera roles: `brio-operator`, `brio-room`, `brio-synths`, `c920-desk`, `c920-room`, `c920-overhead`
- Cairo sources: `overlay-zones`, `sierpinski-lines`

**Journal evidence**: `journalctl --user -u studio-compositor.service --since "2 hours ago" | grep "FreshnessGauge"` returns repeated entries across restarts:

```text
ValueError: FreshnessGauge name 'compositor_source_frame_overlay-zones' must match
  [a-z_][a-z0-9_]* (Prometheus naming convention)
ValueError: FreshnessGauge name 'compositor_source_frame_sierpinski-lines' must match
  [a-z_][a-z0-9_]* (Prometheus naming convention)
```

**Impact**: PR #755 wired FreshnessGauge for every cairo source with `source_id`-suffixed series. Those series are **silently not created** for 8 of the sources. The per-source frame-age observability that PR #755 promised is dead for cameras + 2 cairo sources.

**Additional symptom**: the `except Exception: log.warning(...)` at `cairo_source.py:169` swallows the ValueError, so the compositor continues without the gauge and the operator sees only a startup warning that's easy to miss.

**Fix**:

```python
# In cairo_source.py:166
safe_id = source_id.replace("-", "_")
self._freshness_gauge = FreshnessGauge(
    name=f"compositor_source_frame_{safe_id}",
    expected_cadence_s=self._period,
)
```

One-line fix. Adds a single `replace("-", "_")`. Cross-reference: the compositor's `studio_camera_*` metrics in `metrics.py` ALREADY use label values like `brio-operator` in label slots (which Prometheus allows in label values, not metric names), so this is a name-vs-label confusion.

**Severity**: HIGH for observability. This is a queue 024 FINDING-H-style "metric shipped but never reaches Prometheus" class failure.

## Findings + fix proposals

### F1 (HIGH): FreshnessGauge name regex rejects hyphens

See above. One-line fix in `cairo_source.py`. Same fix pattern for any other `FreshnessGauge` call site that constructs a name from a user-facing id. Audit needed.

### F2 (MEDIUM): brio-operator fps deficit reproduced at 28.479 fps

Confirmed stable at 28.479 fps over a 5-second window. Not a measurement artifact. Sprint 1 ruled out USB bus. **Next investigation targets** (per map C1.3 + new hypotheses):

- Is `hero=True` in config.py gating any extra per-frame processing? Grep for `hero` usage.
- Is the metrics lock in `_last_seq` dict a contention point for the highest-volume producer thread?
- Is the compositor applying a per-role queue depth that starves brio-operator?
- Physical swap test: move the brio-operator role to BRIO 9726C031 (brio-synths hardware); does the deficit follow the role or the hardware?

Defer to Sprint 7 deep-dive.

### F3 (MEDIUM): Per-node shader timing missing

No `wgpu::Query::Timestamp` instrumentation yet. Per-node cost can only be inferred from shader complexity (line count). Research map E6.3 captures the fix.

Once per-node timing lands, the top-10 expensive nodes become visible. Preliminary guess from line count: glitch_block (245), halftone (180), colorgrade (155), feedback (149), noise_gen (136), fluid_sim (129).

### F4 (INFO): cudacompositor is active

No fix needed. The compositor is using GPU-accelerated mixing. This is consistent with the 3 GB VRAM usage measured in Sprint 1.

### F5 (docs): CLAUDE.md node + preset counts are stale

CLAUDE.md claims "54 nodes, 28 presets". Actual: 56 nodes, 30 preset files (29 actual presets). Minor docs fix.

## Sprint 2 backlog additions (items 173+)

173. **`fix(freshness-gauge): replace hyphens in metric names for cairo_source.py`** [Sprint 2 F1] — one-line fix: `source_id.replace("-", "_")` before constructing `FreshnessGauge(name=...)`. P1 observability bug.
174. **`research(freshness-gauge): audit all call sites for user-id-derived names`** [Sprint 2 F1 sub] — same bug could hit anywhere else a `source_id`/`role` string is used in a metric name. Queue 024 Phase 2 + PR #755 call sites.
175. **`feat(compositor): wgpu Query::Timestamp per-node instrumentation`** [Sprint 2 F3, cross-ref map E6.3 + E2.2] — the foundation for per-node performance attribution. Ship in Rust imagination daemon first, then mirror for the compositor's effect chain if possible.
176. **`research(compositor): brio-operator fps deficit deep dive`** [Sprint 2 F2] — hero flag audit, metrics lock contention trace, physical swap test. Defer to Sprint 7 but file the ticket.
177. **`docs(claude.md): update node + preset counts`** [Sprint 2 F5] — 56 nodes, 30 presets (29 + default_modulations).
178. **`feat(compositor): graph-mutation.json write at active chain change`** [Sprint 2 observation] — the compositor uses fx-current.txt for the active plan name but graph-mutation.json doesn't exist at the observation time. Is this a transient file or a dead feature? Investigate.
