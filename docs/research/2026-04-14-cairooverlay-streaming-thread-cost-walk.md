# cairooverlay streaming-thread cost walk — base path + post-fx PiP

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Systematic walk of the two `cairooverlay`
elements in the fx chain, their `on_draw` callbacks,
and the CPU-side compositing work they do on the
GStreamer streaming thread. Drops #35/#36/#37/#38
covered the GPU-side fx chain and the Python
orchestration around it; this drop covers the Python
callbacks that block the streaming thread per frame.
**Register:** scientific, neutral
**Status:** investigation — 4 findings, 2
observability gaps. No code changed.
**Companion:** drop #30 (fx chain GPU↔CPU round
trips), drop #36 (threading model), drop #38
(SlotPipeline passthrough cost)

## Headline

**Two `cairooverlay` elements run Python callbacks on
the GStreamer streaming thread per frame**, blocking
the entire pipeline until each returns. The
compositor unification epic moved all rendering work
off the streaming thread to background runners —
correctly — but the **blit operations themselves are
still CPU-bound Cairo `paint()` calls** on full-canvas
surfaces.

**Two `cairooverlay` elements:**

1. **`overlay`** (fx_chain.py:318) — runs `on_draw`
   (`overlay.py:18`). Called on the BASE path
   BEFORE the shader chain. Blits 2 full-canvas
   (1920×1080) cached surfaces: Sierpinski +
   OverlayZoneManager.
2. **`pip_overlay`** (fx_chain.py:410) — runs
   `_pip_draw` (`fx_chain.py:198`) which calls
   `pip_draw_from_layout`. Runs AFTER the fx chain
   + gldownload. Blits N sources per layout
   assignment (typical: token_pole 300×300, album
   400×520, stream_overlay 400×200) via
   `blit_scaled`.

**Estimated streaming-thread cost per frame**
(Cairo software rasterizer, pixman SIMD-accelerated,
ARGB32 blends):

| Call | Blit size | Estimated ms |
|---|---|---|
| base on_draw — Sierpinski `cr.paint()` | 1920×1080 OVER | 3-5 |
| base on_draw — OverlayZones `cr.paint()` | 1920×1080 OVER | 3-5 |
| pip_overlay — token_pole `blit_scaled` | ~300×300 scaled | <1 |
| pip_overlay — album `blit_scaled` | ~400×520 scaled | <1 |
| pip_overlay — stream_overlay `blit_scaled` | ~400×200 scaled | <1 |
| **total streaming-thread callback time** | | **~7-13 ms/frame** |

**At 30 fps the frame budget is 33 ms.** These
callbacks consume **~20-40% of the streaming-thread
frame budget**. Not catastrophic, but significant —
and the Sierpinski + OverlayZones contribution is
dominated by full-canvas blits, not by any actual
overlay content.

**Nothing measures the actual per-callback latency.**
The comment in `sierpinski_renderer.py:379-380` says
"must be fast (<2ms)" but there's no histogram to
verify it. Drop #36 finding 5 noted the same
observability gap for GLib main-loop timers; this
drop extends the gap to the streaming-thread
callbacks.

## 1. The streaming-thread hot path

### 1.1 Base path cairooverlay (`overlay`)

`agents/studio_compositor/fx_chain.py:316-321`:

```python
from .overlay import on_draw, on_overlay_caps_changed

overlay = Gst.ElementFactory.make("cairooverlay", "overlay")
overlay.connect("draw", lambda o, cr, ts, dur: on_draw(compositor, o, cr, ts, dur))
overlay.connect("caps-changed", lambda o, caps: on_overlay_caps_changed(compositor, o, caps))
```

The `draw` callback fires on every frame that passes
through cairooverlay. The Python closure
`lambda o, cr, ts, dur: on_draw(...)` is invoked on
the streaming thread.

`agents/studio_compositor/overlay.py:18-39`:

```python
def on_draw(compositor: Any, overlay: Any, cr: Any, timestamp: int, duration: int) -> None:
    """Cairo draw callback -- renders Sierpinski triangle + Pango zone overlays."""
    if not compositor.config.overlay_enabled:
        return

    canvas_w, canvas_h = compositor._overlay_canvas_size

    # Sierpinski triangle with video content (drawn BEFORE GL effects apply)
    sierpinski = getattr(compositor, "_sierpinski_renderer", None)
    if sierpinski is not None:
        if hasattr(compositor, "_cached_audio"):
            sierpinski.set_audio_energy(compositor._cached_audio.get("mixer_energy", 0.0))
        loader = getattr(compositor, "_sierpinski_loader", None)
        if loader is not None:
            sierpinski.set_active_slot(loader._active_slot)
        sierpinski.draw(cr, canvas_w, canvas_h)

    # Render content overlay zones (markdown/ANSI from Obsidian via Pango)
    if hasattr(compositor, "_overlay_zone_manager"):
        compositor._overlay_zone_manager.render(cr, canvas_w, canvas_h)
```

