"""Studio FX — independent Python visual effects pipeline.

Replaces the old GStreamer GL shader chain with numpy/OpenCV effects.
Each effect is a self-contained module; a single runner manages resolution
tiers (active/preview/warm/cold) and frame distribution.
"""

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot
from agents.studio_fx.runner import EffectRunner

__all__ = ["BaseEffect", "EffectRunner", "PerceptionSnapshot"]
