"""Extract phase — produces immutable FrameDescription from a Layout.

The Extract phase is the single sync point between the mutable layout
store and the immutable render description. Called once per render frame.
After Extract returns, the FrameDescription can be passed to any thread;
the layout store can be mutated freely on other threads while rendering
runs.

This is the Bevy/Frostbite pattern: retained config + immediate per-frame
rebuild of the runtime description. Phase 2b of the compositor unification
epic. The FrameDescription type exists but is not yet consumed by any
rendering code — that's Phase 3.

See docs/superpowers/specs/2026-04-12-phase-2-data-model-design.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from shared.compositor_model import Layout


@dataclass(frozen=True)
class FrameDescription:
    """Immutable snapshot of compositor state for one frame.

    Produced by the Extract phase; consumed by the render graph compiler
    in Phase 4. Safe to pass between threads.

    Attributes:
        timestamp: Wall clock time when the snapshot was taken (monotonic).
        frame_index: Monotonically increasing frame counter.
        layout: The Layout active at the time of extraction.
        source_versions: Per-source version counters. Phase 4 will use
            these for cache boundaries; for now, an empty or
            partially-populated dict is fine.
        source_metadata: Per-source backend-specific metadata (last frame
            mtime, content hash, decode latency, etc.). Phase 3 backends
            will populate this; for now an empty dict is fine.
    """

    timestamp: float
    frame_index: int
    layout: Layout
    source_versions: dict[str, int] = field(default_factory=dict)
    source_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)

    def source_version(self, source_id: str) -> int:
        """Return the version counter for a source, defaulting to 0."""
        return self.source_versions.get(source_id, 0)

    def source_meta(self, source_id: str) -> dict[str, Any]:
        """Return metadata for a source, defaulting to empty dict."""
        return self.source_metadata.get(source_id, {})


def extract_frame_description(
    layout: Layout,
    frame_index: int,
    source_versions: dict[str, int] | None = None,
    source_metadata: dict[str, dict[str, Any]] | None = None,
    timestamp: float | None = None,
) -> FrameDescription:
    """Snapshot the current layout into an immutable FrameDescription.

    The Extract phase is the single sync point between the mutable layout
    store and the immutable render description. Inputs are copied (not
    aliased) so the caller can mutate them after this call without
    affecting the snapshot.

    Args:
        layout: The current Layout from the layout store. Must already be
            validated (i.e. constructed via the Pydantic model).
        frame_index: Monotonically increasing frame counter.
        source_versions: Per-source version counters. Defaults to empty
            dict. Phase 4 will use these for cache boundaries.
        source_metadata: Per-source backend metadata. Defaults to empty
            dict. Phase 3 backends will populate this.
        timestamp: Wall clock time. Defaults to time.monotonic().

    Returns:
        FrameDescription that's safe to pass between threads.
    """
    return FrameDescription(
        timestamp=timestamp if timestamp is not None else time.monotonic(),
        frame_index=frame_index,
        layout=layout,
        source_versions=dict(source_versions or {}),
        source_metadata={k: dict(v) for k, v in (source_metadata or {}).items()},
    )
