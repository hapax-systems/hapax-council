# Phase 5b: GStreamer + wgpu Unification — Epic Spec

**Date:** 2026-04-12
**Status:** Approved (self-authored, alpha session)
**Epic:** `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md`
**Phase:** 5b of 7
**Risk:** Medium-high (touches the live rendering hot path)
**Depends on:** Phase 5a complete (multi-target compile + v2 plan format)

---

## Purpose

Unify the two parallel rendering pipelines — GStreamer composition for
the v4l2 stream output and wgpu composition for the visual surface —
under one model. After Phase 5b, **the wgpu side is the canonical
compositor** and the GStreamer side becomes pure ingest (cameras,
v4l2 sources, audio).

This is the architectural payoff for the entire compositor unification
epic. Phases 1-5a built the data plane (Source/Surface/Assignment),
the polymorphic executor, the compile-phase optimizations, and the
v2 multi-target plan format. Phase 5b lights it up.

---

## Decomposition into atomic sub-phases

The "multi-week" framing in earlier specs treated 5b as a single
monolithic migration. Restructured as an epic, it ships today as
**four self-contained sub-phases**, each its own PR and each
purely additive on top of the previous:

| Sub-phase | Layer | Risk | Visual change |
|---|---|---|---|
| 5b1 | Rust DynamicPipeline multi-target render loop | Medium | None (default target = "main", ShmOutput unchanged) |
| 5b2 | Multi-target garage-door layout + video_out surfaces | Low | None (layout JSON only, no consumer yet) |
| 5b3 | Per-target output routing API in Python | Low | None (data plumbing, no host wiring yet) |
| 5b4 | GStreamer ingest_only mode + Python↔wgpu bridge | Medium | None when default-off; toggle is operator-controlled |

Each sub-phase preserves the live system's current behavior. Sub-phase
5b4 introduces the ingest_only mode as a **capability**, gated behind
an explicit config flag. The operator flips the flag when ready to
test live; this PR does NOT toggle it on by default.

---

## Sub-phase 5b1: Rust multi-target render loop

### File scope
- `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`

### Changes

1. **`DynamicPass` gains `target: String`** so the executor knows
   which target each pass belongs to. Defaults to `"main"` for v1
   plans.

2. **`DynamicPipeline.passes: Vec<DynamicPass>`** stays as a flat
   vector — but the build phase iterates `plan.passes_by_target()`
   from Phase 5a and tags each pass with its target. The render
   loop walks the same flat vector but groups by target for output
   binding.

3. **Texture name namespacing.** Per-target intermediate textures
   need distinct names so two targets don't clobber each other's
   `layer_0` / `final`. The build phase rewrites pass inputs and
   outputs:
   - `layer_N` → `{target}:layer_N`
   - `final` → `{target}:final`
   - `@accum_*`, `@live`, `@smooth`, `@hls`, `content_slot_*` →
     unchanged (these are global)
   - Any name already containing `:` → unchanged (idempotent)

4. **Texture pool extension.** `self.textures` continues as a flat
   `HashMap<String, PoolTexture>` keyed on the namespaced names.
   `ensure_texture(device, "main:final")` creates the per-target
   final texture.

5. **Render loop walks every pass.** No grouping needed — each pass
   already references its target-namespaced output. `is_temporal`
   detection still uses `@accum_` prefix.

6. **ShmOutput continues to read `main:final`** so the existing
   `/dev/shm/hapax-imagination/frame.jpg` consumer keeps working.

7. **New public API**: `pub fn get_target_output_view(&self,
   target: &str) -> Option<&wgpu::TextureView>` for future host
   wiring (5b3).

### Backwards compat
- v1 plans (`{passes: [...]}`) wrap into a synthetic `"main"` target,
  so legacy plans render byte-identically.
- v2 plans with one `"main"` target produce identical render output
  (just with `main:final` as the texture name internally).
- Existing tests pass with the same render output.

### Tests (Rust)
- `parses_v2_multi_target_plan_into_passes_by_target` — load a 2-target
  plan, verify both targets get DynamicPass entries
- `texture_names_namespaced_by_target` — verify rewrite rules
- `temporal_pass_names_unchanged` — `@accum_*` not rewritten
- `content_slot_names_unchanged` — `content_slot_N` not rewritten
- `v1_plan_synthesizes_main_target` — flat passes load with target=main
- `get_target_output_view_returns_correct_texture`
- `unknown_target_returns_none`

---

## Sub-phase 5b2: Multi-target garage-door layout

### File scope
- `config/layouts/garage-door.json`
- `tests/test_compositor_model.py` (smoke check)

### Changes

Add two new `Surface(kind="video_out")` instances to the canonical
garage-door layout:

```json
{
  "id": "stream-out",
  "geometry": {"kind": "video_out", "target": "/dev/video42"},
  "z_order": 1000,
  "blend_mode": "over"
},
{
  "id": "winit-window",
  "geometry": {"kind": "video_out", "target": "wgpu_window"},
  "z_order": 1000,
  "blend_mode": "over"
}
```

These surfaces are valid Layout entries today (Phase 2a's `SurfaceKind`
already includes `video_out`), but until 5b3 lands no executor reads
them as render targets. They're scaffolding for 5b3.

