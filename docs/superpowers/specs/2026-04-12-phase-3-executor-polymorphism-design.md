# Phase 3: Executor Polymorphism — Design Spec

**Date:** 2026-04-12
**Status:** Approved (self-authored, alpha session)
**Epic:** `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md`
**Phase:** 3 of 7
**Risk:** High (touches the rendering path directly)
**Depends on:** Phase 1 complete (cleanup), Phase 2 complete (data model exists)

---

## Purpose

Promote `effect_graph` from "GPU shader graph" to "content + effects graph" by extending nodes to declare a `backend` and dispatching execution per backend. Today the Rust executor unconditionally treats every pass as a wgpu render pipeline; the duplicate Cairo / Pango / image-loading code in `studio_compositor/` lives outside the graph entirely.

After Phase 3, every content-bearing source — Sierpinski, AlbumOverlay, OverlayZones, TokenPole, the Vitruvian Man PNG, the obsidian text overlays, the YouTube PiPs, every WGSL shader — is dispatched through one polymorphic mechanism. The duplicate code paths consolidate. Adding a new content type becomes a manifest edit + a backend implementation, not a code change in `studio_compositor/`.

**This phase is the highest-risk in the epic.** It touches the rendering hot path. Each sub-phase ships independently behind the existing visual baseline so regressions are easy to pin to one PR.

---

## Scope

Four sub-phases, each a separate PR merging into `epic/compositor-phase-3` (or directly to main, matching the Phase 1/2 pattern):

1. **Phase 3a:** `backend` field in node manifests + Rust dispatch table with one entry (`wgsl_render`). No behavior change. Plumbing only.

2. **Phase 3b:** `cairo` backend. CairoSource protocol + CairoSourceRunner. Migrate SierpinskiRenderer, OverlayZoneManager, AlbumOverlay, TokenPole behind it. Visual output unchanged.

3. **Phase 3c:** `text` backend. Shared `_pango_render` helper. Migrate 5 duplicate Pango code paths into one. on_change cadence with content-hash invalidation.

4. **Phase 3d:** `image_file` backend. Shared mtime-cached image loader. Migrate 5 duplicate image loaders into one.

Each sub-phase preserves byte-for-byte visual output. The acceptance criterion is "fx-snapshot diff is sub-pixel; no structural difference."

---

## Phase 3a: `backend` field in node manifests

### Scope of change

| Layer | Files | Change |
|---|---|---|
| Manifests | `agents/shaders/nodes/*.json` (59 files) | Add `"backend": "wgsl_render"` to each |
| Registry | `agents/effect_graph/registry.py` | `LoadedShaderDef.backend: str = "wgsl_render"` |
| Compiler | `agents/effect_graph/wgsl_compiler.py` | Emit `backend` in pass descriptor |
| Plan parser | `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` | `PlanPass.backend: String`, `DynamicPass.backend: String` |
| Dispatch | `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` | Backend dispatch table with one entry: `"wgsl_render"` → existing render path |

### Manifest format

Before:
```json
{"node_type":"colorgrade","glsl_fragment":"colorgrade.frag","inputs":{"in":"frame"},"outputs":{"out":"frame"},"params":{...},"temporal":false,"temporal_buffers":0}
```

After:
```json
{"node_type":"colorgrade","glsl_fragment":"colorgrade.frag","backend":"wgsl_render","inputs":{"in":"frame"},"outputs":{"out":"frame"},"params":{...},"temporal":false,"temporal_buffers":0}
```

The migration script lives inline in the PR description (sed expression that adds the field). Manifests that already have a `backend` field are left untouched.

### Registry change

```python
@dataclass
class LoadedShaderDef:
    node_type: str
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params: dict[str, ParamDef]
    temporal: bool
    temporal_buffers: int
    compute: bool
    glsl_source: str | None
    requires_content_slots: bool = False
    backend: str = "wgsl_render"   # NEW: dispatcher key
```

The `_load` method reads `raw.get("backend", "wgsl_render")`. The default keeps any future manifest authors from having to remember the field, but the migration writes it explicitly for discoverability.

