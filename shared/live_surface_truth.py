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


@dataclass(frozen=True)
class LiveSurfaceSnapshot:
    service_active: bool
    bridge_active: bool
    cameras_total: int
    cameras_healthy: int
    bridge_expected: bool = False
    v4l2_frames_total: float | None = None
    v4l2_last_frame_age_seconds: float | None = None
    shmsink_frames_total: float | None = None
    shmsink_last_frame_age_seconds: float | None = None
    final_egress_snapshot_frames_total: float | None = None
    final_egress_snapshot_last_frame_age_seconds: float | None = None
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
            if "{" not in line:
                continue
            parsed = _parse_labeled_render_stage_scalar(line)
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


def _parse_labeled_render_stage_scalar(line: str) -> tuple[str, float] | None:
    match = _RENDER_STAGE_SAMPLE.match(line)
    if match is None:
        return None
    try:
        value = float(match.group("value"))
    except ValueError:
        return None
    return f"{match.group('name')}:stage:{match.group('stage')}", value


def snapshot_from_prometheus(
    metrics: Mapping[str, float],
    *,
    service_active: bool,
    bridge_active: bool,
    bridge_expected: bool = False,
    containment_flags: Mapping[str, bool] | None = None,
    hls_active: bool = False,
) -> LiveSurfaceSnapshot:
    return LiveSurfaceSnapshot(
        service_active=service_active,
        bridge_active=bridge_active,
        cameras_total=int(metrics.get("studio_compositor_cameras_total", 0)),
        cameras_healthy=int(metrics.get("studio_compositor_cameras_healthy", 0)),
        bridge_expected=bridge_expected
        or bool(metrics.get("studio_compositor_v4l2_bridge_expected", 0)),
        v4l2_frames_total=metrics.get("studio_compositor_v4l2sink_frames_total"),
        v4l2_last_frame_age_seconds=metrics.get(
            "studio_compositor_v4l2sink_last_frame_seconds_ago"
        ),
        shmsink_frames_total=metrics.get("studio_compositor_shmsink_frames_total"),
        shmsink_last_frame_age_seconds=metrics.get(
            "studio_compositor_shmsink_last_frame_seconds_ago"
        ),
        final_egress_snapshot_frames_total=metrics.get(
            "studio_compositor_render_stage_frames_total:stage:final_egress_snapshot"
        ),
        final_egress_snapshot_last_frame_age_seconds=metrics.get(
            "studio_compositor_render_stage_last_frame_seconds_ago:stage:final_egress_snapshot"
        ),
        containment_flags=containment_flags or {},
        hls_active=hls_active,
    )
