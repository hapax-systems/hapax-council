# Phase 4: Compile Phase + Optimizations — Design Spec

**Date:** 2026-04-12
**Status:** Approved (self-authored, alpha session)
**Epic:** `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md`
**Phase:** 4 of 7
**Risk:** Low–Medium (introduces new optional optimization layer; no rendering hot path touched)
**Depends on:** Phase 2 complete (data model + Extract phase), Phase 3 complete (executor polymorphism)

---

## Purpose

Build the **compile phase** that sits between Extract (Phase 2b) and Execute, and add the three optimizations the master plan calls for:

1. **Dead-source culling** — sources whose output isn't reached by any surface are skipped this frame.
2. **Version counters + cache boundaries** — sources that didn't change reuse their previous render output instead of re-running.
3. **Transient texture pooling** — intermediate textures (effect chain outputs) are allocated from a frame-local pool instead of fresh per-frame.

After Phase 4, **cost scales with what's visible, not what's configured.** Hidden cameras consume zero work. Static text is rendered once and cached. Effect chains don't thrash texture memory.

This is the performance substrate the rest of the epic depends on. Phase 5 (multi-output) and Phase 7 (budget enforcement) both consume the compile output. Phase 6 (plugin system) loads sources at the same plane the compile phase reasons about.

---

## Scope

Three sub-phases, each shipping as its own PR:

1. **Phase 4a — Compile scaffolding + dead-source culling.**
   New `agents/studio_compositor/compile.py` with `compile_frame()`. Defines `CompiledFrame` (immutable, thread-safe). Implements the simplest optimization: mark every source referenced by an assignment as active; everything else is culled. No version logic, no pooling. Tests cover the culling decision and assignment ordering.

2. **Phase 4b — Version counters + cache boundaries.**
   `CompiledFrame` gains `cached_sources: frozenset[str]` for sources whose version is identical to the previous compile's. Compile takes an optional `previous: CompiledFrame | None` argument. Sources whose `version[id] == previous.version[id]` are marked as cacheable (executors can reuse the previous frame's texture). Tests cover the version-based cache decision.

3. **Phase 4c — Transient texture pool (Python-side reasoning, not Rust).**
   New `TransientTextureRegistry` that the compile phase populates with intermediate texture descriptors. The registry exposes a `pool_key(descriptor) -> int` so executors can reuse textures across frames keyed by `(width, height, format)`. The actual pooled allocator lives in the executor (Rust); Phase 4c only ships the Python-side reasoning that says "this intermediate is pool-eligible" + tests + documentation. The Rust executor consumes it in a follow-up. *This is the smallest, most conservative interpretation of 4c — it lands the data plumbing without touching wgpu allocation paths, which is too invasive for one PR.*

Each sub-phase is independently revertible and produces working software on its own.

---

## Phase 4a: Compile scaffolding + dead-source culling

### File structure

Create `agents/studio_compositor/compile.py`:

```python
"""Compile phase — turns FrameDescription into a CompiledFrame execution plan.

The compile phase is the second of three render-time stages:

  Extract  → snapshot the layout into FrameDescription (Phase 2b)
  Compile  → reason about active sources, version cache, and pooling (Phase 4)
  Execute  → run backends in dependency order (Phase 3)

Phase 4a lands the scaffolding plus the first optimization: dead-source
culling. A source is "dead" for a frame if no assignment references it.
Hidden cameras, unbound text overlays, and shader nodes whose output is
not threaded into a surface all become free.

Phase 4 of the compositor unification epic — see
docs/superpowers/specs/2026-04-12-phase-4-compile-phase-design.md
"""
```

### Types

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.studio_compositor.extract import FrameDescription
    from shared.compositor_model import Assignment, Layout


