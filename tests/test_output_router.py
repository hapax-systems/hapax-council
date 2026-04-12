"""Tests for OutputRouter (Phase 5b3 of the compositor unification epic).

OutputRouter walks a Layout's video_out surfaces and produces sink
bindings the operator's compositor code uses to wire each render
target to its physical sink.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.studio_compositor.output_router import (
    OutputBinding,
    OutputRouter,
    _infer_sink_kind,
)
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)

GARAGE_DOOR_PATH = Path(__file__).parent.parent / "config" / "layouts" / "garage-door.json"


# ---------------------------------------------------------------------------
# _infer_sink_kind
# ---------------------------------------------------------------------------


def test_infer_sink_kind_v4l2_for_dev_video_path():
    assert _infer_sink_kind("/dev/video42") == "v4l2"
    assert _infer_sink_kind("/dev/video0") == "v4l2"


def test_infer_sink_kind_winit_for_wgpu_prefix():
    assert _infer_sink_kind("wgpu_winit_window") == "winit"
    assert _infer_sink_kind("wgpu_window") == "winit"
    assert _infer_sink_kind("winit") == "winit"


def test_infer_sink_kind_ndi_for_ndi_url():
    assert _infer_sink_kind("ndi://hapax.local/main") == "ndi"


def test_infer_sink_kind_shm_for_shm_url():
    assert _infer_sink_kind("shm:///dev/shm/hapax-compositor/main.rgba") == "shm"


def test_infer_sink_kind_unknown_falls_back_to_shm():
    """A target that doesn't match any prefix is treated as shm — the
    safe default. The operator can extend the inference rules later
    or override the binding manually."""
    assert _infer_sink_kind("nonsense") == "shm"
    assert _infer_sink_kind("") == "shm"


# ---------------------------------------------------------------------------
# OutputRouter construction + basic queries
# ---------------------------------------------------------------------------


def _src(id_: str = "s") -> SourceSchema:
    return SourceSchema(id=id_, kind="shader", backend="wgsl_render")  # type: ignore[arg-type]


def _video_out_surface(
    id_: str,
    target: str,
    render_target: str | None = None,
    z_order: int = 0,
) -> SurfaceSchema:
    return SurfaceSchema(
        id=id_,
        geometry=SurfaceGeometry(
            kind="video_out",  # type: ignore[arg-type]
            target=target,
            render_target=render_target,
        ),
        z_order=z_order,
    )


def _minimal_layout(*surfaces: SurfaceSchema, name: str = "test") -> Layout:
    """A layout with one source assigned to the first surface so
    Pydantic's reference validation passes."""
    return Layout(
        name=name,
        sources=[_src("s")],
        surfaces=list(surfaces),
        assignments=[Assignment(source="s", surface=surfaces[0].id)] if surfaces else [],
    )


def test_router_from_layout_walks_video_out_surfaces():
    layout = _minimal_layout(
        _video_out_surface("v4l", "/dev/video42", render_target="main"),
        _video_out_surface("win", "wgpu_winit_window", render_target="main"),
    )
    router = OutputRouter.from_layout(layout)
    bindings = router.bindings()
    assert len(bindings) == 2
    assert bindings[0].surface_id == "v4l"
    assert bindings[0].sink_kind == "v4l2"
    assert bindings[0].sink_path == "/dev/video42"
    assert bindings[0].render_target == "main"
    assert bindings[1].sink_kind == "winit"


def test_router_from_layout_default_render_target_is_main():
    """When a video_out surface omits render_target, the router
    defaults to ``main``."""
    layout = _minimal_layout(
        _video_out_surface("v4l", "/dev/video42", render_target=None),
    )
    router = OutputRouter.from_layout(layout)
    assert router.bindings()[0].render_target == "main"


def test_router_skips_video_out_surfaces_without_target():
    """A video_out surface with no geometry.target is malformed —
    the router skips it instead of raising."""
    layout = Layout(
        name="malformed",
        sources=[_src()],
        surfaces=[
            SurfaceSchema(
                id="orphan",
                geometry=SurfaceGeometry(kind="video_out", target=None),  # type: ignore[arg-type]
            ),
        ],
        assignments=[Assignment(source="s", surface="orphan")],
    )
    router = OutputRouter.from_layout(layout)
    assert len(router) == 0


def test_router_only_walks_video_out_kind_surfaces():
    """Non-video_out surfaces (rect, tile, masked_region, wgpu_binding)
    are not output bindings — the router ignores them."""
    layout = Layout(
        name="mixed",
        sources=[_src()],
        surfaces=[
            SurfaceSchema(
                id="rect-surf",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=64, h=64),  # type: ignore[arg-type]
            ),
            _video_out_surface("v4l", "/dev/video42"),
        ],
        assignments=[
            Assignment(source="s", surface="rect-surf"),
            Assignment(source="s", surface="v4l"),
        ],
    )
    router = OutputRouter.from_layout(layout)
    assert len(router) == 1
    assert router.bindings()[0].surface_id == "v4l"


