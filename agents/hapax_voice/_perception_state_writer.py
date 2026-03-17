"""Write perception state to disk for external consumers (e.g. studio compositor).

Atomic write-then-rename to ~/.cache/hapax-voice/perception-state.json each
perception tick. External readers can poll this file without coordination.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.hapax_voice.consent_state import ConsentStateTracker
    from agents.hapax_voice.conversation_pipeline import ConversationPipeline
    from agents.hapax_voice.perception import PerceptionEngine
    from agents.hapax_voice.session import VoiceLifecycle
    from shared.governance.consent import ConsentRegistry

log = logging.getLogger(__name__)

PERCEPTION_STATE_DIR = Path.home() / ".cache" / "hapax-voice"
PERCEPTION_STATE_FILE = PERCEPTION_STATE_DIR / "perception-state.json"

# ── Supplementary content ring buffer ─────────────────────────────────────

_MAX_CONTENT_ITEMS = 5
_CONTENT_TTL_S = 60.0
_supplementary_content: list[dict[str, Any]] = []


def push_supplementary_content(
    content_type: str,
    title: str,
    body: str = "",
    image_path: str = "",
) -> None:
    """Push a supplementary content item from tool execution.

    Called by tool handlers during voice conversation to surface results
    visually on the Hapax Corpora canvas.
    """
    item = {
        "content_type": content_type,
        "title": title,
        "body": body[:200],
        "image_path": image_path,
        "timestamp": time.time(),
    }
    _supplementary_content.append(item)
    # Trim to max
    while len(_supplementary_content) > _MAX_CONTENT_ITEMS:
        _supplementary_content.pop(0)


def _get_live_content() -> list[dict[str, Any]]:
    """Return non-expired supplementary content items."""
    now = time.time()
    live = [c for c in _supplementary_content if now - c["timestamp"] < _CONTENT_TTL_S]
    # Prune expired from the source list too
    _supplementary_content[:] = live
    return live


# ── Voice session snapshot ────────────────────────────────────────────────


def _snapshot_voice_session(
    session: VoiceLifecycle | None,
    pipeline: ConversationPipeline | None,
) -> dict[str, Any]:
    """Build voice_session block from daemon state."""
    if session is None or not session.is_active:
        return {"active": False}

    # Determine pipeline phase
    state = "listening"
    active_tool: str | None = None
    barge_in = False
    last_utterance = ""
    last_response = ""
    turn_count = 0

    if pipeline is not None and pipeline.is_active:
        state = pipeline.state.value  # idle/listening/transcribing/thinking/speaking
        turn_count = pipeline.turn_count
        barge_in = bool(pipeline.buffer and pipeline.buffer.barge_in_detected)

        # Extract last utterance and response from message history
        for msg in reversed(pipeline.messages):
            if msg["role"] == "user" and not last_utterance:
                last_utterance = str(msg.get("content", ""))[:80]
            elif msg["role"] == "assistant" and not last_response:
                content = msg.get("content") or ""
                last_response = str(content)[:80]
            if last_utterance and last_response:
                break

        # Check for active tool execution
        for msg in reversed(pipeline.messages):
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                calls = msg["tool_calls"]
                if calls:
                    last_call = calls[-1]
                    fn = last_call.get("function", {})
                    active_tool = fn.get("name")
                break

    return {
        "active": True,
        "state": state,
        "turn_count": turn_count,
        "last_utterance": last_utterance,
        "last_response": last_response,
        "active_tool": active_tool,
        "barge_in": barge_in,
    }


# ── Perception confidence (WS2) ──────────────────────────────────────────


def _compute_aggregate_confidence(perception: PerceptionEngine) -> float:
    """Compute aggregate confidence from registered backend availability.

    Returns 1.0 when all backends are contributing fresh data,
    lower when backends are missing or stale. Uses getattr for
    backward compat with perception engines that lack the method.
    """
    try:
        backends = perception.registered_backends
        if not isinstance(backends, dict) or not backends:
            return 0.5  # no backends or not a dict
        available_count = sum(
            1 for b in backends.values() if getattr(b, "available", lambda: True)()
        )
        return round(available_count / len(backends), 3)
    except Exception:
        return 1.0


# ── Main writer ───────────────────────────────────────────────────────────


def write_perception_state(
    perception: PerceptionEngine,
    consent_registry: ConsentRegistry,
    consent_tracker: ConsentStateTracker | None = None,
    session: VoiceLifecycle | None = None,
    pipeline: ConversationPipeline | None = None,
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

    # Biometric data from watch backend
    heart_rate = int(_bval("heart_rate_bpm", 0))
    stress_elevated = bool(_bval("stress_elevated", False))
    physiological_load = float(_bval("physiological_load", 0.0))
    sleep_quality = float(_bval("sleep_quality", 1.0))
    watch_activity = str(_bval("watch_activity_state", "unknown"))

    state: dict[str, Any] = {
        "production_activity": str(_bval("production_activity", "")),
        "music_genre": str(_bval("music_genre", "")),
        "flow_state": flow_state,
        "flow_score": flow_score,
        "emotion_valence": float(_bval("emotion_valence", 0.0)),
        "emotion_arousal": float(_bval("emotion_arousal", 0.0)),
        "audio_energy_rms": float(_bval("audio_energy_rms", 0.0)),
        "active_contracts": active_contracts,
        "persistence_allowed": consent_tracker.persistence_allowed if consent_tracker else True,
        "guest_present": consent_tracker.phase.value != "no_guest" if consent_tracker else False,
        "consent_phase": consent_tracker.phase.value if consent_tracker else "no_guest",
        # Biometrics (Batch E)
        "heart_rate_bpm": heart_rate,
        "stress_elevated": stress_elevated,
        "physiological_load": physiological_load,
        "sleep_quality": sleep_quality,
        "watch_activity_state": watch_activity,
        # Voice session (Batch A)
        "voice_session": _snapshot_voice_session(session, pipeline),
        # Supplementary content (Batch B)
        "voice_content": _get_live_content(),
        # WS2: aggregate perception confidence
        "aggregate_confidence": _compute_aggregate_confidence(perception),
        "timestamp": time.time(),
    }

    # Push to ring buffer for temporal depth (WS1)
    _push_to_ring(state)

    try:
        PERCEPTION_STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PERCEPTION_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.rename(PERCEPTION_STATE_FILE)
    except OSError:
        log.debug("Failed to write perception state", exc_info=True)


# ── Perception Ring Buffer (WS1) ────────────────────────────────────────────

_perception_ring: Any = None  # Lazy init to avoid import cycles


def _push_to_ring(state: dict[str, Any]) -> None:
    """Push snapshot to the shared perception ring buffer."""
    global _perception_ring
    if _perception_ring is None:
        from agents.hapax_voice.perception_ring import PerceptionRing

        _perception_ring = PerceptionRing()
    snapshot = {**state, "ts": state.get("timestamp", time.time())}
    _perception_ring.push(snapshot)


def get_perception_ring() -> Any:
    """Return the global perception ring (or None if not yet initialized)."""
    return _perception_ring
