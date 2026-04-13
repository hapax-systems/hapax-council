# Compositor Source Registry — Foundation (PR 1)

**Status**: spec — draft
**Date**: 2026-04-12
**Author**: delta session
**Epic**: Unified Source Abstraction (reverie → affordance-recruited layout routing)
**Target PR**: PR 1 of approximately 6 in the epic
**Intended repo path**: `docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md`

## Summary

Make the existing `Layout` / `SourceSchema` / `SurfaceSchema` / `Assignment` pydantic framework authoritative for the studio compositor's visual composition. Register the reverie rendering surface (`hapax-imagination`) as a first-class compositor source via the `external_rgba` SourceKind, migrate the three hardcoded cairo overlays (token_pole, album_overlay, sierpinski_renderer) into layout-driven assignments, and add runtime command support for mutating PiP position / size / z-order / opacity mid-stream. Wire every source — cameras, cairo overlays, reverie, sierpinski — into the GStreamer glvideomixer as a persistent `fx_chain_input` pad so preset chain switches and future affordance recruitment can route any source into the main compositing path without pipeline rewiring. Retire the standalone `hapax-imagination` winit window in favor of offscreen rendering.

## Motivation

The current compositor has two simultaneous problems.

**Reverie is architecturally separate.** `hapax-imagination` runs as its own winit window, writes its frames to `/dev/shm/hapax-visual/frame.{jpg,rgba}`, and is visible to the operator as a floating Wayland surface. The studio compositor never ingests it; they are two different rendering surfaces that happen to sometimes be visible simultaneously. No affordance routing, no PiP placement, no preset chain access. The operator sees two windows where there should be one integrated output.

**The Layout framework exists but is unused.** The Compositor Unification epic (Phases 2–7) shipped `SourceSchema` / `SurfaceSchema` / `Assignment` / `Layout` in `shared/compositor_model.py` and the `CairoSource` / `CairoSourceRunner` protocol in `agents/studio_compositor/cairo_source.py`. The framework is validated, tested, and documented — but the compositor still instantiates sources via hardcoded Python wiring (`token_pole.py` hardcodes `OVERLAY_X=20`, `album_overlay.py` hardcodes its position, `sierpinski_renderer.py` hardcodes its). No `~/.config/hapax-compositor/layouts/*.json` file is authoritative. The data model is dead code.

The operator needs every visual producer — cameras, cairo overlays, generated surfaces (reverie, sierpinski), encoded feeds — to be uniformly composable in two roles: **PiP slot occupant** and **main-layer FX input**, swappable at runtime, recruitable by the affordance pipeline. That requires making the framework authoritative and giving every source the same "always-available-as-a-pad" treatment in the GStreamer pipeline.

## Goals

- Retire the standalone `hapax-imagination` winit window; render offscreen by default.
- Publish reverie's RGBA frames to a canonical shared-memory path readable by the compositor.
- Register reverie, token_pole, album, and sierpinski as `SourceSchema` entries loaded from `~/.config/hapax-compositor/layouts/default.json`.
- Migrate the three existing cairo overlays off hardcoded canvas offsets onto natural-size rendering with compositor-applied placement.
- Support mid-stream mutation of PiP position / size / z-order / opacity via a `window.__logos` command surface.
- Support file-watched hot-reload of the layout JSON as a parallel control path.
- Lay GStreamer `appsrc` pads for every source so any source is available as a main-layer / FX chain input without pipeline rewiring.
- Extend effect graph preset schema to reference sources by name so preset chain switches can select arbitrary inputs.
- Ship with a test suite that proves both the PiP path and the main-layer path end-to-end.

## Non-goals (deferred to follow-up PRs)

