# Sierpinski renderer per-tick cost walk

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Deep dive on `SierpinskiCairoSource.render()` — the
single most expensive Cairo source in the live BudgetTracker
snapshot. `costs.json` at 2026-04-14 ~14:45 showed
**last_ms=27.9, avg_ms=34.0, p95_ms=65.6** for
`sierpinski-lines`. Drop #41 found this running live; this
drop audits what's inside it.
**Register:** scientific, neutral
**Status:** investigation — 5 findings, 2 architectural options
**Companion:** drop #39 (cairooverlay streaming-thread cost),
drop #41 (BudgetTracker wiring audit which surfaced the live
numbers)

## Headline

**sierpinski-lines averages 34 ms per render tick, p95 is
65.6 ms.** The source targets 10 fps (100 ms period per
`RENDER_FPS = 10` in `sierpinski_renderer.py:33`). At p95 it
consumes **66% of its tick budget**; at p99 (not recorded but
inferable from the shape) it likely exceeds the budget. This
is the single biggest consumer of CPU time on the compositor's
7 Cairo render threads.

**The cost breakdown per tick:**

1. Load 3 YouTube frame JPEGs (mtime-cached, ~0 ms when stable)
2. Compute 1 main triangle + 3 level-1 subdivisions + 12
   level-2 subdivisions + 1 center void = **17 triangles total**
3. Blit 3 YouTube frames into the 3 corner triangles with
   clip + scale + `paint_with_alpha`
4. Draw 8 waveform bars in the center void (cheap rectangles)
5. **Stroke each of the 17 triangles TWICE** — once as a glow
   (line_width × 3, alpha 0.15) and once as a core (line_width
   × 1, alpha 0.8) — for **34 stroke operations per tick**

The 34 stroke operations are the dominant cost. Cairo's
software rasterizer stroking with anti-aliasing + alpha
blending on wide lines (up to ~4.5 px glow width) on a
**1920×1080 canvas** is expensive — each stroke has to
rasterize and composite a significant pixel count along the
stroke path.

## 1. The render function

`agents/studio_compositor/sierpinski_renderer.py:64-116`:

```python
def render(self, cr, canvas_w, canvas_h, t, state) -> None:
    fw = float(canvas_w)
    fh = float(canvas_h)

    # Main triangle (75% of height, slightly above center)
    tri = self._get_triangle(fw, fh, scale=0.75, y_offset=-0.02)

    # Level 1 subdivision: 3 corners + center void
    m01 = self._midpoint(tri[0], tri[1])
    m12 = self._midpoint(tri[1], tri[2])
    m02 = self._midpoint(tri[0], tri[2])

    corner_0 = [tri[0], m01, m02]    # top
    corner_1 = [m01, tri[1], m12]    # bottom-left
    corner_2 = [m02, m12, tri[2]]    # bottom-right
    center = [m01, m12, m02]         # center void

    # Load and draw video frames in corner triangles
    for slot_id, corner in enumerate([corner_0, corner_1, corner_2]):
        frame_surface = self._load_frame(slot_id)
        opacity = 0.9 if slot_id == self._active_slot else 0.4
        self._draw_video_in_triangle(cr, frame_surface, corner, opacity)

    # Waveform in center
    self._draw_waveform(cr, center, self._audio_energy)

    # Level 2 subdivision lines (inside corners)
    all_triangles = [tri, corner_0, corner_1, corner_2, center]

    # Subdivide corners for level 2 line detail
    for corner in [corner_0, corner_1, corner_2]:
        cm01 = self._midpoint(corner[0], corner[1])
        cm12 = self._midpoint(corner[1], corner[2])
        cm02 = self._midpoint(corner[0], corner[2])
        all_triangles.extend([
            [corner[0], cm01, cm02],
            [cm01, corner[1], cm12],
            [cm02, cm12, corner[2]],
            [cm01, cm12, cm02],
        ])
    # all_triangles now has 5 + (3 corners × 4 sub-triangles) = 17

    # Draw line work with audio-reactive width
    line_w = 1.5 + self._audio_energy * 2.0
    self._draw_triangle_lines(cr, all_triangles, line_w, t)
```

### 1.1 `_draw_triangle_lines` — the hot loop

`sierpinski_renderer.py:272-301`:

