"""Attention perception backend — gaze zone, engagement, and posture.

Reads multi-camera signals (when available from perception pipeline)
and provides attention feedback to the content scheduler:
  - gaze_zone: which content zone the operator is looking at
  - engagement_level: from head pose + body pose + micro-movements
  - posture_state: upright / slouching / leaning

When multi-camera backends aren't running, all fields default to neutral
values so the scheduler works without them.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

_ATTENTION_STATE_PATH = Path.home() / ".cache" / "hapax-daimonion" / "attention-state.json"


class AttentionBackend:
    """PerceptionBackend that reads multi-camera attention signals.

    Provides:
      - gaze_zone: str (content zone operator is looking at, or "unknown")
      - engagement_level: float (0.0 = disengaged, 1.0 = fully engaged)
      - posture_state: str ("upright", "slouching", "leaning", "unknown")

    The scheduler uses these to:
      - Boost sources that got recent gaze attention (positive feedback)
      - Reduce sources that were ignored (negative feedback)
      - Adjust display density based on engagement level
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self._path = state_path or _ATTENTION_STATE_PATH
        self._b_gaze: Behavior[str] = Behavior("unknown")
        self._b_engagement: Behavior[float] = Behavior(0.5)
        self._b_posture: Behavior[str] = Behavior("unknown")

    @property
    def name(self) -> str:
        return "attention"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"gaze_zone", "engagement_level", "posture_state"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        return self._path.exists()

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        gaze, engagement, posture = self._read_state()
        self._b_gaze.update(gaze, now)
        self._b_engagement.update(engagement, now)
        self._b_posture.update(posture, now)
        behaviors["gaze_zone"] = self._b_gaze
        behaviors["engagement_level"] = self._b_engagement
        behaviors["posture_state"] = self._b_posture

    def start(self) -> None:
        log.info("Attention backend started (path=%s)", self._path)

    def stop(self) -> None:
        log.info("Attention backend stopped")

    def _read_state(self) -> tuple[str, float, str]:
        """Read attention state from JSON file.

        Returns (gaze_zone, engagement_level, posture_state) or defaults.
        """
        if not self._path.exists():
            return "unknown", 0.5, "unknown"
        try:
            data = json.loads(self._path.read_text())
            gaze = data.get("gaze_zone", "unknown")
            engagement = float(data.get("engagement_level", 0.5))
            engagement = max(0.0, min(1.0, engagement))
            posture = data.get("posture_state", "unknown")
            return gaze, engagement, posture
        except (json.JSONDecodeError, OSError, ValueError):
            return "unknown", 0.5, "unknown"
