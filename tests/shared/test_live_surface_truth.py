from __future__ import annotations

from shared.live_surface_truth import (
    LiveSurfaceSnapshot,
    LiveSurfaceState,
    V4l2EgressMode,
    assess_live_surface,
    parse_prometheus_scalars,
    snapshot_from_prometheus,
)


def test_shmsink_frames_without_v4l2_are_containment_not_restored() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        shmsink_frames_total=25,
        shmsink_last_frame_age_seconds=0.5,
        v4l2_frames_total=0,
        v4l2_last_frame_age_seconds=9999,
    )

    assessment = assess_live_surface(snapshot)

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert not assessment.restored
    assert "shmsink_without_v4l2_egress" in assessment.reasons
    assert "v4l2_no_frames" in assessment.reasons


def test_containment_flags_prevent_restored_state() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
        final_egress_snapshot_frames_total=10,
        final_egress_snapshot_last_frame_age_seconds=0.2,
        containment_flags={"force_cpu": True},
    )

    assessment = assess_live_surface(snapshot)

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert assessment.reasons == ("containment_flag:force_cpu",)


def test_prometheus_parser_preserves_ward_surface_samples() -> None:
    metrics = parse_prometheus_scalars(
        """
studio_compositor_ward_blit_total{ward="programme-context"} 8
studio_compositor_ward_source_surface_pixels{ward="programme-context"} 9216
hapax_compositor_layout_active{layout="segment-programme-context"} 1
"""
    )

    assert metrics["studio_compositor_ward_blit_total:ward:programme-context"] == 8.0
    assert metrics["studio_compositor_ward_source_surface_pixels:ward:programme-context"] == 9216.0
    assert metrics["hapax_compositor_layout_active:layout:segment-programme-context"] == 1.0


def test_healthy_requires_active_service_cameras_bridge_and_fresh_v4l2() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
        final_egress_snapshot_frames_total=10,
        final_egress_snapshot_last_frame_age_seconds=0.2,
    )

    assessment = assess_live_surface(snapshot)

    assert assessment.state is LiveSurfaceState.HEALTHY
    assert assessment.restored
    assert assessment.reasons == ()


def test_require_hls_degrades_when_playlist_missing() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
        final_egress_snapshot_frames_total=10,
        final_egress_snapshot_last_frame_age_seconds=0.2,
        hls_active=False,
    )

    assessment = assess_live_surface(snapshot, require_hls=True)

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert "hls_playlist_missing" in assessment.reasons


def test_require_hls_degrades_when_playlist_stale() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
        final_egress_snapshot_frames_total=10,
        final_egress_snapshot_last_frame_age_seconds=0.2,
        hls_active=True,
        hls_playlist_age_seconds=45.0,
    )

    assessment = assess_live_surface(
        snapshot,
        require_hls=True,
        max_hls_age_seconds=10.0,
    )

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert "hls_playlist_stale" in assessment.reasons


def test_bridge_mode_requires_write_and_decoded_video42_proof() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_egress_mode=V4l2EgressMode.BRIDGE,
        shmsink_frames_total=100,
        shmsink_last_frame_age_seconds=0.1,
    )

    assessment = assess_live_surface(snapshot)

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert "bridge_v4l2_write_no_frames" in assessment.reasons
    assert "bridge_v4l2_write_no_bytes" in assessment.reasons
    assert "bridge_heartbeat_stale" in assessment.reasons
    assert "decoded_video42_no_frames" in assessment.reasons
    assert "v4l2_no_frames" not in assessment.reasons


def test_bridge_mode_can_be_healthy_with_bridge_write_and_decoded_frame_proof() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_egress_mode=V4l2EgressMode.BRIDGE,
        shmsink_frames_total=100,
        shmsink_last_frame_age_seconds=0.1,
        bridge_write_frames_total=10,
        bridge_write_bytes_total=1024,
        bridge_write_errors_total=0,
        bridge_heartbeat_age_seconds=0.5,
        decoded_video42_frames_total=8,
        decoded_video42_last_frame_age_seconds=0.4,
    )

    assessment = assess_live_surface(snapshot)

    assert assessment.state is LiveSurfaceState.HEALTHY


def test_bridge_mode_accepts_obs_decoder_motion_when_video42_has_exclusive_reader() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_egress_mode=V4l2EgressMode.BRIDGE,
        shmsink_frames_total=100,
        shmsink_last_frame_age_seconds=0.1,
        bridge_write_frames_total=10,
        bridge_write_bytes_total=1024,
        bridge_write_errors_total=0,
        bridge_heartbeat_age_seconds=0.5,
        obs_source_active=True,
        obs_playing=False,
        obs_screenshot_changed=True,
        obs_screenshot_flat=False,
        obs_screenshot_age_seconds=0.2,
    )

    assessment = assess_live_surface(snapshot, require_obs_decoder=True)

    assert assessment.state is LiveSurfaceState.HEALTHY
    assert "decoded_video42_no_frames" not in assessment.reasons


def test_obs_playing_without_decoder_motion_is_not_restored() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
        final_egress_snapshot_frames_total=10,
        final_egress_snapshot_last_frame_age_seconds=0.2,
        obs_source_active=True,
        obs_playing=True,
    )

    assessment = assess_live_surface(snapshot, require_obs_decoder=True)

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert "obs_playing_without_decoder_motion" in assessment.reasons