@dataclass(frozen=True)
class CompiledFrame:
    """Immutable execution plan for one frame.

    Produced by compile_frame(); consumed by the executor.

    Attributes:
        frame_index: Monotonically increasing frame counter (mirrors
            FrameDescription.frame_index).
        timestamp: Wall clock time when the source FrameDescription was
            extracted (mirrors FrameDescription.timestamp).
        layout_name: Name of the active Layout.
        active_sources: Tuple of source IDs that need rendering this
            frame, in stable layout order. A source is "active" iff
            at least one assignment references it AND it's not in
            culled_sources.
        culled_sources: Frozen set of source IDs skipped this frame
            because no assignment references them. Empty when every
            source is bound.
        active_assignments: Tuple of Assignments whose source is in
            active_sources, ordered by the surface's z_order then by
            stable layout order for deterministic output.
        cull_reason: Per-culled-source reason string for observability.
    """

    frame_index: int
    timestamp: float
    layout_name: str
    active_sources: tuple[str, ...]
    culled_sources: frozenset[str]
    active_assignments: tuple[Assignment, ...]
    cull_reason: dict[str, str] = field(default_factory=dict)

    @property
    def total_sources(self) -> int:
        return len(self.active_sources) + len(self.culled_sources)

    @property
    def cull_count(self) -> int:
        return len(self.culled_sources)
```

### Function

```python
def compile_frame(frame: FrameDescription) -> CompiledFrame:
    """Compile a FrameDescription into a CompiledFrame execution plan.

    Phase 4a: dead-source culling only. A source is active iff at least
    one Assignment in the layout references it. Future sub-phases will
    extend this with version-cache boundaries (4b) and transient pool
    descriptors (4c).

    The compile phase is pure: it produces an immutable CompiledFrame
    from an immutable FrameDescription. No I/O, no thread state, no
    side effects. Safe to call from any thread.

    Args:
        frame: The FrameDescription produced by extract_frame_description().

    Returns:
        Immutable CompiledFrame. Safe to pass to executors on any thread.
    """
    layout = frame.layout
    referenced: set[str] = set()
    for assignment in layout.assignments:
        referenced.add(assignment.source)

    active_ids: list[str] = []
    culled_ids: set[str] = set()
    cull_reason: dict[str, str] = {}
    for source in layout.sources:
        if source.id in referenced:
            active_ids.append(source.id)
        else:
            culled_ids.add(source.id)
            cull_reason[source.id] = "no_assignment_references_source"

    # Order assignments by z_order of the destination surface, then by
    # the assignment's position in the layout for stable output.
    surface_z: dict[str, int] = {s.id: s.z_order for s in layout.surfaces}

    def _key(item: tuple[int, Assignment]) -> tuple[int, int]:
        idx, assignment = item
        z = surface_z.get(assignment.surface, 0)
        return (z, idx)

    indexed = list(enumerate(layout.assignments))
    indexed.sort(key=_key)
    active_assignments = tuple(
        a for _, a in indexed if a.source in referenced
    )

    return CompiledFrame(
        frame_index=frame.frame_index,
        timestamp=frame.timestamp,
        layout_name=layout.name,
        active_sources=tuple(active_ids),
        culled_sources=frozenset(culled_ids),
        active_assignments=active_assignments,
        cull_reason=cull_reason,
    )
```

### Tests

`tests/test_compile.py`:

- `test_empty_layout_compiles_to_empty_plan` — layout with no sources/surfaces/assignments
- `test_all_sources_referenced_no_culling` — every source has at least one assignment
- `test_unreferenced_source_is_culled` — one orphan source → culled with reason
- `test_culled_source_excluded_from_active` — verify the active_sources tuple
- `test_active_assignments_ordered_by_surface_zorder` — ascending z_order
- `test_active_assignments_stable_within_zorder` — two assignments with the same z_order preserve layout order
- `test_assignments_to_culled_sources_excluded` — orphan assignments are not in active_assignments
- `test_total_sources_property` — active + culled = total
- `test_cull_count_property` — matches culled_sources length
- `test_compiled_frame_is_frozen` — cannot mutate
- `test_compile_frame_is_pure_function` — same input twice → equal output
- `test_compile_garage_door_layout` — round-trip the canonical garage-door.json layout

### Acceptance

- `agents/studio_compositor/compile.py::compile_frame` exists
- `CompiledFrame` is frozen and thread-safe
- 12 unit tests pass
- `compile_frame(extract_frame_description(layout, 0))` succeeds for the canonical garage-door layout
- No rendering code consumes the CompiledFrame yet — same additive pattern as Phase 2

### PR shape

- ~150 lines of new module
- ~250 lines of tests
- 0 modifications to existing code (additive only)

### Risk

Very low. Pure function, no side effects, no rendering touched.

---

## Phase 4b: Version counters + cache boundaries

### Scope

Extend `CompiledFrame` and `compile_frame()` with version-based cache decisions:

```python
@dataclass(frozen=True)
class CompiledFrame:
    # ... existing 4a fields ...
    cached_sources: frozenset[str] = frozenset()
    """Source IDs whose version is unchanged from previous frame and can
    reuse their previous-frame texture without re-rendering."""


