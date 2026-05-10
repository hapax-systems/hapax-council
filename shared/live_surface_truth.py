"""Viewer-facing livestream truth predicates.

These predicates deliberately distinguish internal compositor flow from
egress/consumer truth. A moving HLS playlist, fresh camera pad probes, or a
compositor-side SHM write can keep an incident contained, but none of them is
enough to call the livestream restored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class LiveSurfaceState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED_CONTAINMENT = "degraded_containment"
    FAILED = "failed"


@dataclass(frozen=True)
class LiveSurfaceSnapshot:
    service_active: bool
    bridge_active: bool
    cameras_total: int
    cameras_healthy: int
    v4l2_frames_total: float | None = None
    v4l2_last_frame_age_seconds: float | None = None
    shmsink_frames_total: float | None = None
    shmsink_last_frame_age_seconds: float | None = None
    containment_flags: Mapping[str, bool] = field(default_factory=dict)
    hls_active: bool = False


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

    for name, active in sorted(snapshot.containment_flags.items()):
        if active:
            degraded.append(f"containment_flag:{name}")

    shmsink_positive = _metric_positive(snapshot.shmsink_frames_total)
    v4l2_positive = _metric_positive(snapshot.v4l2_frames_total)
    v4l2_fresh = _metric_fresh(
        snapshot.v4l2_last_frame_age_seconds,
        max_age_seconds=max_egress_age_seconds,
    )

    if require_v4l2:
        if not snapshot.bridge_active:
            degraded.append("v4l2_bridge_inactive")
        if not v4l2_positive:
            degraded.append("v4l2_no_frames")
        elif not v4l2_fresh:
            degraded.append("v4l2_stale_frames")

    if shmsink_positive and not v4l2_positive:
        degraded.append("shmsink_without_v4l2_egress")

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


def parse_prometheus_scalars(text: str) -> dict[str, float]:
    """Parse unlabeled Prometheus scalar samples from text exposition."""

    values: dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "{" in line:
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


def snapshot_from_prometheus(
    metrics: Mapping[str, float],
    *,
    service_active: bool,
    bridge_active: bool,
    containment_flags: Mapping[str, bool] | None = None,
    hls_active: bool = False,
) -> LiveSurfaceSnapshot:
    return LiveSurfaceSnapshot(
        service_active=service_active,
        bridge_active=bridge_active,
        cameras_total=int(metrics.get("studio_compositor_cameras_total", 0)),
        cameras_healthy=int(metrics.get("studio_compositor_cameras_healthy", 0)),
        v4l2_frames_total=metrics.get("studio_compositor_v4l2sink_frames_total"),
        v4l2_last_frame_age_seconds=metrics.get(
            "studio_compositor_v4l2sink_last_frame_seconds_ago"
        ),
        shmsink_frames_total=metrics.get("studio_compositor_shmsink_frames_total"),
        shmsink_last_frame_age_seconds=metrics.get(
            "studio_compositor_shmsink_last_frame_seconds_ago"
        ),
        containment_flags=containment_flags or {},
        hls_active=hls_active,
    )