**Two blit calls**: `sierpinski.draw(...)` and
`_overlay_zone_manager.render(...)`.

### 1.2 Each blit resolves to a full-canvas `cr.paint()`

`agents/studio_compositor/sierpinski_renderer.py:376-389`:

```python
def draw(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
    """Blit the pre-rendered output surface. Called from on_draw at 30fps.

    This method must be fast (<2ms) — it runs in the GStreamer streaming
    thread. All rendering happens in the background thread.
    """
    self._runner.set_canvas_size(canvas_w, canvas_h)

    surface = self._runner.get_output_surface()
    if surface is not None:
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
```

`agents/studio_compositor/overlay_zones.py:407-419`:

```python
def render(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> None:
    """Blit the pre-rendered output surface.

    This method runs on the GStreamer streaming thread and must stay
    under ~2ms. All content loading, Pango layout, and outlined-text
    rendering happens on the background runner thread.
    """
    self._runner.set_canvas_size(canvas_w, canvas_h)
    surface = self._runner.get_output_surface()
    if surface is None:
        return
    cr.set_source_surface(surface, 0, 0)
    cr.paint()
```

**Both call `cr.paint()` at 0,0** with the pre-rendered
background-thread surface as the source.

`set_source_surface` + `paint()` is a blend of the
source surface over the destination. Cairo defaults
to `OPERATOR_OVER` (alpha blend), which for ARGB32
pixels is:

```text
dst.rgb = src.rgb * src.a + dst.rgb * (1 - src.a)
dst.a   = src.a + dst.a * (1 - src.a)
```

Executed per-pixel across the full destination size.
For 1920×1080, that's **2,073,600 pixel blends per
blit**. At typical pixman SIMD speeds
(~100-300 pixels per cycle with SSE/AVX on x86-64),
**one full-canvas blit ≈ 3-5 ms on a modern desktop
CPU**.

Two blits per on_draw ≈ **6-10 ms per frame** just
for the base-path cairooverlay.

### 1.3 Post-fx cairooverlay (`pip_overlay`)

`agents/studio_compositor/fx_chain.py:410-414`:

```python
pip_overlay = Gst.ElementFactory.make("cairooverlay", "pip-overlay")
pip_overlay.connect("draw", lambda o, cr, ts, dur: _pip_draw(compositor, cr))
pipeline.add(pip_overlay)
fx_convert.link(pip_overlay)
pip_overlay.link(output_tee)
```

`agents/studio_compositor/fx_chain.py:198-211`:

```python
def _pip_draw(compositor: Any, cr: Any) -> None:
    layout_state = getattr(compositor, "layout_state", None)
    source_registry = getattr(compositor, "source_registry", None)
    if layout_state is not None and source_registry is not None:
        pip_draw_from_layout(cr, layout_state, source_registry)
```

`pip_draw_from_layout` (fx_chain.py:61-105):

```python
def pip_draw_from_layout(cr, layout_state, source_registry) -> None:
    layout = layout_state.get()
    pairs: list[tuple[Any, Any]] = []
    for assignment in layout.assignments:
        surface_schema = layout.surface_by_id(assignment.surface)
        if surface_schema is None:
            continue
        if surface_schema.geometry.kind != "rect":
            continue
        pairs.append((assignment, surface_schema))
    pairs.sort(key=lambda p: p[1].z_order)

    for assignment, surface_schema in pairs:
        try:
            src = source_registry.get_current_surface(assignment.source)
        except KeyError:
            continue
        if src is None:
            continue
        blit_scaled(
            cr,
            src,
            surface_schema.geometry,
            opacity=assignment.opacity,
            blend_mode=surface_schema.blend_mode,
        )
```

Per-frame work:
- Walk `layout.assignments` (typically 3-5 entries)
- Sort by z_order
- For each, look up the source's `get_current_surface`
  (cross-thread lock)
- Call `blit_scaled` which does scale + paint

### 1.4 `blit_scaled` does full Cairo transformation

`agents/studio_compositor/fx_chain.py:21-58`:

```python
def blit_scaled(cr, src, geom, opacity, blend_mode) -> None:
    if geom.kind != "rect":
        return
    cr.save()
    cr.translate(geom.x or 0, geom.y or 0)
    src_w = max(src.get_width(), 1)
    src_h = max(src.get_height(), 1)
    sx = (geom.w or src_w) / src_w
    sy = (geom.h or src_h) / src_h
    cr.scale(sx, sy)
    cr.set_source_surface(src, 0, 0)
    pattern = cr.get_source()
    try:
        pattern.set_filter(cairo.FILTER_BILINEAR)
    except Exception:
        log.debug("cairo FILTER_BILINEAR unavailable on this pattern", exc_info=True)
    if blend_mode == "plus":
        cr.set_operator(cairo.OPERATOR_ADD)
    else:
        cr.set_operator(cairo.OPERATOR_OVER)
    cr.paint_with_alpha(opacity)
    cr.restore()
```