def compile_frame(
    frame: FrameDescription,
    previous: CompiledFrame | None = None,
    previous_versions: dict[str, int] | None = None,
) -> CompiledFrame:
```

The decision rule:

```python
cached: set[str] = set()
if previous is not None and previous_versions is not None:
    for source_id in active_ids:
        prev_version = previous_versions.get(source_id)
        curr_version = frame.source_versions.get(source_id)
        if prev_version is not None and prev_version == curr_version:
            cached.add(source_id)
```

A source is *cacheable* iff:
1. It's in `active_sources` (not culled)
2. The previous compile produced an output for it
3. Its current version equals its previous version

The executor reads `cached_sources` and skips re-rendering those — it
just rebinds the previous frame's texture. The Rust side already
keeps named output textures across frames; this is the Python-side
hint that says "no need to re-run the pass."

### Tests

`tests/test_compile.py` (additional):

- `test_no_previous_frame_no_caching` — first frame has empty cached_sources
- `test_unchanged_version_marks_source_cached` — same version → cached
- `test_changed_version_marks_source_not_cached` — different version → re-render
- `test_culled_sources_not_cached` — culled sources are not in cached_sources
- `test_new_source_not_cached` — source not in previous_versions → not cached
- `test_missing_current_version_treated_as_changed` — defensive
- `test_compile_frame_with_previous_compiles_garage_door` — round-trip

### Acceptance

- `CompiledFrame.cached_sources` exists
- `compile_frame()` accepts `previous` + `previous_versions` arguments
- Cache decision matches the rule above
- 7 additional unit tests pass

### PR shape

- ~80 lines of new code (one field, one decision pass)
- ~150 lines of tests

### Risk

Low. Still purely additive, still no rendering touched.

---

## Phase 4c: Transient texture pool (Python-side reasoning)

### Scope

The compile phase identifies intermediate textures — outputs of effect-chain stages that aren't the final output of any surface. These are pool-eligible: their lifetime is exactly one frame, and a future frame can reuse the GPU memory without conflict.

Phase 4c lands the **Python-side reasoning** that decides which intermediates are pool-eligible. The actual GPU allocator lives in the Rust executor and is touched in a follow-up PR (4c-rust).

```python
@dataclass(frozen=True)
class TextureDescriptor:
    """Compact key for transient texture pooling.

    Two intermediates with the same descriptor can share GPU memory
    across frames. (width, height, format) is the canonical key
    matching the Rust pool's bucket strategy.
    """
    width: int
    height: int
    format: str  # e.g. "rgba8unorm"


@dataclass(frozen=True)
class TransientTexture:
    """An intermediate texture in a frame's render plan.

    Has a stable name (the surface effect-chain stage that produces it),
    a descriptor for pool key matching, and a pool_key the executor uses
    to look up a reusable allocation.
    """
    name: str
    descriptor: TextureDescriptor
    pool_key: int  # hash(descriptor) — stable across frames


@dataclass(frozen=True)
class CompiledFrame:
    # ... existing fields ...
    transient_textures: tuple[TransientTexture, ...] = ()
```

The compile phase walks each active surface's effect chain. For each
non-final stage, it generates a TransientTexture with a descriptor
derived from the surface geometry (`w, h`) and the canonical RGBA
format. The pool_key is `hash(descriptor)`.

### Tests

`tests/test_compile.py` (additional):

- `test_no_effect_chains_no_transients` — surfaces without effect chains
- `test_one_stage_chain_one_transient` — single effect node → one transient
- `test_multi_stage_chain_per_stage_transients` — N effect nodes → N transients
- `test_pool_key_stable_for_same_descriptor` — two transients with same dims share key
- `test_pool_key_distinct_for_different_descriptors` — different dims → different keys

### Acceptance

- `TextureDescriptor`, `TransientTexture` exist
- `CompiledFrame.transient_textures` populated by compile_frame()
- Pool key is deterministic and stable across frames
- 5 additional unit tests pass

### PR shape

- ~100 lines of new code
- ~120 lines of tests

### Risk

Low. Adds Python-side reasoning only; no GPU allocator changes.

The Rust side becomes a follow-up: a separate `Phase 4c-rust` PR that
adds a `TransientTexturePool` to `dynamic_pipeline.rs` keyed on the
same `pool_key`. That PR is sized similarly to Phase 3a — small,
mechanical, and reversible.

---

## Cross-sub-phase concerns

### Branch strategy

```
main
 ├── feat/phase-4a-compile-culling     (PR A) — scaffolding + dead-source culling
 ├── feat/phase-4b-compile-versions    (PR B, depends on A) — version cache
 └── feat/phase-4c-compile-transients  (PR C, depends on B) — transient pool reasoning