### Tests
- `test_garage_door_has_video_out_surfaces` — round-trip the layout,
  count `video_out` surfaces
- `test_video_out_surfaces_have_target_field` — geometry.target
  populated

---

## Sub-phase 5b3: Per-target output routing API

### File scope
- `agents/studio_compositor/output_router.py` (new)
- `tests/test_output_router.py` (new)

### Changes

`OutputRouter` is the host-side glue that maps a `CompiledFrame`'s
targets to physical sinks:

```python
@dataclass(frozen=True)
class OutputBinding:
    target: str        # render target name (e.g. "main")
    sink_kind: str     # "v4l2", "winit", "shm", "ndi"
    sink_path: str     # device path or sink-specific identifier


class OutputRouter:
    """Maps render targets to output sinks per layout."""

    def __init__(self, bindings: list[OutputBinding]) -> None: ...

    @classmethod
    def from_layout(cls, layout: Layout) -> OutputRouter:
        """Build an OutputRouter by walking video_out surfaces in the
        layout. Each video_out surface becomes one OutputBinding.
        The binding's sink_kind is inferred from the geometry.target
        prefix:
            /dev/video* → v4l2
            wgpu_window  → winit
            ndi://...    → ndi
            shm://...    → shm
        Anything else → "shm" (safe default).
        """

    def bindings(self) -> tuple[OutputBinding, ...]: ...
    def for_target(self, target: str) -> OutputBinding | None: ...
```

This is a pure-Python data plumbing module. No actual sink writes
happen here — that's the operator's compositor code, which reads
the bindings and wires them appropriately.

### Tests
- `test_output_router_from_layout_walks_video_out_surfaces`
- `test_v4l2_sink_kind_inferred_from_dev_video_path`
- `test_wgpu_window_sink_kind_inferred`
- `test_ndi_sink_kind_inferred`
- `test_unknown_target_falls_back_to_shm`
- `test_for_target_returns_binding_or_none`
- `test_garage_door_layout_produces_two_bindings`

---

## Sub-phase 5b4: GStreamer ingest_only mode

### File scope
- `agents/studio_compositor/ingest_mode.py` (new)
- `tests/test_ingest_mode.py` (new)

### Changes

`IngestMode` is a typed enum + helper that lets the operator switch
between **compose mode** (current behavior — GStreamer composites
cameras, overlays, fx in a single pipeline) and **ingest mode**
(GStreamer ingests cameras only, the wgpu side composites).

```python
class IngestMode(StrEnum):
    COMPOSE = "compose"      # current default
    INGEST_ONLY = "ingest_only"  # Phase 5b4: cameras → wgpu


def current_mode() -> IngestMode:
    """Read the current mode from ~/.cache/hapax/compositor-mode.

    Defaults to COMPOSE so existing operators see no change. The
    operator flips the flag when ready to test the wgpu compositor
    pipeline end-to-end.
    """

def set_mode(mode: IngestMode) -> None: ...
def is_ingest_only() -> bool: ...
```

The mode is read by the GStreamer compositor at pipeline-build time
(in `pipeline.py`). When `INGEST_ONLY`, the compositor:
1. Builds only the camera ingest legs (v4l2src + decode + tee)
2. Wires each camera tee to a shared-memory writer the wgpu side
   reads via the existing source protocol (Phase 1b)
3. Skips the cairooverlay, glvideomixer, and v4l2sink legs — the
   wgpu side now produces the v4l2sink output via its `main:final`
   render target (already exposed via 5b1's `get_target_output_view`)

This PR ships the **mode flag and the helper** but does NOT
modify `pipeline.py` or wire the wgpu→v4l2sink path. Those are
deferred to a final wiring PR (5b5) the operator can flip
explicitly when ready to test the live system. The 5b4 capability
gives the operator a clean toggle without changing default behavior.

### Tests
- `test_default_mode_is_compose`
- `test_set_mode_persists_to_disk`
- `test_set_mode_then_current_mode_returns_value`
- `test_is_ingest_only_helper`
- `test_invalid_mode_in_file_falls_back_to_compose`
- `test_set_mode_creates_parent_dir`

---

## Acceptance (epic-wide)

- The Rust executor renders multi-target plans (5b1)
- The garage-door layout declares `video_out` surfaces for stream +
  window targets (5b2)
- `OutputRouter.from_layout()` produces correct sink bindings (5b3)
- An `IngestMode` toggle exists with COMPOSE as the default (5b4)
- All existing tests pass (no regressions)
- New tests pass (~30 additional)
- `cargo check` clean
- Visual output unchanged when defaults are used

---

## What's *not* in 5b (deferred)

The "actual GStreamer pipeline rewire" — modifying `pipeline.py` to
honor `is_ingest_only()` and skip the cairooverlay/glvideomixer
legs — is a final wiring step. It's small (one if/else branch in
`pipeline.py::create_pipeline`) but requires live-system smoke
testing and an operator-supervised toggle event. After 5b1-5b4
land, the operator can ship that final flip in a one-liner PR
with explicit live validation.

Phase 5b's epic deliverable: **the capability exists, the data
plane is connected end-to-end, and flipping the mode is a one-line
config change**. The flip itself is the operator's call.
