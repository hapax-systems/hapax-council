# Legacy GStreamer FX Removal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the legacy GStreamer FX preset system so only the graph-based effect pipeline remains.

**Architecture:** Delete `studio_effects.py`, `studio_stutter.py`, and legacy shaders. Rewrite `fx_chain.py` to build a simplified GStreamer pipeline (queue → glupload → SlotPipeline → gldownload → output_tee). Remove all legacy state variables and the `switch_fx_preset()` code path. Make the API preset list dynamic.

**Tech Stack:** Python 3.12, GStreamer (gi.repository), FastAPI, effect_graph module

**Spec:** `docs/superpowers/specs/2026-04-01-legacy-fx-removal-design.md`

---

### File Map

| Action | File | Responsibility after change |
|--------|------|-----------------------------|
| Delete | `agents/studio_effects.py` | — |
| Delete | `agents/studio_stutter.py` | — |
| Delete | `agents/shaders/post_process.frag` | — |
| Delete | `agents/shaders/ambient_fbm.frag` | — |
| Delete | `agents/shaders/slice_warp.frag` | — |
| Delete | `agents/shaders/ascii.frag` | — |
| Delete | `agents/shaders/color_grade.frag` | — |
| Delete | `agents/shaders/glitch_blocks.frag` | — |
| Delete | `agents/shaders/halftone.frag` | — |
| Delete | `agents/shaders/pixsort.frag` | — |
| Delete | `agents/shaders/slitscan.frag` | — |
| Delete | `agents/shaders/thermal.frag` | — |
| Delete | `agents/shaders/vhs.frag` | — |
| Rewrite | `agents/studio_compositor/fx_chain.py` | Simplified graph-only pipeline build + tick |
| Modify | `agents/studio_compositor/effects.py` | Graph runtime init + preset loading (no legacy) |
| Modify | `agents/studio_compositor/state.py` | Graph-only preset dispatch |
| Modify | `agents/studio_compositor/compositor.py` | Remove crossfade trigger + legacy state |
| Modify | `agents/studio_compositor/fx_tick.py` | Remove `_fx_graph_mode` guard |
| Modify | `agents/studio_compositor/lifecycle.py` | Remove `hasattr` guard |
| Modify | `logos/api/routes/studio.py` | Dynamic preset list |

---

### Task 1: Delete legacy files

**Files:**
- Delete: `agents/studio_effects.py`
- Delete: `agents/studio_stutter.py`
- Delete: `agents/shaders/post_process.frag`
- Delete: `agents/shaders/ambient_fbm.frag`
- Delete: `agents/shaders/slice_warp.frag`
- Delete: `agents/shaders/ascii.frag`
- Delete: `agents/shaders/color_grade.frag`
- Delete: `agents/shaders/glitch_blocks.frag`
- Delete: `agents/shaders/halftone.frag`
- Delete: `agents/shaders/pixsort.frag`
- Delete: `agents/shaders/slitscan.frag`
- Delete: `agents/shaders/thermal.frag`
- Delete: `agents/shaders/vhs.frag`

- [ ] **Step 1: Delete the files**

```bash
rm agents/studio_effects.py agents/studio_stutter.py
rm agents/shaders/post_process.frag agents/shaders/ambient_fbm.frag agents/shaders/slice_warp.frag
rm agents/shaders/ascii.frag agents/shaders/color_grade.frag agents/shaders/glitch_blocks.frag
rm agents/shaders/halftone.frag agents/shaders/pixsort.frag agents/shaders/slitscan.frag
rm agents/shaders/thermal.frag agents/shaders/vhs.frag
```

- [ ] **Step 2: Verify graph shader nodes are intact**

```bash
ls agents/shaders/nodes/*.frag | wc -l
# Expected: 53 (unchanged)
```

- [ ] **Step 3: Commit**

```bash
git add -u
git commit -m "chore: delete legacy FX preset system and duplicate shaders

Remove studio_effects.py (PRESETS dict, EffectPreset dataclasses),
studio_stutter.py (custom GStreamer element), and 11 legacy shaders
that are duplicated in agents/shaders/nodes/ for the graph system."
```

---

### Task 2: Rewrite fx_chain.py — simplified pipeline

**Files:**
- Rewrite: `agents/studio_compositor/fx_chain.py`

The new pipeline removes gleffects, temporalfx, crossfade, StutterElement, and the legacy post_proc glshader. The chain becomes:

```
pre_fx_tee → queue → videoconvert(RGBA) → capsfilter → glupload → glcolorconvert
  → [SlotPipeline: 8 slots]
  → glcolorconvert → gldownload → videoconvert → output_tee
```

