"""Publish CPAL state to /dev/shm for SCM integration.

Writes two files atomically:
- /dev/shm/hapax-conversation/state.json -- full CPAL state
- /dev/shm/hapax-conversation/health.json -- ControlSignal for mesh health
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from agents.hapax_daimonion.cpal.loop_gain import LoopGainController
from agents.hapax_daimonion.cpal.types import CorrectionTier, ErrorSignal
from shared.control_signal import ControlSignal, publish_health

_DEFAULT_STATE_PATH = Path("/dev/shm/hapax-conversation/state.json")
_DEFAULT_HEALTH_PATH = Path("/dev/shm/hapax-conversation/health.json")


def publish_cpal_state(
    *,
    gain_controller: LoopGainController,
    error: ErrorSignal,
    action_tier: CorrectionTier,
    path: Path = _DEFAULT_STATE_PATH,
    health_path: Path = _DEFAULT_HEALTH_PATH,
) -> None:
    """Publish CPAL state atomically to /dev/shm."""
    state = {
        "gain": gain_controller.gain,
        "region": gain_controller.region.value,
        "error": {
            "comprehension": error.comprehension,
            "affective": error.affective,
            "temporal": error.temporal,
            "magnitude": error.magnitude,
            "dominant": error.dominant.value,
        },
        "action_tier": action_tier.value,
        "timestamp": time.time(),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.rename(path)

    cs = ControlSignal(
        component="conversation",
        reference=1.0,
        perception=1.0 - error.magnitude,
    )
    publish_health(cs, path=health_path)
