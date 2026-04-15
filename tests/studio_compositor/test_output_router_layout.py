"""Tests for OutputRouter + layout integration (LRR Phase 2 item 10c).

Focused regression pin on the router-layout relationship. The existing
`test_compositor_wiring.py::TestStudioCompositorOutputRouterWiring`
covers the compositor-level wiring; this file covers the router's
own contract against layouts at a lower level:

- `OutputRouter.from_layout()` with the production layout
- `OutputRouter.from_layout()` with the hardcoded fallback layout
- Sink-kind inference for every sink pattern used in production
- `for_surface` / `for_render_target` / `sinks_of_kind` accessor
  invariants
- Layout without video_out surfaces → empty router
- Layouts with surfaces but missing geometry.target → skipped

Spec: docs/superpowers/specs/2026-04-15-lrr-phase-2-archive-research-instrument-design.md §3.10
"""

from __future__ import annotations

from pathlib import Path

from agents.studio_compositor.compositor import _FALLBACK_LAYOUT, load_layout_or_fallback
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

DEFAULT_LAYOUT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "default.json"
)


class TestSinkKindInference:
    """`_infer_sink_kind` string-prefix dispatch — every production target."""

    def test_v4l2_device_path(self):
        assert _infer_sink_kind("/dev/video42") == "v4l2"
        assert _infer_sink_kind("/dev/video0") == "v4l2"

    def test_rtmp_urls(self):
        assert _infer_sink_kind("rtmp://127.0.0.1:1935/studio") == "rtmp"
        assert _infer_sink_kind("rtmps://secure.example.com/live") == "rtmp"

    def test_hls_paths(self):
        assert _infer_sink_kind("hls://local") == "hls"
        assert _infer_sink_kind("/some/path/playlist.m3u8") == "hls"

    def test_ndi_urls(self):
        assert _infer_sink_kind("ndi://workstation/stream") == "ndi"

    def test_shm_paths(self):
        assert _infer_sink_kind("shm:///dev/shm/compositor/out") == "shm"

    def test_winit_window(self):
        assert _infer_sink_kind("winit") == "winit"
        assert _infer_sink_kind("wgpu_winit_window") == "winit"
        assert _infer_sink_kind("wgpu_something") == "winit"

    def test_unknown_target_defaults_to_shm(self):
        assert _infer_sink_kind("mystery-sink") == "shm"
        assert _infer_sink_kind("") == "shm"


class TestFromLayoutProduction:
    """`OutputRouter.from_layout` against the REAL production layout."""

    def test_production_default_json_produces_v4l2_rtmp_hls_bindings(self):
        assert DEFAULT_LAYOUT_PATH.exists(), f"production layout missing at {DEFAULT_LAYOUT_PATH}"
        layout = load_layout_or_fallback(DEFAULT_LAYOUT_PATH)
        router = OutputRouter.from_layout(layout)
        sink_kinds = {b.sink_kind for b in router}
        assert {"v4l2", "rtmp", "hls"}.issubset(sink_kinds), (
            f"production layout missing required sink kinds: got {sink_kinds}"
        )

    def test_production_bindings_match_video_out_surface_count(self):
        layout = load_layout_or_fallback(DEFAULT_LAYOUT_PATH)
        router = OutputRouter.from_layout(layout)
        video_out_surfaces = layout.video_outputs()
        assert len(router) == len(video_out_surfaces), (
            f"router length {len(router)} does not match video_out count {len(video_out_surfaces)}"
        )

    def test_production_v4l2_target_is_dev_video42(self):
        layout = load_layout_or_fallback(DEFAULT_LAYOUT_PATH)
        router = OutputRouter.from_layout(layout)
        v4l2_bindings = router.sinks_of_kind("v4l2")
        assert len(v4l2_bindings) == 1
        assert v4l2_bindings[0].sink_path == "/dev/video42"

    def test_production_rtmp_target_is_mediamtx(self):
        layout = load_layout_or_fallback(DEFAULT_LAYOUT_PATH)
        router = OutputRouter.from_layout(layout)
        rtmp_bindings = router.sinks_of_kind("rtmp")
        assert len(rtmp_bindings) == 1
        assert rtmp_bindings[0].sink_path == "rtmp://127.0.0.1:1935/studio"


