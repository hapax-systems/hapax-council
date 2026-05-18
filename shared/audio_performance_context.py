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

An optional fast path reads a pre-computed snapshot from
``/dev/shm/hapax-audio/performance-context.json`` (written by the
audio perception layer). When that file is absent or stale the module
falls back to scanning the DMN impingement bus + voice state file.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── SHM paths ──────────────────────────────────────────────────────────────

PERFORMANCE_CONTEXT_PATH = Path("/dev/shm/hapax-audio/performance-context.json")
IMPINGEMENTS_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
VOICE_STATE_PATH = Path("/dev/shm/hapax-compositor/voice-state.json")

_MAX_AGE_S = 60.0

# ── Recruitment scale defaults per mode ────────────────────────────────────

_MODE_RECRUITMENT_SCALE: dict[str, float] = {
    "idle": 1.0,
    "passive_music": 1.1,
    "active_performance": 1.3,
    "speaking": 0.8,
}


# ── Pydantic model ─────────────────────────────────────────────────────────

PerformanceMode = Literal["active_performance", "speaking", "passive_music", "idle"]


class AudioPerformanceContext(BaseModel):
    """Snapshot of the operator's current audio performance posture.

    Fields:
        mode: Current performance classification.
        confidence: How confident the classification is (0.0-1.0).
            1.0 when read from the pre-computed SHM snapshot; lower
            when inferred from impingement scanning.
        recruitment_scale: Multiplicative factor for affordance scores.
            >1.0 boosts expression capabilities during active performance;
            <1.0 dampens them when the operator is speaking.
    """

    mode: PerformanceMode = "idle"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    recruitment_scale: float = Field(default=1.0, ge=0.0, le=2.0)


# ── Mode detection ─────────────────────────────────────────────────────────


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


# ── Context builder ────────────────────────────────────────────────────────


def build_performance_context() -> dict[str, str]:
    """Build a context dict for AffordancePipeline.select().

    Fast path: reads ``/dev/shm/hapax-audio/performance-context.json``
    when it exists and is fresh (<60s). Falls back to impingement
    scanning otherwise.

    Returns a dict with a single key ``audio_performance_mode`` set to
    the current mode. The pipeline's context_boost mechanism uses this
    to modulate recruitment scores for capabilities that have learned
    associations with specific modes.
    """
    ctx = _try_read_shm_snapshot()
    if ctx is not None:
        return {"audio_performance_mode": ctx.mode}
    mode = read_audio_performance_mode()
    return {"audio_performance_mode": mode}


def build_performance_context_full() -> AudioPerformanceContext:
    """Build the full Pydantic context model.

    Prefer the SHM snapshot (high confidence). Fall back to
    impingement scanning (lower confidence).
    """
    ctx = _try_read_shm_snapshot()
    if ctx is not None:
        return ctx

    mode = read_audio_performance_mode()
    return AudioPerformanceContext(
        mode=mode,
        confidence=0.6,
        recruitment_scale=_MODE_RECRUITMENT_SCALE.get(mode, 1.0),
    )


def _try_read_shm_snapshot() -> AudioPerformanceContext | None:
    """Attempt to read the pre-computed SHM performance context snapshot."""
    try:
        if not PERFORMANCE_CONTEXT_PATH.exists():
            return None
        raw = json.loads(PERFORMANCE_CONTEXT_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        # Staleness check
        ts = raw.get("timestamp", 0)
        if time.time() - ts > _MAX_AGE_S:
            return None
        mode = raw.get("mode", "idle")
        if mode not in ("active_performance", "speaking", "passive_music", "idle"):
            mode = "idle"
        confidence = float(raw.get("confidence", 0.9))
        recruitment_scale = float(
            raw.get("recruitment_scale", _MODE_RECRUITMENT_SCALE.get(mode, 1.0))
        )
        return AudioPerformanceContext(
            mode=mode,
            confidence=min(1.0, max(0.0, confidence)),
            recruitment_scale=min(2.0, max(0.0, recruitment_scale)),
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None
