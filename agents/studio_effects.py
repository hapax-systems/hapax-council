"""Studio visual effects — GPU-accelerated effect chain for compositor output.

Provides EffectBin (a GstBin subclass) that wraps switchable GL-based
visual effect chains. Each preset configures a different combination
of GLSL shaders, blend modes, and temporal effects.

The EffectBin sits in the pipeline as:
  output-tee → queue → EffectBin → fx-tee
    ├─ v4l2sink (/dev/video50)
    └─ appsink (fx snapshot to /dev/shm)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SHADER_DIR = Path(__file__).parent / "shaders"


@dataclass
class TrailConfig:
    count: int = 0
    opacity: float = 0.3
    blend_mode: str = "add"  # add | multiply | difference
    drift_x: float = 0.0
    drift_y: float = 0.0
    filter_params: dict[str, float] = field(default_factory=dict)


@dataclass
class ColorGradeConfig:
    saturation: float = 1.0
    brightness: float = 1.0
    contrast: float = 1.0
    sepia: float = 0.0
    hue_rotate: float = 0.0  # degrees


@dataclass
class WarpConfig:
    pan_x: float = 0.0
    pan_y: float = 0.0
    rotation: float = 0.0
    zoom: float = 1.0
    zoom_breath: float = 0.0
    slice_count: int = 0
    slice_amplitude: float = 0.0


@dataclass
class StutterConfig:
    check_interval: int = 10
    freeze_chance: float = 0.3
    freeze_min: int = 3
    freeze_max: int = 10
    replay_frames: int = 3


@dataclass
class PostProcessConfig:
    vignette_strength: float = 0.0
    scanline_alpha: float = 0.0
    band_chance: float = 0.0
    band_max_shift: float = 0.0
    syrup_gradient: bool = False
    syrup_color: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class EffectPreset:
    name: str
    color_grade: ColorGradeConfig = field(default_factory=ColorGradeConfig)
    trail: TrailConfig = field(default_factory=TrailConfig)
    warp: WarpConfig | None = None
    stutter: StutterConfig | None = None
    post_process: PostProcessConfig = field(default_factory=PostProcessConfig)
    use_glow: bool = False  # gleffects glow pass
    use_vhs_shader: bool = False  # VHS-specific shader
    use_sobel: bool = False  # edge detection


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESETS: dict[str, EffectPreset] = {
    "ghost": EffectPreset(
        name="ghost",
        color_grade=ColorGradeConfig(saturation=0.85, brightness=0.9),
        trail=TrailConfig(count=4, opacity=0.4, blend_mode="add", drift_x=18, drift_y=24),
        warp=WarpConfig(pan_x=4, pan_y=3, rotation=0.005, zoom=1.01, zoom_breath=0.005),
        post_process=PostProcessConfig(vignette_strength=0.35),
        use_sobel=True,
    ),
    "trails": EffectPreset(
        name="trails",
        color_grade=ColorGradeConfig(saturation=0.7, brightness=1.15, sepia=0.1, hue_rotate=20),
        trail=TrailConfig(
            count=10, opacity=0.65, blend_mode="add", drift_x=6, drift_y=8,
            filter_params={"saturation": 0.8, "brightness": 1.8, "sepia": 0.15, "hue_rotate": 45},
        ),
        warp=WarpConfig(pan_x=3, pan_y=2, rotation=0.004, zoom=1.01, zoom_breath=0.005),
    ),
    "screwed": EffectPreset(
        name="screwed",
        color_grade=ColorGradeConfig(saturation=0.55, brightness=0.9, contrast=1.05, sepia=0.4, hue_rotate=250),
        trail=TrailConfig(
            count=3, opacity=0.2, blend_mode="add", drift_y=6,
            filter_params={"saturation": 0.3, "brightness": 0.5, "sepia": 0.6, "hue_rotate": 250},
        ),
        warp=WarpConfig(pan_x=20, pan_y=22, rotation=0.025, zoom=1.06, zoom_breath=0.04, slice_count=24, slice_amplitude=6),
        stutter=StutterConfig(check_interval=10, freeze_chance=0.5, freeze_min=3, freeze_max=10, replay_frames=3),
        post_process=PostProcessConfig(
            vignette_strength=0.3, scanline_alpha=0.12,
            band_chance=0.18, band_max_shift=15,
            syrup_gradient=True, syrup_color=(0.24, 0.08, 0.31),
        ),
    ),
    "datamosh": EffectPreset(
        name="datamosh",
        color_grade=ColorGradeConfig(saturation=0.6, brightness=1.15, contrast=1.8, hue_rotate=40),
        trail=TrailConfig(
            count=7, opacity=0.95, blend_mode="difference", drift_x=8, drift_y=6,
            filter_params={"saturation": 0.8, "brightness": 1.4, "contrast": 2.2, "hue_rotate": 90},
        ),
        stutter=StutterConfig(check_interval=8, freeze_chance=0.35, freeze_min=2, freeze_max=6, replay_frames=3),
        post_process=PostProcessConfig(scanline_alpha=0.12, band_chance=0.5, band_max_shift=40),
    ),
    "vhs": EffectPreset(
        name="vhs",
        color_grade=ColorGradeConfig(saturation=0.4, brightness=1.1, contrast=1.25, sepia=0.55, hue_rotate=-10),
        trail=TrailConfig(count=3, opacity=0.25, blend_mode="add", drift_x=4, drift_y=2),
        warp=WarpConfig(pan_x=2, pan_y=1, rotation=0.002, zoom=1.02, zoom_breath=0.004, slice_count=10, slice_amplitude=2),
        stutter=StutterConfig(check_interval=20, freeze_chance=0.15, freeze_min=2, freeze_max=5, replay_frames=2),
        post_process=PostProcessConfig(
            vignette_strength=0.4, scanline_alpha=0.12,
            band_chance=0.2, band_max_shift=12,
        ),
        use_vhs_shader=True,
    ),
    "neon": EffectPreset(
        name="neon",
        color_grade=ColorGradeConfig(saturation=3.5, brightness=1.45, contrast=1.5),
        trail=TrailConfig(
            count=8, opacity=0.6, blend_mode="add", drift_x=3, drift_y=4,
            filter_params={"saturation": 4.0, "brightness": 1.9, "contrast": 1.3},
        ),
        warp=WarpConfig(pan_x=4, pan_y=3, rotation=0.008, zoom=1.02, zoom_breath=0.012),
        post_process=PostProcessConfig(vignette_strength=0.5),
        use_glow=True,
    ),
    "trap": EffectPreset(
        name="trap",
        color_grade=ColorGradeConfig(saturation=0.2, brightness=0.65, contrast=1.3, sepia=0.4, hue_rotate=160),
        trail=TrailConfig(
            count=4, opacity=0.55, blend_mode="multiply", drift_x=1, drift_y=4,
            filter_params={"saturation": 0.15, "brightness": 0.4, "sepia": 0.5, "hue_rotate": 180},
        ),
        warp=WarpConfig(pan_x=1, pan_y=1, rotation=0.002, zoom=1.005, zoom_breath=0.003),
        post_process=PostProcessConfig(
            vignette_strength=0.55,
            syrup_gradient=True, syrup_color=(0.04, 0.02, 0.06),
        ),
    ),
    "diff": EffectPreset(
        name="diff",
        color_grade=ColorGradeConfig(saturation=0.0, brightness=0.85, contrast=1.6),
        trail=TrailConfig(
            count=2, opacity=0.95, blend_mode="difference",
            filter_params={"saturation": 0.0, "brightness": 1.6, "contrast": 2.5},
        ),
        post_process=PostProcessConfig(vignette_strength=0.15),
    ),
    "clean": EffectPreset(
        name="clean",
        color_grade=ColorGradeConfig(saturation=1.05, contrast=1.05),
        trail=TrailConfig(count=2, opacity=0.15, blend_mode="source-over"),
        post_process=PostProcessConfig(vignette_strength=0.12),
    ),
}


def load_shader(name: str) -> str:
    """Load a GLSL shader from the shaders directory."""
    path = SHADER_DIR / name
    if not path.exists():
        log.warning("Shader not found: %s", path)
        return ""
    return path.read_text()


def build_uniform_struct(params: dict[str, float]) -> str:
    """Build a GstStructure string for glshader uniforms."""
    parts = ["uniforms"]
    for k, v in params.items():
        parts.append(f"{k}=(float){v}")
    return ",".join(parts)
