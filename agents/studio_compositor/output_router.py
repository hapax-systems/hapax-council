"""OutputRouter — host-side glue between render targets and output sinks.

Phase 5b3 of the compositor unification epic. Walks a Layout's
``video_out`` surfaces and produces a list of :class:`OutputBinding`
records that the operator's compositor code uses to wire each render
target's output to the appropriate sink (v4l2 device, NDI source,
winit window, shared memory).

This module is **pure data plumbing**. No actual sink writes happen
here — the operator's GStreamer pipeline (or future wgpu sink code)
reads the bindings and acts on them. Phase 5b1 already exposes
``DynamicPipeline.get_target_output_view(target)`` which the sink
code calls to grab the wgpu texture for each target.

The router infers ``sink_kind`` from the surface's
``geometry.target`` string:

- ``/dev/video*`` → ``v4l2`` (the streaming v4l2sink output)
- ``wgpu_winit_window`` (or ``wgpu_window``) → ``winit``
- ``ndi://...`` → ``ndi``
- ``shm://...`` → ``shm``
- anything else → ``shm`` (safe default)

A surface's ``render_target`` field selects which Phase 5b1 render
target feeds the sink. ``None`` defaults to ``"main"`` so the
existing single-target garage-door layout works without ceremony.

See: docs/superpowers/specs/2026-04-12-phase-5b-unification-epic.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from shared.compositor_model import Layout


SinkKind = Literal["v4l2", "winit", "ndi", "shm", "rtmp", "hls"]


@dataclass(frozen=True)
class OutputBinding:
    """One render target → output sink wiring.

    Attributes:
        surface_id: The video_out surface ID this binding came from.
            Lets the operator look the binding back up by surface
            name.
        render_target: Phase 5b1 render target name (e.g. ``"main"``,
            ``"hud"``). Pass to
            ``DynamicPipeline.get_target_output_view`` to grab the
            wgpu texture view.
        sink_kind: Inferred sink type. The operator's compositor code
            dispatches on this to choose between v4l2sink, winit
            present, NDI sender, etc.
        sink_path: The opaque per-sink identifier (device path, NDI
            source name, shm path, etc.) — passed to the sink-side
            constructor as-is.
    """

    surface_id: str
    render_target: str
    sink_kind: SinkKind
    sink_path: str


def _infer_sink_kind(target: str) -> SinkKind:
    """Infer the sink kind from a Layout surface's geometry.target string.

    The rules are intentionally simple — string-prefix dispatch with
    a safe default. Adding a new sink kind means adding one branch
    here and one literal to the SinkKind union.
    """
    if target.startswith("/dev/video"):
        return "v4l2"
    if target.startswith("wgpu_") or target == "winit":
        return "winit"
    if target.startswith("ndi://"):
        return "ndi"
    if target.startswith("shm://"):
        return "shm"
    if target.startswith("rtmp://") or target.startswith("rtmps://"):
        return "rtmp"
    if target.startswith("hls://") or target.endswith(".m3u8"):
        return "hls"
    return "shm"


class OutputRouter:
    """Maps render targets to output sinks for a given Layout.

    Constructed once per layout swap. Holds an immutable list of
    :class:`OutputBinding` records — the operator's compositor code
    iterates over them when (re)building its sink chain.
    """

    def __init__(self, bindings: list[OutputBinding]) -> None:
        self._bindings: tuple[OutputBinding, ...] = tuple(bindings)

    @classmethod
    def from_layout(cls, layout: Layout) -> OutputRouter:
        """Build an OutputRouter by walking the layout's video_out surfaces.

        Each ``video_out`` surface becomes one OutputBinding. The
        binding's ``sink_kind`` is inferred from
        ``geometry.target``; the ``render_target`` defaults to
        ``"main"`` when unset on the surface so backwards-compat
        layouts route correctly.

        Surfaces without a ``geometry.target`` are skipped — those
        are malformed video_out surfaces (the schema permits
        ``target=None`` but the router has nothing to wire). The
        operator's layout authoring tools should reject these
        upstream.
        """
        bindings: list[OutputBinding] = []
        for surface in layout.video_outputs():
            target = surface.geometry.target
            if target is None:
                continue
            render_target = surface.geometry.render_target or "main"
            bindings.append(
                OutputBinding(
                    surface_id=surface.id,
                    render_target=render_target,
                    sink_kind=_infer_sink_kind(target),
                    sink_path=target,
                )
            )
        return cls(bindings)

    def bindings(self) -> tuple[OutputBinding, ...]:
        """Return all output bindings in stable layout order."""
        return self._bindings

    def for_surface(self, surface_id: str) -> OutputBinding | None:
        """Look up the binding for a specific video_out surface ID."""
        for binding in self._bindings:
            if binding.surface_id == surface_id:
                return binding
        return None

    def for_render_target(self, render_target: str) -> tuple[OutputBinding, ...]:
        """Return every binding routing the named render target.

        A render target may feed multiple sinks (e.g. ``"main"``
        feeding both /dev/video42 AND the winit window in the
        canonical garage-door layout). The result is in stable
        layout order.
        """
        return tuple(b for b in self._bindings if b.render_target == render_target)

    def render_targets(self) -> tuple[str, ...]:
        """Return the sorted set of render targets referenced by any binding."""
        return tuple(sorted({b.render_target for b in self._bindings}))

    def sinks_of_kind(self, sink_kind: SinkKind) -> tuple[OutputBinding, ...]:
        """Return every binding whose sink_kind matches."""
        return tuple(b for b in self._bindings if b.sink_kind == sink_kind)

    def __len__(self) -> int:
        return len(self._bindings)

    def __iter__(self):
        return iter(self._bindings)