- **Default-layout assignments that promote non-camera sources to the main layer.** PR 1 ships the mechanism; no visible runtime behavior change on the main output.
- **AffordancePipeline recruitment hook.** No wiring of AffordancePipeline to layout mutations.
- **Animation tweens on geometry changes.** Snap-only in PR 1.
- **`compositor.assignment.add` / `compositor.assignment.remove` commands.** Mutations edit existing assignments only.
- **`overlay_zones.py` migration.** Zones animate across the full canvas (DVD-bounce) and need a different migration story. Kept on the legacy fullscreen path with a TODO.
- **Operator UI for drag-to-move PiPs.** Commands exist; frontend affordance is a separate PR.
- **Multiple named layouts + runtime layout swap.** PR 1 has only `default.json`.
- **Runtime source registration / deregistration.** Sources are registered at compositor startup only.

## Architecture

Three layers, one authoritative state.

### 1. Declarative baseline — JSON on disk

`~/.config/hapax-compositor/layouts/default.json` defines the initial `Layout`. Loaded once at startup, validated by the `Layout` pydantic model. File-watched via inotify; valid on-disk edits trigger hot-reload into LayoutState. Invalid edits keep current state and emit a WARNING + ntfy. Missing or unparseable file at startup → compositor falls back to a hardcoded `_FALLBACK_LAYOUT` (semantically identical to the JSON) + WARNING + ntfy. Deleting the file never breaks the stream.

### 2. Live state — in-memory authority

New module: `agents/studio_compositor/layout_state.py`.

```python
class LayoutState:
    _layout: Layout
    _lock: threading.RLock
    _subscribers: list[Callable[[Layout], None]]
    _last_self_write_mtime: float

    def get(self) -> Layout: ...
    def mutate(self, fn: Callable[[Layout], Layout]) -> None: ...
    def subscribe(self, callback: Callable[[Layout], None]) -> None: ...
```

- `get()` returns the current `Layout` snapshot (reference, not a clone — callers must not mutate). RLock-guarded.
- `mutate(fn)` acquires the lock, calls `fn(current_layout)` to produce a new Layout (pydantic immutable pattern via `model_copy(update=...)`), re-runs `Layout.model_validate` (catches broken references), atomically swaps, emits `layout_mutated` to subscribers, and triggers the debounced auto-save.
- `subscribe(callback)` lets interested parties register. In PR 1 the render loop just calls `get()` every frame, so subscribers are only used for auto-save and Prometheus metric bumps.

**Auto-save.** A background thread debounces mutations by 500ms and writes the current layout back to `default.json` atomically (tmpfile + rename). `compositor.layout.save` command forces an immediate flush.

**Self-write detection.** After auto-save writes to disk, it records the new mtime in `_last_self_write_mtime`. The inotify handler compares incoming `IN_CLOSE_WRITE` mtimes against this value within a 2-second tolerance window and skips self-writes to avoid reload loops.

### 3. Render loop — walks LayoutState each frame

The existing GStreamer `cairooverlay` post-FX draw callback (`fx_chain.py:_pip_draw`) is refactored to walk `layout_state.get().assignments` by `z_order`, pull each source's most-recent natural-size surface from a `SourceRegistry` keyed by `source.id`, and blit it scaled to the target `SurfaceSchema.geometry`. No hardcoded `OVERLAY_X` / `OVERLAY_Y` / `OVERLAY_SIZE` anywhere.

The draw callback stays inside the GStreamer draw thread — no new pipeline element, no new thread. The only new module-level work is `SourceRegistry` lookup and scaled blit.

## Source backends

Dispatched by `SourceSchema.backend`.

### `backend: "cairo"`

Existing `CairoSourceRunner`, modified to accept `natural_w` / `natural_h` separate from canvas dimensions. The runner allocates `cairo.ImageSurface` at natural size and passes those dims to `source.render()`. The backend factory looks up `SourceSchema.params.class_name` in an import-by-name table under `agents/studio_compositor/cairo_sources/` to instantiate the concrete `CairoSource` subclass. Adding a new cairo source means dropping a class file into that directory and referencing its `class_name` in JSON — no edits to a hardcoded dispatch table.

### `backend: "shm_rgba"`