### Compiler change

In `wgsl_compiler.py::compile_to_wgsl_plan`, after the `requires_content_slots` block:

```python
descriptor: dict[str, object] = {
    "node_id": step.node_id,
    "shader": f"{step.node_type}.wgsl",
    "type": pass_type,
    "backend": (node_def.backend if node_def else "wgsl_render"),
    "inputs": inputs,
    "output": output,
    "uniforms": uniforms,
    "param_order": param_order,
}
```

The plan version stays at `1` — adding an optional field with a default is forward-compatible. No `version: 2` bump.

### Rust dispatch

`PlanPass` gains:
```rust
#[derive(Debug, Deserialize)]
struct PlanPass {
    // ... existing ...
    /// Backend dispatcher key. Defaults to "wgsl_render" for plans
    /// written by older compilers that don't emit this field.
    #[serde(default = "default_backend")]
    backend: String,
}

fn default_backend() -> String {
    "wgsl_render".into()
}
```

`DynamicPass` gains a matching field. When constructing a `DynamicPass` from a `PlanPass`, the backend is propagated.

The dispatch entry point lives in the existing render loop. Today the loop unconditionally executes the wgpu render pipeline. Add a match:

```rust
match pass.backend.as_str() {
    "wgsl_render" => {
        // existing wgpu render path
    }
    other => {
        log::warn!("Unknown backend '{}' for pass '{}'; skipping", other, pass.node_id);
    }
}
```

For Phase 3a, the only branch is `wgsl_render`, which is the existing code path. The match exists so 3b/3c/3d can add branches.

### Tests

`tests/test_wgsl_compiler.py::test_plan_emits_backend_field` — compile a vocabulary graph, verify every pass has `"backend": "wgsl_render"`.

`tests/test_registry.py::test_backend_field_default` — load a manifest without `backend`, verify it defaults to `wgsl_render`. Load one with `backend: "cairo"`, verify it's preserved.

Rust unit test in `dynamic_pipeline.rs` (or integration in `test_plan_parsing.rs` if it exists): parse a plan.json with explicit `backend: "wgsl_render"`, verify the field is present and the pass dispatches correctly.

### Acceptance

- 59 node manifests have `"backend": "wgsl_render"`.
- `LoadedShaderDef.backend` exists with default `"wgsl_render"`.
- `wgsl_compiler.py` emits `backend` in each pass descriptor.
- `PlanPass` and `DynamicPass` carry the `backend` field.
- Backend dispatch match exists with one branch (`wgsl_render`) wired to the existing render path.
- All existing tests pass. Visual output unchanged (verified via running compositor).
- Plan version stays at `1`.

### PR shape

- ~120 lines of manifest changes (1 line per file × 59 files; sed-script applied)
- ~30 lines of Python (registry + compiler)
- ~40 lines of Rust (PlanPass field + DynamicPass field + dispatch match)
- ~60 lines of tests
- Total: ~250 lines net add

### Risk

Very low. Adding an optional field with a sensible default is a forward-compatible change. The dispatch match has only one branch, so no behavior change is possible.

---

## Phase 3b: Cairo backend

### Purpose

Move all Python Cairo-rendering code (SierpinskiRenderer, OverlayZoneManager, AlbumOverlay, TokenPole) from ad-hoc per-class implementations into a uniform `CairoSource` protocol. Each becomes a registered source kind with a manifest. The bridge from Cairo `ImageSurface` to wgpu texture goes through the existing source protocol (`/dev/shm/hapax-imagination/sources/{id}/frame.rgba`).

### Architecture

```
┌─────────────────────────────────┐
│  Layout (garage-door.json)      │
│  source: sierpinski-lines       │
│  backend: "cairo"               │
│  params: {render_fps: 10}       │
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  CairoSourceRunner              │
│  (background thread per source) │
│  ticks at update_cadence        │
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  CairoSource implementation     │
│  .render(cr, w, h, t, state)    │
│  produces ImageSurface          │
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  rgba_writer.inject_rgba()      │
│  → /dev/shm/.../frame.rgba      │
└─────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│  ContentSourceManager (Rust)    │
│  reads RGBA, uploads to wgpu    │
│  texture, exposes via bind grp  │
└─────────────────────────────────┘
```

