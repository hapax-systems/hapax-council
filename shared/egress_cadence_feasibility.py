"""Deterministic 60 fps egress cadence sizing helpers.

The compositor output cadence is a deployment decision, not just a config
integer. These helpers keep the byte-rate and standing-buffer math in source
so research notes and canary scripts do not recalculate it by hand.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

MIB = 1024 * 1024


@dataclass(frozen=True)
class BufferFootprint:
    """A frame-count-bounded buffer or queue footprint."""

    name: str
    pixel_format: str
    frames: int
    mib: float


@dataclass(frozen=True)
class EgressCadenceReport:
    """Sizing and readiness result for a target egress cadence."""

    width: int
    height: int
    current_fps: int
    target_fps: int
    workload_multiplier: float
    nv12_frame_mib: float
    bgra_frame_mib: float
    current_nv12_mib_per_s: float
    target_nv12_mib_per_s: float
    added_nv12_mib_per_s: float
    current_bgra_mib_per_s: float
    target_bgra_mib_per_s: float
    added_bgra_mib_per_s: float
    bridge_copy_added_mib_per_s: float
    standing_buffer_increment_mib: float
    standing_buffers: tuple[BufferFootprint, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def nv12_frame_bytes(width: int, height: int) -> int:
    """Return bytes for one 8-bit NV12 frame."""

    _validate_geometry(width, height)
    return width * height * 3 // 2


def bgra_frame_bytes(width: int, height: int) -> int:
    """Return bytes for one 8-bit BGRA frame."""

    _validate_geometry(width, height)
    return width * height * 4


def mib(value: int | float) -> float:
    return float(value) / MIB


def mib_per_second(frame_bytes: int, fps: int | float) -> float:
    if fps < 0:
        raise ValueError("fps must be non-negative")
    return mib(frame_bytes * fps)


def assess_egress_cadence(
    *,
    width: int = 1280,
    height: int = 720,
    current_fps: int = 30,
    target_fps: int = 60,
    source_publish_fps: float | None = None,
    live_egress_fps: float | None = None,
    free_vram_mib: float | None = None,
    three_d_mode: bool = False,
) -> EgressCadenceReport:
    """Assess whether a target egress cadence is ready for canarying.

    The steady-state buffer estimate deliberately treats 30 fps and 60 fps as
    equal when the same resolution and frame-count-bounded queues are used.
    Cadence primarily doubles throughput and encoder work; it should not
    double standing VRAM by itself.
    """

    _validate_geometry(width, height)
    if current_fps <= 0:
        raise ValueError("current_fps must be positive")
    if target_fps <= 0:
        raise ValueError("target_fps must be positive")

    nv12 = nv12_frame_bytes(width, height)
    bgra = bgra_frame_bytes(width, height)
    workload_multiplier = target_fps / current_fps

    current_nv12 = mib_per_second(nv12, current_fps)
    target_nv12 = mib_per_second(nv12, target_fps)
    current_bgra = mib_per_second(bgra, current_fps)
    target_bgra = mib_per_second(bgra, target_fps)

    standing_buffers = (
        BufferFootprint("shmsink_ring", "NV12", 8, mib(nv12 * 8)),
        BufferFootprint("v4l2_egress_queue", "BGRA", 4, mib(bgra * 4)),
        BufferFootprint("bridge_queue", "NV12", 5, mib(nv12 * 5)),
        BufferFootprint("bridge_appsink", "NV12", 2, mib(nv12 * 2)),
        BufferFootprint("hls_queue", "BGRA", 20, mib(bgra * 20)),
        BufferFootprint("rtmp_video_queue", "BGRA", 30, mib(bgra * 30)),
    )

    blockers: list[str] = []
    warnings: list[str] = []

    if three_d_mode:
        blockers.append("3d_compositor_bypasses_gstreamer_v4l2_hls_egress")

    if source_publish_fps is not None and source_publish_fps < target_fps * 0.9:
        blockers.append(
            f"source_publish_fps_below_target:{source_publish_fps:.2f}<{target_fps * 0.9:.2f}"
        )

    if live_egress_fps is not None and live_egress_fps < target_fps * 0.9:
        blockers.append(
            f"live_egress_fps_below_target:{live_egress_fps:.2f}<{target_fps * 0.9:.2f}"
        )

    if free_vram_mib is not None:
        # The model expects minimal standing VRAM growth; keep enough room for
        # encoder/context churn and one pipeline rebuild without cgroup pressure.
        if free_vram_mib < 512:
            blockers.append(f"free_vram_below_canary_floor:{free_vram_mib:.0f}<512")
        elif free_vram_mib < 2048:
            warnings.append(f"free_vram_below_comfort_floor:{free_vram_mib:.0f}<2048")

    if target_fps > current_fps:
        warnings.append(
            f"egress_workload_multiplier:{workload_multiplier:.2f}x; verify NVENC/FX latency live"
        )

    recommendation = "candidate_canary" if not blockers else "do_not_enable"

    return EgressCadenceReport(
        width=width,
        height=height,
        current_fps=current_fps,
        target_fps=target_fps,
        workload_multiplier=workload_multiplier,
        nv12_frame_mib=mib(nv12),
        bgra_frame_mib=mib(bgra),
        current_nv12_mib_per_s=current_nv12,
        target_nv12_mib_per_s=target_nv12,
        added_nv12_mib_per_s=target_nv12 - current_nv12,
        current_bgra_mib_per_s=current_bgra,
        target_bgra_mib_per_s=target_bgra,
        added_bgra_mib_per_s=target_bgra - current_bgra,
        bridge_copy_added_mib_per_s=(target_nv12 - current_nv12) * 2,
        standing_buffer_increment_mib=0.0,
        standing_buffers=standing_buffers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        recommendation=recommendation,
    )


def _validate_geometry(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if width % 2 != 0 or height % 2 != 0:
        raise ValueError("NV12 geometry requires even width and height")