New `ShmRgbaReader`. Mmaps `<shm_path>` (from `SourceSchema.params.shm_path`), reads a sidecar JSON alongside (`<shm_path>.json` with `{w, h, stride, frame_id}`) to know the current frame geometry, and exposes `get_current_surface() -> cairo.ImageSurface | None` (returning a surface created via `cairo.ImageSurface.create_for_data(mmap, FORMAT_ARGB32, w, h, stride)`). Invalidates and re-wraps the surface on `frame_id` change. Zero Python per new shm source — declare entirely in JSON.

Both backends produce `cairo.ImageSurface` for the draw callback. The draw callback does not care which backend produced the pixels.

### SourceRegistry

New module: `agents/studio_compositor/source_registry.py`. Thin map `{source_id → backend_handle}` where `backend_handle` is either a `CairoSourceRunner` or a `ShmRgbaReader`. Single public read method: `get_current_surface(source_id) -> cairo.ImageSurface | None`. Returns the same cached surface reference per frame for multi-Assignment callers; rendering happens once per source per tick on the source's own thread, blitting happens N times in the draw callback.

## Reverie offscreen mode

Env var `HAPAX_IMAGINATION_HEADLESS=1` tells `src-imagination/src/main.rs` to skip winit window creation and run a pure offscreen render loop.

- `ApplicationHandler::resumed()` constructs a `headless::Renderer` instead of a `Window` + `wgpu::Surface`. Headless renderer owns a wgpu texture (no surface) and calls `DynamicPipeline::render` into that texture on a 60fps tokio interval.
- `gpu.surface.get_current_texture()` and `gpu.surface.configure()` are bypassed in the headless path.
- `ShmOutput::write_frame()` runs unchanged; it was already the authoritative off-screen path.
- **New**: the render loop also writes `/dev/shm/hapax-sources/reverie.rgba` + `reverie.rgba.json` sidecar alongside the existing `/dev/shm/hapax-visual/frame.{jpg,rgba}` outputs. The sidecar contains `{w, h, stride, frame_id}` and is written atomically (tmpfile + rename) after the RGBA buffer update.
- IPC UDS (`$XDG_RUNTIME_DIR/hapax-imagination.sock`) still runs. `Window{*}` commands become no-ops in headless mode, returning `{status: "headless"}`. `Render{SetFps, Pause, Resume}` and `Status` still work.

Opt-out for debugging: `HAPAX_IMAGINATION_HEADLESS=0` keeps the winit window. Systemd unit sets it to 1 by default.

Unit delta (`systemd/units/hapax-imagination.service`): add `Environment=HAPAX_IMAGINATION_HEADLESS=1`. That is the whole systemd change.

## Natural-size cairo source migration

Each existing cairo source drops its canvas-relative positioning and renders into a surface sized to its content:

- **`token_pole.py`**: natural 300×300. Delete `OVERLAY_X`, `OVERLAY_Y`, `OVERLAY_SIZE` constants. Particle-explosion coordinates become relative to the 300×300 origin (they already reference the overlay center; origin-shift is trivial). Class renamed `TokenPoleCairoSource` to match the `class_name` convention.
- **`album_overlay.py`**: natural 400×520. Album cover + splattribution text + PiP effects position relative to local coords.
- **`sierpinski_renderer.py`**: natural 640×640. Triangle vertices and yt-frame inscribed rects compute relative to local origin.
- **`overlay_zones.py`**: NOT migrated in PR 1. Kept on the legacy fullscreen path with a TODO in the file.

Each migrated class lives under `agents/studio_compositor/cairo_sources/` so the `class_name` dispatcher finds it. The legacy module files (`token_pole.py`, etc.) remain as thin shims importing from `cairo_sources/` to preserve any existing imports during the migration.

`CairoSourceRunner.__init__` signature gains `natural_w` / `natural_h` (defaults to canvas_w/h for backward compat, but all migrated sources pass explicit values).

## default.json

