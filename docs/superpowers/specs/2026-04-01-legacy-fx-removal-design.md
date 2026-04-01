# Legacy GStreamer FX System Removal

**Date:** 2026-04-01
**Status:** Design
**Motivation:** The legacy GStreamer FX preset system (PRESETS dict, gleffects, temporalfx, crossfade, StutterElement, post_process.frag) is fully superseded by the graph-based effect system (SlotPipeline + 56 shader nodes + 30 graph presets). The legacy system causes active bugs: graph presets that have no legacy equivalent produce black frames because `switch_fx_preset()` runs unconditionally and leaves surrounding GStreamer elements unconfigured.

---

## Scope

**Phase 1 (this spec):** Remove all legacy FX backend code. Simplify the GStreamer pipeline to graph-only. Fix API. No frontend changes.

**Phase 2 (future spec):** Tear down and replace the entire effects/layers frontend UX (effectSources.ts, CameraHero effect rendering, effect picker UI, layer controls). Marked here for context but out of scope.

---

## Problem

1. `switch_fx_preset()` runs for every preset request, even when `try_graph_preset()` already loaded the graph. For graph-only presets (mirror_rorschach, sculpture, tunnelvision, etc.) it logs "Unknown FX preset" and returns without configuring gleffects/temporalfx/post_proc, leaving the pipeline producing black frames.
2. The legacy pipeline adds 5 unnecessary GStreamer elements (gleffects, temporalfx, crossfade, StutterElement, post_process glshader) between the SlotPipeline and the output tee. These waste GPU cycles even when graph mode is active.
3. Two parallel code paths for the same operation create maintenance burden and confusion.

---

## Solution

Remove the legacy FX system entirely. The graph system is a verified complete replacement:

- All 20 frontend effect sources have graph presets
- All 9 legacy visual effect categories (glow, edge detect, temporal feedback, stutter, VHS, thermal, halftone, ascii, pixsort) have graph node equivalents
- The SlotPipeline handles temporal effects via per-node `@accum_fb` texture, not GStreamer FBO
- Graph presets include their own postprocess/vignette nodes — no need for the surrounding legacy post_proc
- Zero tests reference the legacy system

---

## Changes

### 1. Delete files (3 files, ~550 lines)

| File | Lines | Contents |
|------|-------|----------|
| `agents/studio_effects.py` | 385 | PRESETS dict, EffectPreset/TrailConfig/ColorGradeConfig/WarpConfig/StutterConfig/PostProcessConfig dataclasses, `load_shader()`, `build_uniform_struct()` |
| `agents/studio_stutter.py` | 151 | Custom GStreamer `StutterElement` Python element |
| `agents/shaders/post_process.frag` | ~30 | Legacy post-process GLSL (vignette, scanlines, bands, syrup). Graph system has `postprocess` node in `shaders/nodes/` |

### 2. Delete legacy shaders from `agents/shaders/` (8 files)

These are duplicates of graph node shaders in `agents/shaders/nodes/`:

| Legacy file | Graph equivalent |
|-------------|-----------------|
| `ascii.frag` | `nodes/ascii.frag` |
| `color_grade.frag` | `nodes/colorgrade.frag` |
| `glitch_blocks.frag` | `nodes/glitch_block.frag` |
| `halftone.frag` | `nodes/halftone.frag` |
| `pixsort.frag` | `nodes/pixsort.frag` |
| `slitscan.frag` | `nodes/slitscan.frag` |
| `thermal.frag` | `nodes/thermal.frag` |
| `vhs.frag` | `nodes/vhs.frag` |

Keep `ambient_fbm.frag` and `slice_warp.frag` only if referenced elsewhere. If not, delete.

### 3. Rewrite `agents/studio_compositor/fx_chain.py`

**Remove:**
- All imports from `studio_effects`
- `StutterElement` creation and linking
- `gleffects` ("fx-glow") element
- `temporalfx` ("fx-temporal") element
- `crossfade` ("fx-crossfade") element
- Legacy `post_proc` glshader ("fx-post-process") and its shader loading
- All legacy state assignments: `_fx_temporal`, `_fx_crossfade`, `_fx_stutter`, `_fx_glow_effect`, `_fx_post_proc`, `_fx_active_preset`, `_fx_tick`
- The `_fx_graph_mode` flag (always graph now)

**Simplified `build_inline_fx_chain()` pipeline:**
```
pre_fx_tee → queue → videoconvert → capsfilter(RGBA) → glupload → glcolorconvert_in
  → [SlotPipeline: 8 glshader slots]
  → glcolorconvert_out → gldownload → videoconvert → output_tee
```

Six elements between SlotPipeline and output instead of eleven.

**Rewrite `fx_tick_callback()`:**
- Remove `PRESETS` import and lookup
- Remove all legacy uniform updates (post_proc bands, vignette, syrup)
- Keep: `tick_governance()`, `tick_modulator()`, `tick_slot_pipeline()` calls
- Compute `t` from a simple monotonic counter
- Compute `energy` and `b` (beat smoothing) from overlay state — this logic stays

### 4. Clean up `agents/studio_compositor/effects.py`

**Delete:** `switch_fx_preset()` function (lines 125-193) and its import of `studio_effects.PRESETS`.

**Keep:** `init_graph_runtime()`, `try_graph_preset()`, `GRAPH_PRESET_ALIASES`, `merge_default_modulations()`, `get_available_preset_names()`.

### 5. Clean up `agents/studio_compositor/state.py`