- [ ] **Step 1: Rewrite fx_chain.py with graph-only pipeline**

Replace the entire file content with:

```python
"""Inline GPU effects chain and per-frame tick callback."""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


def build_inline_fx_chain(
    compositor: Any, pipeline: Any, pre_fx_tee: Any, output_tee: Any, fps: int
) -> bool:
    """Build graph-only GPU effects chain between pre_fx_tee and output_tee.

    Pipeline: queue → videoconvert → capsfilter(RGBA) → glupload → glcolorconvert
      → [SlotPipeline: 8 glshader slots]
      → glcolorconvert → gldownload → videoconvert → output_tee
    """
    Gst = compositor._Gst

    queue = Gst.ElementFactory.make("queue", "queue-fx")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 2)

    convert_rgba = Gst.ElementFactory.make("videoconvert", "fx-convert-rgba")
    rgba_caps = Gst.ElementFactory.make("capsfilter", "fx-rgba-caps")
    rgba_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGBA"))

    glupload = Gst.ElementFactory.make("glupload", "fx-glupload")
    glcolorconvert_in = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-in")

    from agents.effect_graph.pipeline import SlotPipeline

    registry = compositor._graph_runtime._registry if compositor._graph_runtime else None
    compositor._slot_pipeline = SlotPipeline(registry, num_slots=8)

    glcolorconvert_out = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-out")
    gldownload = Gst.ElementFactory.make("gldownload", "fx-gldownload")
    fx_convert = Gst.ElementFactory.make("videoconvert", "fx-out-convert")

    required = [
        queue,
        convert_rgba,
        rgba_caps,
        glupload,
        glcolorconvert_in,
        glcolorconvert_out,
        gldownload,
        fx_convert,
    ]
    for el in required:
        if el is None:
            log.error("Failed to create required FX element — effects disabled")
            return False

    for el in required:
        pipeline.add(el)

    queue.link(convert_rgba)
    convert_rgba.link(rgba_caps)
    rgba_caps.link(glupload)
    glupload.link(glcolorconvert_in)

    compositor._slot_pipeline.build_chain(
        pipeline, Gst, glcolorconvert_in, glcolorconvert_out
    )

    glcolorconvert_out.link(gldownload)
    gldownload.link(fx_convert)
    fx_convert.link(output_tee)

    tee_pad = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)

    log.info(
        "FX chain: graph-only pipeline with %d shader slots",
        compositor._slot_pipeline.num_slots,
    )
    return True


def fx_tick_callback(compositor: Any) -> bool:
    """GLib timeout: update graph shader uniforms at ~30fps."""
    if not compositor._running:
        return False
    if not hasattr(compositor, "_slot_pipeline") or compositor._slot_pipeline is None:
        return False

    from .fx_tick import tick_governance, tick_modulator, tick_slot_pipeline

    if not hasattr(compositor, "_fx_monotonic_start"):
        compositor._fx_monotonic_start = time.monotonic()
    t = time.monotonic() - compositor._fx_monotonic_start

    with compositor._overlay_state._lock:
        energy = compositor._overlay_state._data.audio_energy_rms
    beat = min(energy * 4.0, 1.0)
    if not hasattr(compositor, "_fx_beat_smooth"):
        compositor._fx_beat_smooth = 0.0
    compositor._fx_beat_smooth = max(beat, compositor._fx_beat_smooth * 0.85)
    b = compositor._fx_beat_smooth

    tick_governance(compositor, t)
    tick_modulator(compositor, t, energy, b)
    tick_slot_pipeline(compositor, t)

    return True
```

- [ ] **Step 2: Verify syntax**

```bash
uv run python -c "import ast; ast.parse(open('agents/studio_compositor/fx_chain.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add agents/studio_compositor/fx_chain.py
git commit -m "refactor: rewrite fx_chain.py to graph-only pipeline

Remove gleffects, temporalfx, crossfade, StutterElement, and legacy
post_proc glshader. Pipeline is now queue → glupload → SlotPipeline →
gldownload → output_tee. Tick callback uses monotonic time instead of
frame counter and drops all legacy uniform updates."
```

---

### Task 3: Remove switch_fx_preset from effects.py

**Files:**
- Modify: `agents/studio_compositor/effects.py:125-193`

- [ ] **Step 1: Delete the switch_fx_preset function**

Delete lines 125-193 (the entire `switch_fx_preset()` function). The file should end after `get_available_preset_names()` at line 122.