```json
{
  "name": "default",
  "description": "Default studio compositor layout — PR 1 baseline",
  "sources": [
    {
      "id": "token_pole",
      "kind": "cairo",
      "backend": "cairo",
      "params": {"class_name": "TokenPoleCairoSource", "natural_w": 300, "natural_h": 300}
    },
    {
      "id": "album",
      "kind": "cairo",
      "backend": "cairo",
      "params": {"class_name": "AlbumOverlayCairoSource", "natural_w": 400, "natural_h": 520}
    },
    {
      "id": "sierpinski",
      "kind": "cairo",
      "backend": "cairo",
      "params": {"class_name": "SierpinskiCairoSource", "natural_w": 640, "natural_h": 640}
    },
    {
      "id": "reverie",
      "kind": "external_rgba",
      "backend": "shm_rgba",
      "params": {
        "natural_w": 640,
        "natural_h": 360,
        "shm_path": "/dev/shm/hapax-sources/reverie.rgba"
      }
    }
  ],
  "surfaces": [
    {"id": "pip-ul", "geometry": {"kind": "rect", "x":   20, "y":  20, "w": 300, "h": 300}, "z_order": 10},
    {"id": "pip-ur", "geometry": {"kind": "rect", "x": 1260, "y":  20, "w": 640, "h": 360}, "z_order": 10},
    {"id": "pip-ll", "geometry": {"kind": "rect", "x":   20, "y": 540, "w": 400, "h": 520}, "z_order": 10},
    {"id": "pip-lr", "geometry": {"kind": "rect", "x": 1260, "y": 420, "w": 640, "h": 640}, "z_order": 10}
  ],
  "assignments": [
    {"source": "token_pole", "surface": "pip-ul"},
    {"source": "reverie",    "surface": "pip-ur"},
    {"source": "album",      "surface": "pip-ll"}
  ]
}
```

Notes:

- `pip-lr` is declared but has no default assignment — operator and affordance pipeline populate it at runtime.
- `sierpinski` is registered as a source but has no default assignment — available for runtime binding, not visible in the default stream.
- Cameras and main-layer `video_out` surfaces are NOT in this JSON in PR 1. They stay wired by the existing Python path. A follow-up PR migrates them.
- The surfaces declare a full 2×2 quadrant grid so operators and affordance can promote any source into any empty slot via `compositor.surface.set_geometry` followed by a future `compositor.assignment.add`.

## Render path

Each source renders at its natural resolution; the draw callback scales during composition.

### Scale-on-blit

```python
def blit_scaled(cr, src, geom, opacity, blend_mode):
    cr.save()
    cr.translate(geom.x, geom.y)
    scale_x = geom.w / src.get_width()
    scale_y = geom.h / src.get_height()
    cr.scale(scale_x, scale_y)
    cr.set_source_surface(src, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_BILINEAR)  # NEAREST if source.params.filter == "nearest"
    if blend_mode == "plus":
        cr.set_operator(cairo.OPERATOR_ADD)
    else:
        cr.set_operator(cairo.OPERATOR_OVER)
    cr.paint_with_alpha(opacity)
    cr.restore()
```

The `filter` choice is per-source (declared in `SourceSchema.params.filter`, default `"bilinear"`). Pixel-art-style overlays can opt into nearest-neighbor scaling.

### Multi-Assignment caching

`SourceRegistry.get_current_surface(source_id)` returns the same `cairo.ImageSurface` reference per frame regardless of how many assignments point at the source. Rendering happens once per source per tick on the source's own thread; blitting happens N times in the draw callback. No re-sampling for multi-Assignment sources.

### One render, two consumers

Each source's single rendered frame feeds **both** the PiP path (via `SourceRegistry.get_current_surface()` → `_pip_draw` blit) **and** the main-layer path (via `CairoSourceRunner.gst_appsrc()` push-buffer). Cairo sources push the same underlying pixel buffer to both destinations from the render thread after a successful tick; no double-rendering, no double-allocation. `ShmRgbaReader` does the same: the mmap view is read once, the resulting cairo surface is cached for PiP reads, and the RGBA buffer is simultaneously pushed to the appsrc element.

