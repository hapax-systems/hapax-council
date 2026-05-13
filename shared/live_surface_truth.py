"""Viewer-facing livestream truth predicates.

These predicates deliberately distinguish internal compositor flow from
egress/consumer truth. A moving HLS playlist, fresh camera pad probes, or a
compositor-side SHM write can keep an incident contained, but none of them is
enough to call the livestream restored.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class LiveSurfaceState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED_CONTAINMENT = "degraded_containment"
    FAILED = "failed"


class V4l2EgressMode(StrEnum):
    DIRECT = "direct_v4l2"
    BRIDGE = "bridge_v4l2"
    DISABLED = "disabled"


@dataclass(frozen=True)
class LiveSurfaceSnapshot:
    service_active: bool
    bridge_active: bool
    cameras_total: int
    cameras_healthy: int
    camera_last_frame_age_seconds: Mapping[str, float] = field(default_factory=dict)
    v4l2_egress_mode: V4l2EgressMode = V4l2EgressMode.DIRECT
    bridge_expected: bool = False
    v4l2_frames_total: float | None = None
    v4l2_last_frame_age_seconds: float | None = None
    shmsink_frames_total: float | None = None
    shmsink_last_frame_age_seconds: float | None = None
    bridge_write_frames_total: float | None = None
    bridge_write_bytes_total: float | None = None
    bridge_write_errors_total: float | None = None
    bridge_reconnects_total: float | None = None
    bridge_heartbeat_age_seconds: float | None = None
    decoded_video42_frames_total: float | None = None
    decoded_video42_last_frame_age_seconds: float | None = None
    final_egress_snapshot_frames_total: float | None = None
    final_egress_snapshot_last_frame_age_seconds: float | None = None
    containment_flags: Mapping[str, bool] = field(default_factory=dict)
    hls_active: bool = False
    hls_playlist_age_seconds: float | None = None
    rtmp_connected: bool | None = None
    rtmp_bytes_total: float | None = None
    rtmp_bitrate_bps: float | None = None
    obs_source_active: bool | None = None
    obs_playing: bool | None = None
    obs_screenshot_changed: bool | None = None
    obs_screenshot_flat: bool | None = None
    obs_screenshot_age_seconds: float | None = None
    public_output_live: bool | None = None
    watchdog_last_fed_age_seconds: float | None = None
    director_last_intent_age_seconds: float | None = None


@dataclass(frozen=True)
class LiveSurfaceAssessment:
    state: LiveSurfaceState
    reasons: tuple[str, ...]

    @property
    def restored(self) -> bool:
        return self.state is LiveSurfaceState.HEALTHY


def _metric_positive(value: float | None) -> bool:
    return value is not None and value > 0


def _metric_fresh(value: float | None, *, max_age_seconds: float) -> bool:
    return value is not None and 0 <= value <= max_age_seconds


def assess_live_surface(
    snapshot: LiveSurfaceSnapshot,
    *,
    max_egress_age_seconds: float = 10.0,
    require_v4l2: bool = True,
    require_hls: bool = False,
    require_rtmp: bool = False,
    require_obs_decoder: bool = False,
    require_public_output: bool = False,
    max_hls_age_seconds: float | None = None,
    max_obs_screenshot_age_seconds: float | None = None,
    max_director_silence_seconds: float = 180.0,
) -> LiveSurfaceAssessment:
    """Classify a livestream surface snapshot.

    ``DEGRADED_CONTAINMENT`` means the surface may be useful for keeping a
    private incident feed moving, but it is not restored. ``FAILED`` means a
    hard precondition such as service liveness or camera availability is false.
    """

    failures: list[str] = []
    degraded: list[str] = []

    if not snapshot.service_active:
        failures.append("studio_compositor_inactive")
    if snapshot.cameras_total <= 0:
        failures.append("no_registered_cameras")
    elif snapshot.cameras_healthy < snapshot.cameras_total:
        degraded.append("not_all_cameras_healthy")

    for role, age_seconds in sorted(snapshot.camera_last_frame_age_seconds.items()):
        if not _metric_fresh(age_seconds, max_age_seconds=max_egress_age_seconds):
            degraded.append(f"camera_stale:{role}")

    for name, active in sorted(snapshot.containment_flags.items()):
        if active:
            degraded.append(f"containment_flag:{name}")

    if (
        snapshot.director_last_intent_age_seconds is not None
        and snapshot.director_last_intent_age_seconds > max_director_silence_seconds
    ):
        degraded.append("director_silent")

    shmsink_positive = _metric_positive(snapshot.shmsink_frames_total)
    v4l2_positive = _metric_positive(snapshot.v4l2_frames_total)
    v4l2_fresh = _metric_fresh(
        snapshot.v4l2_last_frame_age_seconds,
        max_age_seconds=max_egress_age_seconds,
    )

    if require_v4l2:
        if snapshot.v4l2_egress_mode is V4l2EgressMode.DISABLED:
            degraded.append("v4l2_output_disabled")
        elif snapshot.v4l2_egress_mode is V4l2EgressMode.BRIDGE:
            _assess_bridge_v4l2(snapshot, degraded, max_egress_age_seconds)
        else:
            if snapshot.bridge_expected and not snapshot.bridge_active:
                degraded.append("v4l2_bridge_inactive")
            if not v4l2_positive:
                degraded.append("v4l2_no_frames")
            elif not v4l2_fresh:
                degraded.append("v4l2_stale_frames")
            elif not _metric_positive(snapshot.final_egress_snapshot_frames_total):
                degraded.append("final_egress_snapshot_no_frames")
            elif not _metric_fresh(
                snapshot.final_egress_snapshot_last_frame_age_seconds,
                max_age_seconds=max_egress_age_seconds,
            ):
                degraded.append("final_egress_snapshot_stale")

    if (
        snapshot.v4l2_egress_mode is not V4l2EgressMode.BRIDGE
        and shmsink_positive
        and not v4l2_positive
    ):
        degraded.append("shmsink_without_v4l2_egress")

    if require_hls:
        if not snapshot.hls_active:
            degraded.append("hls_playlist_missing")
        elif snapshot.hls_playlist_age_seconds is None:
            degraded.append("hls_playlist_age_unknown")
        elif not _metric_fresh(
            snapshot.hls_playlist_age_seconds,
            max_age_seconds=(
                max_hls_age_seconds if max_hls_age_seconds is not None else max_egress_age_seconds
            ),
        ):
            degraded.append("hls_playlist_stale")

    if require_rtmp:
        if snapshot.rtmp_connected is not True:
            degraded.append("rtmp_not_connected")
        elif not _metric_positive(snapshot.rtmp_bytes_total):
            degraded.append("rtmp_no_bytes")

    if require_obs_decoder:
        _assess_obs_decoder(
            snapshot,
            degraded,
            max_age_seconds=(
                max_obs_screenshot_age_seconds
                if max_obs_screenshot_age_seconds is not None
                else max_egress_age_seconds
            ),
        )

    if require_public_output and snapshot.public_output_live is not True:
        degraded.append("public_output_unverified")

    if failures:
        return LiveSurfaceAssessment(
            state=LiveSurfaceState.FAILED,
            reasons=tuple(failures + degraded),
        )
    if degraded:
        return LiveSurfaceAssessment(
            state=LiveSurfaceState.DEGRADED_CONTAINMENT,
            reasons=tuple(degraded),
        )
    return LiveSurfaceAssessment(state=LiveSurfaceState.HEALTHY, reasons=())


def _assess_bridge_v4l2(
    snapshot: LiveSurfaceSnapshot,
    degraded: list[str],
    max_egress_age_seconds: float,
) -> None:
    if not snapshot.bridge_active:
        degraded.append("v4l2_bridge_inactive")
    if not _metric_positive(snapshot.shmsink_frames_total):
        degraded.append("bridge_shmsink_no_frames")
    elif not _metric_fresh(
        snapshot.shmsink_last_frame_age_seconds,
        max_age_seconds=max_egress_age_seconds,
    ):
        degraded.append("bridge_shmsink_stale")

    if not _metric_positive(snapshot.bridge_write_frames_total):
        degraded.append("bridge_v4l2_write_no_frames")
    if not _metric_positive(snapshot.bridge_write_bytes_total):
        degraded.append("bridge_v4l2_write_no_bytes")
    if snapshot.bridge_write_errors_total is not None and snapshot.bridge_write_errors_total > 0:
        degraded.append("bridge_v4l2_write_errors")
    if not _metric_fresh(
        snapshot.bridge_heartbeat_age_seconds,
        max_age_seconds=max_egress_age_seconds,
    ):
        degraded.append("bridge_heartbeat_stale")

    if _obs_decoder_is_fresh(snapshot, max_egress_age_seconds=max_egress_age_seconds):
        return

    if not _metric_positive(snapshot.decoded_video42_frames_total):
        degraded.append("decoded_video42_no_frames")
    elif not _metric_fresh(
        snapshot.decoded_video42_last_frame_age_seconds,
        max_age_seconds=max_egress_age_seconds,
    ):
        degraded.append("decoded_video42_stale")


def _obs_decoder_is_fresh(
    snapshot: LiveSurfaceSnapshot,
    *,
    max_egress_age_seconds: float,
) -> bool:
    return (
        snapshot.obs_source_active is True
        and snapshot.obs_screenshot_changed is True
        and snapshot.obs_screenshot_flat is False
        and _metric_fresh(
            snapshot.obs_screenshot_age_seconds,
            max_age_seconds=max_egress_age_seconds,
        )
    )


def _assess_obs_decoder(
    snapshot: LiveSurfaceSnapshot,
    degraded: list[str],
    *,
    max_age_seconds: float,
) -> None:
    if snapshot.obs_source_active is not True:
        degraded.append("obs_source_inactive")
    if snapshot.obs_screenshot_age_seconds is None:
        if snapshot.obs_playing is True:
            degraded.append("obs_playing_without_decoder_motion")
        else:
            degraded.append("obs_screenshot_missing")
        return
    if not _metric_fresh(snapshot.obs_screenshot_age_seconds, max_age_seconds=max_age_seconds):
        degraded.append("obs_screenshot_stale")
    if snapshot.obs_screenshot_flat is True:
        degraded.append("obs_screenshot_flat")
    if snapshot.obs_screenshot_changed is not True:
        if snapshot.obs_playing is True:
            degraded.append("obs_playing_without_decoder_motion")
        degraded.append("obs_decoder_stale_hash")


def parse_prometheus_scalars(text: str) -> dict[str, float]:
    """Parse unlabeled Prometheus scalar samples from text exposition."""

    values: dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "{" in line:
            if "{" not in line:
                continue
            parsed = _parse_labeled_scalar(line)
            if parsed is None:
                continue
            name, value = parsed
            values[name] = value
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        name, raw_value = parts
        try:
            values[name] = float(raw_value)
        except ValueError:
            continue
    return values


_RENDER_STAGE_SAMPLE = re.compile(
    r"^(?P<name>studio_compositor_render_stage_(?:frames_total|last_frame_seconds_ago))"
    r'\{stage="(?P<stage>[^"]+)"\}\s+(?P<value>[-+0-9.eE]+)$'
)


_FEATURE_SAMPLE = re.compile(
    r'^(?P<name>studio_compositor_runtime_feature_active)\{feature="(?P<feature>[^"]+)"\}'
    r"\s+(?P<value>[-+0-9.eE]+)$"
)
_RTMP_SAMPLE = re.compile(
    r'^(?P<name>studio_rtmp_(?:connected|bytes_total|bitrate_bps))\{endpoint="(?P<endpoint>[^"]+)"\}'
    r"\s+(?P<value>[-+0-9.eE]+)$"
)
_CAMERA_SAMPLE = re.compile(
    r'^(?P<name>studio_camera_last_frame_age_seconds)\{camera_role="(?P<camera_role>[^"]+)"\}'
    r"\s+(?P<value>[-+0-9.eE]+)$"
)
_WARD_SAMPLE = re.compile(
    r"^(?P<name>studio_compositor_ward_(?:blit_total|source_surface_pixels))"
    r'\{ward="(?P<ward>[^"]+)"\}\s+(?P<value>[-+0-9.eE]+)$'
)
_LAYOUT_ACTIVE_SAMPLE = re.compile(
    r'^(?P<name>hapax_compositor_layout_active)\{layout="(?P<layout>[^"]+)"\}'
    r"\s+(?P<value>[-+0-9.eE]+)$"
)


def _parse_labeled_scalar(line: str) -> tuple[str, float] | None:
    for pattern, label_name in (
        (_RENDER_STAGE_SAMPLE, "stage"),
        (_FEATURE_SAMPLE, "feature"),
        (_RTMP_SAMPLE, "endpoint"),
        (_CAMERA_SAMPLE, "camera_role"),
        (_WARD_SAMPLE, "ward"),
        (_LAYOUT_ACTIVE_SAMPLE, "layout"),
    ):
        match = pattern.match(line)
        if match is None:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            return None
        return f"{match.group('name')}:{label_name}:{match.group(label_name)}", value
    return None


def _egress_mode_from_metrics(
    metrics: Mapping[str, float],
    *,
    bridge_expected: bool,
) -> V4l2EgressMode:
    if bool(metrics.get("studio_compositor_runtime_feature_active:feature:v4l2_output", 1)):
        if bool(metrics.get("studio_compositor_runtime_feature_active:feature:shmsink_bridge", 0)):
            return V4l2EgressMode.BRIDGE
        if bool(metrics.get("studio_compositor_runtime_feature_active:feature:direct_v4l2", 0)):
            return V4l2EgressMode.DIRECT
        return V4l2EgressMode.BRIDGE if bridge_expected else V4l2EgressMode.DIRECT
    return V4l2EgressMode.DISABLED


def _rtmp_connected(metrics: Mapping[str, float]) -> bool | None:
    values = [
        value for key, value in metrics.items() if key.startswith("studio_rtmp_connected:endpoint:")
    ]
    if not values:
        return None
    return any(value > 0 for value in values)


def _rtmp_total(metrics: Mapping[str, float], metric_name: str) -> float | None:
    values = [value for key, value in metrics.items() if key.startswith(f"{metric_name}:endpoint:")]
    if not values:
        return None
    return sum(values)


def _metric_bool(metrics: Mapping[str, float], name: str) -> bool | None:
    if name not in metrics:
        return None
    return metrics[name] > 0


def _metric_value(metrics: Mapping[str, float], name: str) -> float | None:
    return metrics.get(name)


def _camera_ages(metrics: Mapping[str, float]) -> dict[str, float]:
    prefix = "studio_camera_last_frame_age_seconds:camera_role:"
    return {
        key.removeprefix(prefix): value for key, value in metrics.items() if key.startswith(prefix)
    }


def snapshot_from_prometheus(
    metrics: Mapping[str, float],
    *,
    service_active: bool,
    bridge_active: bool,
    bridge_expected: bool = False,
    containment_flags: Mapping[str, bool] | None = None,
    hls_active: bool = False,
    hls_playlist_age_seconds: float | None = None,
) -> LiveSurfaceSnapshot:
    bridge_expected_value = bridge_expected or bool(
        metrics.get("studio_compositor_v4l2_bridge_expected", 0)
    )
    return LiveSurfaceSnapshot(
        service_active=service_active,
        bridge_active=bridge_active,
        cameras_total=int(metrics.get("studio_compositor_cameras_total", 0)),
        cameras_healthy=int(metrics.get("studio_compositor_cameras_healthy", 0)),
        camera_last_frame_age_seconds=_camera_ages(metrics),
        v4l2_egress_mode=_egress_mode_from_metrics(
            metrics,
            bridge_expected=bridge_expected_value,
        ),
        bridge_expected=bridge_expected_value,
        v4l2_frames_total=metrics.get("studio_compositor_v4l2sink_frames_total"),
        v4l2_last_frame_age_seconds=metrics.get(
            "studio_compositor_v4l2sink_last_frame_seconds_ago"
        ),
        shmsink_frames_total=metrics.get("studio_compositor_shmsink_frames_total"),
        shmsink_last_frame_age_seconds=metrics.get(
            "studio_compositor_shmsink_last_frame_seconds_ago"
        ),
        bridge_write_frames_total=_metric_value(
            metrics,
            "hapax_v4l2_bridge_write_frames_total",
        ),
        bridge_write_bytes_total=_metric_value(
            metrics,
            "hapax_v4l2_bridge_write_bytes_total",
        ),
        bridge_write_errors_total=_metric_value(
            metrics,
            "hapax_v4l2_bridge_write_errors_total",
        ),
        bridge_reconnects_total=_metric_value(
            metrics,
            "hapax_v4l2_bridge_reconnects_total",
        ),
        bridge_heartbeat_age_seconds=_metric_value(
            metrics,
            "hapax_v4l2_bridge_heartbeat_seconds_ago",
        ),
        decoded_video42_frames_total=_metric_value(
            metrics,
            "hapax_video42_decoded_frames_total",
        ),
        decoded_video42_last_frame_age_seconds=_metric_value(
            metrics,
            "hapax_video42_decoded_last_frame_seconds_ago",
        ),
        final_egress_snapshot_frames_total=metrics.get(
            "studio_compositor_render_stage_frames_total:stage:final_egress_snapshot"
        ),
        final_egress_snapshot_last_frame_age_seconds=metrics.get(
            "studio_compositor_render_stage_last_frame_seconds_ago:stage:final_egress_snapshot"
        ),
        containment_flags=containment_flags or {},
        hls_active=hls_active or bool(metrics.get("studio_compositor_hls_playlist_active", 0)),
        hls_playlist_age_seconds=(
            hls_playlist_age_seconds
            if hls_playlist_age_seconds is not None
            else metrics.get("studio_compositor_hls_playlist_last_write_seconds_ago")
        ),
        rtmp_connected=_rtmp_connected(metrics),
        rtmp_bytes_total=_rtmp_total(metrics, "studio_rtmp_bytes_total"),
        rtmp_bitrate_bps=_rtmp_total(metrics, "studio_rtmp_bitrate_bps"),
        obs_source_active=_metric_bool(metrics, "hapax_obs_decoder_source_active"),
        obs_playing=_metric_bool(metrics, "hapax_obs_decoder_playing"),
        obs_screenshot_changed=_metric_bool(metrics, "hapax_obs_decoder_frame_hash_changed"),
        obs_screenshot_flat=_metric_bool(metrics, "hapax_obs_decoder_frame_flat"),
        obs_screenshot_age_seconds=_metric_value(
            metrics,
            "hapax_obs_decoder_screenshot_seconds_ago",
        ),
        public_output_live=_metric_bool(metrics, "hapax_public_output_live"),
        watchdog_last_fed_age_seconds=_metric_value(
            metrics,
            "studio_compositor_watchdog_last_fed_seconds_ago",
        ),
        director_last_intent_age_seconds=_metric_value(
            metrics,
            "studio_compositor_director_last_intent_seconds_ago",
        ),
    )