The remaining functions in the file are:
- `init_graph_runtime()` (keep)
- `try_graph_preset()` (keep)
- `merge_default_modulations()` (keep)
- `get_available_preset_names()` (keep)
- `GRAPH_PRESET_ALIASES` dict (keep)

- [ ] **Step 2: Verify no broken references within file**

```bash
uv run python -c "import ast; ast.parse(open('agents/studio_compositor/effects.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add agents/studio_compositor/effects.py
git commit -m "refactor: remove switch_fx_preset() from effects.py

Graph system handles all preset switching via try_graph_preset().
Legacy PRESETS dict import and GStreamer element manipulation removed."
```

---

### Task 4: Simplify state.py — graph-only preset dispatch

**Files:**
- Modify: `agents/studio_compositor/state.py:66-153`

- [ ] **Step 1: Remove legacy import and simplify FX request handling**

Remove the `from .effects import switch_fx_preset` import at line 68.

Replace the FX preset switch block (lines 131-153) with:

```python
        # FX preset switch requests
        fx_request_path = SNAPSHOT_DIR / "fx-request.txt"
        if fx_request_path.exists():
            try:
                preset_name = fx_request_path.read_text().strip()
                fx_request_path.unlink(missing_ok=True)
                if preset_name and compositor._graph_runtime is not None:
                    try_graph_preset(compositor, preset_name)
                    try:
                        (SNAPSHOT_DIR / "fx-current.txt").write_text(preset_name)
                    except OSError:
                        pass
            except Exception as exc:
                log.debug("Failed to process FX request: %s", exc)
                fx_request_path.unlink(missing_ok=True)
        time.sleep(1.0)
```

This removes:
- The `switch_fx_preset` import (line 68)
- The `graph_activated` variable
- The `hasattr(compositor, "_fx_post_proc")` check
- The `_fx_graph_mode` toggle

- [ ] **Step 2: Verify syntax**

```bash
uv run python -c "import ast; ast.parse(open('agents/studio_compositor/state.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add agents/studio_compositor/state.py
git commit -m "refactor: simplify state.py to graph-only preset dispatch

Remove switch_fx_preset import and call. FX request handler now only
calls try_graph_preset(). No more _fx_graph_mode toggle."
```

---

### Task 5: Clean up compositor.py — remove crossfade and legacy state

**Files:**
- Modify: `agents/studio_compositor/compositor.py:71-81`

- [ ] **Step 1: Simplify _on_graph_plan_changed**

Replace the method (lines 71-81) with:

```python
    def _on_graph_plan_changed(self, old_plan: Any, new_plan: Any) -> None:
        if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
            self._slot_pipeline.activate_plan(new_plan)
            log.info("Slot pipeline activated: %s", new_plan.name if new_plan else "none")
```

This removes:
- The `_fx_crossfade` check and trigger (lines 73-77)
- The `_fx_graph_mode = True` assignment (line 80)

- [ ] **Step 2: Verify syntax**

```bash
uv run python -c "import ast; ast.parse(open('agents/studio_compositor/compositor.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add agents/studio_compositor/compositor.py
git commit -m "refactor: remove crossfade trigger and _fx_graph_mode from compositor

Plan changes now directly activate the slot pipeline without triggering
the deleted crossfade element or setting legacy state flags."
```

---

### Task 6: Clean up fx_tick.py — remove _fx_graph_mode guard

**Files:**
- Modify: `agents/studio_compositor/fx_tick.py:111`

- [ ] **Step 1: Remove the _fx_graph_mode check**

Replace line 111:

```python
    if not compositor._fx_graph_mode or not compositor._slot_pipeline:
```

With:

```python
    if not compositor._slot_pipeline:
```

- [ ] **Step 2: Verify syntax**

```bash
uv run python -c "import ast; ast.parse(open('agents/studio_compositor/fx_tick.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add agents/studio_compositor/fx_tick.py
git commit -m "refactor: remove _fx_graph_mode guard from tick_slot_pipeline

Graph mode is always active now. Only check for _slot_pipeline existence."
```

---

### Task 7: Clean up lifecycle.py — remove hasattr guard

**Files:**
- Modify: `agents/studio_compositor/lifecycle.py:101-102`

- [ ] **Step 1: Remove the hasattr guard**

Replace lines 101-102:

```python
    if hasattr(compositor, "_slot_pipeline"):
        GLib.timeout_add(33, lambda: fx_tick_callback(compositor))
```

With:

```python
    GLib.timeout_add(33, lambda: fx_tick_callback(compositor))
```

- [ ] **Step 2: Verify syntax**