The Rust executor's `cairo` backend dispatch is a **no-op for the shader pipeline** — by the time the shader pass runs, the Cairo content is already uploaded. The dispatch entry just verifies the source exists in `ContentSourceManager` and logs at debug level.

### CairoSource protocol

`agents/studio_compositor/cairo_source.py`:

```python
"""CairoSource protocol — content sources that render via Cairo.

Each implementation provides a render() method that draws into a Cairo
context. The CairoSourceRunner wraps it in a background thread, ticks
at the declared cadence, and writes the result to the source protocol
shared memory location.

Phase 3b of the compositor unification epic.
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Any

import cairo


class CairoSource(ABC):
    """Abstract base for Python Cairo content sources.

    Subclasses provide render() and (optionally) state(). The runner
    handles cadence, surface allocation, and the bridge to the shared
    memory source protocol.
    """

    @abstractmethod
    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Draw into the Cairo context. Called once per tick."""

    def state(self) -> dict[str, Any]:
        """Return per-tick state passed into render(). Override if needed."""
        return {}

    def cleanup(self) -> None:
        """Release any resources. Called when the runner stops."""


class CairoSourceRunner:
    """Drives a CairoSource at the declared cadence on a background thread.

    Renders into an ImageSurface, extracts RGBA bytes, writes via the
    source protocol writer to /dev/shm/hapax-imagination/sources/{id}/.
    """

    def __init__(
        self,
        source_id: str,
        source: CairoSource,
        canvas_w: int,
        canvas_h: int,
        target_fps: float = 10.0,
    ) -> None:
        self._source_id = source_id
        self._source = source
        self._canvas_w = canvas_w
        self._canvas_h = canvas_h
        self._period = 1.0 / max(target_fps, 0.1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop,
            name=f"cairo-source-{self._source_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._source.cleanup()

    def _loop(self) -> None:
        from agents.imagination_source_protocol import inject_rgba
        next_tick = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now < next_tick:
                self._stop.wait(min(next_tick - now, 0.05))
                continue
            next_tick = now + self._period
            try:
                surface = cairo.ImageSurface(
                    cairo.FORMAT_ARGB32, self._canvas_w, self._canvas_h
                )
                cr = cairo.Context(surface)
                self._source.render(
                    cr, self._canvas_w, self._canvas_h, now, self._source.state()
                )
                surface.flush()
                rgba_bytes = bytes(surface.get_data())
                inject_rgba(
                    self._source_id,
                    rgba_bytes,
                    self._canvas_w,
                    self._canvas_h,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "CairoSource %s render failed", self._source_id
                )
```

### Backend dispatch (Rust)

In `dynamic_pipeline.rs`, the new `cairo` arm:

```rust
"cairo" => {
    // Cairo content is uploaded by the Python CairoSourceRunner via
    // ContentSourceManager. The shader pass that consumes it (typically
    // content_layer with wgsl_render backend) reads from content_slot_*.
    // For a standalone cairo pass, we'd bind the source's texture
    // directly here, but the current vocabulary doesn't have one.
    // No-op for now; future: bind cairo source texture as pass output.
}
```

### Migration: SierpinskiRenderer

Today (`agents/studio_compositor/sierpinski_renderer.py`) is a free-standing class with its own background thread. The migration:

1. Define `SierpinskiCairoSource(CairoSource)` that implements `render()` containing the existing draw logic.
2. Delete the standalone background thread; instead, instantiate one `CairoSourceRunner(source_id="sierpinski-lines", source=SierpinskiCairoSource(), canvas_w=1920, canvas_h=1080)` at compositor init.
3. Remove the direct `inject_rgba` calls inside SierpinskiRenderer; the runner does it.
4. Keep the Sierpinski-specific state (point cache, color cycle) inside the class as instance attributes; expose via `state()`.

