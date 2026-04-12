"""Compile phase — turns FrameDescription into a CompiledFrame execution plan.

The compile phase is the second of three render-time stages:

  Extract  → snapshot the layout into FrameDescription (Phase 2b)
  Compile  → reason about active sources, version cache, pool keys (Phase 4)
  Execute  → run backends in dependency order (Phase 3)

Phase 4a lands the scaffolding plus the first optimization: dead-source
culling. A source is "dead" for a frame if no Assignment in the layout
references it. Hidden cameras, unbound text overlays, and shader nodes
whose output is not threaded into a surface all become free.

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
        active_assignments: Tuple of Assignments whose source is in
            ``active_sources``, ordered by destination surface z_order
            then by stable layout order. The executor walks this tuple
            to composite in z order.
        cull_reason: Per-culled-source reason string for observability.
            Today the only reason is ``"no_assignment_references_source"``;
            Phase 4b/4c will extend this with version-based and pool-
            eligibility reasons.
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
        """Total source count across active and culled."""
        return len(self.active_sources) + len(self.culled_sources)

    @property
    def cull_count(self) -> int:
        """Number of sources skipped this frame."""
        return len(self.culled_sources)


def compile_frame(frame: FrameDescription) -> CompiledFrame:
    """Compile a FrameDescription into a CompiledFrame execution plan.

    Phase 4a: dead-source culling only. A source is active iff at least
    one Assignment in the layout references it. Future sub-phases will
    extend this with version-cache boundaries (4b) and transient texture
    pool descriptors (4c).

    The compile phase is pure: no I/O, no side effects, no thread state.
    Same input → same output.

    Args:
        frame: The FrameDescription produced by extract_frame_description().

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

    return CompiledFrame(
        frame_index=frame.frame_index,
        timestamp=frame.timestamp,
        layout_name=layout.name,
        active_sources=tuple(active_ids),
        culled_sources=frozenset(culled_ids),
        active_assignments=active_assignments,
        cull_reason=cull_reason,
    )
