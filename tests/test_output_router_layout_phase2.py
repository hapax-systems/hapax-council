"""Tests for LRR Phase 2 item 10 — layout-declared video_out surfaces
in config/compositor-layouts/default.json + new rtmp/hls sink kinds.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.studio_compositor.output_router import (
    OutputRouter,
    _infer_sink_kind,
)
from shared.compositor_model import Layout

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LAYOUT_PATH = REPO_ROOT / "config" / "compositor-layouts" / "default.json"


class TestInferSinkKindExtensions:
    def test_rtmp_sink(self) -> None:
        assert _infer_sink_kind("rtmp://127.0.0.1:1935/studio") == "rtmp"

    def test_rtmps_sink(self) -> None:
        assert _infer_sink_kind("rtmps://example.com/live") == "rtmp"

    def test_hls_scheme(self) -> None:
        assert _infer_sink_kind("hls:///tmp/stream.m3u8") == "hls"

    def test_hls_m3u8_suffix(self) -> None:
        assert _infer_sink_kind("~/.cache/hapax-compositor/hls/stream.m3u8") == "hls"

    def test_v4l2_still_works(self) -> None:
        assert _infer_sink_kind("/dev/video42") == "v4l2"


class TestDefaultLayoutVideoOutSurfaces:
    def test_default_layout_parses(self) -> None:
        payload = json.loads(DEFAULT_LAYOUT_PATH.read_text(encoding="utf-8"))
        layout = Layout.model_validate(payload)
        assert layout.name == "default"

    def test_default_layout_declares_expected_video_outs(self) -> None:
        payload = json.loads(DEFAULT_LAYOUT_PATH.read_text(encoding="utf-8"))
        layout = Layout.model_validate(payload)
        video_outs = layout.video_outputs()
        assert len(video_outs) >= 3

        targets = {s.geometry.target for s in video_outs}
        assert "/dev/video42" in targets
        assert "rtmp://127.0.0.1:1935/studio" in targets
        assert any(t is not None and t.startswith("hls://") for t in targets)

    def test_output_router_from_default_layout(self) -> None:
        payload = json.loads(DEFAULT_LAYOUT_PATH.read_text(encoding="utf-8"))
        layout = Layout.model_validate(payload)
        router = OutputRouter.from_layout(layout)
        bindings = router.bindings()
        assert len(bindings) >= 3

        sink_kinds = {b.sink_kind for b in bindings}
        assert "v4l2" in sink_kinds
        assert "rtmp" in sink_kinds
        assert "hls" in sink_kinds

    def test_all_video_outs_on_main_render_target(self) -> None:
        payload = json.loads(DEFAULT_LAYOUT_PATH.read_text(encoding="utf-8"))
        layout = Layout.model_validate(payload)
        router = OutputRouter.from_layout(layout)
        for binding in router.bindings():
            assert binding.render_target == "main"
