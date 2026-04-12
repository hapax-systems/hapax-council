"""Compile phase — turns FrameDescription into a CompiledFrame execution plan.

The compile phase is the second of three render-time stages:

  Extract  → snapshot the layout into FrameDescription (Phase 2b)
  Compile  → reason about active sources, version cache, pool keys (Phase 4)
  Execute  → run backends in dependency order (Phase 3)

Phase 4a landed the scaffolding plus dead-source culling. A source is
"dead" for a frame if no Assignment in the layout references it.
Hidden cameras, unbound text overlays, and shader nodes whose output
is not threaded into a surface all become free.

Phase 4b adds version-based cache boundaries. Sources whose version
counter matches the previous frame's are marked cacheable — the
executor can reuse the previous frame's output texture instead of
re-rendering. The version contract: source backends bump their
version when their output would change. Sources that never change
(static images, idle text overlays) trivially stay cached.

The compile phase is pure: it produces an immutable CompiledFrame from
an immutable FrameDescription. No I/O, no thread state, no side effects.
Safe to call from any thread.

No rendering code consumes CompiledFrame yet — same additive pattern as
the Phase 2 extract phase. Future executors built against the unified
data model become its first consumers.

See: docs/superpowers/specs/2026-04-12-phase-4-compile-phase-design.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.studio_compositor.extract import FrameDescription
    from shared.compositor_model import Assignment


@dataclass(frozen=True)
class CompiledFrame:
    """Immutable execution plan for one frame.

    Produced by :func:`compile_frame`; consumed by future executors.

    The dataclass is frozen so callers can pass it freely between threads
    without locking. The contained Assignment objects are themselves
    frozen Pydantic models, so the entire structure is shallow-immutable.

    Attributes:
        frame_index: Monotonically increasing frame counter, mirrored
            from FrameDescription.
        timestamp: Monotonic timestamp when the source FrameDescription
            was extracted.
        layout_name: Name of the active Layout at extract time.
        active_sources: Tuple of source IDs that need rendering this
            frame, in stable layout order. A source is "active" iff at
            least one assignment references it.
        culled_sources: Frozen set of source IDs skipped this frame
            because no assignment references them. Empty when every
            source in the layout is bound to a surface.
        cached_sources: Phase 4b. Frozen set of source IDs whose
            version counter equals the previous compile's version, so
            the executor can rebind the previous frame's texture
            without re-rendering. Always a subset of ``active_sources``
            — culled sources are never cached.
        active_assignments: Tuple of Assignments whose source is in
            ``active_sources``, ordered by destination surface z_order
            then by stable layout order. The executor walks this tuple
            to composite in z order.
        source_versions: Per-source version snapshot taken from the
            FrameDescription. Carried forward so the next compile
            (which receives this CompiledFrame as ``previous``) can
            diff against it without needing the original FrameDescription.
        cull_reason: Per-culled-source reason string for observability.
            Today the reasons are ``"no_assignment_references_source"``
            (4a) and may grow in 4c with pool-eligibility annotations.
    """

    frame_index: int
    timestamp: float
    layout_name: str
    active_sources: tuple[str, ...]
    culled_sources: frozenset[str]
    active_assignments: tuple[Assignment, ...]
    source_versions: dict[str, int] = field(default_factory=dict)
    cached_sources: frozenset[str] = frozenset()
    cull_reason: dict[str, str] = field(default_factory=dict)

    @property
    def total_sources(self) -> int:
        """Total source count across active and culled."""
        return len(self.active_sources) + len(self.culled_sources)

    @property
    def cull_count(self) -> int:
        """Number of sources skipped this frame."""
        return len(self.culled_sources)

    @property
    def cache_count(self) -> int:
        """Number of active sources reusing the previous frame's output."""
        return len(self.cached_sources)

    @property
    def render_count(self) -> int:
        """Number of active sources that need a fresh render this frame."""
        return len(self.active_sources) - len(self.cached_sources)


def compile_frame(
    frame: FrameDescription,
    previous: CompiledFrame | None = None,
) -> CompiledFrame:
    """Compile a FrameDescription into a CompiledFrame execution plan.

    Walks the layout in three logical passes:

    1. **Dead-source culling (4a)** — a source is active iff at least
       one Assignment in the layout references it.
    2. **Version-cache boundary (4b)** — when ``previous`` is supplied,
       any active source whose version matches the previous compile's
       version is marked as cacheable. The executor reuses the previous
       frame's output texture instead of re-rendering. Sources missing
       from the previous compile (new sources, freshly added) are
       always rendered. Sources whose version is unknown in the
       current frame (no entry in ``source_versions``) are treated as
       changed — defensive default that errs on the side of correctness.
    3. **Render order (4a)** — assignments sorted by destination surface
       z_order then stable layout order.

    The compile phase is pure: no I/O, no side effects, no thread state.
    Same inputs → same output.

    Args:
        frame: The FrameDescription produced by extract_frame_description().
        previous: The CompiledFrame from the immediately preceding frame,
            if any. First frame after startup passes ``None``.

    Returns:
        Immutable CompiledFrame. Safe to pass to executors on any thread.
    """
    layout = frame.layout

    # Build the set of source IDs referenced by any assignment. This is
    # the single pass that determines which sources are alive this frame.
    referenced: set[str] = {assignment.source for assignment in layout.assignments}

    # Walk sources in stable layout order. Each source is either active
    # (referenced) or culled (not referenced). The cull reason is
    # recorded for observability — future sub-phases add more reasons.
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
    # the assignment's position in the layout for stable output. The
    # executor walks the resulting tuple in render order.
    surface_z: dict[str, int] = {s.id: s.z_order for s in layout.surfaces}

    indexed = list(enumerate(layout.assignments))
    indexed.sort(key=lambda item: (surface_z.get(item[1].surface, 0), item[0]))

    # Drop assignments whose source got culled. (An orphan assignment
    # can't happen on a validated Layout because Pydantic enforces
    # source existence; this filter is defensive against future changes.)
    active_assignments = tuple(
        assignment for _, assignment in indexed if assignment.source in referenced
    )

    # Phase 4b: version-cache boundary. A source is cacheable iff:
    #   1. It's active (not culled),
    #   2. The previous compile produced an output for it (it was active
    #      in the previous frame too),
    #   3. Its current version equals its previous version, AND
    #   4. Both versions are present (defensive — missing version is
    #      treated as "changed").
    cached_ids: set[str] = set()
    if previous is not None:
        previous_versions = previous.source_versions
        previous_active = set(previous.active_sources)
        for source_id in active_ids:
            if source_id not in previous_active:
                continue
            prev_v = previous_versions.get(source_id)
            curr_v = frame.source_versions.get(source_id)
            if prev_v is None or curr_v is None:
                continue
            if prev_v == curr_v:
                cached_ids.add(source_id)

    return CompiledFrame(
        frame_index=frame.frame_index,
        timestamp=frame.timestamp,
        layout_name=layout.name,
        active_sources=tuple(active_ids),
        culled_sources=frozenset(culled_ids),
        active_assignments=active_assignments,
        source_versions=dict(frame.source_versions),
        cached_sources=frozenset(cached_ids),
        cull_reason=cull_reason,
    )