```python
def _draw_triangle_lines(self, cr, triangles, line_width, t) -> None:
    for i, tri in enumerate(triangles):
        color_idx = (i + int(t * 0.5)) % len(COLORS)
        r, g, b = COLORS[color_idx]

        # Glow (wider, semi-transparent)
        cr.set_line_width(line_width * 3.0)
        cr.set_source_rgba(r, g, b, 0.15)
        cr.move_to(*tri[0])
        cr.line_to(*tri[1])
        cr.line_to(*tri[2])
        cr.close_path()
        cr.stroke()

        # Core line
        cr.set_line_width(line_width)
        cr.set_source_rgba(r, g, b, 0.8)
        cr.move_to(*tri[0])
        cr.line_to(*tri[1])
        cr.line_to(*tri[2])
        cr.close_path()
        cr.stroke()
```

**17 triangles × 2 strokes = 34 stroke operations per tick.**

Each stroke:
- Glow: `line_width × 3.0 ≈ 4.5 px` (with `line_width = 1.5 +
  audio_energy × 2.0`, max ~10.5 px at peak audio)
- Core: `line_width × 1.0 ≈ 1.5-3.5 px`

The main triangle (index 0) has edges of length ~1050 px
(0.75 × 1080 × 1.3 for 75%-of-height triangle base). Stroking
a 4.5 px wide line along a 1050 px path anti-aliased in
software is non-trivial — roughly ~5000-10000 pixels per edge
× 3 edges = ~30k pixels per main triangle glow stroke.

Subdivided triangles are proportionally smaller, but the
count multiplies.

**Aggregate pixel touch count per tick** (rough):
- 1 main triangle: 3 edges × 1050 px × 4.5 px wide ≈ 14k
  pixels for glow stroke + 5k for core = ~19k
- 3 level-1 corners: each ~half size, so ~9k glow + 2.5k core
  = ~11k × 3 = ~33k
- 1 center void: same as level-1 corners ≈ 11k
- 12 level-2 sub-triangles: each ~quarter size of level-1,
  ~5k each × 12 = ~60k
- **Total: ~125k pixels/tick touched by stroke operations**

At Cairo software rasterizer throughput (~2-5M pixels/sec for
anti-aliased alpha-blended strokes), 125k pixels ≈ 25-60 ms
per tick. **Matches observed 34 ms mean / 65 ms p95.**

## 2. Findings

### 2.1 Finding 1 — full-canvas 1920×1080 render, but
natural size is 640×640

The layout config `config/compositor-layouts/default.json`
declares:

```json
{
  "id": "sierpinski",
  "kind": "cairo",
  "backend": "cairo",
  "params": {
    "class_name": "SierpinskiCairoSource",
    "natural_w": 640,
    "natural_h": 640
  }
}
```

**Natural size is 640×640**, but the live `sierpinski-lines`
runner is invoked from `SierpinskiRenderer.__init__` with
`canvas_w=1920, canvas_h=1080` (hardcoded, see
`sierpinski_renderer.py:355-359`):

```python
self._runner = CairoSourceRunner(
    source_id="sierpinski-lines",
    source=self._source,
    canvas_w=1920,
    canvas_h=1080,
    target_fps=RENDER_FPS,
    budget_tracker=budget_tracker,
)
```