**Before (lines 131-153):**
```python
fx_request_path = SNAPSHOT_DIR / "fx-request.txt"
if fx_request_path.exists():
    preset_name = fx_request_path.read_text().strip()
    fx_request_path.unlink(missing_ok=True)
    if preset_name:
        graph_activated = False
        if compositor._graph_runtime is not None:
            graph_activated = try_graph_preset(compositor, preset_name)
        if hasattr(compositor, "_fx_post_proc"):
            switch_fx_preset(compositor, preset_name)
            if graph_activated:
                compositor._fx_graph_mode = True
        (SNAPSHOT_DIR / "fx-current.txt").write_text(preset_name)
```

**After:**
```python
fx_request_path = SNAPSHOT_DIR / "fx-request.txt"
if fx_request_path.exists():
    preset_name = fx_request_path.read_text().strip()
    fx_request_path.unlink(missing_ok=True)
    if preset_name and compositor._graph_runtime is not None:
        try_graph_preset(compositor, preset_name)
        (SNAPSHOT_DIR / "fx-current.txt").write_text(preset_name)
```

Remove `switch_fx_preset` import (line 68).

### 6. Clean up `agents/studio_compositor/compositor.py`

**`_on_graph_plan_changed()`** — remove crossfade trigger:
```python
# Before
def _on_graph_plan_changed(self, old_plan, new_plan):
    if old_plan is not None and hasattr(self, "_fx_crossfade") and self._fx_crossfade is not None:
        self._fx_crossfade.set_property("trigger", True)
    if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
        self._slot_pipeline.activate_plan(new_plan)
        self._fx_graph_mode = True

# After
def _on_graph_plan_changed(self, old_plan, new_plan):
    if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
        self._slot_pipeline.activate_plan(new_plan)
```

Remove `_fx_graph_mode` assignment — no longer needed.

### 7. Clean up `agents/studio_compositor/fx_tick.py`

**`tick_slot_pipeline()`** — remove `_fx_graph_mode` guard:
```python
# Before
def tick_slot_pipeline(compositor, t):
    if not compositor._fx_graph_mode or not compositor._slot_pipeline:
        return

# After
def tick_slot_pipeline(compositor, t):
    if not compositor._slot_pipeline:
        return
```

### 8. Fix API route `logos/api/routes/studio.py`

**`GET /studio/effect/current`** — replace hardcoded `available` list with dynamic scan:
```python
@router.get("/studio/effect/current")
async def get_current_effect():
    current_path = Path("/dev/shm/hapax-compositor/fx-current.txt")
    preset = "clean"
    if current_path.exists():
        try:
            preset = current_path.read_text().strip() or "clean"
        except OSError:
            pass
    from agents.studio_compositor.effects import get_available_preset_names
    available = sorted(get_available_preset_names())
    return {"preset": preset, "available": available}
```

**`POST /studio/effect/select`** — no changes needed. The fx-request.txt protocol is shared.

### 9. Clean up lifecycle.py

Line 101-102: Remove `hasattr` guard (SlotPipeline is always present after this change):
```python
# Before
if hasattr(compositor, "_slot_pipeline"):
    GLib.timeout_add(33, lambda: fx_tick_callback(compositor))

# After
GLib.timeout_add(33, lambda: fx_tick_callback(compositor))
```

---

## Phase 2 — Frontend Teardown (future, out of scope)

The following frontend code is **marked for teardown and replacement** in a subsequent spec:

| File | What | Why |
|------|------|-----|
| `hapax-logos/src/components/studio/effectSources.ts` | Hardcoded 20-source list, `sourceUrl()`, `selectEffect()`, `BACKEND_PRESET_MAP` | Should be dynamic from API, not hardcoded. Graph system has 30 presets. |
| `hapax-logos/src/components/terrain/ground/CameraHero.tsx` | Dual snapshot/HLS rendering, effect source switching, FX polling via `useSnapshotPoll` | Needs redesign for graph-native UX |
| `hapax-logos/src/hooks/useSnapshotPoll.ts` | Single-URL snapshot polling for FX stream | May be replaced by unified polling |
| `hapax-logos/src/contexts/GroundStudioContext.tsx` | `effectSourceId`, `activePreset`, `smoothMode` state | Effect model needs redesign |
| Effect picker UI (wherever it lives) | Preset selection interface | Should reflect full graph preset library, not legacy 20 |
| Layer controls | Content layer, visual surface integration | Needs redesign with graph-native model |

This frontend work will be designed in a separate brainstorming session after Phase 1 lands.

---

## Verification

1. `uv run ruff check agents/studio_compositor/ agents/studio_effects.py agents/studio_stutter.py` — confirm deleted files are gone, no broken imports
2. `uv run pytest tests/effect_graph/ -q` — graph system tests still pass
3. `grep -r "studio_effects\|switch_fx_preset\|StutterElement\|_fx_temporal\|_fx_glow\|_fx_stutter\|_fx_post_proc\|_fx_active_preset\|_fx_tick\b\|_fx_graph_mode" agents/ logos/` — zero hits
4. Restart `studio-compositor` service, verify:
   - Cameras render in thumbnails
   - Select "clean" preset — main viewport shows feed
   - Select "ghost" preset — temporal trail effect visible
   - Select "mirror_rorschach" — mirror effect visible (was black before)
   - FX snapshot at `/dev/shm/hapax-compositor/fx-snapshot.jpg` is non-black
5. `curl http://localhost:8051/api/studio/effect/current` — returns dynamic preset list
6. Frontend effect switching still works (selectEffect → fx-request.txt → graph preset)

---

## Risk

**Low.** The graph system is production-proven (running since PR #300). Zero tests break. The legacy code has zero test coverage. The only risk is a graph preset that doesn't cover some nuance of a legacy preset's behavior — but all 20 frontend presets have been running as graph presets for days.

**Rollback:** `git revert` the removal commit. The legacy code is self-contained.