```

Each PR merges directly into main. Same incremental pattern as Phase 1, 2, and 3.

### Coexistence with current rendering

Phase 4 is **purely additive**. The compile phase produces a CompiledFrame that no rendering code yet consumes. The current GStreamer compositor and the wgpu DynamicPipeline run unchanged. CompiledFrame becomes the input contract for future executors built against the unified data model.

This is the same pattern as Phase 2 (extract phase exists, nothing consumes it yet). The plumbing lands first; consumers come later — likely in Phase 5, when multi-output forces a real executor against the data model.

### Validation strategy

Pure function, deterministic output. The validation criterion is: **`compile_frame(extract_frame_description(garage_door_layout, 0))` produces a CompiledFrame whose active_sources matches the manually-derived expectation.** If it does, the compile reasoning is correct.

Visual output is trivially unchanged because no rendering reads CompiledFrame yet.

### Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Compile phase becomes too tightly coupled to current Layout shape | Medium | Low | CompiledFrame is independent of Layout — it only stores derived data, not Pydantic refs (except `Assignment` which is already frozen) |
| Future executor needs different CompiledFrame fields | Medium | Low | Frozen dataclass; new fields are forward-compatible additions |
| Version counter source-of-truth is unclear (who increments?) | High | Low | Phase 4b documents the contract: source backends bump their version when output would change. The Phase 3b CairoSourceRunner, the wgsl_compiler param-change diff, and the image_loader mtime cache all become natural version sources. This gets implemented incrementally; for Phase 4b, source_versions can be empty (everything appears changed). |
| TransientTexture descriptor doesn't match future Rust pool granularity | Medium | Low | Format/dim is the standard pool key in every render graph implementation we surveyed. If the Rust side wants more (mip levels, sample count), the descriptor extends forward-compatibly. |

### Success metrics

Phase 4 is complete when:
- **`compile_frame()` exists** and produces deterministic CompiledFrame output for the canonical layout
- **Dead-source culling identifies orphan sources** in the garage-door layout (verified via test)
- **Version-cache decision is correct** for both first frame (empty) and steady-state frames (cached)
- **Transient texture descriptors are stable** (same input → same pool keys)
- **Zero rendering regressions** (this phase touches no rendering code)
- **All Phase 4 tests pass** (~24 new tests across 3 sub-phases)

---

## Not in scope

Phase 4 does not:

- Wire any executor to consume CompiledFrame (deferred to Phase 5 or follow-up).
- Change wgpu allocator or texture management (the Rust pool is a follow-up to 4c).
- Implement source backends that produce version counters (Phase 4b's `source_versions` can stay empty until Phase 5/6 backends populate it).
- Add multi-output support (Phase 5).
- Cull culled sources from the GStreamer side (different code path; not in scope).
- Per-source frame-time accounting (Phase 7).

---

## Appendix A: future executor consumer (Phase 5 preview)

After Phase 4 lands, a future Phase 5 executor will look like:

```python
def execute_frame(compiled: CompiledFrame, executor: Executor) -> None:
    for source_id in compiled.active_sources:
        if source_id in compiled.cached_sources:
            executor.bind_cached(source_id)        # texture reuse
            continue
        executor.render_source(source_id)          # cold render
    for assignment in compiled.active_assignments:
        executor.composite(assignment)             # destination blit
```

Three branches: cached source → bind, active source → render, assignment
→ composite. Each branch reads exactly the fields the compile phase
populated. This is the contract the executor will hit; the compile phase's
job is to make these decisions correct.