### Main layer stays GStreamer

Cameras still feed `glvideomixer` via `v4l2src → glupload`. The cairo draw callback blits PiPs onto the glvideomixer output via `cairooverlay`. No change to the main pipeline topology in PR 1 beyond the appsrc branches added for main-layer availability (see below).

## Command surface

New frontend command registry entries (new file: `hapax-logos/src/lib/commands/compositor.ts`):

| Command ID | Args | Effect |
|---|---|---|
| `compositor.surface.set_geometry` | `surface_id: string, x: int, y: int, w: int, h: int` | Mutate a rect surface's geometry |
| `compositor.surface.set_z_order` | `surface_id: string, z_order: int` | Reorder |
| `compositor.assignment.set_opacity` | `source_id: string, surface_id: string, opacity: float` | 0..1 blend opacity for a specific binding |
| `compositor.layout.save` | (none) | Flush debounced auto-save immediately |
| `compositor.layout.reload` | (none) | Force re-read from disk |

`compositor.assignment.add` / `compositor.assignment.remove` are deferred to PR 2.

### Control flow

1. Frontend: `window.__logos.execute("compositor.surface.set_geometry", {surface_id: "pip-ur", x: 1300, y: 40, w: 560, h: 315})`.
2. Command registry dispatches to a thin Rust handler in `hapax-logos/src-tauri/src/commands/compositor.rs` that forwards the JSON payload to the compositor's UDS socket at `$XDG_RUNTIME_DIR/hapax-compositor.sock` (new). Tauri side has no compositor logic — pass-through only.
3. Compositor UDS handler (`agents/studio_compositor/command_server.py`, new) parses the JSON, validates against known surface / source IDs, calls `layout_state.mutate(fn)` with the appropriate SurfaceSchema edit.
4. `LayoutState.mutate()` triggers debounced auto-save and Prometheus metric bump.

MCP / voice / affordance pipeline reach the same UDS endpoint either through `window.__logos` via the existing `:8052/ws/commands` WebSocket relay (browser-mediated) or via direct UDS (no browser required). Both paths are supported.

### Error responses (structured, returned to caller)

| Error | Trigger |
|---|---|
| `unknown_surface` | surface_id not in layout; includes did-you-mean hint via `difflib.get_close_matches` |
| `unknown_source` | source_id not in layout; includes did-you-mean hint |
| `invalid_geometry` | w ≤ 0, h ≤ 0, NaN, non-finite floats |
| `layout_immutable_kind` | `set_geometry` on `video_out`, `wgpu_binding`, or `fx_chain_input` surface (only `rect` is mutable in PR 1) |
| `persistence_failed` | debounce write failed (disk full, permission); non-fatal, in-memory state remains correct |

## Main-layer availability — the "railroad tracks"

### New SurfaceKind: `fx_chain_input`

Add `"fx_chain_input"` to the `SurfaceKind` literal in `shared/compositor_model.py`. Represents a named `appsrc` pad that feeds `glvideomixer` in the main pipeline. Geometry fields (`x/y/w/h`) are not used for `fx_chain_input` surfaces; only the surface `id` (which becomes the pad name) matters.

### Persistent appsrc pads

At compositor startup, for every source registered in the layout (regardless of whether any default assignment binds it to a rect surface), `fx_chain.py` constructs an `appsrc → glupload → capsfilter` branch feeding a glvideomixer pad. Each source's `CairoSourceRunner` or `ShmRgbaReader` gains a `gst_appsrc()` method that returns or lazily constructs its appsrc element.

- **Cairo sources**: runner's render thread, after successfully rendering a frame, pushes the ImageSurface's buffer to the appsrc via `appsrc.emit("push-buffer", buffer)`.
- **Shm sources**: a small polling thread watches the shm sidecar `frame_id` field and pushes buffers when it changes.