class TestFromLayoutFallback:
    """`OutputRouter.from_layout` against the hardcoded `_FALLBACK_LAYOUT`."""

    def test_fallback_layout_produces_same_sink_kinds_as_production(self):
        router = OutputRouter.from_layout(_FALLBACK_LAYOUT)
        sink_kinds = {b.sink_kind for b in router}
        assert {"v4l2", "rtmp", "hls"}.issubset(sink_kinds), (
            "fallback layout missing the same sinks as production — "
            "drift between _FALLBACK_LAYOUT and config/compositor-layouts/default.json"
        )

    def test_fallback_layout_yields_three_bindings(self):
        router = OutputRouter.from_layout(_FALLBACK_LAYOUT)
        # Phase 2 item 10: v4l2 loopback + RTMP MediaMTX + HLS playlist
        assert len(router) == 3

    def test_fallback_layout_render_targets_default_to_main(self):
        router = OutputRouter.from_layout(_FALLBACK_LAYOUT)
        targets = {b.render_target for b in router}
        assert targets == {"main"}, f"unexpected render targets in fallback: {targets}"

    def test_missing_layout_file_triggers_fallback_router(self, tmp_path: Path):
        """When the layout file is missing, load_layout_or_fallback returns
        _FALLBACK_LAYOUT and OutputRouter.from_layout produces a valid
        3-binding router. This is the end-to-end fallback path."""
        missing = tmp_path / "does-not-exist.json"
        layout = load_layout_or_fallback(missing)
        router = OutputRouter.from_layout(layout)
        assert len(router) >= 3
        sink_kinds = {b.sink_kind for b in router}
        assert {"v4l2", "rtmp", "hls"}.issubset(sink_kinds)


class TestAccessors:
    """`for_surface` / `for_render_target` / `sinks_of_kind` contract."""

    def _build_router(self) -> OutputRouter:
        return OutputRouter(
            [
                OutputBinding(
                    surface_id="v4l2_a",
                    render_target="main",
                    sink_kind="v4l2",
                    sink_path="/dev/video42",
                ),
                OutputBinding(
                    surface_id="rtmp_b",
                    render_target="main",
                    sink_kind="rtmp",
                    sink_path="rtmp://127.0.0.1:1935/s",
                ),
                OutputBinding(
                    surface_id="hls_c",
                    render_target="main",
                    sink_kind="hls",
                    sink_path="hls://local",
                ),
                OutputBinding(
                    surface_id="winit_d",
                    render_target="preview",
                    sink_kind="winit",
                    sink_path="wgpu_winit_window",
                ),
            ]
        )

    def test_for_surface_returns_matching_binding(self):
        router = self._build_router()
        binding = router.for_surface("v4l2_a")
        assert binding is not None
        assert binding.sink_kind == "v4l2"

    def test_for_surface_returns_none_for_unknown(self):
        router = self._build_router()
        assert router.for_surface("nope") is None

    def test_for_render_target_returns_all_matching(self):
        router = self._build_router()
        main_bindings = router.for_render_target("main")
        assert len(main_bindings) == 3  # v4l2 + rtmp + hls
        preview_bindings = router.for_render_target("preview")
        assert len(preview_bindings) == 1  # winit only

    def test_render_targets_is_sorted_set(self):
        router = self._build_router()
        assert router.render_targets() == ("main", "preview")

    def test_sinks_of_kind_filters_correctly(self):
        router = self._build_router()
        assert len(router.sinks_of_kind("v4l2")) == 1
        assert len(router.sinks_of_kind("rtmp")) == 1
        assert len(router.sinks_of_kind("hls")) == 1
        assert len(router.sinks_of_kind("winit")) == 1
        assert len(router.sinks_of_kind("ndi")) == 0

    def test_iteration_and_len(self):
        router = self._build_router()
        assert len(router) == 4
        assert len(list(router)) == 4


class TestEmptyAndEdgeCases:
    """Layouts without video_out surfaces + malformed cases."""

    def test_layout_without_video_out_produces_empty_router(self):
        layout = Layout(
            name="no-outputs",
            description="Layout with zero video_out surfaces",
            sources=[
                SourceSchema(id="s1", kind="cairo", backend="cairo", params={}),
            ],
            surfaces=[
                SurfaceSchema(
                    id="pip",
                    geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=100, h=100),
                    z_order=1,
                ),
            ],
            assignments=[
                Assignment(source="s1", surface="pip"),
            ],
        )
        router = OutputRouter.from_layout(layout)
        assert len(router) == 0
        assert router.bindings() == ()

    def test_video_out_with_none_target_is_skipped(self):
        layout = Layout(
            name="malformed",
            description="video_out surface with target=None",
            sources=[],
            surfaces=[
                SurfaceSchema(
                    id="malformed_out",
                    geometry=SurfaceGeometry(
                        kind="video_out",
                        target=None,
                        render_target="main",
                    ),
                    z_order=1,
                ),
                SurfaceSchema(
                    id="good_out",
                    geometry=SurfaceGeometry(
                        kind="video_out",
                        target="/dev/video42",
                        render_target="main",
                    ),
                    z_order=2,
                ),
            ],
            assignments=[],
        )
        router = OutputRouter.from_layout(layout)
        assert len(router) == 1
        assert router.bindings()[0].surface_id == "good_out"

    def test_render_target_defaults_to_main_when_unset(self):
        layout = Layout(
            name="default-target",
            description="video_out with no render_target",
            sources=[],
            surfaces=[
                SurfaceSchema(
                    id="v",
                    geometry=SurfaceGeometry(
                        kind="video_out",
                        target="/dev/video42",
                        render_target=None,
                    ),
                    z_order=1,
                ),
            ],
            assignments=[],
        )
        router = OutputRouter.from_layout(layout)
        assert len(router) == 1
        assert router.bindings()[0].render_target == "main"