def test_flat_or_unchanged_obs_screenshot_triggers_decoder_degraded_state() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
        final_egress_snapshot_frames_total=10,
        final_egress_snapshot_last_frame_age_seconds=0.2,
        obs_source_active=True,
        obs_playing=True,
        obs_screenshot_age_seconds=0.2,
        obs_screenshot_changed=False,
        obs_screenshot_flat=True,
    )

    assessment = assess_live_surface(snapshot, require_obs_decoder=True)

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert "obs_screenshot_flat" in assessment.reasons
    assert "obs_playing_without_decoder_motion" in assessment.reasons
    assert "obs_decoder_stale_hash" in assessment.reasons


def test_director_silence_and_stale_camera_are_visible_degraded_facts() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=1,
        cameras_healthy=1,
        camera_last_frame_age_seconds={"desk": 22.0},
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
        final_egress_snapshot_frames_total=10,
        final_egress_snapshot_last_frame_age_seconds=0.2,
        director_last_intent_age_seconds=181.0,
    )

    assessment = assess_live_surface(snapshot, max_egress_age_seconds=10.0)

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert "camera_stale:desk" in assessment.reasons
    assert "director_silent" in assessment.reasons


def test_rtmp_and_public_output_are_separate_required_boundaries() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
        final_egress_snapshot_frames_total=10,
        final_egress_snapshot_last_frame_age_seconds=0.2,
        rtmp_connected=True,
        rtmp_bytes_total=0,
        public_output_live=False,
    )

    assessment = assess_live_surface(
        snapshot,
        require_rtmp=True,
        require_public_output=True,
    )

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert "rtmp_no_bytes" in assessment.reasons
    assert "public_output_unverified" in assessment.reasons


def test_parse_prometheus_and_build_snapshot() -> None:
    metrics = parse_prometheus_scalars(
        """
        # HELP ignored ignored
        studio_compositor_cameras_total 6
        studio_compositor_cameras_healthy 5
        studio_compositor_v4l2sink_frames_total 3
        studio_compositor_v4l2sink_last_frame_seconds_ago 12
        studio_compositor_render_stage_frames_total{stage="final_egress_snapshot"} 2
        studio_compositor_render_stage_last_frame_seconds_ago{stage="final_egress_snapshot"} 1
        studio_compositor_hls_playlist_active 1
        studio_compositor_hls_playlist_last_write_seconds_ago 3
        studio_camera_last_frame_age_seconds{camera_role="desk"} 0.2
        studio_compositor_runtime_feature_active{feature="v4l2_output"} 1
        studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
        hapax_v4l2_bridge_write_frames_total 9
        hapax_v4l2_bridge_write_bytes_total 9000
        hapax_v4l2_bridge_write_errors_total 0
        hapax_v4l2_bridge_heartbeat_seconds_ago 1
        hapax_video42_decoded_frames_total 8
        hapax_video42_decoded_last_frame_seconds_ago 1
        studio_rtmp_connected{endpoint="youtube"} 1
        studio_rtmp_bytes_total{endpoint="youtube"} 2048
        hapax_obs_decoder_source_active 1
        hapax_obs_decoder_playing 1
        hapax_obs_decoder_frame_hash_changed 1
        hapax_obs_decoder_frame_flat 0
        hapax_obs_decoder_screenshot_seconds_ago 0.4
        hapax_public_output_live 1
        """
    )

    snapshot = snapshot_from_prometheus(
        metrics,
        service_active=True,
        bridge_active=True,
    )

    assert snapshot.cameras_total == 6
    assert snapshot.cameras_healthy == 5
    assert snapshot.camera_last_frame_age_seconds == {"desk": 0.2}
    assert snapshot.v4l2_egress_mode is V4l2EgressMode.BRIDGE
    assert snapshot.v4l2_frames_total == 3
    assert snapshot.v4l2_last_frame_age_seconds == 12
    assert snapshot.final_egress_snapshot_frames_total == 2
    assert snapshot.final_egress_snapshot_last_frame_age_seconds == 1
    assert snapshot.hls_active is True
    assert snapshot.hls_playlist_age_seconds == 3
    assert snapshot.bridge_write_frames_total == 9
    assert snapshot.decoded_video42_frames_total == 8
    assert snapshot.rtmp_connected is True
    assert snapshot.rtmp_bytes_total == 2048
    assert snapshot.obs_source_active is True
    assert snapshot.obs_screenshot_flat is False
    assert snapshot.public_output_live is True


def test_parse_prometheus_accepts_current_camera_role_label_shape() -> None:
    metrics = parse_prometheus_scalars(
        """
        studio_compositor_cameras_total 2
        studio_compositor_cameras_healthy 1
        studio_camera_last_frame_age_seconds{model="unknown",role="brio-operator"} 7.5
        studio_camera_last_frame_age_seconds{role="c920-overhead",model="unknown"} 0.2
        """
    )

    snapshot = snapshot_from_prometheus(
        metrics,
        service_active=True,
        bridge_active=True,
    )

    assert snapshot.camera_last_frame_age_seconds == {
        "brio-operator": 7.5,
        "c920-overhead": 0.2,
    }