This is the **legacy facade path** (drop #41 finding 1) — the
one that's actually running. The layout-declared `sierpinski`
source with natural 640×640 is NOT started (drop #41 finding
1), so the live sierpinski render is always at 1920×1080.

**If the legacy facade rendered at 640×640 instead of
1920×1080**, the stroke pixel count drops by `(640×640) /
(1920×1080) = 0.197`, i.e. **~80% reduction in pixel touch
count**. Estimated new render time: ~7-13 ms per tick,
comfortably within the 100 ms tick budget.

**Trade-off**: the cairooverlay blit would then need to
scale 640×640 → 1920×1080 during the `cr.paint()` call on the
streaming thread. That scaling cost is modest (Cairo bilinear
is fast) and lands on the streaming thread (the 2 ms budget
side). The net move is **from 34 ms/tick on the background
thread to ~7-13 ms/tick on the background thread + ~1-2 ms
scaling on the streaming thread**.

### 2.2 Finding 2 — dynamic `gi.require_version` imports in
the hot path

`_load_frame` (sierpinski_renderer.py:118-148):

```python
def _load_frame(self, slot_id):
    ...
    try:
        mtime = path.stat().st_mtime
        if mtime == self._frame_mtimes.get(slot_id, 0):
            return self._frame_surfaces.get(slot_id)
        # Load JPEG via GdkPixbuf → Cairo surface
        import gi  # ← top-level already imported but re-imported
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
        w, h = pixbuf.get_width(), pixbuf.get_height()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk

        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()
        ...
```

**`gi.require_version` + `from gi.repository import` runs on
every frame load** when the mtime changes. Python's import
cache deduplicates the actual module loading (fast after first
call), but `gi.require_version` itself has to hit GI's typelib
registry which involves a file lookup + version check.

When cached (mtime unchanged), this path returns early and is
free. When the YouTube frames are actively updating (external
process writes `yt-frame-{0,1,2}.jpg` periodically), this
runs ~3 times per tick × 10 fps = **30 imports per second**.

**Fix**: cache the gi imports at module top. ~3 lines of
import hoisting. Eliminates the per-frame import overhead
when YouTube frames are hot.

### 2.3 Finding 3 — inscribed rectangle math re-computed
every tick

`_inscribed_rect` is called **4 times per tick**:
- 3× from `_draw_video_in_triangle` (once per corner)
- 1× from `_draw_waveform` (center void)

The triangle geometry is **deterministic given canvas
dimensions** — `_get_triangle` produces the same output for
the same (w, h, scale, y_offset) every call, and the
midpoints chain is pure function of those. Unless the canvas
size changes, the inscribed rects are static.

**Fix**: cache the 4 inscribed rects on first call, invalidate
only when `canvas_w` or `canvas_h` changes. Saves 4
`_inscribed_rect` calls per tick (each ~50 lines of math).
Small absolute saving (~100-200 µs per tick) but free.

### 2.4 Finding 4 — `_draw_triangle_lines` loops in Python

The stroke loop iterates 17 triangles × 2 stroke calls each =
34 Python-side cr.set_line_width / cr.set_source_rgba /
cr.move_to / cr.line_to × 3 / cr.close_path / cr.stroke call
groups per tick.

Python-to-C call overhead for pycairo is ~2-5 µs per call.
34 strokes × 8 calls per stroke = 272 Python→C calls per
tick × 10 fps = **2720 Python→C calls per second** just for
line drawing.

Absolute cost: 2720 × 3 µs ≈ 8 ms/sec of CPU time ≈ 0.8% of
one core. Modest, but cumulative with other sources.

**Fix** (marginal): coalesce strokes by color group. All
triangles sharing the same color (`color_idx`) could be
stroked in a single path with one `set_source_rgba` and one
`stroke` — but the path is per-triangle (closed path per
triangle), so this requires building one uber-path with
multiple subpaths. ~10 lines of refactor, saves roughly half
the Python→C overhead.

### 2.5 Finding 5 — `time.monotonic()` called inside
`_draw_waveform` but the renderer already receives `t`

`sierpinski_renderer.py:321`:

```python
amp = (energy * 0.5 + 0.1) * (0.5 + 0.5 * math.sin(i * 0.8 + time.monotonic() * 2.0))
```

The `render()` function receives `t` as a parameter (from
`CairoSourceRunner._render_one_frame` — it's the monotonic
time at start of tick). But `_draw_waveform` calls
`time.monotonic()` again inside its loop.

**Two problems**:
1. Duplicate clock read (trivial cost)
2. **Each of 8 bars uses a different `monotonic()` value** —
   the phase shift across bars reflects the elapsed time
   *during the draw loop*, not the tick time. For 8 bars at
   ~50 µs per iteration, the phase drift is ~400 µs across
   the loop — imperceptible visually but inconsistent.

**Fix**: use the `t` parameter for the sine phase. 1-line
change. Preserves behavior intention.

## 3. Ring summary

### Ring 1 — free correctness + small optimization

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **SIERP-1** | Cache 4 inscribed rects, invalidate on canvas-size change | `sierpinski_renderer.py` | ~10 | ~0.2 ms/tick saved |
| **SIERP-2** | Hoist gi.require_version + GdkPixbuf/Gdk imports to module top | `sierpinski_renderer.py:1-30` | ~5 | ~1 ms/tick saved when YT frames are hot |
| **SIERP-3** | Use `t` parameter instead of `time.monotonic()` inside `_draw_waveform` | `sierpinski_renderer.py:321` | 1 | Correctness — phase consistency |

**Risk profile**: zero. All three are local refactors with no
behavior change or trivial improvement.

### Ring 2 — the big win (requires careful change)

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **SIERP-4** | Render at 640×640 natural size, rely on cairooverlay blit-scale to upscale | `sierpinski_renderer.py:355-359` + `overlay.py:on_draw` | ~10 | **~80% reduction in render cost.** p95 drops from 65 ms → ~13 ms |

**Risk profile**: **medium**. Two things change:

1. The Sierpinski triangle now renders at 640×640 instead of
   1920×1080 — line widths that looked good at 1080p need to
   scale proportionally (or they'll look too thin after
   upscaling). The `line_w = 1.5 + audio_energy × 2.0`
   baseline needs to be halved to `0.75 + audio_energy × 1.0`
   to maintain visual equivalence after 3× upscale.
2. The cairooverlay draw callback now scales the cached
   surface to 1920×1080 on the streaming thread. `cr.scale()`
   + `cr.set_source_surface()` + `cr.paint()` with
   FILTER_BILINEAR is ~1-2 ms on the streaming thread.
   Acceptable (streaming thread budget is ~30 ms per frame
   at 30 fps — drop #39 findings).

**The bigger tension**: is 640×640 enough resolution for the
line detail to look good after upscaling? Sierpinski level-2
subdivisions produce lines ~20-30 px apart at 640 resolution,
which upscales to ~60-90 px apart at 1920 — visible and
distinct. **Probably fine** but operator visual verification
needed.

### Ring 3 — architectural (deferred)

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **SIERP-5** | Move Sierpinski stroke work to GL via a dedicated glshader slot in the fx chain | New WGSL-or-GLSL shader + fx chain wiring | >100 | ~0 ms Python CPU cost; GPU handles everything; YT frames still blitted via cairo |
| **SIERP-6** | Stroke only the static subdivisions once into a cached surface, composite with audio-reactive foreground per tick | `sierpinski_renderer.py` major refactor | ~50 | ~70% reduction in render cost without res change; keeps visual quality |

**SIERP-5** is the long-term fix — Sierpinski lines are
perfect for GLSL because they're deterministic geometry. But
it's a large rewrite.

**SIERP-6** is the middle ground — split static path
(level-2 subdivisions at fixed line width) from dynamic
(main + level-1 with audio-reactive line width). Cache the
static one. Saves 12 of 17 triangles' stroke work per tick.

## 4. Cumulative impact estimate

**Ring 1 alone**: saves ~1.2 ms per tick. p95 goes from
65.6 → ~64.4 ms. Small.

**Ring 1 + Ring 2 SIERP-4**: saves ~28 ms per tick at
average, ~52 ms at p95. **p95 goes from 65.6 → ~13 ms.**
Sierpinski becomes a non-issue in the budget.

**Ring 3 SIERP-5**: saves all 34 ms/tick by moving work to
GPU. **Python render cost: 0.**

**Composite impact on drop #36's cairo allocation churn
estimate**: drop #36 estimated ~175 MB/s for the aggregate
Cairo source heap churn, of which sierpinski-lines at
1920×1080 × 4 bytes × 10 fps ≈ 82 MB/s is the largest single
contributor. **Ring 2 SIERP-4 reduces sierpinski's
contribution to ~9 MB/s, cutting total cairo allocation
churn to ~100 MB/s.**

## 5. Cross-references

- `agents/studio_compositor/sierpinski_renderer.py:44-116` —
  `SierpinskiCairoSource.render()`
- `agents/studio_compositor/sierpinski_renderer.py:272-301` —
  `_draw_triangle_lines` stroke hot loop
- `agents/studio_compositor/sierpinski_renderer.py:333-359` —
  `SierpinskiRenderer` facade that hardcodes 1920×1080
- `config/compositor-layouts/default.json` — declares
  `natural_w=640, natural_h=640` for the sierpinski source
  (but the layout source is not started — drop #41 finding 1)
- Live `costs.json` at 2026-04-14 ~14:45 — the measurement
  that drove this drop
- Drop #39 — cairooverlay streaming-thread cost (overall
  blit budget context)
- Drop #41 — BudgetTracker wiring audit (surfaced that only
  sierpinski-lines and overlay-zones are the live sources)

## 6. Open question for operator

**Is the current Sierpinski visual quality acceptable as a
baseline?** If yes, Ring 2 SIERP-4 (render at 640×640) is
the right win. If the operator wants to preserve
pixel-perfect sharp lines, Ring 3 SIERP-5 (GLSL shader
version) is the only way.

Simpler question first: **has the operator noticed
sierpinski-lines content ever appearing frozen or one-frame-
old in the livestream output?** If yes, that's the p95=65 ms
ticks causing visible stutter. If no, the current 34 ms
average is absorbing into the stream without artifacts and
the urgency is lower.
