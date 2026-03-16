"""Write perception state to disk for external consumers (e.g. studio compositor).

Atomic write-then-rename to ~/.cache/hapax-voice/perception-state.json each
perception tick. External readers can poll this file without coordination.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_voice.consent_state import ConsentStateTracker
    from agents.hapax_voice.perception import PerceptionEngine
    from shared.governance.consent import ConsentRegistry

log = logging.getLogger(__name__)

PERCEPTION_STATE_DIR = Path.home() / ".cache" / "hapax-voice"
PERCEPTION_STATE_FILE = PERCEPTION_STATE_DIR / "perception-state.json"


def write_perception_state(
    perception: PerceptionEngine,
    consent_registry: ConsentRegistry,
    consent_tracker: ConsentStateTracker | None = None,
) -> None:
    """Snapshot current perception state and write atomically to disk.

    Called once per perception tick (~2.5s). Tolerant of missing behaviors.
    """
    behaviors = perception.behaviors

    def _bval(name: str, default: object = "") -> object:
        b = behaviors.get(name)
        if b is None:
            return default
        return b.value

    # Determine flow state from score
    flow_score = float(_bval("flow_state_score", 0.0))
    if flow_score >= 0.6:
        flow_state = "active"
    elif flow_score >= 0.3:
        flow_state = "warming"
    else:
        flow_state = "idle"

    # Collect active consent contract IDs
    active_contracts: list[str] = []
    try:
        for contract in consent_registry.active_contracts():
            active_contracts.append(contract.id)
    except Exception:
        pass  # consent registry may not be loaded yet

    state = {
        "production_activity": str(_bval("production_activity", "")),
        "music_genre": str(_bval("music_genre", "")),
        "flow_state": flow_state,
        "flow_score": flow_score,
        "emotion_valence": float(_bval("emotion_valence", 0.0)),
        "emotion_arousal": float(_bval("emotion_arousal", 0.0)),
        "audio_energy_rms": float(_bval("audio_energy_rms", 0.0)),
        "active_contracts": active_contracts,
        "persistence_allowed": consent_tracker.persistence_allowed if consent_tracker else True,
        "timestamp": time.time(),
    }

    try:
        PERCEPTION_STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PERCEPTION_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.rename(PERCEPTION_STATE_FILE)
    except OSError:
        log.debug("Failed to write perception state", exc_info=True)