# ---------------------------------------------------------------------------
# Lookup methods
# ---------------------------------------------------------------------------


def test_for_surface_returns_binding_or_none():
    layout = _minimal_layout(
        _video_out_surface("v4l", "/dev/video42"),
    )
    router = OutputRouter.from_layout(layout)
    assert router.for_surface("v4l") is not None
    assert router.for_surface("nonexistent") is None


def test_for_render_target_returns_all_matching_bindings():
    """A render target may feed multiple sinks (the canonical case
    in garage-door: ``main`` feeds both /dev/video42 and the winit
    window)."""
    layout = _minimal_layout(
        _video_out_surface("v4l", "/dev/video42", render_target="main"),
        _video_out_surface("win", "wgpu_winit_window", render_target="main"),
        _video_out_surface("hud", "ndi://hapax.local/hud", render_target="hud"),
    )
    router = OutputRouter.from_layout(layout)
    main_bindings = router.for_render_target("main")
    assert len(main_bindings) == 2
    assert {b.surface_id for b in main_bindings} == {"v4l", "win"}
    hud_bindings = router.for_render_target("hud")
    assert len(hud_bindings) == 1
    assert hud_bindings[0].surface_id == "hud"


def test_render_targets_returns_sorted_set():
    layout = _minimal_layout(
        _video_out_surface("a", "/dev/video42", render_target="main"),
        _video_out_surface("b", "ndi://x/y", render_target="hud"),
        _video_out_surface("c", "wgpu_window", render_target="main"),
    )
    router = OutputRouter.from_layout(layout)
    assert router.render_targets() == ("hud", "main")


def test_sinks_of_kind_filters_correctly():
    layout = _minimal_layout(
        _video_out_surface("v4l", "/dev/video42"),
        _video_out_surface("win", "wgpu_winit_window"),
        _video_out_surface("ndi", "ndi://x/y"),
    )
    router = OutputRouter.from_layout(layout)
    assert len(router.sinks_of_kind("v4l2")) == 1
    assert len(router.sinks_of_kind("winit")) == 1
    assert len(router.sinks_of_kind("ndi")) == 1
    assert len(router.sinks_of_kind("shm")) == 0


# ---------------------------------------------------------------------------
# Iteration / dunder methods
# ---------------------------------------------------------------------------


def test_router_supports_len_and_iteration():
    layout = _minimal_layout(
        _video_out_surface("a", "/dev/video42"),
        _video_out_surface("b", "wgpu_window"),
    )
    router = OutputRouter.from_layout(layout)
    assert len(router) == 2
    surface_ids = [b.surface_id for b in router]
    assert surface_ids == ["a", "b"]


# ---------------------------------------------------------------------------
# Garage-door canonical layout end-to-end
# ---------------------------------------------------------------------------


def test_garage_door_layout_produces_two_bindings():
    """The canonical garage-door layout has exactly two video_out
    surfaces (one v4l2, one winit), both feeding the main render
    target."""
    if not GARAGE_DOOR_PATH.exists():
        pytest.skip("garage-door.json not present in this checkout")
    layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
    router = OutputRouter.from_layout(layout)
    assert len(router) == 2

    v4l = router.for_surface("main-output")
    assert v4l is not None
    assert v4l.sink_kind == "v4l2"
    assert v4l.sink_path == "/dev/video42"
    assert v4l.render_target == "main"

    winit = router.for_surface("wgpu-surface")
    assert winit is not None
    assert winit.sink_kind == "winit"
    assert winit.render_target == "main"


def test_garage_door_main_target_feeds_two_sinks():
    """The Phase 5b1 ``main`` render target should feed both the
    v4l2 stream output and the winit window in the canonical
    layout — proving the multi-sink, single-target case works
    end-to-end."""
    if not GARAGE_DOOR_PATH.exists():
        pytest.skip("garage-door.json not present in this checkout")
    layout = Layout.model_validate_json(GARAGE_DOOR_PATH.read_text())
    router = OutputRouter.from_layout(layout)
    main = router.for_render_target("main")
    assert len(main) == 2
    sink_kinds = {b.sink_kind for b in main}
    assert sink_kinds == {"v4l2", "winit"}


def test_output_binding_is_frozen():
    """OutputBinding is frozen so callers can hash it / use it as a
    dict key without copying."""
    binding = OutputBinding(
        surface_id="v4l",
        render_target="main",
        sink_kind="v4l2",
        sink_path="/dev/video42",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        binding.surface_id = "other"  # type: ignore[misc]