Inactive sources (not bound to any main-layer assignment and not referenced by the current preset) have their glvideomixer sink pad held at `alpha=0` via the pad's `alpha` property. The compositor pipeline stays in a steady state regardless of which sources are "active" — preset switches are alpha-snap decisions on existing pads, not pipeline rewiring, and there is no startup latency when a preset switches a source in.

### Preset schema extension

Effect graph presets gain an optional `inputs` array:

```json
{
  "name": "high-contrast-vinyl",
  "nodes": [...],
  "inputs": [
    {"pad": "cam-vinyl", "as": "layer0"},
    {"pad": "album",     "as": "layer1"},
    {"pad": "reverie",   "as": "layer2"}
  ]
}
```

When a preset loads, the effect graph resolves `pad` names against the SourceRegistry's pad table at load-time (not tick-time — cache the resolution). Presets that don't declare `inputs` preserve existing behavior. Presets that reference a source that doesn't exist fail preset-load loudly (structured error, no silent no-op). This is deliberately loud — consistent with the silent-failure discipline from the 2026-04-12 reverie-bridge audit.

### Default runtime behavior is unchanged

`default.json` declares no `fx_chain_input` surfaces and no main-layer assignments to non-camera sources. The appsrc pads exist and carry frames, but no preset references them and no assignment binds them to the main layer. Visible stream output matches current behavior on day one.

### End-to-end proof ships with PR 1

A dedicated integration test (`tests/studio_compositor/test_main_layer_path.py`) loads an augmented layout fixture that adds an `fx_chain_input` surface + assignment binding reverie to it, runs the compositor for 30 frames, and asserts reverie's RGBA bytes appear in the glvideomixer output pad buffer via a golden-image comparison with ~5% tolerance. The test does NOT change `default.json` or runtime behavior; it proves the railroad tracks carry traffic without promoting anything visibly.

## Testing

| Level | Test | What it proves |
|---|---|---|
| Unit | `LayoutState.mutate()` atomic under concurrent readers (10 writers × 50 readers, no torn reads) | RLock + snapshot correctness |
| Unit | Pydantic round-trip on each source kind, including `params.class_name` validation | Factory table resolves |
| Unit | `CairoSourceRunner` with `natural_w`/`natural_h` ≠ canvas → output surface matches natural dims | Migration delta honored |
| Unit | `ShmRgbaReader` round-trip (write tmpfile + sidecar, read, assert bytes match) | Shared-memory path intact |
| Unit | `_pip_draw` with fixture LayoutState + canned source surfaces → expected pixels at expected coords | Blit + scale correct |
| Unit | Geometry command validation (unknown IDs with did-you-mean, negative dims, NaN, wrong surface kind) | Error surface complete |
| Unit | Debounced auto-save coalesces 5 rapid mutations into 1 disk write within 500ms | Persistence bounded |
| Unit | File-watch reload skips self-writes within 2s window | No reload loop |
| Unit | Each migrated cairo source (`TokenPoleCairoSource`, `AlbumOverlayCairoSource`, `SierpinskiCairoSource`) renders its natural-size output at origin (0,0) with expected pixel layout | Migration correct |
| Integration | Compositor boots with default.json, renders 30 frames, asserts pip-ul/ur/ll sources blit at expected positions (golden-image, ~5% tolerance) | End-to-end PiP path alive |
| **Integration** | **Compositor boots with augmented layout fixture (adds `fx_chain_input` assignment for reverie), renders 30 frames, asserts reverie RGBA reaches glvideomixer output pad** | **End-to-end main-layer path alive — tracks carry traffic** |
| Integration | Layout file corruption at startup → fallback loads → ntfy fires → frames valid | Rollback safety |
| Integration | `set_geometry` via UDS → next frame shows move → default.json on disk updates within 1s | Control path alive |
| Integration | File-watch reload: write modified default.json → compositor picks up within 2s | Hot-reload alive |
| Integration | Reverie headless mode: `HAPAX_IMAGINATION_HEADLESS=1 hapax-imagination` → no winit window → `/dev/shm/hapax-sources/reverie.rgba` populates | Headless path alive |
| Regression | Existing `tests/studio_compositor/` suite passes unchanged | No silent break |

