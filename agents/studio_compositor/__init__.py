"""Studio Compositor package -- backward-compatible re-exports."""

from .compositor import StudioCompositor
from .config import load_config
from .layout import compute_tile_layout
from .models import (
    CameraProfile,
    CameraSpec,
    CameraV4L2,
    CompositorConfig,
    HlsConfig,
    OverlayData,
    OverlayState,
    RecordingConfig,
    TileRect,
)
from .profiles import (
    apply_camera_profile,
    evaluate_active_profile,
    load_camera_profiles,
)

__all__ = [
    "CameraProfile",
    "CameraSpec",
    "CameraV4L2",
    "CompositorConfig",
    "HlsConfig",
    "OverlayData",
    "OverlayState",
    "RecordingConfig",
    "StudioCompositor",
    "TileRect",
    "apply_camera_profile",
    "compute_tile_layout",
    "evaluate_active_profile",
    "load_camera_profiles",
    "load_config",
]
