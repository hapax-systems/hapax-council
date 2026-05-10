from __future__ import annotations

from shared.live_surface_truth import (
    LiveSurfaceSnapshot,
    LiveSurfaceState,
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
        containment_flags={"force_cpu": True},
    )

    assessment = assess_live_surface(snapshot)

    assert assessment.state is LiveSurfaceState.DEGRADED_CONTAINMENT
    assert assessment.reasons == ("containment_flag:force_cpu",)


def test_healthy_requires_active_service_cameras_bridge_and_fresh_v4l2() -> None:
    snapshot = LiveSurfaceSnapshot(
        service_active=True,
        bridge_active=True,
        cameras_total=6,
        cameras_healthy=6,
        v4l2_frames_total=100,
        v4l2_last_frame_age_seconds=0.2,
    )

    assessment = assess_live_surface(snapshot)

    assert assessment.state is LiveSurfaceState.HEALTHY
    assert assessment.restored
    assert assessment.reasons == ()


def test_parse_prometheus_and_build_snapshot() -> None:
    metrics = parse_prometheus_scalars(
        """
        # HELP ignored ignored
        studio_compositor_cameras_total 6
        studio_compositor_cameras_healthy 5
        studio_compositor_v4l2sink_frames_total 3
        studio_compositor_v4l2sink_last_frame_seconds_ago 12
        studio_camera_last_frame_age_seconds{camera_role="desk"} 0.2
        """
    )

    snapshot = snapshot_from_prometheus(
        metrics,
        service_active=True,
        bridge_active=True,
    )

    assert snapshot.cameras_total == 6
    assert snapshot.cameras_healthy == 5
    assert snapshot.v4l2_frames_total == 3
    assert snapshot.v4l2_last_frame_age_seconds == 12
