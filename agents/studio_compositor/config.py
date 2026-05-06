"""Configuration constants and loaders for the studio compositor."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .models import CameraSpec, CompositorConfig

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".cache" / "hapax-compositor"
STATUS_FILE = CACHE_DIR / "status.json"
CONSENT_AUDIT_PATH = CACHE_DIR / "consent-audit.jsonl"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hapax-compositor" / "config.yaml"
SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")
PERCEPTION_STATE_PATH = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
PROFILES_CONFIG_PATH = Path.home() / ".config" / "hapax-compositor" / "profiles.yaml"

# A+ Stage 2 (2026-04-17): canvas 1920x1080 → 1280x720. Operator directive
# 2026-04-17: "1080p is NOT a priority at all." Rationale per research:
# 2.25x fewer pixels through the cudacompositor + glfeedback chain + NVENC
# encoder; YouTube Live at 720p30 accepts 2500-4000 kbps (vs 6000 at 1080p);
# OBS and every PiP in the current layout are already ≤720p natively, so
# 1080p canvas was upscale-then-downscale waste. Layout JSON coordinates
# are scaled below via LAYOUT_COORD_SCALE.
#
# 2026-04-21 crispness pass considered reverting to 1920x1080 (Tier B of
# the livestream-crispness research) but the 3090 is already at 22 GiB /
# 24 GiB VRAM with TabbyAPI's Command-R 35B + compositor shader state;
# doubling canvas pixel area would push past the VRAM cap. Stay at 720p
# until VRAM headroom changes (model swap / rig migration).
#
# Override via HAPAX_COMPOSITOR_OUTPUT_WIDTH / _HEIGHT env vars for
# debugging or A/B comparison without a code change.
import os as _os

OUTPUT_WIDTH = int(_os.environ.get("HAPAX_COMPOSITOR_OUTPUT_WIDTH", "1280"))
OUTPUT_HEIGHT = int(_os.environ.get("HAPAX_COMPOSITOR_OUTPUT_HEIGHT", "720"))
# Multiplier applied to absolute pixel coordinates in layout JSON so
# existing 1920x1080-authored layouts render correctly at the smaller
# canvas. 1280/1920 = 0.6667.
LAYOUT_COORD_SCALE = OUTPUT_WIDTH / 1920.0

# ---------------------------------------------------------------------------
# Default camera config
# ---------------------------------------------------------------------------

# Task #135 — camera classification metadata. ``semantic_role`` /
# ``subject_ontology`` / ``angle`` / ``operator_visible`` /
# ``ambient_priority`` let the director reason about what each camera
# points at semantically, not just by role string. The 6 production
# cameras map to the semantic roles documented in the task spec.
_DEFAULT_CAMERAS: list[dict[str, Any]] = [
    {
        "role": "brio-operator",
        "device": "/dev/video60",
        "width": 1280,
        "height": 720,
        "input_format": "mjpeg",
        "hero": True,
        "semantic_role": "operator-face",
        "subject_ontology": ["person"],
        "angle": "front",
        "operator_visible": True,
        "ambient_priority": 7,
    },
    {
        "role": "c920-desk",
        "device": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0",
        "width": 1280,
        "height": 720,
        "input_format": "mjpeg",
        "semantic_role": "operator-hands",
        "subject_ontology": ["hands", "mpc"],
        "angle": "oblique",
        "operator_visible": False,
        "ambient_priority": 5,
    },
    {
        "role": "c920-room",
        "device": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_86B6B75F-video-index0",
        "width": 1280,
        "height": 720,
        "input_format": "mjpeg",
        "semantic_role": "room-wide",
        "subject_ontology": ["room", "person"],
        "angle": "oblique",
        "operator_visible": True,
        "ambient_priority": 8,
    },
    {
        "role": "c920-overhead",
        "device": "/dev/video61",
        "width": 1280,
        "height": 720,
        "input_format": "mjpeg",
        "semantic_role": "operator-desk-topdown",
        "subject_ontology": ["hands", "mpc", "desk"],
        "angle": "top-down",
        "operator_visible": False,
        "ambient_priority": 6,
    },
    {
        "role": "brio-room",
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A-video-index0",
        "width": 1280,
        "height": 720,
        "input_format": "mjpeg",
        "semantic_role": "outboard-gear",
        "subject_ontology": ["eurorack", "outboard"],
        "angle": "front",
        "operator_visible": False,
        "ambient_priority": 3,
    },
    {
        "role": "brio-synths",
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index0",
        "width": 640,
        "height": 480,
        "framerate": 15,
        "input_format": "mjpeg",
        "semantic_role": "turntables",
        "subject_ontology": ["turntable", "vinyl"],
        "angle": "top-down",
        "operator_visible": False,
        "ambient_priority": 4,
    },
]


def _default_config() -> CompositorConfig:
    return CompositorConfig(cameras=[CameraSpec(**c) for c in _DEFAULT_CAMERAS])


# Fields that fall back to ``_DEFAULT_CAMERAS`` (keyed by ``role``) when
# absent from the user YAML. Without this overlay, a YAML file that names
# the cameras but omits classification fields produces an entire fleet of
# ``semantic_role="unspecified", subject_ontology=[], operator_visible=False``
# cameras — which collapses ``FollowModeController._score_camera`` to a
# pure round-robin (every camera scores ``priority=5`` and the only
# differentiator becomes the recency penalty). The semantic-recruitment
# audit on 2026-05-02 documented the resulting degeneracy: 322
# hero-camera-override events in 15 min, every single one tagged
# ``priority=5, repetition-3.0``. The 6 production cameras already carry
# correct classifications in ``_DEFAULT_CAMERAS``; this overlay is what
# carries them through to deployments whose YAML predates Task #135.
_CLASSIFICATION_FIELDS: tuple[str, ...] = (
    "semantic_role",
    "subject_ontology",
    "angle",
    "operator_visible",
    "ambient_priority",
)


def _merge_camera_classifications(
    yaml_cameras: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay ``_DEFAULT_CAMERAS`` classification fields onto YAML cameras.

    For each camera in ``yaml_cameras`` that matches a known ``role`` in
    ``_DEFAULT_CAMERAS``, fill in classification fields the YAML omitted.
    YAML-supplied values always win — this is a fill-the-blanks merge,
    not a clobber.
    """
    by_role = {cam["role"]: cam for cam in _DEFAULT_CAMERAS if "role" in cam}
    merged: list[dict[str, Any]] = []
    for cam in yaml_cameras:
        if not isinstance(cam, dict):
            merged.append(cam)
            continue
        role = cam.get("role")
        defaults = by_role.get(role)
        if defaults is None:
            merged.append(cam)
            continue
        filled = dict(cam)
        for field in _CLASSIFICATION_FIELDS:
            if field not in filled and field in defaults:
                filled[field] = defaults[field]
        merged.append(filled)
    return merged


def load_config(path: Path | None = None) -> CompositorConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
            if isinstance(data, dict) and isinstance(data.get("cameras"), list):
                data["cameras"] = _merge_camera_classifications(data["cameras"])
            return CompositorConfig(**data)
        except Exception as exc:
            log.warning("Failed to load config from %s: %s -- using defaults", config_path, exc)
    return _default_config()
