# Non-Destructive Overlay Effects Layer — Design Spec

**CVS task:** #157
**Upstream:** #18 · **Cross-refs:** #128 (preset variety expansion), #150 (video/image classification), #124 (reverie preservation)
**Source research:** `/tmp/cvs-research-157.md` (2026-04-18)
**Status:** SPEC

---

## 1. Goal

Operator (2026-04-06):

> "We need the overlay to be part of it's own contained effects layer that is interesting in and of itself but does not get gobbled up by the effects beneath it... combinations of non-destructive effects. Not necessarily MILD in combination, but something that won't distort the video so severely that it's not indicative of its underlying content."

Tag-gated enforcement so overlay-zone content (the `content_layer` WGSL node compositing inside the shader graph) only receives non-destructive effects. The overlay layer must stay **visually interesting in itself** — strong combinations are allowed — while preserving indication of the underlying video content.

## 2. Two Senses of "Overlay"

- **Cairo overlay zones** — `OverlayZoneManager` (`agents/studio_compositor/overlay_zones.py`). Pango markdown/ANSI + PNGs blitted via `cairooverlay` at the pipeline tail, already post-shader. **NOT the subject of this task** — pure chrome.
- **`content_layer` WGSL node** — `agents/shaders/nodes/content_layer.wgsl`. Video-ish overlay: Sierpinski/YouTube frames, album art, detection crops routed into `content_slot_{0..3}` textures, composited **inside** the WGSL graph. **THIS IS the subject.** The content-bearing overlay zone.

## 3. Current Preset Topology (Problem)

Stable across all 28 presets:

```
@live → [effect1] → [effect2] → ... → [effectN] → content_layer → postprocess → out
```

`content_layer` sits between the main effect chain and postprocess. Content slots sample `textureSample(content_slot_k, …)` against a `tex` binding that is the **post-effect stream**. A `vhs → scanlines → noise → vignette → content_layer` chain blends overlay content onto an already-VHS'd base — the upstream destructive chain "gobbles up" the overlay content via screen-blend inheritance. **No separation between effects-on-video and effects-on-overlay exists today.**

## 4. Shader Classification (56 nodes under `agents/shaders/nodes/`)

Criterion: "won't distort such that content is not indicative of its underlying."

**Non-destructive (~23)** — preserve content legibility:
`colorgrade`, `vignette`, `scanlines`, `noise_overlay`, `bloom`, `dither`, `posterize`, `vhs`, `sharpen`, `breathing`, `invert`, `emboss`, `strobe`, `color_map`, `solid`, `circular_mask`, `chroma_key`, `luma_key`, `sierpinski_content`, `sierpinski_lines`, `waveform_render`, `postprocess` (defaults), subtle-offset `chromatic_aberration`. Representative combinations: alpha tint, vignette, scanlines, CRT glow, subtle chroma, dust/grain, edge-preserving stylize.

**Destructive (~24)** — distort or replace content:
`feedback`, `reaction_diffusion`, `fluid_sim`, `droste`, `kaleidoscope`, `tunnel`, `fisheye`, `warp`, `mirror`, `pixsort`, `slitscan`, `glitch_block`, `stutter`, `trail`, `echo`, `displacement_map`, `rutt_etra`, `halftone`, `syrup`, `ascii`, `thermal`, `drift`, `voronoi_overlay`, `tile`. Covers feedback, RD, distortion, heavy flow, post-aggressive color remap, melt.

**Borderline (~5, parameter-dependent)** — need bounded params baked into the tag:
`chromatic_aberration` (safe if `offset < 4px`), `threshold`, `transform`, `particle_system`, `edge_detect`.

Utility nodes (`blend`, `crossfade`, `content_layer`, `noise_gen`) inherit from inputs / are N/A.

## 5. Tag Mechanism

**Author-claim, verifier-enforced.** Author tags the preset; loader verifies the graph respects the claim.

- **`EffectGraph` pydantic model** (`agents/effect_graph/types.py`): new `tags: list[str] = []` field.
- **`LoadedShaderDef`** (`agents/effect_graph/registry.py`): new `destructive: bool` flag plus optional `borderline_params: dict[str, {min, max}]`.
- **New file `agents/effect_graph/destructive_taxonomy.json`** — operator-editable source of truth. Keyed by node_type:
  ```json
  { "vignette":          { "destructive": false },
    "feedback":          { "destructive": true  },
    "chromatic_aberration": {
      "destructive": false,
      "borderline_params": { "offset_x": { "max": 4 }, "offset_y": { "max": 4 } }
    } }
  ```
- **Preset JSON** gains `tags` array. Preset author claims `non_destructive_overlay`; the loader verifies every node is whitelisted (and borderline params are in-range).

