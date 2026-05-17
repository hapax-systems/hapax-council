"""Audio performance context for affordance recruitment boost.

Reads recent audio engine impingements from the DMN bus to determine
the operator's current audio performance mode. Used as context input
to AffordancePipeline.select() so recruitment scores are modulated
by what the operator is actively doing.

Performance modes (ordered by activity level):
- idle: no audio engines active
- passive_music: music playing but no operator involvement (streaming)
- active_performance: vinyl spinning OR mixer actively driven
- speaking: operator voice detected (highest priority, dampens music fx)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

IMPINGEMENTS_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
VOICE_STATE_PATH = Path("/dev/shm/hapax-compositor/voice-state.json")
_MAX_AGE_S = 60.0


def read_audio_performance_mode() -> str:
    """Return the current audio performance mode string."""
    now = time.time()

    voice_active = _read_voice_active()
    if voice_active:
        return "speaking"

    music_active = False
    vinyl_active = False
    mixer_active = False

    try:
        if IMPINGEMENTS_PATH.exists():
            lines = IMPINGEMENTS_PATH.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines[-50:]):
                try:
                    imp = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = imp.get("timestamp", 0)
                if now - ts > _MAX_AGE_S:
                    break
                source = imp.get("source", "")
                content = imp.get("content", {})
                to_state = content.get("to_state", "")
                if source == "audio.music_playing" and to_state == "ASSERTED":
                    music_active = True
                elif source == "audio.vinyl_spinning" and to_state == "ASSERTED":
                    vinyl_active = True
                elif source == "audio.mixer_input" and to_state == "ACTIVE":
                    mixer_active = True
    except (OSError, ValueError):
        log.debug("Failed to read impingements for performance mode", exc_info=True)

    if vinyl_active or mixer_active:
        return "active_performance"
    if music_active:
        return "passive_music"
    return "idle"


def _read_voice_active() -> bool:
    try:
        if not VOICE_STATE_PATH.exists():
            return False
        data = json.loads(VOICE_STATE_PATH.read_text(encoding="utf-8"))
        return bool(data.get("operator_speech_active", False))
    except (OSError, json.JSONDecodeError):
        return False


def build_performance_context() -> dict[str, str]:
    """Build a context dict for AffordancePipeline.select().

    Returns a dict with a single key "audio_performance_mode" set to
    the current mode. The pipeline's context_boost mechanism uses this
    to modulate recruitment scores for capabilities that have learned
    associations with specific modes.
    """
    mode = read_audio_performance_mode()
    return {"audio_performance_mode": mode}
