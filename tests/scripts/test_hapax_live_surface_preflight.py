from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-live-surface-preflight"


def _run(
    metrics: str,
    *args: str,
    tmp_path: Path,
    after_metrics: str | None = None,
) -> subprocess.CompletedProcess[str]:
    metrics_file = tmp_path / "metrics.prom"
    metrics_file.write_text(metrics, encoding="utf-8")
    after_args: list[str] = []
    if after_metrics is not None:
        after_metrics_file = tmp_path / "metrics-after.prom"
        after_metrics_file.write_text(after_metrics, encoding="utf-8")
        after_args = ["--metrics-file-after", str(after_metrics_file)]
    return subprocess.run(
        [
            str(SCRIPT),
            "--no-systemd",
            "--metrics-file",
            str(metrics_file),
            "--layout-state-json",
            str(tmp_path / "missing-layout-state.json"),
            *after_args,
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )


def test_preflight_fails_closed_when_only_shmsink_is_flowing(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_shmsink_frames_total 40
studio_compositor_shmsink_last_frame_seconds_ago 0.2
studio_compositor_v4l2sink_frames_total 0
studio_compositor_v4l2sink_last_frame_seconds_ago 9999
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--env",
        "HAPAX_V4L2_BRIDGE_ENABLED=1",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert payload["v4l2_egress_mode"] == "bridge_v4l2"
    assert "bridge_v4l2_write_no_frames" in payload["reasons"]
    assert "decoded_video42_no_frames" in payload["reasons"]


def test_preflight_fails_closed_on_containment_flags(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 4
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--env",
        "HAPAX_COMPOSITOR_FORCE_CPU=1",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert "containment_flag:force_cpu" in payload["reasons"]


def test_preflight_full_surface_blocks_active_suppressors(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 4
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 0
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 0
studio_compositor_runtime_feature_active{feature="ward_modulator"} 0
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
hapax_compositor_layout_active{layout="default"} 1
hapax_ward_modulator_tick_total 0
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--env",
        "HAPAX_COMPOSITOR_DISABLE_SHADER_FX=1",
        "--env",
        "HAPAX_FOLLOW_MODE_ACTIVE=0",
        "--env",
        "HAPAX_WARD_MODULATOR_ACTIVE=0",
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=2",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert payload["restored"] is False
    assert payload["full_surface_required"] is True
    assert "full_surface:LSC-FX-001:shader_fx_disabled" in payload["reasons"]
    assert "full_surface:LSC-FX-001:fx_slots_below_min:2<8" in payload["reasons"]
    assert "full_surface:LSC-WARD-001:visible_ward_count_below_min:1<3" in payload["reasons"]
    assert "full_surface:LSC-LAYOUT-003:legacy_static_layout_active:default" in payload["reasons"]
    assert "full_surface:LSC-SCRIM-001:gem_substrate_not_active" in payload["reasons"]
    assert "full_surface:LSC-SCRIM-001:gem_substrate_not_painting" in payload["reasons"]
    assert "full_surface:LSC-SCRIM-001:gem_substrate_disabled" not in payload["reasons"]


def test_preflight_full_surface_can_pass_with_complete_surface_evidence(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 4
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="tier-panel"} 10
studio_compositor_ward_blit_total{ward="artifact-detail-panel"} 10
hapax_compositor_layout_active{layout="segment-programme-context"} 1
hapax_ward_modulator_tick_total 5
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 8
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=8",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert payload["full_surface_required"] is True
    assert payload["full_surface_failures"] == []


def test_preflight_accepts_default_template_only_with_responsible_layout_mode(
    tmp_path: Path,
) -> None:
    layout_state = tmp_path / "current-layout-state.json"
    layout_state.write_text(
        json.dumps({"layout_name": "default", "layout_mode": "follow/c920-room"}),
        encoding="utf-8",
    )

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 4
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="gem"} 10
studio_compositor_ward_blit_total{ward="egress-footer"} 10
hapax_compositor_layout_active{layout="default"} 1
hapax_ward_modulator_tick_total 5
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 8
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--layout-state-json",
        str(layout_state),
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=8",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert payload["full_surface_failures"] == []


def test_preflight_gem_substrate_requires_live_runtime_proof(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 4
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="tier-panel"} 10
studio_compositor_ward_blit_total{ward="artifact-detail-panel"} 10
hapax_compositor_layout_active{layout="segment-programme-context"} 1
hapax_ward_modulator_tick_total 5
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=8",
        "--env",
        "HAPAX_GEM_SUBSTRATE_ENABLED=1",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert "full_surface:LSC-SCRIM-001:gem_substrate_not_active" in payload["reasons"]
    assert "full_surface:LSC-SCRIM-001:gem_substrate_not_painting" in payload["reasons"]
    assert "full_surface:LSC-SCRIM-001:gem_substrate_disabled" not in payload["reasons"]


def test_preflight_ignores_stale_gem_substrate_env_when_runtime_proves_it(
    tmp_path: Path,
) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 4
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="tier-panel"} 10
studio_compositor_ward_blit_total{ward="artifact-detail-panel"} 10
hapax_compositor_layout_active{layout="segment-programme-context"} 1
hapax_ward_modulator_tick_total 5
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 8
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=8",
        "--env",
        "HAPAX_GEM_SUBSTRATE_ENABLED=0",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert payload["full_surface_failures"] == []


def test_preflight_full_surface_performance_sample_can_pass(tmp_path: Path) -> None:
    before = """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="compositor_src"} 100
studio_compositor_render_stage_frames_total{stage="output_tee_sink"} 100
studio_compositor_render_stage_frames_total{stage="v4l2_appsink"} 100
studio_compositor_render_stage_frames_total{stage="hls_parser_src"} 100
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 10
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="tier-panel"} 10
studio_compositor_ward_blit_total{ward="artifact-detail-panel"} 10
hapax_compositor_layout_active{layout="segment-programme-context"} 1
hapax_ward_modulator_tick_total 5
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 8
"""
    after = before.replace(
        'studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 10',
        'studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 13',
    )
    for stage in ("compositor_src", "output_tee_sink", "v4l2_appsink", "hls_parser_src"):
        after = after.replace(
            f'studio_compositor_render_stage_frames_total{{stage="{stage}"}} 100',
            f'studio_compositor_render_stage_frames_total{{stage="{stage}"}} 130',
        )

    result = _run(
        before,
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--full-surface-sample-seconds",
        "1",
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=8",
        tmp_path=tmp_path,
        after_metrics=after,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert payload["full_surface_performance"]["sampled"] is True
    assert payload["full_surface_performance"]["stage_fps"]["v4l2_appsink"] == 30.0


def test_preflight_full_surface_accepts_one_hz_final_egress_proof(
    tmp_path: Path,
) -> None:
    before = """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="compositor_src"} 100
studio_compositor_render_stage_frames_total{stage="output_tee_sink"} 100
studio_compositor_render_stage_frames_total{stage="v4l2_appsink"} 100
studio_compositor_render_stage_frames_total{stage="hls_parser_src"} 100
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 10
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="tier-panel"} 10
studio_compositor_ward_blit_total{ward="artifact-detail-panel"} 10
hapax_compositor_layout_active{layout="segment-programme-context"} 1
hapax_ward_modulator_tick_total 5
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 8
"""
    after = before.replace(
        'studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 10',
        'studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11',
    )
    for stage in ("compositor_src", "output_tee_sink", "v4l2_appsink", "hls_parser_src"):
        after = after.replace(
            f'studio_compositor_render_stage_frames_total{{stage="{stage}"}} 100',
            f'studio_compositor_render_stage_frames_total{{stage="{stage}"}} 130',
        )

    result = _run(
        before,
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--full-surface-sample-seconds",
        "1",
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=8",
        tmp_path=tmp_path,
        after_metrics=after,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert payload["full_surface_performance"]["stage_fps"]["final_egress_snapshot"] == 1.0


def test_preflight_full_surface_blocks_missing_final_egress_proof_progress(
    tmp_path: Path,
) -> None:
    before = """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="compositor_src"} 100
studio_compositor_render_stage_frames_total{stage="output_tee_sink"} 100
studio_compositor_render_stage_frames_total{stage="v4l2_appsink"} 100
studio_compositor_render_stage_frames_total{stage="hls_parser_src"} 100
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 10
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="tier-panel"} 10
studio_compositor_ward_blit_total{ward="artifact-detail-panel"} 10
hapax_compositor_layout_active{layout="segment-programme-context"} 1
hapax_ward_modulator_tick_total 5
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 8
"""
    after = before
    for stage in ("compositor_src", "output_tee_sink", "v4l2_appsink", "hls_parser_src"):
        after = after.replace(
            f'studio_compositor_render_stage_frames_total{{stage="{stage}"}} 100',
            f'studio_compositor_render_stage_frames_total{{stage="{stage}"}} 130',
        )

    result = _run(
        before,
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--full-surface-sample-seconds",
        "1",
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=8",
        tmp_path=tmp_path,
        after_metrics=after,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert (
        "full_surface:LSC-VIEWER-001:stage_fps_below_floor:final_egress_snapshot:0.00<0.80"
        in payload["reasons"]
    )


def test_preflight_full_surface_performance_sample_blocks_slow_hls(tmp_path: Path) -> None:
    before = """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="compositor_src"} 100
studio_compositor_render_stage_frames_total{stage="output_tee_sink"} 100
studio_compositor_render_stage_frames_total{stage="v4l2_appsink"} 100
studio_compositor_render_stage_frames_total{stage="hls_parser_src"} 100
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 10
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="tier-panel"} 10
studio_compositor_ward_blit_total{ward="artifact-detail-panel"} 10
hapax_compositor_layout_active{layout="segment-programme-context"} 1
hapax_ward_modulator_tick_total 5
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 8
"""
    after = before
    replacements = {
        "compositor_src": 130,
        "output_tee_sink": 130,
        "v4l2_appsink": 130,
        "hls_parser_src": 120,
    }
    for stage, count in replacements.items():
        after = after.replace(
            f'studio_compositor_render_stage_frames_total{{stage="{stage}"}} 100',
            f'studio_compositor_render_stage_frames_total{{stage="{stage}"}} {count}',
        )
    after = after.replace(
        'studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 10',
        'studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 13',
    )

    result = _run(
        before,
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--full-surface-sample-seconds",
        "1",
        "--env",
        "HAPAX_COMPOSITOR_FX_SLOTS=8",
        tmp_path=tmp_path,
        after_metrics=after,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert (
        "full_surface:LSC-EGRESS-002:stage_fps_below_floor:hls_parser_src:20.00<29.00"
        in payload["reasons"]
    )


def test_preflight_allow_containment_does_not_normalize_full_surface_failure(
    tmp_path: Path,
) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 4
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
studio_compositor_runtime_feature_active{feature="shader_fx"} 0
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="tier-panel"} 10
studio_compositor_ward_blit_total{ward="artifact-detail-panel"} 10
hapax_compositor_layout_active{layout="segment-programme-context"} 1
hapax_ward_modulator_tick_total 5
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 8
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--allow-containment",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert payload["restored"] is False
    assert "full_surface:LSC-FX-001:feature_inactive:shader_fx" in payload["reasons"]


def test_preflight_passes_when_final_v4l2_truth_is_fresh(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 10
studio_compositor_v4l2sink_last_frame_seconds_ago 0.1
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 4
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.2
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["state"] == "healthy"


def test_preflight_accepts_fresh_direct_v4l2_when_bridge_not_expected(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_shmsink_frames_total 0
studio_compositor_shmsink_last_frame_seconds_ago 9999
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--env",
        "HAPAX_V4L2_BRIDGE_ENABLED=0",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert "v4l2_bridge_inactive" not in payload["reasons"]


def test_preflight_requires_bridge_when_bridge_mode_expected(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--env",
        "HAPAX_V4L2_BRIDGE_ENABLED=1",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "v4l2_bridge_inactive" in payload["reasons"]


def test_preflight_accepts_bridge_mode_with_bridge_and_decoded_proof(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_runtime_feature_active{feature="v4l2_output"} 1
studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
studio_compositor_shmsink_frames_total 140
studio_compositor_shmsink_last_frame_seconds_ago 0.03
hapax_v4l2_bridge_write_frames_total 120
hapax_v4l2_bridge_write_bytes_total 120000
hapax_v4l2_bridge_write_errors_total 0
hapax_v4l2_bridge_heartbeat_seconds_ago 0.5
hapax_video42_decoded_frames_total 20
hapax_video42_decoded_last_frame_seconds_ago 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert payload["v4l2_egress_mode"] == "bridge_v4l2"


def test_preflight_full_surface_samples_bridge_cadence_without_direct_appsink(
    tmp_path: Path,
) -> None:
    before = """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_runtime_feature_active{feature="v4l2_output"} 1
studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_render_stage_frames_total{stage="compositor_src"} 100
studio_compositor_render_stage_frames_total{stage="output_tee_sink"} 100
studio_compositor_render_stage_frames_total{stage="hls_parser_src"} 100
studio_compositor_shmsink_frames_total 100
studio_compositor_shmsink_last_frame_seconds_ago 0.03
hapax_v4l2_bridge_write_frames_total 100
hapax_v4l2_bridge_write_bytes_total 100000
hapax_v4l2_bridge_write_errors_total 0
hapax_v4l2_bridge_heartbeat_seconds_ago 0.2
hapax_obs_decoder_source_active 1
hapax_obs_decoder_frame_hash_changed 1
hapax_obs_decoder_frame_flat 0
hapax_obs_decoder_screenshot_seconds_ago 0.2
studio_compositor_ward_blit_total{ward="programme-context"} 10
studio_compositor_ward_blit_total{ward="gem"} 10
studio_compositor_ward_blit_total{ward="egress-footer"} 10
hapax_ward_modulator_tick_total 20
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 10
hapax_compositor_layout_active{layout="forcefield"} 1
"""
    after = """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_runtime_feature_active{feature="v4l2_output"} 1
studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
studio_compositor_runtime_feature_active{feature="shader_fx"} 1
studio_compositor_runtime_feature_active{feature="inline_fx"} 1
studio_compositor_runtime_feature_active{feature="hero_effect"} 1
studio_compositor_runtime_feature_active{feature="follow_mode"} 1
studio_compositor_runtime_feature_active{feature="ward_modulator"} 1
studio_compositor_runtime_feature_active{feature="flash_overlay"} 0
studio_compositor_render_stage_frames_total{stage="compositor_src"} 131
studio_compositor_render_stage_frames_total{stage="output_tee_sink"} 130
studio_compositor_render_stage_frames_total{stage="hls_parser_src"} 130
studio_compositor_shmsink_frames_total 131
studio_compositor_shmsink_last_frame_seconds_ago 0.03
hapax_v4l2_bridge_write_frames_total 131
hapax_v4l2_bridge_write_bytes_total 131000
hapax_v4l2_bridge_write_errors_total 0
hapax_v4l2_bridge_heartbeat_seconds_ago 0.2
hapax_obs_decoder_source_active 1
hapax_obs_decoder_frame_hash_changed 1
hapax_obs_decoder_frame_flat 0
hapax_obs_decoder_screenshot_seconds_ago 0.2
studio_compositor_ward_blit_total{ward="programme-context"} 11
studio_compositor_ward_blit_total{ward="gem"} 11
studio_compositor_ward_blit_total{ward="egress-footer"} 11
hapax_ward_modulator_tick_total 21
studio_compositor_gem_substrate_active 1
studio_compositor_gem_substrate_paint_total 11
hapax_compositor_layout_active{layout="forcefield"} 1
"""

    result = _run(
        before,
        "--service-active",
        "true",
        "--bridge-active",
        "true",
        "--require-full-surface",
        "--require-obs-decoder",
        "--full-surface-sample-seconds",
        "1",
        tmp_path=tmp_path,
        after_metrics=after,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    stage_fps = payload["full_surface_performance"]["stage_fps"]
    assert stage_fps["v4l2_bridge_writer"] >= 29.5
    assert stage_fps["shmsink_bridge"] >= 29.5
    assert "v4l2_appsink" not in stage_fps
    assert "final_egress_snapshot" not in stage_fps


def test_preflight_requires_obs_decoder_motion_when_requested(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
hapax_obs_decoder_source_active 1
hapax_obs_decoder_playing 1
hapax_obs_decoder_frame_hash_changed 0
hapax_obs_decoder_frame_flat 1
hapax_obs_decoder_screenshot_seconds_ago 0.5
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--require-obs-decoder",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["obs_playing"] is True
    assert "obs_screenshot_flat" in payload["reasons"]
    assert "obs_playing_without_decoder_motion" in payload["reasons"]


def test_preflight_degrades_when_final_egress_snapshot_is_stale(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 90
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "final_egress_snapshot_stale" in payload["reasons"]


def test_preflight_degrades_when_final_egress_snapshot_missing(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "final_egress_snapshot_no_frames" in payload["reasons"]


def test_preflight_degrades_on_black_final_frame_image(tmp_path: Path) -> None:
    image_path = tmp_path / "black.jpg"
    Image.new("RGB", (64, 36), (0, 0, 0)).save(image_path)

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--final-frame-image",
        str(image_path),
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "unclassified_black_exceeds_threshold" in payload["reasons"]
    assert payload["final_frame_classification"]["black_fraction"] == 1.0
    assert payload["final_frame_classification"]["max_unclassified_black_fraction"] == 0.08


def test_preflight_accepts_forcefield_declared_negative_space(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "forcefield-sparse.png"
    image = Image.new("RGB", (128, 72), (0, 0, 0))
    pixels = image.load()
    for y in range(8, 30):
        for x in range(8, 44):
            pixels[x, y] = (220, 120, 40)
    for y in range(42, 64):
        for x in range(82, 120):
            pixels[x, y] = (60, 170, 220)
    image.save(image_path)
    layout_state = tmp_path / "current-layout-state.json"
    layout_state.write_text(
        json.dumps({"layout_mode": "forcefield", "layout_name": "segment-compare"}),
        encoding="utf-8",
    )

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--final-frame-image",
        str(image_path),
        "--layout-state-json",
        str(layout_state),
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    classification = payload["final_frame_classification"]
    assert payload["state"] == "healthy"
    assert classification["black_fraction"] > 0.08
    assert classification["black_fraction"] <= 0.90
    assert classification["layout_mode"] == "forcefield"
    assert classification["max_unclassified_black_fraction"] == 0.9
    assert "unclassified_black_exceeds_threshold" not in payload["reasons"]


def test_preflight_degrades_on_uniform_grey_final_frame_with_live_upstream(
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "final-grey.jpg"
    upstream_path = tmp_path / "upstream-content.jpg"
    Image.new("RGB", (64, 36), (128, 128, 128)).save(final_path)
    upstream = Image.new("RGB", (64, 36), (0, 0, 0))
    pixels = upstream.load()
    for y in range(4, 30):
        for x in range(8, 56):
            pixels[x, y] = (220, 120, 40)
    upstream.save(upstream_path)

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--final-frame-image",
        str(final_path),
        "--upstream-frame-image",
        str(upstream_path),
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "uniform_gray_final_egress_collapse" in payload["reasons"]
    assert payload["final_frame_classification"]["upstream_luma_standard_deviation"] >= 8.0


def test_preflight_degrades_on_geometry_decorrelated_final_frame(
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "final-noise.png"
    upstream_path = tmp_path / "upstream-content.png"
    upstream = Image.new("RGB", (128, 72), (0, 0, 0))
    upstream_pixels = upstream.load()
    for y in range(8, 64):
        for x in range(12, 116):
            if (x // 12 + y // 10) % 2 == 0:
                upstream_pixels[x, y] = (220, 120, 40)
    upstream.save(upstream_path)
    final = Image.new("RGB", (128, 72), (0, 0, 0))
    final_pixels = final.load()
    for y in range(72):
        for x in range(128):
            n = (x * 41 + y * 67 + ((x * y) % 53)) % 256
            final_pixels[x, y] = (n, (n * 7) % 256, (n * 13) % 256)
    final.save(final_path)

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--final-frame-image",
        str(final_path),
        "--upstream-frame-image",
        str(upstream_path),
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "geometry_decorrelation_final_egress_collapse" in payload["reasons"]


def test_preflight_require_final_pixel_proof_degrades_on_bad_series(
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "final-noise.png"
    upstream_path = tmp_path / "upstream-content.png"
    upstream = Image.new("RGB", (128, 72), (0, 0, 0))
    upstream_pixels = upstream.load()
    for y in range(8, 64):
        for x in range(12, 116):
            if (x // 12 + y // 10) % 2 == 0:
                upstream_pixels[x, y] = (220, 120, 40)
            elif (x // 15 + y // 9) % 2 == 0:
                upstream_pixels[x, y] = (40, 180, 230)
    upstream.save(upstream_path)
    final = Image.new("RGB", (128, 72), (0, 0, 0))
    final_pixels = final.load()
    for y in range(72):
        for x in range(128):
            n = (x * 41 + y * 67 + ((x * y) % 53)) % 256
            final_pixels[x, y] = (n, (n * 7) % 256, (n * 13) % 256)
    final.save(final_path)

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--final-frame-image",
        str(final_path),
        "--upstream-frame-image",
        str(upstream_path),
        "--require-final-pixel-proof",
        "--final-frame-window-seconds",
        "0",
        "--final-frame-interval-ms",
        "0",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert payload["final_pixel_proof"]["frame_count"] == 6
    assert any(
        reason.startswith("final_pixel_proof:edge_correlation_median_below_threshold")
        for reason in payload["reasons"]
    )


def test_preflight_consumes_ward_visibility_json_as_gate(tmp_path: Path) -> None:
    ward_visibility = tmp_path / "ward-visibility.json"
    ward_visibility.write_text(
        json.dumps(
            {
                "ok": False,
                "reasons": [
                    "active_ward_missing:tier-panel",
                    "visible_ward_count_below_min:1<3",
                ],
                "wards": [],
            }
        ),
        encoding="utf-8",
    )

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--ward-visibility-json",
        str(ward_visibility),
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "ward_visibility:active_ward_missing:tier-panel" in payload["reasons"]
    assert "ward_visibility:visible_ward_count_below_min:1<3" in payload["reasons"]
    assert payload["ward_visibility"]["ok"] is False


def test_preflight_consumes_effect_surface_json_as_gate(tmp_path: Path) -> None:
    effect_surface = tmp_path / "effect-surface.json"
    effect_surface.write_text(
        json.dumps(
            {
                "ok": False,
                "reasons": [
                    "visual_governance_missing_preset:missing",
                    "preset_node_type_unknown:bad:node:mystery",
                ],
                "summary": {"reason_count": 2},
            }
        ),
        encoding="utf-8",
    )

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--effect-surface-json",
        str(effect_surface),
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "effect_surface:visual_governance_missing_preset:missing" in payload["reasons"]
    assert "effect_surface:preset_node_type_unknown:bad:node:mystery" in payload["reasons"]
    assert payload["effect_surface"]["ok"] is False


def test_preflight_can_require_fresh_hls_playlist(tmp_path: Path) -> None:
    playlist = tmp_path / "stream.m3u8"
    playlist.write_text("#EXTM3U\n", encoding="utf-8")

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--require-hls",
        "--hls-playlist",
        str(playlist),
        "--max-hls-age-seconds",
        "30",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert payload["hls_playlist_age_seconds"] is not None
    assert payload["hls_max_age_seconds"] == 30.0


def test_preflight_derives_hls_freshness_from_target_duration(tmp_path: Path) -> None:
    playlist = tmp_path / "stream.m3u8"
    playlist.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:10\n", encoding="utf-8")
    old = time.time() - 11
    os.utime(playlist, (old, old))

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--require-hls",
        "--hls-playlist",
        str(playlist),
        tmp_path=tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == "healthy"
    assert payload["hls_max_age_seconds"] == 22.0
    assert "hls_playlist_stale" not in payload["reasons"]


def test_preflight_degrades_on_implausible_hls_target_duration(tmp_path: Path) -> None:
    playlist = tmp_path / "stream.m3u8"
    playlist.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:3600000\n", encoding="utf-8")

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--require-hls",
        "--hls-playlist",
        str(playlist),
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert payload["hls_target_duration_seconds"] == 3600000.0
    assert payload["hls_max_age_seconds"] == 10.0
    assert "hls_playlist_malformed_target_duration" in payload["reasons"]


def test_preflight_degrades_when_required_hls_playlist_is_stale(tmp_path: Path) -> None:
    playlist = tmp_path / "stream.m3u8"
    playlist.write_text("#EXTM3U\n", encoding="utf-8")
    old = time.time() - 120
    os.utime(playlist, (old, old))

    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--require-hls",
        "--hls-playlist",
        str(playlist),
        "--max-hls-age-seconds",
        "10",
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "hls_playlist_stale" in payload["reasons"]


def test_preflight_degrades_when_required_hls_playlist_is_missing(tmp_path: Path) -> None:
    result = _run(
        """
studio_compositor_cameras_total 6
studio_compositor_cameras_healthy 6
studio_compositor_v4l2sink_frames_total 140
studio_compositor_v4l2sink_last_frame_seconds_ago 0.03
studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 11
studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 0.4
""",
        "--service-active",
        "true",
        "--bridge-active",
        "false",
        "--require-hls",
        "--hls-playlist",
        str(tmp_path / "missing.m3u8"),
        tmp_path=tmp_path,
    )

    assert result.returncode == 10
    payload = json.loads(result.stdout)
    assert payload["state"] == "degraded_containment"
    assert "hls_playlist_missing" in payload["reasons"]


def test_preflight_fails_closed_with_json_when_metrics_are_unavailable() -> None:
    result = subprocess.run(
        [
            str(SCRIPT),
            "--no-systemd",
            "--metrics-file",
            "/path/that/does/not/exist.prom",
            "--service-active",
            "false",
            "--bridge-active",
            "false",
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 11
    payload = json.loads(result.stdout)
    assert payload["state"] == "failed"
    assert payload["restored"] is False
    assert payload["reasons"] == ["metrics_unavailable:FileNotFoundError"]
    assert result.stderr == ""
