"""Shared camera configuration — single source of truth for multi-camera system.

All camera roles, resolutions, aliases, and classification live here.
Consumers import from this module rather than hardcoding camera lists.

Camera classes:
  brio   — Logitech Brio 4K, 1920x1080 @ 30fps, high-quality person sensing
  c920   — Logitech C920, 1280x720, environment/object sensing

With 6 cameras (3 Brio + 3 C920), the system covers multiple perspectives
of the workspace. Any Brio-class camera can run person enrichment classifiers
(gaze, emotion, posture, gesture, action).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CameraSpec:
    """Specification for a single camera."""

    role: str  # Full role name (e.g., "brio-operator")
    short: str  # Short name used by vision backend (e.g., "operator")
    width: int
    height: int
    camera_class: str  # "brio" | "c920"
    person_enrichment: bool  # Can run gaze/emotion/posture classifiers
    # Approximate room position (meters from origin) and aim direction.
    # Initial estimates — operator can calibrate via compositor UI.
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (x, y, z)
    yaw_deg: float = 0.0  # horizontal aim (0=north, 90=east)


# ── Camera registry ───────────────────────────────────────────────────

CAMERAS: tuple[CameraSpec, ...] = (
    # Brio cameras — high-res, person enrichment capable
    CameraSpec(
        "brio-operator", "operator", 1920, 1080, "brio", True, position=(1.5, 0.8, 1.2), yaw_deg=180
    ),
    CameraSpec(
        "brio-room", "room-brio", 1920, 1080, "brio", True, position=(0.0, 3.0, 1.5), yaw_deg=90
    ),
    CameraSpec(
        "brio-synths",
        "synths-brio",
        1920,
        1080,
        "brio",
        True,
        position=(3.0, 2.0, 1.8),
        yaw_deg=270,
    ),
    # C920 cameras — environment/object sensing
    CameraSpec(
        "c920-desk", "desk", 1280, 720, "c920", False, position=(1.5, 0.5, 2.0), yaw_deg=270
    ),
    CameraSpec("c920-room", "room", 1280, 720, "c920", False, position=(0.0, 0.0, 1.5), yaw_deg=45),
    CameraSpec(
        "c920-overhead", "overhead", 1280, 720, "c920", False, position=(1.5, 1.5, 2.5), yaw_deg=0
    ),
)


# ── Instrument zones (overhead camera) ────────────────────────────────


@dataclass(frozen=True)
class InstrumentZone:
    """Bounding box for an instrument zone in the overhead frame."""

    name: str
    x1: int
    y1: int
    x2: int
    y2: int


OVERHEAD_ZONES: tuple[InstrumentZone, ...] = (
    InstrumentZone("turntable", 0, 100, 400, 550),
    InstrumentZone("pads", 400, 150, 800, 500),
    InstrumentZone("mixer", 300, 0, 550, 200),
    InstrumentZone("keyboard", 800, 300, 1280, 600),
)


def point_in_zone(x: int, y: int) -> str:
    """Return the instrument zone name for a pixel coordinate, or 'unknown'."""
    for z in OVERHEAD_ZONES:
        if z.x1 <= x <= z.x2 and z.y1 <= y <= z.y2:
            return z.name
    return "unknown"


# ── Derived lookups ───────────────────────────────────────────────────

# All camera role names (full)
CAMERA_ROLES: list[str] = [c.role for c in CAMERAS]

# Short name → full role name
SHORT_TO_ROLE: dict[str, str] = {c.short: c.role for c in CAMERAS}

# Full role name → short name
ROLE_TO_SHORT: dict[str, str] = {c.role: c.short for c in CAMERAS}

# Resolution lookup (both short and full names)
RESOLUTIONS: dict[str, tuple[int, int]] = {}
for _c in CAMERAS:
    RESOLUTIONS[_c.role] = (_c.width, _c.height)
    RESOLUTIONS[_c.short] = (_c.width, _c.height)

# Cameras that can run person enrichment classifiers
ENRICHMENT_CAMERAS: set[str] = set()
for _c in CAMERAS:
    if _c.person_enrichment:
        ENRICHMENT_CAMERAS.add(_c.role)
        ENRICHMENT_CAMERAS.add(_c.short)

# Brio-class cameras (for cross-camera person matching with better resolution)
BRIO_ROLES: list[str] = [c.role for c in CAMERAS if c.camera_class == "brio"]

# Vision backend uses short names
VISION_CAMERA_ROLES: list[str] = [c.short for c in CAMERAS]


def resolve_role(camera: str) -> str:
    """Resolve a short or full camera name to the canonical full role name."""
    return SHORT_TO_ROLE.get(camera, camera)


def resolution(camera: str) -> tuple[int, int]:
    """Get resolution for a camera by short or full name. Defaults to 1920x1080."""
    return RESOLUTIONS.get(camera, (1920, 1080))


def can_enrich_persons(camera: str) -> bool:
    """Whether this camera can run person enrichment classifiers."""
    return camera in ENRICHMENT_CAMERAS
