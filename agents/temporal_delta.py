"""Temporal delta correlator — derive motion signals from sightings history.

Pure computation module: no I/O, no GPU, no network. Takes sightings
(normalized box coordinates) and timestamps, returns per-entity temporal
derivatives: velocity, direction, dwell, entry/exit classification.

Designed as a Batch 2 building block: consumes the enriched sightings
from SceneInventory.snapshot_for_overlay(), produces fields that attach
to ClassificationDetection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TemporalDelta:
    """Per-entity temporal derivatives computed from sightings history."""

    velocity: float  # normalized coords/s (0 = stationary)
    direction_deg: float | None  # 0=right, 90=down, 180=left, 270=up; None if stationary
    confidence_stability: float  # stddev of confidence over sightings (0 = perfectly stable)
    dwell_s: float  # seconds at current position (low velocity)
    is_entering: bool  # first appeared within last 2 sightings
    is_exiting: bool  # last seen > threshold ago


# Velocity below this is considered stationary (no direction)
_VELOCITY_THRESHOLD = 0.005  # ~0.5% of frame per second


def compute_temporal_delta(
    sightings: list[dict],
    first_seen: float,
    last_seen: float,
    now: float,
    exit_threshold_s: float = 10.0,
    camera: str | None = None,
) -> TemporalDelta:
    """Compute temporal delta from a sightings ring buffer.

    Args:
        sightings: List of dicts with keys: box (4-element list, normalized 0-1),
                   conf (float), ts (float timestamp), camera (str, optional).
        first_seen: Epoch timestamp of entity's first detection.
        last_seen: Epoch timestamp of entity's most recent detection.
        now: Current epoch timestamp.
        exit_threshold_s: Seconds since last_seen to classify as exiting.
        camera: If provided, only use sightings from this camera for
                velocity/direction computation (prevents cross-camera
                coordinate mixing in multi-perspective setups).

    Returns:
        TemporalDelta with derived motion signals.
    """
    # Filter to same-camera sightings for spatial computation
<<<<<<< HEAD
    all_sightings = sightings
=======
>>>>>>> origin/feat/six-camera-wiring
    if camera:
        sightings = [s for s in sightings if s.get("camera", "") == camera or not s.get("camera")]
    if len(sightings) < 2:
        # Cross-camera: spatial velocity unavailable but entry/exit can use all sightings
        use_all = len(all_sightings) >= 2
        return TemporalDelta(
            velocity=0.0,
            direction_deg=None,
            confidence_stability=0.0,
            dwell_s=now - first_seen if first_seen > 0 else 0.0,
            is_entering=(len(all_sightings) <= 2 and (now - first_seen) < 5.0)
            if use_all
            else (len(sightings) <= 2 and (now - first_seen) < 5.0),
            is_exiting=(now - last_seen) > exit_threshold_s if last_seen > 0 else False,
        )

    # Compute centroids from boxes
    centroids: list[tuple[float, float, float]] = []  # (cx, cy, ts)
    confidences: list[float] = []

    for s in sightings:
        box = s.get("box", [])
        if len(box) != 4:
            continue
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        ts = s.get("ts", 0.0)
        centroids.append((cx, cy, ts))
        confidences.append(s.get("conf", 0.0))

    if len(centroids) < 2:
        return TemporalDelta(
            velocity=0.0,
            direction_deg=None,
            confidence_stability=0.0,
            dwell_s=now - first_seen,
            is_entering=len(sightings) <= 2 and (now - first_seen) < 5.0,
            is_exiting=(now - last_seen) > exit_threshold_s,
        )

    # Velocity: average displacement per second across consecutive pairs
    total_dist = 0.0
    total_dt = 0.0
    for i in range(1, len(centroids)):
        dx = centroids[i][0] - centroids[i - 1][0]
        dy = centroids[i][1] - centroids[i - 1][1]
        dt = centroids[i][2] - centroids[i - 1][2]
        if dt > 0:
            total_dist += math.sqrt(dx * dx + dy * dy)
            total_dt += dt

    velocity = total_dist / total_dt if total_dt > 0 else 0.0

    # Direction: angle from first to last centroid
    direction_deg: float | None = None
    if velocity >= _VELOCITY_THRESHOLD:
        dx = centroids[-1][0] - centroids[0][0]
        dy = centroids[-1][1] - centroids[0][1]
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            angle_rad = math.atan2(dy, dx)  # atan2(y,x): 0=right, pi/2=down
            direction_deg = math.degrees(angle_rad) % 360.0

    # Confidence stability: stddev of confidence values
    confidence_stability = 0.0
    if len(confidences) >= 2:
        mean_conf = sum(confidences) / len(confidences)
        variance = sum((c - mean_conf) ** 2 for c in confidences) / len(confidences)
        confidence_stability = math.sqrt(variance)

    # Dwell: time spent near current position (velocity < threshold)
    dwell_s = 0.0
    if velocity < _VELOCITY_THRESHOLD:
        dwell_s = now - first_seen
    else:
        # Find how long velocity has been low in recent history
        for i in range(len(centroids) - 1, 0, -1):
            dx = centroids[i][0] - centroids[i - 1][0]
            dy = centroids[i][1] - centroids[i - 1][1]
            dt = centroids[i][2] - centroids[i - 1][2]
            if dt > 0:
                seg_vel = math.sqrt(dx * dx + dy * dy) / dt
                if seg_vel < _VELOCITY_THRESHOLD:
                    dwell_s = now - centroids[i - 1][2]
                else:
                    break

    # Entry: appeared within last 2 ticks
    is_entering = len(sightings) <= 2 and (now - first_seen) < 5.0

    # Exit: not seen recently
    is_exiting = (now - last_seen) > exit_threshold_s

    return TemporalDelta(
        velocity=round(velocity, 6),
        direction_deg=round(direction_deg, 1) if direction_deg is not None else None,
        confidence_stability=round(confidence_stability, 4),
        dwell_s=round(dwell_s, 1),
        is_entering=is_entering,
        is_exiting=is_exiting,
    )
