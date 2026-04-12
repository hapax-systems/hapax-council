# Phase 2: Source/Surface/Assignment Data Model — Design Spec

**Date:** 2026-04-12
**Status:** Approved (self-authored, alpha session)
**Epic:** `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md`
**Phase:** 2 of 7
**Risk:** Medium (introduces new abstractions, doesn't replace any yet)
**Depends on:** Phase 1 complete (cleanup + content backend unification)

---

## Purpose

Define the core data model for the compositor — `Source`, `Surface`, `Assignment`, `Layout` — and validate it by writing the current "garage door" arrangement as a JSON file. The model exists alongside the existing rendering code; no rendering paths are migrated yet.

**This phase makes the unified abstraction concrete without breaking anything.** The Pydantic schema, the Extract phase, and the Layout loader exist as standalone modules that the rest of the codebase doesn't yet depend on. Future phases will migrate rendering to consume them.

---

## Scope

Three sub-phases, each a separate PR merging into `epic/compositor-phase-2`:

1. **Phase 2a:** Pydantic schema for `Source`, `Surface`, `Assignment`, `Layout`. Schema validation, JSON serialization round-trip tests, the first layout file (`garage-door.json`) written using the schema.

2. **Phase 2b:** Extract phase. `extract_frame_description()` produces immutable `FrameDescription` snapshots from a `Layout`. The function is called per-frame but its output is not yet consumed by any rendering code.

3. **Phase 2c:** `LayoutStore` with hot-reload. Watches a directory of layout JSONs, loads one as active, supports runtime swap. Wired into the compositor at startup so the Layout exists in process state but doesn't yet drive rendering.

---

## Phase 2a: Pydantic schema

### File structure

Create `shared/compositor_model.py`:

```python
"""Compositor data model — Source, Surface, Assignment, Layout.

The unified content abstraction. A Source produces pixels (camera, video,
shader, image, text, cairo, external_rgba). A Surface is a destination
region (rect, tile, masked region, wgpu binding, video output). An
Assignment binds a Source to a Surface with per-assignment transform,
opacity, and effects.

A Layout collects Sources, Surfaces, and Assignments into a named scene
that can be loaded from JSON and swapped at runtime.

Phase 2 of the compositor unification epic — see
docs/superpowers/plans/2026-04-12-compositor-unification-epic.md
"""
```

### Type definitions

```python
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


SourceKind = Literal[
    "camera",        # USB camera via v4l2 (current GStreamer ingest)
    "video",         # YouTube PiP via youtube-player + source protocol
    "shader",        # WGSL/GLSL shader (effect_graph node)
    "image",         # PNG/JPEG file with mtime cache
    "text",          # Pango-rendered text
    "cairo",         # Python Cairo surface (Sierpinski, AlbumOverlay, TokenPole)
    "external_rgba", # Raw RGBA from /dev/shm source protocol
    "ndi",           # NDI input (Phase 5)
    "generative",    # noise_gen, solid, waveform_render
]

UpdateCadence = Literal["always", "on_change", "manual", "rate"]

SurfaceKind = Literal[
    "rect",            # Fixed rectangle on the canvas (x, y, w, h)
    "tile",            # Compositor tile (positioned by layout algorithm)
    "masked_region",   # Inscribed rect inside a mask shape (Sierpinski corner)
    "wgpu_binding",    # Named wgpu bind group entry (content_slot_*)
    "video_out",       # /dev/video42, ndi-out, OBS feed
    "ndi_out",         # NDI source advertisement (Phase 5)
]

BlendMode = Literal["over", "plus", "in", "out", "atop"]


class SourceSchema(BaseModel):
    """A typed content producer with a schema.

    Sources don't know what surfaces they'll be assigned to. Surfaces
    don't know what sources will fill them. They meet at Assignment.
    """
    id: str = Field(..., min_length=1, max_length=64)
    kind: SourceKind
    backend: str  # dispatcher key (e.g. "wgsl_render", "cairo", "v4l2_camera")
    params: dict[str, Any] = Field(default_factory=dict)
    update_cadence: UpdateCadence = "always"
    rate_hz: float | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_rate(self) -> SourceSchema:
        if self.update_cadence == "rate" and self.rate_hz is None:
            raise ValueError(
                f"source {self.id}: update_cadence='rate' requires rate_hz"
            )
        if self.update_cadence != "rate" and self.rate_hz is not None:
            raise ValueError(
                f"source {self.id}: rate_hz only valid with update_cadence='rate'"
            )
        return self


class SurfaceGeometry(BaseModel):
    """Geometric definition of a surface region."""
    kind: SurfaceKind
    # rect / tile fields
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    # masked_region: reference to a mask shape (e.g. "sierpinski_corner_top")
    mask: str | None = None
    # wgpu_binding: the binding name (e.g. "content_slot_0")
    binding_name: str | None = None
    # video_out / ndi_out: the output target name
    target: str | None = None


class SurfaceSchema(BaseModel):
    """A typed destination region with optional per-surface effect chain."""
    id: str = Field(..., min_length=1, max_length=64)
    geometry: SurfaceGeometry
    effect_chain: list[str] = Field(default_factory=list)  # ordered effect node IDs
    blend_mode: BlendMode = "over"
    z_order: int = 0
    update_cadence: UpdateCadence = "always"


class Assignment(BaseModel):
    """Binding of source to surface with per-assignment overrides."""
    source: str  # source ID
    surface: str  # surface ID
    transform: dict[str, float] = Field(default_factory=dict)
    opacity: float = Field(1.0, ge=0.0, le=1.0)
    per_assignment_effects: list[str] = Field(default_factory=list)


class Layout(BaseModel):
    """A named scene composed of sources, surfaces, and assignments."""
    name: str
    description: str = ""
    sources: list[SourceSchema]
    surfaces: list[SurfaceSchema]
    assignments: list[Assignment]

    @model_validator(mode="after")
    def _validate_references(self) -> Layout:
        source_ids = {s.id for s in self.sources}
        surface_ids = {s.id for s in self.surfaces}
        if len(source_ids) != len(self.sources):
            raise ValueError("duplicate source IDs in layout")
        if len(surface_ids) != len(self.surfaces):
            raise ValueError("duplicate surface IDs in layout")
        for a in self.assignments:
            if a.source not in source_ids:
                raise ValueError(
                    f"assignment references unknown source: {a.source}"
                )
            if a.surface not in surface_ids:
                raise ValueError(
                    f"assignment references unknown surface: {a.surface}"
                )
        return self
```

### The first layout file: garage-door.json

`config/layouts/garage-door.json` describes the current Sierpinski + cameras + overlays arrangement using the new schema. This is the validation: if the current scene round-trips through the schema, the model is sufficient.

### Tests

`tests/test_compositor_model.py`:

- `test_source_schema_basic` — round-trip a simple camera source
- `test_source_rate_validation` — rate cadence requires rate_hz
- `test_source_kind_enum` — invalid kind rejected
- `test_surface_geometry_kinds` — each SurfaceKind round-trips
- `test_assignment_references` — invalid source/surface refs rejected
- `test_layout_no_duplicate_ids` — duplicate source IDs rejected
- `test_layout_blend_modes` — each BlendMode round-trips
- `test_garage_door_layout_round_trip` — load garage-door.json, dump, parse, compare

### Acceptance

- `shared/compositor_model.py` exists with all 6 types
- `config/layouts/garage-door.json` exists and round-trips through `Layout.model_validate_json()`
- 8+ unit tests pass
- No imports of the new module from existing rendering code (this is an additive phase)

---

## Phase 2b: Extract phase

### File structure

Create `agents/studio_compositor/extract.py`:

```python
"""Extract phase — produces immutable FrameDescription from a Layout.

The Extract phase is the single sync point between the mutable layout
store and the immutable render description. Called once per render frame.
After Extract returns, the FrameDescription can be passed to any thread;
the layout store can be mutated freely on other threads while rendering
runs.

This is the Bevy/Frostbite pattern: retained config + immediate
per-frame rebuild of the runtime description.
"""
```

### Types

```python
from dataclasses import dataclass
from shared.compositor_model import Layout


@dataclass(frozen=True)
class FrameDescription:
    """Immutable snapshot of compositor state for one frame.

    Produced by Extract phase, consumed by the render graph compiler.
    Safe to pass between threads.
    """
    timestamp: float
    frame_index: int
    layout: Layout
    source_versions: dict[str, int]  # source_id → version counter
    source_metadata: dict[str, dict]  # source_id → backend-specific state
```

### Function

```python
def extract_frame_description(
    layout: Layout,
    frame_index: int,
    source_versions: dict[str, int] | None = None,
    source_metadata: dict[str, dict] | None = None,
    timestamp: float | None = None,
) -> FrameDescription:
    """Snapshot the current layout into an immutable FrameDescription.

    Args:
        layout: The current Layout from the layout store. Must already be
            validated.
        frame_index: Monotonically increasing frame counter.
        source_versions: Per-source version counters (Phase 4 will use
            these for cache boundaries). Pass empty dict for now.
        source_metadata: Per-source backend metadata (e.g. last frame
            mtime, content hash). Pass empty dict for now.
        timestamp: Wall clock time. Defaults to time.monotonic().

    Returns:
        FrameDescription that's safe to pass between threads.
    """
    return FrameDescription(
        timestamp=timestamp if timestamp is not None else time.monotonic(),
        frame_index=frame_index,
        layout=layout,
        source_versions=dict(source_versions or {}),
        source_metadata=dict(source_metadata or {}),
    )
```

### Tests

`tests/test_extract.py`:

- `test_extract_basic_returns_frame_description`
- `test_extract_preserves_layout_reference`
- `test_extract_copies_source_versions` (mutating the input dict doesn't affect the snapshot)
- `test_extract_default_timestamp_is_monotonic`
- `test_frame_description_is_frozen` (cannot mutate)
- `test_frame_description_thread_safe_access`

### Acceptance

- `agents/studio_compositor/extract.py` defines `FrameDescription` and `extract_frame_description`
- 5+ unit tests pass
- No rendering code consumes the FrameDescription yet (additive phase)

---

## Phase 2c: Layout loader + hot-reload

### File structure

Create `agents/studio_compositor/layout_loader.py`:

```python
"""LayoutStore — loads Layouts from disk, watches for changes.

Hot-reload via mtime polling at low cadence (1s). Active layout selected
by name. The compositor reads the active layout each frame via the
Extract phase.

The store is the single source of truth for the current Layout. Mutations
go through set_active() or by editing JSON files in the watch directory.
"""
```

### Types

```python
class LayoutStore:
    """Thread-safe holder for the current Layout with disk watch.

    Layouts live at ~/.config/hapax-compositor/layouts/*.json. The store
    watches the directory at startup and on each tick (called from the
    state reader loop). Layout reload is per-file mtime cached.
    """

    def __init__(self, layout_dir: Path | None = None) -> None:
        self._layout_dir = layout_dir or _default_layout_dir()
        self._layouts: dict[str, Layout] = {}
        self._mtimes: dict[str, float] = {}
        self._active_name: str | None = None
        self._lock = threading.Lock()

    def get_active(self) -> Layout | None:
        """Return the currently active Layout, or None if no layout loaded."""
        ...

    def set_active(self, name: str) -> bool:
        """Switch the active layout. Returns True on success."""
        ...

    def list_available(self) -> list[str]:
        """Return the names of all loaded layouts."""
        ...

    def reload_changed(self) -> list[str]:
        """Re-scan the layout directory for new or modified files.

        Returns the list of layout names that changed (added or modified).
        Called from the state reader loop at low cadence (1s).
        """
        ...
```

### Behavior

- On `__init__`, scan the layout directory and load all `.json` files
- `get_active()` returns the active layout (None if not yet set)
- `set_active(name)` requires the name to exist in `_layouts`
- `reload_changed()` is called periodically; mtime comparison triggers reload
- Failed JSON parses are logged but do not crash the loader

### Compositor integration

In `agents/studio_compositor/compositor.py`:

```python
from agents.studio_compositor.layout_loader import LayoutStore

class Compositor:
    def __init__(self):
        # ... existing init ...
        self._layout_store = LayoutStore()
        # Try to load 'garage-door' as the default active layout
        if "garage-door" in self._layout_store.list_available():
            self._layout_store.set_active("garage-door")
```

In `agents/studio_compositor/state.py::state_reader_loop`, add a periodic reload check:

```python
# Layout hot-reload (every ~1s, same cadence as profiles)
if profile_check_counter == 0:  # already-existing 1Hz tick
    try:
        changed = compositor._layout_store.reload_changed()
        if changed:
            log.info("Layouts reloaded: %s", changed)
    except Exception:
        log.debug("Layout reload failed", exc_info=True)
```

The active layout is exposed via `compositor._layout_store.get_active()` but no rendering code yet calls Extract or consumes the FrameDescription.

### Tests

`tests/test_layout_loader.py`:

- `test_loader_loads_files_from_directory`
- `test_loader_skips_invalid_json`
- `test_loader_skips_non_layout_files`
- `test_get_active_returns_none_initially`
- `test_set_active_requires_existing_name`
- `test_reload_detects_modified_files`
- `test_reload_detects_added_files`
- `test_reload_detects_deleted_files`
- `test_thread_safe_get_active_during_reload`

### Acceptance

- `LayoutStore` class loads layouts from `~/.config/hapax-compositor/layouts/`
- Compositor instantiates LayoutStore at startup, sets `garage-door` as active
- State reader loop calls `reload_changed()` at 1Hz
- 8+ unit tests pass
- Live compositor logs "Layouts reloaded" when a layout file changes

---

## Cross-sub-phase concerns

### Branch strategy

```
main
 └── epic/compositor-phase-2 (optional)
      ├── feat/phase-2a-schema      (PR A) — schema + tests + garage-door.json
      ├── feat/phase-2b-extract     (PR B, depends on A) — Extract phase
      └── feat/phase-2c-layout-loader (PR C, depends on B) — LayoutStore
```

Each PR is independently revertible. Each merges sequentially into main.

### Coexistence with current rendering

Phase 2 introduces the data model but does NOT replace any rendering code. The existing GStreamer compositor, the wgpu DynamicPipeline, and all source classes (SierpinskiRenderer, OverlayZoneManager, etc.) continue to work exactly as today. The new Layout exists alongside them as a parallel description.

This is intentional. Phase 3 (executor polymorphism) is where rendering code begins consuming the data model. Phase 2 is the "land the types" phase.

### Validation strategy

The single validation criterion: **the current garage-door arrangement round-trips through the schema cleanly.** If we can't write today's compositor state as a valid Layout JSON, the schema is wrong and needs revision.

The garage-door.json file is the canonical example. Future layouts will be authored against this template.

### Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Schema misses a kind/dimension we'll need in Phase 3 | Medium | Low | Phase 3 spec will revisit and revise; this is expected iteration |
| Layout JSON files conflict with existing config files | Low | Low | Use a new directory `~/.config/hapax-compositor/layouts/` |
| LayoutStore mtime polling adds load to state_reader_loop | Low | Low | 1Hz cadence is the same as the profile check that already runs |
| Adding fields to schemas later breaks existing layouts | Medium | Low | Pydantic supports `extra="allow"` for forward compat |

### Success metrics

Phase 2 is successful when:
- **Zero rendering regressions** (this phase touches no rendering code)
- **garage-door.json round-trips cleanly** through the schema
- **Layout hot-reload works at runtime** (verified by editing the file and seeing log messages)
- **All Phase 2 tests pass** (~25 new tests across 3 test files)
- **The model is concrete enough that Phase 3 can begin** (no fundamental schema gaps surfaced)

---

## Not in scope

Phase 2 does not:

- Replace any rendering code (Phase 3+)
- Implement source/surface dispatch from the data model (Phase 3)
- Cull dead sources or version-check (Phase 4)
- Multi-output targets (Phase 5)
- Plugin discovery (Phase 6)

This is purely a model-introduction phase. The data structures land; nothing consumes them yet.

---

## Appendix A: garage-door.json structure (preview)

```json
{
  "name": "garage-door",
  "description": "Current Garage Door Open layout — Sierpinski + 6 cameras + overlays + 24 shader slots",
  "sources": [
    {"id": "cam-brio-operator", "kind": "camera", "backend": "v4l2",
     "params": {"device": "/dev/v4l/by-id/...", "format": "mjpeg",
                "width": 1280, "height": 720, "framerate": 30}},
    {"id": "cam-c920-desk", "kind": "camera", "backend": "v4l2", "params": {...}},
    ...
    {"id": "yt-slot-0", "kind": "video", "backend": "youtube_player",
     "params": {"slot_id": 0}, "update_cadence": "rate", "rate_hz": 10},
    {"id": "yt-slot-1", "kind": "video", "backend": "youtube_player", "params": {"slot_id": 1}},
    {"id": "yt-slot-2", "kind": "video", "backend": "youtube_player", "params": {"slot_id": 2}},
    {"id": "sierpinski-lines", "kind": "cairo", "backend": "sierpinski_renderer",
     "params": {"render_fps": 10}},
    {"id": "album-cover", "kind": "image", "backend": "image_file",
     "params": {"path": "/dev/shm/hapax-compositor/album-cover.png"},
     "update_cadence": "on_change"},
    {"id": "vitruvian-man", "kind": "image", "backend": "image_file",
     "params": {"path": "assets/vitruvian_man_overlay.png"},
     "update_cadence": "manual"},
    {"id": "obsidian-overlay-cycle", "kind": "text", "backend": "pango",
     "params": {"folder": "~/Documents/Personal/30-areas/stream-overlays/",
                "cycle_seconds": 15}},
    {"id": "halftone-shader", "kind": "shader", "backend": "wgsl_render",
     "params": {"node_type": "halftone"}}
  ],
  "surfaces": [
    {"id": "main-output", "geometry": {"kind": "video_out", "target": "/dev/video42"},
     "z_order": 0},
    {"id": "tile-cam-operator", "geometry": {"kind": "tile"},
     "z_order": 1},
    {"id": "sierpinski-corner-top",
     "geometry": {"kind": "masked_region", "mask": "sierpinski_top"},
     "blend_mode": "over", "z_order": 2},
    {"id": "lower-left-album",
     "geometry": {"kind": "rect", "x": 20, "y": 760, "w": 300, "h": 300},
     "z_order": 3},
    {"id": "upper-left-vitruvian",
     "geometry": {"kind": "rect", "x": 20, "y": 20, "w": 300, "h": 300},
     "z_order": 3},
    {"id": "content-slot-0",
     "geometry": {"kind": "wgpu_binding", "binding_name": "content_slot_0"},
     "z_order": 5}
  ],
  "assignments": [
    {"source": "cam-brio-operator", "surface": "tile-cam-operator", "opacity": 1.0},
    {"source": "yt-slot-0", "surface": "sierpinski-corner-top", "opacity": 0.9},
    {"source": "yt-slot-0", "surface": "content-slot-0", "opacity": 0.9},
    {"source": "album-cover", "surface": "lower-left-album", "opacity": 1.0},
    {"source": "vitruvian-man", "surface": "upper-left-vitruvian", "opacity": 1.0}
  ]
}
```

The full file will be written as part of Phase 2a and committed alongside the schema.
