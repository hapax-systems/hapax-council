from __future__ import annotations

from pathlib import Path
from unittest import mock

from agents.studio_compositor.compositor import StudioCompositor
from agents.studio_compositor.config import _default_config


def _make_compositor() -> StudioCompositor:
    with mock.patch(
        "agents.studio_compositor.compositor.load_camera_profiles",
        return_value=[],
    ):
        return StudioCompositor(_default_config())


def test_shmsink_frame_does_not_increment_v4l2_egress_truth() -> None:
    compositor = _make_compositor()

    compositor._on_shmsink_frame_pushed()

    assert compositor._shmsink_frame_count == 1
    assert compositor.shmsink_frame_seen_within(2.0)
    assert compositor._v4l2_frame_count == 0
    assert not compositor.v4l2_frame_seen_within(2.0)


def test_bridge_pipeline_uses_shmsink_callback_not_v4l2_callback() -> None:
    source = (Path(__file__).parents[2] / "agents/studio_compositor/pipeline.py").read_text(
        encoding="utf-8"
    )

    bridge_block = source.split("if is_bridge_enabled():", 1)[1].split("else:", 1)[0]
    assert "on_frame=compositor._on_shmsink_frame_pushed" in bridge_block
    assert "on_frame=compositor._on_v4l2_frame_pushed" not in bridge_block
