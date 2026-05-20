from __future__ import annotations

import pytest

from shared.egress_cadence_feasibility import assess_egress_cadence, nv12_frame_bytes


def test_720p_nv12_frame_size() -> None:
    assert nv12_frame_bytes(1280, 720) == 1_382_400


def test_60fps_doubles_throughput_without_standing_buffer_growth() -> None:
    report = assess_egress_cadence(width=1280, height=720, current_fps=30, target_fps=60)

    assert report.recommendation == "candidate_canary"
    assert report.workload_multiplier == 2.0
    assert report.current_nv12_mib_per_s == pytest.approx(39.55078125)
    assert report.target_nv12_mib_per_s == pytest.approx(79.1015625)
    assert report.bridge_copy_added_mib_per_s == pytest.approx(79.1015625)
    assert report.standing_buffer_increment_mib == 0.0


def test_3d_mode_and_slow_source_publish_block_enablement() -> None:
    report = assess_egress_cadence(
        source_publish_fps=6,
        live_egress_fps=0,
        three_d_mode=True,
    )

    assert report.recommendation == "do_not_enable"
    assert "3d_compositor_bypasses_gstreamer_v4l2_hls_egress" in report.blockers
    assert "source_publish_fps_below_target:6.00<54.00" in report.blockers
    assert "live_egress_fps_below_target:0.00<54.00" in report.blockers


def test_low_vram_warning_is_not_a_hard_block_above_floor() -> None:
    report = assess_egress_cadence(free_vram_mib=1024)

    assert report.recommendation == "candidate_canary"
    assert "free_vram_below_comfort_floor:1024<2048" in report.warnings


def test_tiny_vram_headroom_blocks_canary() -> None:
    report = assess_egress_cadence(free_vram_mib=128)

    assert report.recommendation == "do_not_enable"
    assert "free_vram_below_canary_floor:128<512" in report.blockers


def test_nv12_geometry_requires_even_dimensions() -> None:
    with pytest.raises(ValueError, match="even width and height"):
        assess_egress_cadence(width=1279, height=720)