- `cr.save()`/`cr.restore()` — stack push/pop
- `cr.translate()`/`cr.scale()` — CTM updates (cheap)
- `set_source_surface` + `FILTER_BILINEAR` — bilinear
  sampling (4 texel reads per destination pixel)
- `paint_with_alpha` — same as paint() but with
  global alpha multiplier

**Bilinear scaling doubles or triples per-pixel cost**
vs nearest-neighbor. For a 200×200 source scaled to
400×400 on 1920×1080 canvas:

- Destination pixels = 400×400 = 160,000
- Per-pixel cost with bilinear ≈ 4 texel reads + blend
- Total ≈ 160,000 × ~8-16 cycles = **1-3 ms per PiP
  blit**

With 3-5 PiP elements per layout, **pip_overlay cost
≈ 3-15 ms per frame**.

## 2. Findings

### 2.1 Finding 1 — streaming-thread Cairo cost is
significant but unmeasured

Sum of estimated Cairo work per frame on the
streaming thread:

- base path `on_draw`: **6-10 ms** (Sierpinski +
  OverlayZones full-canvas blits)
- post-fx `_pip_draw`: **3-15 ms** (N PiP blits with
  bilinear scaling)
- **Total: 9-25 ms per frame**

At 30 fps frame budget of 33 ms, this is **27-76% of
the frame budget**. The variance is wide because
post-fx PiP count depends on the layout.

**Nothing measures this today.** Sierpinski and
OverlayZones both have `<2ms` guidance comments but
no histogram. pip_draw_from_layout has no comment
AND no histogram.

**Fix (observability, ring 1)**: wrap each callback
with a timing probe and export as histograms:

```python
_BASE_ON_DRAW_MS = Histogram("compositor_overlay_base_on_draw_ms", ...)
_PIP_DRAW_MS = Histogram("compositor_overlay_pip_draw_ms", ...)

def on_draw(compositor, overlay, cr, ts, dur) -> None:
    t0 = time.monotonic()
    try:
        # ... existing work ...
    finally:
        _BASE_ON_DRAW_MS.observe((time.monotonic() - t0) * 1000)
```

~10 lines per callback, two callbacks. Closes the
single biggest observability gap in the streaming
thread hot path.

### 2.2 Finding 2 — base path blits are full-canvas

Both Sierpinski and OverlayZones `render()` surfaces
are allocated at `canvas_w × canvas_h = 1920 × 1080`
(`_runner.set_canvas_size(canvas_w, canvas_h)` passes
the full canvas). Each `cr.paint()` blits the entire
1920×1080 surface over the destination.

**If the overlay content occupies only a fraction of
the canvas** (e.g., Sierpinski triangle at 75% of
canvas height, ~150×150 circles for vertices, sparse
text zones), the vast majority of the blit pixels are
transparent and contribute nothing. But Cairo's
`paint()` still processes every pixel in the source
rectangle — it can't cheaply skip transparent regions.

**Two potential fixes:**

- **Ring 3 architectural**: have Sierpinski and
  OverlayZones render at smaller natural sizes
  (their actual content-containing rect) and use
  `blit_scaled` (with scaling) to place them on the
  canvas. Saves pixel blend work proportional to
  (natural_area / canvas_area). For Sierpinski at
  640×640 natural size instead of 1920×1080, this
  is a 9× reduction in blit pixels.
- **Ring 3 architectural**: use clipping
  (`cr.rectangle(x, y, w, h); cr.clip()`) around
  known content bounds before `paint()`. Cairo's
  rasterizer honors clip regions and skips
  outside-bounds pixels.

Both would require the render functions to expose
their content bounding box. Non-trivial but
achievable.

### 2.3 Finding 3 — bilinear scaling in `blit_scaled`
doubles pip cost

`blit_scaled` sets `FILTER_BILINEAR` explicitly. This
is the right choice for quality (prevents aliasing
when scaling up or down by non-integer factors) but
doubles the per-pixel cost vs `FILTER_NEAREST`.

For small PiPs the absolute cost is <1 ms per blit,
so the quality win is worth the cost. **No change
recommended** — just documenting the cost model.

### 2.4 Finding 4 — the base cairooverlay sits on CPU
memory between two GL operations

The base path topology:

```text
input_selector → queue → cairooverlay (CPU, our on_draw) → videoconvert → glupload → glcolorconvert → glvideomixer
```

`cairooverlay` operates on `GstVideoFrame` memory
(CPU). The frame arrives from the input_selector
on CPU. cairooverlay does its CPU-side compositing.
Then `videoconvert` (CPU-side format conversion) →
`glupload` (CPU→GPU) → `glcolorconvert` (GPU).