Additional tag vocabulary (cross-refs #128): `destructive_full_frame`, `satellite_only`, `temporal_stable`, `low_motion`.

## 6. Enforcement Surfaces (3)

All three tag-gated. Gate: **reject when zone is `overlay`/`content_layer` AND preset lacks `non_destructive_overlay` tag, OR preset claims the tag but fails node-whitelist verification.**

1. **`agents/studio_compositor/effects.py::try_graph_preset`** — central loader. Validate tag claim against the destructive-taxonomy whitelist after `EffectGraph(**raw)`. Reject with log on mismatch.
2. **`agents/studio_compositor/chat_reactor.py::_maybe_apply_preset`** — keyword dispatch. Zone-scoped: if the target zone is overlay/content_layer and the matched preset lacks the tag, reject silently (log, no stream change).
3. **`agents/studio_compositor/twitch_director.py` + `compositional_consumer.py::dispatch_overlay_emphasis`** — director recruitment. Filter candidate pool by tag before random selection under mood modulation.

```python
def apply_preset_to_zone(zone: str, preset_name: str) -> bool:
    graph = load_preset_graph(preset_name)
    if zone in ("overlay", "content_layer"):
        if "non_destructive_overlay" not in graph.tags:
            log.warning("rejected %s on overlay zone (no non_destructive_overlay tag)", preset_name)
            return False
        if not _verify_node_whitelist(graph):
            log.warning("rejected %s: tag claimed but graph contains destructive node", preset_name)
            return False
    return _commit_preset(zone, graph)
```

## 7. Test Strategy

New: `tests/effect_graph/test_non_destructive_overlay_ssim.py`.

- **Content-preservation floor:** render a 5s static-camera talking-head YouTube reference clip (720p, high spatial detail) through a headless `DynamicPipeline` with each preset `P` where `"non_destructive_overlay" in P.tags`. For 10 sampled frames, `SSIM(rendered, reference)`. Assert mean **SSIM ≥ 0.6**. Permissive bar: "stylized but recognizable."
- **Temporal-stability floor:** `SSIM(first_frame, last_frame) ≥ 0.3` on the rendered stream. Catches feedback/trail-style compound drift (preset may pass instantaneous SSIM but degenerate over time).
- **Tag-violation tests:** construct a preset that tags `non_destructive_overlay` but includes a blacklisted node (`feedback`) — loader must reject. Construct one with `chromatic_aberration.offset_x = 12` — loader must reject (borderline bounds violation).

CI: runs under `uv run pytest tests/effect_graph/ -q`. No LLM involvement; exempt from default LLM exclusion.

## 8. File-Level Plan

| File | Change |
|---|---|
| `agents/effect_graph/destructive_taxonomy.json` | NEW. Per-node `destructive` + `borderline_params`. Single source of truth. |
| `agents/effect_graph/types.py` | ADD `tags: list[str]` to `EffectGraph`. |
| `agents/effect_graph/registry.py` | ADD `destructive: bool` (+ `borderline_params`) on `LoadedShaderDef`; load from taxonomy JSON. |
| `agents/studio_compositor/effects.py` | Tag validation in `try_graph_preset` + node-whitelist verifier. |
| `agents/studio_compositor/chat_reactor.py` | Zone-scoped rejection in `_maybe_apply_preset`. |
| `agents/studio_compositor/twitch_director.py` | Tag-filter recruitment candidate pool. |
| `agents/studio_compositor/compositional_consumer.py` | `dispatch_overlay_emphasis` consults tag before dispatch. |
| `tests/effect_graph/test_non_destructive_overlay_ssim.py` | NEW. SSIM + temporal + tag-violation tests. |
| Preset JSONs | ADD `tags` field on existing presets that qualify (curation pass). |

## 9. Implementation Order

1. **Classification JSON first** (`destructive_taxonomy.json`) — operator-editable, no code dependencies. Enables review/curation before any gating turns on.
2. **Model fields** — `tags` on `EffectGraph`, `destructive` on `LoadedShaderDef`. Populate from taxonomy at registry load.
3. **Enforcement** — gate at the three surfaces (`effects.py`, `chat_reactor.py`, `twitch_director.py` + `compositional_consumer.py`).
4. **Test suite** — SSIM + temporal-stability + tag-violation tests.
5. **Preset curation pass** — tag existing presets that already qualify; flag ones that don't.

## 10. Open Questions

1. Should `content_layer` stay between effect chain and `postprocess`, or should the overlay-content path be **extracted into a second parallel graph** that composites at the end? A parallel path isolates overlay effects completely; current architecture still bleeds destructive upstream effects into the `tex` base even under tag gating. V1 recommendation: keep current topology, enforce tag. V2 consider parallel-graph refactor.
2. Two tiers (`strict` SSIM ≥ 0.85 vs `stylized` SSIM ≥ 0.6)? Research recommends single tier at 0.6 — operator explicitly said "NOT necessarily MILD."
3. Author source for new `non_destructive_overlay` presets — human curation (V1) vs tool-assisted variety expansion (V2, via #128).

## 11. Related

Pairs naturally with **#128 preset variety expansion** — #157 defines the tag system + gate; #128 populates the `non_destructive_overlay` pool to ≥6 presets. Without #128 the tag-gated pool may be too sparse for director recruitment to rotate meaningfully. With the tag system, variety becomes measurable ("we have N presets tagged `non_destructive_overlay`, M tagged `satellite_only`, …") and the director can recruit-by-mood rather than recruit-by-name. Also parallel to **#124** (reverie preservation) on the imagination side and **#150** (video/image classification) for content-preservation floor validation.