## Observability

Reuses existing infrastructure; adds sparse new signals.

### Prometheus

- `compositor_surface_mutations_total{surface_id}` — counter
- `compositor_layout_reloads_total{source="file"|"command"}` — counter
- `compositor_source_frame_age_seconds{source_id}` — gauge, catches sources that die mid-stream

### Structured log events (via `shared/telemetry.hapax_event`)

- `layout_mutated` — `{surface_id, field, old, new}`
- `layout_reloaded` — `{source: "file"|"fallback", reason?}`
- `layout_validation_failed` — `{path, first_error}`
- `source_registered` — `{source_id, backend, natural_w, natural_h}`
- `source_unavailable` — `{source_id, reason}`

### Budget integration

`CairoSourceRunner` existing `BudgetTracker` hookup unchanged. `ShmRgbaReader` takes an optional `BudgetTracker` and calls `tracker.record(source_id, elapsed_ms)` after each successful mmap read, mirroring how `CairoSourceRunner._render_one_frame` already reports into the tracker. This lets VLA see shm source costs alongside cairo ones through the existing degraded-signal publishing path.

## Error handling

| Failure | Behavior |
|---|---|
| `default.json` missing at startup | Load `_FALLBACK_LAYOUT` + WARNING + ntfy |
| `default.json` corrupt at startup | Load `_FALLBACK_LAYOUT` + WARNING + ntfy |
| `default.json` corrupt on reload | Keep current LayoutState + WARNING + ntfy (do not clobber) |
| Source render fails | Blit previous-frame cache + DEBUG log; `compositor_source_frame_age_seconds` catches chronic staleness |
| appsrc push-buffer fails | Pad probe drops buffer + metric counter + no pipeline block |
| Preset references unknown source pad | Preset load fails loudly with structured error; chain switch blocked |
| Geometry command on unmutable surface | Return `layout_immutable_kind` error to caller |
| Debounced save fails | Log warning; in-memory state unchanged; next successful save catches up |
| Reverie offscreen render fails to write shm | Log error; stale previous-frame stays in shm; `compositor_source_frame_age_seconds{reverie}` climbs |

**No silent failures anywhere.** Preset unknown-source failure is deliberately loud.

## File-level change list

### New files

- `agents/studio_compositor/layout_state.py`
- `agents/studio_compositor/source_registry.py`
- `agents/studio_compositor/shm_rgba_reader.py`
- `agents/studio_compositor/command_server.py`
- `agents/studio_compositor/cairo_sources/__init__.py` — class_name dispatch table
- `agents/studio_compositor/cairo_sources/token_pole_source.py`
- `agents/studio_compositor/cairo_sources/album_overlay_source.py`
- `agents/studio_compositor/cairo_sources/sierpinski_source.py`
- `scripts/install-compositor-layout.sh` — installs the baseline `default.json` to `~/.config/hapax-compositor/layouts/` on first run
- `hapax-logos/src/lib/commands/compositor.ts` — frontend command registry entries
- `hapax-logos/src-tauri/src/commands/compositor.rs` — Tauri → UDS pass-through
- `tests/studio_compositor/test_layout_state.py`
- `tests/studio_compositor/test_source_registry.py`
- `tests/studio_compositor/test_shm_rgba_reader.py`
- `tests/studio_compositor/test_pip_draw_refactor.py`
- `tests/studio_compositor/test_command_server.py`
- `tests/studio_compositor/test_main_layer_path.py` — the end-to-end main-layer integration test
- `tests/studio_compositor/test_layout_file_watch.py`
- `tests/studio_compositor/test_cairo_source_natural_size.py`
- `tests/studio_compositor/fixtures/augmented_layout_with_fx_chain_input.json`
- `docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md` (this document)