**Each frame costs a full CPU→GPU upload AFTER the
Cairo compositing** — the 1920×1080 BGRA frame gets
uploaded to the GPU via glupload.

Drop #30 already flagged this as part of the fx chain
round-trip audit. This drop reaffirms: the
cairooverlay's CPU-side blits force the base path to
stay on CPU memory right until the GL chain starts.

**Alternative architecture**: move the overlays into
GL via `glshader` or `gldmabufimport`. The Sierpinski
geometry + text zones would render as textures
uploaded once at content-change events, then
composited with `glvideomixer` pads at zero CPU cost
per frame. This is a larger refactor and is not in
scope for this drop.

## 3. Observability gaps

1. **No per-callback latency histogram** — finding 1.
   ~20 lines of code, free observability.
2. **No cairooverlay frame-drop metric.** If the
   streaming thread is blocked too long, downstream
   `queue` elements with `leaky=downstream` drop
   frames silently. A counter
   `compositor_cairooverlay_blit_overrun_total{element}`
   incremented when latency > frame_budget would
   surface this.

## 4. Ring summary

### Ring 1 — observability

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **OVL-1** | Per-callback latency histograms (base + pip) | `metrics.py` + `overlay.py` + `fx_chain.py:_pip_draw` | ~30 | Streaming-thread cost becomes scrape-visible |
| **OVL-2** | Blit-overrun counter (observation > frame budget) | Same as OVL-1 | ~10 | Frame-drop root cause isolation |

### Ring 2 — tuning

No Ring 2 items. The current architecture is correct;
the only wins are observability first, then architecture.

### Ring 3 — architectural (deferred until OVL-1
data is available)

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **OVL-3** | Sierpinski + OverlayZones render at natural size + blit_scaled | `sierpinski_renderer.py`, `overlay_zones.py`, `overlay.py` | ~20 | Reduces blit pixel count by up to 9× |
| **OVL-4** | Cairo clip regions around known content bounds | Same | ~30 | Additional skip of transparent regions |
| **OVL-5** | Move overlays to GL via `glshader` or `gldmabufimport` | Large refactor | >200 | Zero CPU cost per frame |

## 5. Cumulative impact estimate

**Ring 1 (observability) is the only shippable
action today.** Ring 3 requires Ring 1 data first to
decide if it's worth shipping.

**If OVL-1 shows latency consistently <5 ms per frame**:
the current architecture is fine. Ring 3 is deferred
indefinitely.

**If OVL-1 shows latency consistently >10 ms per
frame**: Ring 3 OVL-3 + OVL-4 become the next
architectural work.

**If OVL-1 shows spikes above frame budget**: OVL-2
(the overrun counter) will surface them, and the fix
priority jumps to Ring 3 OVL-5 (GL migration).

Combined with prior drops' estimates:

- Drop #31 Ring 1+2: ~900 MB/s CPU↔GPU
- Drop #32 Ring 1+2: ~33 MB/s
- Drop #36 Ring 2: ~275-350 MB/s CPU memory
- Drop #38 Ring 3: ~6 GB/s GPU memory
- **Drop #39 Ring 1: observability (prerequisite for
  Ring 3 decisions)**

## 6. Cross-references

- `agents/studio_compositor/fx_chain.py:21-58` —
  `blit_scaled` helper
- `agents/studio_compositor/fx_chain.py:61-105` —
  `pip_draw_from_layout`
- `agents/studio_compositor/fx_chain.py:198-211` —
  `_pip_draw`
- `agents/studio_compositor/fx_chain.py:316-321` —
  `cairooverlay` base path creation
- `agents/studio_compositor/fx_chain.py:410-414` —
  `pip_overlay` post-fx creation
- `agents/studio_compositor/overlay.py:18-39` —
  `on_draw` base path callback
- `agents/studio_compositor/sierpinski_renderer.py:376-389`
  — Sierpinski blit
- `agents/studio_compositor/overlay_zones.py:407-419`
  — OverlayZones blit
- Drop #30 — fx chain GPU↔CPU audit (covered the
  glupload/gldownload boundaries)
- Drop #36 finding 5 — GLib main-loop latency
  observability gap (same gap class as finding 1
  here)
- Drop #38 — 24-slot fx chain passthrough cost (Ring
  3 Option A decision depends on GPU headroom which
  depends in part on cairooverlay streaming-thread
  time here)

## 7. Open question for operator

**Does the operator observe any streaming-thread
stutter in the livestream output today?** If yes,
this drop's OVL-1 + OVL-2 become the first step to
isolating whether it's cairooverlay, fx chain, or
somewhere else. If no, the current architecture is
working fine and Ring 3 is pure optimization without
clear benefit.
