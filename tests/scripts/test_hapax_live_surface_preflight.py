from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-live-surface-preflight"


def _run(metrics: str, *args: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    metrics_file = tmp_path / "metrics.prom"
    metrics_file.write_text(metrics, encoding="utf-8")
    return subprocess.run(
        [
            str(SCRIPT),
            "--no-systemd",
            "--metrics-file",
            str(metrics_file),
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