### Modified files

- `shared/compositor_model.py` — add `"fx_chain_input"` to `SurfaceKind` literal
- `agents/studio_compositor/compositor.py` — load default.json, construct LayoutState + SourceRegistry, pass into fx_chain; start command_server UDS; start file-watch thread
- `agents/studio_compositor/fx_chain.py` — refactor `_pip_draw` to walk LayoutState; construct appsrc branches per source at pipeline build time
- `agents/studio_compositor/cairo_source.py` — `CairoSourceRunner` gains `natural_w` / `natural_h` parameters; defaults preserve current behavior
- `agents/studio_compositor/token_pole.py` — thin shim importing `TokenPoleCairoSource` from `cairo_sources/token_pole_source.py`
- `agents/studio_compositor/album_overlay.py` — thin shim
- `agents/studio_compositor/sierpinski_renderer.py` — thin shim
- `agents/effect_graph/types.py` — preset type gains optional `inputs: list[{pad, as}]` field
- `agents/effect_graph/compiler.py` or `agents/effect_graph/pipeline.py` — preset loader resolves `inputs.pad` names against SourceRegistry at load-time (not tick-time), pins the resolved references, fails loudly on unknown pad names. Which of the two files owns preset loading is confirmed during implementation; both are candidates based on naming
- `src-imagination/src/main.rs` — headless mode branch
- `crates/hapax-visual/src/output.rs` — second shm output path (`/dev/shm/hapax-sources/reverie.rgba` + sidecar JSON, atomic writes)
- `systemd/units/hapax-imagination.service` — `Environment=HAPAX_IMAGINATION_HEADLESS=1`

## Acceptance criteria

1. Compositor boots with `default.json`; all four sources register; reverie PiP (upper-right) shows live reverie frames.
2. Existing visible behavior preserved: Vitruvian upper-left, album lower-left. No regression in stream output.
3. `hapax-imagination.service` starts in headless mode; no winit window visible on the desktop.
4. `window.__logos.execute("compositor.surface.set_geometry", {...})` from Playwright moves a PiP within ≤1 frame; change persists after compositor restart.
5. File-watch reload: hand-editing `default.json` with a valid change reloads within ≤2s; invalid edit is ignored with a warning log.
6. Every source has a persistent `appsrc` pad in the GStreamer pipeline; integration test asserts reverie's RGBA bytes reach the glvideomixer output pad.
7. Preset load with an unknown source reference fails loudly with a structured error.
8. Deleting `default.json` → compositor falls back to hardcoded layout + ntfy; stream stays up.
9. All new tests pass. Existing `tests/studio_compositor/` suite passes unchanged.
10. `compositor_source_frame_age_seconds` Prometheus metric populates for every registered source.
11. `CairoSourceRunner` natural-size migration preserves the visual output of the three migrated cairo sources (golden-image regression).

## Open questions

1. **fx_chain_input surface IDs**: should they match source IDs 1:1 (simplest — each source has one pad) or be named independently (more flexible — one source could feed multiple pads)? **Recommendation**: 1:1 for PR 1. Independent naming is a follow-up when a concrete use case emerges.
2. **Appsrc push cadence**: push every rendered frame regardless of whether the pad is bound, or throttle on inactive pads? **Recommendation**: push every frame. The pad_probe drops inactive buffers cheaply, and always-hot pads remove startup latency at preset switch time.
3. **Preset `inputs` resolution timing**: load-time or tick-time? **Recommendation**: load-time. Resolve once, pin references. Needs a look at the current preset loader structure before writing the implementation plan.
4. **Process / branching**: delta cannot create a feature branch while alpha and beta have open PRs (blocked by `no-stale-branches.sh`). This spec is written to the cache (`~/.cache/hapax/delta-brainstorm/`) pending unblock. Resolution paths: (a) hand implementation off to alpha or beta once their current PRs merge, (b) operator explicitly unblocks delta. Process question, not architectural.

---

**End of spec.**