### Migration: OverlayZoneManager

Same pattern. `OverlayZoneCairoSource(CairoSource)` wraps the existing zone-rendering logic. Each zone (text, image, video) becomes a separately registered source — but the implementation lives in one class with a `zone_kind` parameter.

Initially, this looks like a 1:1 migration. Phase 3c will then split the Pango-rendering zones into the `text` backend (consolidating across all 5 callsites).

### Migration: AlbumOverlay, TokenPole

Same pattern. Each becomes a `CairoSource` subclass.

### Tests

`tests/test_cairo_source.py`:

- `test_cairo_source_runner_starts_and_stops`
- `test_cairo_source_runner_calls_render` (verify render called N times in M seconds)
- `test_cairo_source_runner_writes_to_source_protocol` (mock inject_rgba, verify call shape)
- `test_cairo_source_runner_handles_render_exception` (one exception doesn't kill the thread)
- `test_sierpinski_cairo_source_renders_without_error`
- `test_overlay_zone_cairo_source_renders_text_zone`
- `test_album_overlay_cairo_source_renders`
- `test_token_pole_cairo_source_renders`

### Acceptance

- `agents/studio_compositor/cairo_source.py` exists with `CairoSource` ABC + `CairoSourceRunner`.
- SierpinskiRenderer, OverlayZoneManager, AlbumOverlay, TokenPole are all `CairoSource` subclasses.
- Each is wrapped in a `CairoSourceRunner` at compositor init.
- Old standalone background threads are removed.
- Visual output is byte-identical (fx-snapshot baseline comparison).
- 8+ unit tests pass.
- LOC delta: ~+800 added, ~-500 deleted (the `CairoSource` infrastructure is new; the migration removes per-class thread code).

### Risk

High. The Cairo migration touches the same Cairo `ImageSurface` allocation pattern in 4 places. A subtle change in surface format or stride can produce visually different output. Mitigation: each migration is its own commit within the PR; bisect can pin a regression to one source.

---

## Phase 3c: Text backend

### Purpose

Five places in the codebase render Pango text:

1. `agents/studio_compositor/overlay_zones.py::_render_text_zone`
2. `agents/studio_compositor/album_overlay.py` (attribution text)
3. `agents/studio_compositor/fx_chain.py::_text_overlay_draw` (legacy YouTube path — verify still live after Phase 1)
4. `agents/studio_compositor/token_pole.py` (text fields)
5. `agents/imagination_source_protocol.py::_render_text_to_rgba`

Each independently sets up a `PangoCairo` context, lays out text, and draws. The fonts, sizes, colors, and alignment vary, but the boilerplate is identical. Phase 3c collapses them into one helper.

### The shared helper

`agents/studio_compositor/text_render.py`:

```python
"""Pango text rendering — single source of truth for text-on-Cairo.

Consolidates 5 duplicate code paths. Used by the `text` backend and by
any code that renders text into a Cairo context.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cairo
import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo


@dataclass(frozen=True)
class TextStyle:
    """All knobs for one text render."""
    text: str
    font_family: str = "IBM Plex Mono"
    font_size_pt: float = 14.0
    weight: Literal["normal", "bold"] = "normal"
    italic: bool = False
    color_rgba: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    outline_color_rgba: tuple[float, float, float, float] | None = None
    outline_width_px: float = 0.0
    width_px: int | None = None         # wrap width; None = no wrap
    align: Literal["left", "center", "right"] = "left"
    line_spacing: float = 1.0


def render_text(
    cr: cairo.Context,
    style: TextStyle,
    x: float = 0.0,
    y: float = 0.0,
) -> tuple[int, int]:
    """Render text at (x, y). Returns the (width, height) of the laid-out text.

    The single Pango code path. Used by the text backend, by Cairo
    sources that render text inline, and by the imagination source
    protocol's text writer.
    """
    layout = PangoCairo.create_layout(cr)
    desc = Pango.FontDescription()
    desc.set_family(style.font_family)
    desc.set_absolute_size(style.font_size_pt * Pango.SCALE)
    if style.weight == "bold":
        desc.set_weight(Pango.Weight.BOLD)
    if style.italic:
        desc.set_style(Pango.Style.ITALIC)
    layout.set_font_description(desc)
    layout.set_text(style.text, -1)

    if style.width_px is not None:
        layout.set_width(style.width_px * Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    align_map = {
        "left": Pango.Alignment.LEFT,
        "center": Pango.Alignment.CENTER,
        "right": Pango.Alignment.RIGHT,
    }
    layout.set_alignment(align_map[style.align])
    layout.set_line_spacing(style.line_spacing)

    width, height = layout.get_pixel_size()

    cr.save()
    cr.translate(x, y)

    if style.outline_color_rgba is not None and style.outline_width_px > 0:
        cr.set_source_rgba(*style.outline_color_rgba)
        cr.set_line_width(style.outline_width_px)
        PangoCairo.layout_path(cr, layout)
        cr.stroke()

    cr.set_source_rgba(*style.color_rgba)
    PangoCairo.show_layout(cr, layout)
    cr.restore()
    return width, height
```

### TextSource

`agents/studio_compositor/text_source.py`:

```python
"""Text backend source — Pango-rendered text via the unified text helper.

A TextSource is a CairoSource subclass that draws a single text style
into its allocated canvas. Update cadence is on_change keyed on the
content hash.
"""
from __future__ import annotations
from typing import Any

from .cairo_source import CairoSource
from .text_render import TextStyle, render_text


class TextSource(CairoSource):
    def __init__(self, style: TextStyle, padding_px: int = 8) -> None:
        self._style = style
        self._padding = padding_px
        self._content_hash = hash((style.text, style.font_family,
                                   style.font_size_pt, style.color_rgba))

    def update_style(self, style: TextStyle) -> bool:
        new_hash = hash((style.text, style.font_family,
                         style.font_size_pt, style.color_rgba))
        if new_hash == self._content_hash:
            return False
        self._style = style
        self._content_hash = new_hash
        return True

    def render(self, cr, canvas_w: int, canvas_h: int, t: float, state: dict[str, Any]) -> None:
        cr.set_operator(__import__("cairo").OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(__import__("cairo").OPERATOR_OVER)
        render_text(cr, self._style, x=self._padding, y=self._padding)
```

For on_change cadence, the runner skips the inject_rgba call when the content hash hasn't changed since the last successful render. (The CairoSourceRunner needs a small extension to support this — pass `cadence: UpdateCadence` and `last_hash` tracking.)

### Migrations

Each callsite is rewritten to construct a `TextStyle` and call `render_text()` directly (when rendering inline into an existing Cairo context) or to instantiate a `TextSource` (when the text needs its own source slot).

Quantitative target: collapse 5 Pango setup blocks (~100 lines each = 500 lines) into one (~80 lines), saving ~420 lines.

### Tests

`tests/test_text_render.py`:

- `test_render_text_returns_layout_size`
- `test_render_text_with_wrap`
- `test_render_text_with_outline`
- `test_render_text_alignment` (left/center/right produce different positions)
- `test_text_style_immutable`
- `test_text_source_change_detection` (same text → no update; different text → update)
- `test_text_source_renders_into_canvas`

### Acceptance

- `text_render.py::render_text` exists and is the only Pango code path in `studio_compositor/`.
- All 5 callsites import and use `render_text`.
- `TextSource` exists for source-protocol text rendering.
- Visual output unchanged (font metrics + alignment match the legacy paths).
- LOC delta: ~+500 added, ~-700 deleted (net ~-200).
- 7+ unit tests pass.

### Risk

Medium. Pango font metrics are subtle — a wrong absolute_size vs size_pt conversion can produce text that's 1px taller, breaking alignment. Mitigation: `render_text` returns the laid-out size, callers can compute baselines explicitly.

---

## Phase 3d: Image_file backend

### Purpose

Five places in the codebase load PNG/JPEG images:

1. `agents/studio_compositor/token_pole.py::_load_image` (PNG)
2. `agents/studio_compositor/album_overlay.py::cairo.ImageSurface.create_from_png`
3. `agents/studio_compositor/overlay_zones.py::_load_image` (PIL → Cairo)
4. `agents/studio_compositor/sierpinski_renderer.py` (GdkPixbuf decode of YouTube frames)
5. `agents/studio_compositor/content_capability_router.py` (PIL decode)

Each independently caches results (or doesn't), handles mtime invalidation (or doesn't), and converts to Cairo `ImageSurface` (or to RGBA bytes). Phase 3d unifies them.

### The shared loader

`agents/studio_compositor/image_loader.py`:

```python
"""Image file loader — single source of truth for PNG/JPEG → Cairo surface.

mtime-cached. Thread-safe. Used by the `image_file` backend and any
inline image draw.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import cairo

log = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    surface: cairo.ImageSurface
    mtime: float
    width: int
    height: int


class ImageLoader:
    """Process-wide image cache. mtime invalidation.

    Returns Cairo ImageSurfaces. The cache key is the absolute path.
    Concurrent access is safe; one decode per (path, mtime) pair.
    """

    def __init__(self) -> None:
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def load(self, path: str | Path) -> cairo.ImageSurface | None:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            return None
        try:
            mtime = p.stat().st_mtime
        except OSError:
            return None
        key = str(p)
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry.mtime == mtime:
                return entry.surface
        surface = self._decode(p)
        if surface is None:
            return None
        with self._lock:
            self._cache[key] = _CacheEntry(
                surface=surface, mtime=mtime,
                width=surface.get_width(), height=surface.get_height(),
            )
        return surface

    def _decode(self, path: Path) -> cairo.ImageSurface | None:
        suffix = path.suffix.lower()
        try:
            if suffix == ".png":
                return cairo.ImageSurface.create_from_png(str(path))
            elif suffix in (".jpg", ".jpeg"):
                return self._decode_jpeg(path)
            else:
                log.warning("Unsupported image format: %s", path)
                return None
        except Exception:
            log.exception("Failed to decode %s", path)
            return None

    def _decode_jpeg(self, path: Path) -> cairo.ImageSurface | None:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        # Cairo wants BGRA premultiplied for FORMAT_ARGB32
        import numpy as np
        arr = np.asarray(img, dtype=np.uint8)
        bgra = arr[..., [2, 1, 0, 3]].copy()
        # Premultiply
        alpha = bgra[..., 3:4].astype(np.float32) / 255.0
        bgra[..., :3] = (bgra[..., :3].astype(np.float32) * alpha).astype(np.uint8)
        surface = cairo.ImageSurface.create_for_data(
            memoryview(bgra), cairo.FORMAT_ARGB32, w, h, w * 4
        )
        return surface


# Process-wide singleton
_LOADER: ImageLoader | None = None


def get_image_loader() -> ImageLoader:
    global _LOADER
    if _LOADER is None:
        _LOADER = ImageLoader()
    return _LOADER
```

### ImageFileSource

`agents/studio_compositor/image_file_source.py`:

```python
"""Image_file backend source — wraps a static PNG/JPEG as a content source.

Used for the Vitruvian Man, album cover overlay, folder PNGs. mtime-cached
via the shared ImageLoader. on_change cadence (writes to source protocol
only when the underlying file changes).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

from .cairo_source import CairoSource
from .image_loader import get_image_loader


class ImageFileSource(CairoSource):
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._loader = get_image_loader()
        self._last_mtime: float | None = None

    def render(self, cr, canvas_w: int, canvas_h: int, t: float, state: dict[str, Any]) -> None:
        surface = self._loader.load(self._path)
        if surface is None:
            return
        sw = surface.get_width()
        sh = surface.get_height()
        # Fit to canvas, preserve aspect, center.
        scale = min(canvas_w / sw, canvas_h / sh)
        dw = sw * scale
        dh = sh * scale
        ox = (canvas_w - dw) * 0.5
        oy = (canvas_h - dh) * 0.5
        cr.save()
        cr.translate(ox, oy)
        cr.scale(scale, scale)
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
        cr.restore()
```

### Migrations

Each callsite changes from `cairo.ImageSurface.create_from_png(path)` (or PIL/GdkPixbuf equivalents) to `get_image_loader().load(path)`. The cache makes repeated loads free.

### Tests

`tests/test_image_loader.py`:

- `test_load_png_returns_surface`
- `test_load_missing_file_returns_none`
- `test_load_caches_result` (two loads of the same file → second is cached, verify via mock)
- `test_mtime_invalidation` (touch file → next load decodes again)
- `test_load_jpeg_returns_premultiplied_argb`
- `test_load_unsupported_format_returns_none`
- `test_image_file_source_renders_centered`
- `test_thread_safety_concurrent_load` (two threads loading the same file → no race)

### Acceptance

- `image_loader.py::ImageLoader` exists with mtime-cached load.
- All 5 callsites use `get_image_loader().load(...)`.
- `ImageFileSource` is registered as a content source kind.
- Visual output unchanged.
- LOC delta: ~+400 added, ~-500 deleted (net ~-100).
- 7+ unit tests pass.

### Risk

Low-medium. The Cairo surface lifetime is tricky — if a cached surface is mutated by a caller, the cache poisons all future reads. Mitigation: document that cached surfaces are immutable; callers must `cr.set_source_surface(surface, 0, 0)` and never paint into the cached surface directly.

---

## Cross-sub-phase concerns

### Branch strategy

```
main
 ├── feat/phase-3a-backend-field    (PR A) — manifests + dispatch table
 ├── feat/phase-3b-cairo            (PR B, depends on A) — Cairo backend
 ├── feat/phase-3c-text             (PR C, depends on B) — Text backend
 └── feat/phase-3d-image            (PR D, depends on C) — Image backend
```

Following the Phase 1/2 pattern: each sub-phase gets its own feature branch off main, merges into main when CI is green and visual output matches baseline. No long-lived `epic/compositor-phase-3` branch — direct-to-main keeps the alpha worktree always on the latest content.

### Validation strategy

After each sub-phase merge:

1. Restart `studio-compositor.service` and `hapax-imagination.service`.
2. Capture an fx-snapshot from `/dev/shm/hapax-visual/frame.jpg`.
3. Compare against the pre-Phase-3 baseline. Sub-pixel divergence is acceptable; structural divergence is not.
4. Run the live stream for ~5 minutes; check for log-level errors and visual artifacts.

If a regression is detected, the affected sub-phase PR is reverted via `git revert`. The next sub-phase is unblocked once the regression is fixed.

### Coexistence with current rendering

Phase 3 begins with **3a being a no-op** — adding plumbing without changing behavior. 3b, 3c, 3d each migrate one set of code paths but leave the others alone. Until 3d is merged, Cairo, text, and image rendering live in mixed states (some via the new backends, some still ad-hoc). This is intentional: each sub-phase reduces risk by changing only the minimum surface area.

Phase 4 (compile phase improvements) and Phase 5 (multi-output) can begin once Phase 3 is fully merged.

### Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Backend dispatch dispatches wrong code path | Low | High | Phase 3a has only one branch — no behavior change possible |
| Cairo migration changes surface format → wrong colors | Medium | High | Per-source migration commits within Phase 3b PR; bisect-friendly |
| Pango font metrics differ from legacy paths | Medium | Medium | render_text returns laid-out size; callers compute baselines explicitly |
| Image cache returns stale surface after mtime change | Low | Medium | mtime equality check on every load; tests cover the case |
| Surface protocol writer falls behind cadence | Low | Low | inject_rgba is non-blocking; runner ticks at declared rate |
| Threading deadlock between source runner and main loop | Low | High | Runner is daemon thread; uses threading.Event for stop; no shared mutexes with main |

### Success metrics

Phase 3 is complete when:

- **Zero visual regressions** across all 4 sub-phases (verified via fx-snapshot).
- **All Cairo, text, and image content paths flow through the unified backends.**
- **Duplicate code is eliminated**: 5 Pango paths → 1, 5 image loaders → 1, 4 ad-hoc Cairo classes → 1 protocol.
- **LOC delta**: ~+1700 added, ~-1700 deleted (net neutral, but reorganized into a polymorphic structure).
- **Adding a new content type** is now a single-class `CairoSource` subclass + a manifest entry, not a code change in `studio_compositor/`.

---

## Not in scope

Phase 3 does not:

- Replace the WGSL shader pipeline (the `wgsl_render` backend remains the workhorse).
- Multi-output (Phase 5).
- Dead-source culling (Phase 4).
- Plugin discovery (Phase 6).
- Per-source frame-time accounting (Phase 7).
- Refactor the Layout struct (Phase 2 froze it; future schema changes happen in their own phase).

Phase 3 is purely about **how the executor dispatches work** — promoting the existing rendering machinery to a polymorphic mechanism.

---

## Appendix A: existing rendering code paths to retire

| File | Class/Function | Sub-phase | Replacement |
|---|---|---|---|
| `sierpinski_renderer.py` | `SierpinskiRenderer` standalone thread | 3b | `SierpinskiCairoSource + CairoSourceRunner` |
| `overlay_zones.py` | `OverlayZoneManager._draw_zone` per-zone Cairo | 3b | `OverlayZoneCairoSource` |
| `album_overlay.py` | `AlbumOverlay._draw` standalone Cairo | 3b | `AlbumOverlayCairoSource` |
| `token_pole.py` | `TokenPole._draw` standalone Cairo | 3b | `TokenPoleCairoSource` |
| `overlay_zones.py` | `_render_text_zone` Pango setup | 3c | `text_render.render_text` |
| `album_overlay.py` | `_draw_attribution` Pango setup | 3c | `text_render.render_text` |
| `fx_chain.py` | `_text_overlay_draw` Pango setup | 3c | `text_render.render_text` |
| `token_pole.py` | text field Pango setup | 3c | `text_render.render_text` |
| `imagination_source_protocol.py` | `_render_text_to_rgba` Pango | 3c | `text_render.render_text` + inject_rgba |
| `token_pole.py` | `_load_image` PNG load | 3d | `get_image_loader().load` |
| `album_overlay.py` | `cairo.ImageSurface.create_from_png` | 3d | `get_image_loader().load` |
| `overlay_zones.py` | `_load_image` PIL → Cairo | 3d | `get_image_loader().load` |
| `sierpinski_renderer.py` | GdkPixbuf YouTube frame decode | 3d | `get_image_loader().load` |
| `content_capability_router.py` | PIL decode | 3d | `get_image_loader().load` |

After Phase 3 ships, the only image/text/Cairo code in `studio_compositor/` is in `cairo_source.py`, `text_render.py`, `image_loader.py`, and the per-source `*_cairo_source.py` thin adapters.

---

## Appendix B: future backends (deferred to later phases)

Backends not implemented in Phase 3 but reserved in the dispatch table for later:

| Backend key | Purpose | Phase |
|---|---|---|
| `wgsl_render` | WGSL shader pass (existing) | 3a |
| `wgsl_compute` | WGSL compute pass (no nodes today) | future |
| `cairo` | Python Cairo content | 3b |
| `text` | Pango text content | 3c |
| `image_file` | Static PNG/JPEG | 3d |
| `v4l2_camera` | USB camera ingest | Phase 5 (when GStreamer + wgpu unify) |
| `youtube_player` | YouTube PiP video | Phase 5 |
| `external_rgba` | Raw RGBA from disk path | Phase 5 |
| `ndi` | NDI input | Phase 5 |
| `noise_gen` | Procedural noise | future |
| `solid` | Solid color | future |
| `waveform_render` | Audio waveform visualization | future |
| `clock_widget` | Reference plugin | Phase 6 |

Phase 3a's dispatch match handles unknown backends by logging a warning and skipping the pass — so adding new backends is backward-compatible.