```bash
uv run python -c "import ast; ast.parse(open('agents/studio_compositor/lifecycle.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add agents/studio_compositor/lifecycle.py
git commit -m "refactor: always start FX tick callback

SlotPipeline is always present after fx_chain removal of legacy path."
```

---

### Task 8: Fix API — dynamic preset list

**Files:**
- Modify: `logos/api/routes/studio.py:319-348`

- [ ] **Step 1: Replace hardcoded available list with dynamic scan**

Replace the `get_current_effect` endpoint (lines 319-348) with:

```python
@router.get("/studio/effect/current")
async def get_current_effect():
    """Return the currently active visual effect preset name."""
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

- [ ] **Step 2: Verify syntax**

```bash
uv run python -c "import ast; ast.parse(open('logos/api/routes/studio.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add logos/api/routes/studio.py
git commit -m "refactor: dynamic preset list from graph preset directory

Replace hardcoded 17-preset available list with scan of presets/*.json
via get_available_preset_names(). Returns all 30 graph presets."
```

---

### Task 9: Lint, test, verify

**Files:** All modified files

- [ ] **Step 1: Ruff check**

```bash
uv run ruff check agents/studio_compositor/ logos/api/routes/studio.py
```

Fix any issues found.

- [ ] **Step 2: Ruff format**

```bash
uv run ruff format agents/studio_compositor/ logos/api/routes/studio.py
```

- [ ] **Step 3: Run effect graph tests**

```bash
uv run pytest tests/effect_graph/ -q
```

Expected: All pass (these test the graph system, not the deleted legacy system).

- [ ] **Step 4: Grep for any remaining legacy references**

```bash
grep -rn "studio_effects\|switch_fx_preset\|StutterElement\|_fx_temporal\|_fx_glow\|_fx_stutter\|_fx_post_proc\|_fx_active_preset\|_fx_graph_mode" agents/ logos/ --include="*.py" | grep -v __pycache__ | grep -v "design.md"
```

Expected: Zero hits. If any found, fix them.

- [ ] **Step 5: Grep for deleted file imports**

```bash
grep -rn "studio_stutter\|from agents.studio_effects\|load_shader" agents/ logos/ --include="*.py" | grep -v __pycache__
```

Expected: Zero hits.

- [ ] **Step 6: Commit lint fixes if any**

```bash
git add -u
git status
# Only commit if there are changes
git commit -m "style: lint fixes after legacy FX removal"
```

---

### Task 10: Restart compositor and verify

- [ ] **Step 1: Restart the compositor service**

```bash
systemctl --user restart studio-compositor
```

- [ ] **Step 2: Wait for pipeline to start, check logs**

```bash
sleep 3
journalctl --user -u studio-compositor --since "30 sec ago" --no-pager | tail -20
```

Expected: "FX chain: graph-only pipeline with 8 shader slots" in logs. No errors about missing elements.

- [ ] **Step 3: Verify FX snapshot is non-black**

```bash
sleep 2
identify -verbose /dev/shm/hapax-compositor/fx-snapshot.jpg 2>&1 | grep -E 'mean|Geometry'
```

Expected: Geometry 1920x1080, mean > 0 (non-black).

- [ ] **Step 4: Test preset switching via API**

```bash
# Select clean preset
curl -s -X POST http://localhost:8051/api/studio/effect/select \
  -H "Content-Type: application/json" -d '{"preset":"clean"}' && sleep 2
identify -verbose /dev/shm/hapax-compositor/fx-snapshot.jpg 2>&1 | grep mean

# Select ghost preset
curl -s -X POST http://localhost:8051/api/studio/effect/select \
  -H "Content-Type: application/json" -d '{"preset":"ghost"}' && sleep 2
identify -verbose /dev/shm/hapax-compositor/fx-snapshot.jpg 2>&1 | grep mean

# Select mirror_rorschach (was black before — this is the original bug)
curl -s -X POST http://localhost:8051/api/studio/effect/select \
  -H "Content-Type: application/json" -d '{"preset":"mirror_rorschach"}' && sleep 2
identify -verbose /dev/shm/hapax-compositor/fx-snapshot.jpg 2>&1 | grep mean
```

Expected: All three show mean > 0 (non-black frames).

- [ ] **Step 5: Verify dynamic preset list**

```bash
curl -s http://localhost:8051/api/studio/effect/current | python -m json.tool
```

Expected: `available` field contains ~30 presets (not the old hardcoded 17).

- [ ] **Step 6: Commit verification notes (if any fixes needed)**

If any fixes were required during verification, commit them.
