"""Perceptual coverage — camera frustum and microphone pickup zone queries.

Computes which devices are visible from which cameras, which microphone
best covers a position, and where coverage gaps exist. Uses the equipment
registry (workspace_graph) for device positions and the camera registry
(_cameras.py) for camera specs.

Camera frustums are 6-plane convex volumes computed from position,
orientation, and field of view. Point-in-frustum is 6 dot products.

Microphone pickup uses the first-order polar equation:
    G(theta) = alpha + (1 - alpha) * cos(theta)
where alpha determines the pattern (1.0=omni, 0.5=cardioid, 0.0=figure8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from shared import workspace_graph


@dataclass(frozen=True)
class FrustumPlane:
    normal: tuple[float, float, float]
    d: float

    def signed_distance(self, point: tuple[float, float, float]) -> float:
        return (
            self.normal[0] * point[0]
            + self.normal[1] * point[1]
            + self.normal[2] * point[2]
            + self.d
        )


@dataclass(frozen=True)
class CameraFrustum:
    planes: tuple[FrustumPlane, ...]
    camera_id: str

    def contains_point(self, point: tuple[float, float, float]) -> bool:
        return all(p.signed_distance(point) >= 0 for p in self.planes)


# BRIO: ~78 deg diagonal → ~65h x ~40v. C920: ~78 deg diagonal → ~65h x ~40v.
_DEFAULT_FOV_H = 65.0
_DEFAULT_FOV_V = 40.0
_DEFAULT_NEAR = 0.1
_DEFAULT_FAR = 5.0


def build_frustum(
    position: tuple[float, float, float],
    yaw_deg: float,
    pitch_deg: float = 0.0,
    fov_h_deg: float = _DEFAULT_FOV_H,
    fov_v_deg: float = _DEFAULT_FOV_V,
    near: float = _DEFAULT_NEAR,
    far: float = _DEFAULT_FAR,
    camera_id: str = "",
) -> CameraFrustum:
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)

    forward = np.array(
        [
            math.cos(pitch) * math.sin(yaw),
            math.cos(pitch) * math.cos(yaw),
            math.sin(pitch),
        ]
    )
    world_up = np.array([0.0, 0.0, 1.0])
    right = np.cross(forward, world_up)
    norm = np.linalg.norm(right)
    if norm < 1e-6:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / norm
    up = np.cross(right, forward)
    up = up / np.linalg.norm(up)

    pos = np.array(position)
    half_h = math.radians(fov_h_deg / 2)
    half_v = math.radians(fov_v_deg / 2)

    def plane_from_point_normal(point: np.ndarray, normal: np.ndarray) -> FrustumPlane:
        n = normal / np.linalg.norm(normal)
        d = -float(np.dot(n, point))
        return FrustumPlane(normal=tuple(n.tolist()), d=d)

    near_plane = plane_from_point_normal(pos + forward * near, forward)
    far_plane = plane_from_point_normal(pos + forward * far, -forward)

    left_dir = forward * math.cos(half_h) + right * math.sin(half_h)
    left_normal = np.cross(up, left_dir)
    left_normal = left_normal / np.linalg.norm(left_normal)

    right_dir = forward * math.cos(half_h) - right * math.sin(half_h)
    right_normal = np.cross(right_dir, up)
    right_normal = right_normal / np.linalg.norm(right_normal)

    top_dir = forward * math.cos(half_v) + up * math.sin(half_v)
    top_normal = np.cross(top_dir, right)
    top_normal = top_normal / np.linalg.norm(top_normal)

    bottom_dir = forward * math.cos(half_v) - up * math.sin(half_v)
    bottom_normal = np.cross(right, bottom_dir)
    bottom_normal = bottom_normal / np.linalg.norm(bottom_normal)

    planes = (
        near_plane,
        far_plane,
        plane_from_point_normal(pos, left_normal),
        plane_from_point_normal(pos, right_normal),
        plane_from_point_normal(pos, top_normal),
        plane_from_point_normal(pos, bottom_normal),
    )
    return CameraFrustum(planes=planes, camera_id=camera_id)


def _get_camera_frustums() -> list[CameraFrustum]:
    try:
        from agents._cameras import CAMERAS
    except ImportError:
        return []

    frustums = []
    for cam in CAMERAS:
        frustums.append(
            build_frustum(
                position=cam.position,
                yaw_deg=cam.yaw_deg,
                camera_id=cam.role,
            )
        )
    return frustums


def which_cameras_see(device_id: str) -> list[str]:
    device = workspace_graph.by_id(device_id)
    if not device:
        return []

    placement = device.get("placement", {})
    pos = placement.get("position_m")
    if not pos or len(pos) != 3:
        return []

    position = tuple(pos)
    frustums = _get_camera_frustums()
    return [f.camera_id for f in frustums if f.contains_point(position)]


def devices_on_stream(active_camera_id: str | None = None) -> list[str]:
    if active_camera_id is None:
        return []

    frustums = _get_camera_frustums()
    frustum = next((f for f in frustums if f.camera_id == active_camera_id), None)
    if not frustum:
        return []

    visible = []
    for device in workspace_graph.all_devices():
        placement = device.get("placement", {})
        pos = placement.get("position_m")
        if pos and len(pos) == 3 and frustum.contains_point(tuple(pos)):
            visible.append(device["device_id"])
    return visible


def coverage_gaps(
    zone_bounds: tuple[float, float, float, float] | None = None,
    grid_spacing: float = 0.5,
    z_height: float = 0.8,
) -> list[tuple[float, float, float]]:
    if zone_bounds is None:
        zone_bounds = (0.0, 0.0, 2.0, 1.5)

    x_min, y_min, x_max, y_max = zone_bounds
    frustums = _get_camera_frustums()
    gaps = []

    x = x_min
    while x <= x_max:
        y = y_min
        while y <= y_max:
            point = (x, y, z_height)
            if not any(f.contains_point(point) for f in frustums):
                gaps.append(point)
            y += grid_spacing
        x += grid_spacing

    return gaps


@dataclass(frozen=True)
class MicSpec:
    mic_id: str
    position: tuple[float, float, float]
    orientation_deg: float
    pattern_alpha: float


def mic_sensitivity(mic: MicSpec, target: tuple[float, float, float]) -> float:
    dx = target[0] - mic.position[0]
    dy = target[1] - mic.position[1]
    dz = target[2] - mic.position[2]
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    if distance < 0.01:
        return 1.0

    angle_to_target = math.atan2(dx, dy)
    mic_angle = math.radians(mic.orientation_deg)
    theta = abs(angle_to_target - mic_angle)
    if theta > math.pi:
        theta = 2 * math.pi - theta

    gain = mic.pattern_alpha + (1 - mic.pattern_alpha) * math.cos(theta)
    return max(0.0, gain) / distance


def best_mic_for(
    position: tuple[float, float, float],
    mics: list[MicSpec],
) -> MicSpec | None:
    if not mics:
        return None
    return max(mics, key=lambda m: mic_sensitivity(m, position))
