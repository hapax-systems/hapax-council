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

    # Routing info from last utterance
    routing_tier = ""
    routing_reason = ""
    routing_activation = 0.0
    if pipeline is not None:
        routing_tier = getattr(pipeline, "_turn_model_tier", "")
        # Get last routing decision from salience router
        router = getattr(pipeline, "_salience_router", None)
        if router is not None:
            breakdown = getattr(router, "last_breakdown", None)
            if breakdown is not None:
                routing_reason = getattr(breakdown, "reason", "")
                routing_activation = round(getattr(breakdown, "final_activation", 0.0), 3)

    return {
        "active": True,
        "state": state,
        "turn_count": turn_count,
        "last_utterance": last_utterance,
        "last_response": last_response,
        "active_tool": active_tool,
        "barge_in": barge_in,
        "routing_tier": routing_tier,
        "routing_reason": routing_reason,
        "routing_activation": routing_activation,
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


# ── Scene inventory helper ────────────────────────────────────────────────


def _parse_scene_inventory(raw: object) -> dict[str, Any]:
    """Parse scene inventory from behavior value (JSON string or dict)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


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
        # Vision classification
        "detected_objects": str(_bval("detected_objects", "[]")),
        "person_count": int(_bval("person_count", 0) or 0),
        "pose_summary": str(_bval("pose_summary", "unknown")),
        "scene_objects": str(_bval("scene_objects", "")),
        "scene_type": str(_bval("scene_type", "unknown")),
        "gaze_direction": str(_bval("gaze_direction", "unknown")),
        "hand_gesture": str(_bval("hand_gesture", "none")),
        "posture": str(_bval("posture", "unknown")),
        "ambient_brightness": float(_bval("ambient_brightness", 0.0) or 0),
        "color_temperature": str(_bval("color_temperature", "unknown")),
        "top_emotion": str(_bval("top_emotion", "neutral")),
        "face_count": int(_bval("face_count", 0) or 0),
        "operator_present": bool(_bval("operator_present", False))
        or int(_bval("person_count", 0) or 0) > 0,
        "operator_confirmed": bool(_bval("operator_confirmed", False)),
        "activity_mode": str(_bval("activity_mode", "unknown")),
        "interruptibility_score": float(_bval("interruptibility_score", 0.9) or 0.9),
        "vad_confidence": float(_bval("vad_confidence", 0.0) or 0),
        "presence_score": float(_bval("presence_score", 0.0) or 0),
        "nearest_person_distance": str(_bval("nearest_person_distance", "none")),
        "detected_action": str(_bval("detected_action", "unknown")),
        "audio_scene": str(_bval("audio_scene", "silence")),
        "scene_state_clip": str(_bval("scene_state_clip", "")),
        "usb_devices": str(_bval("usb_devices", "")),
        "network_devices": str(_bval("network_devices", "")),
        "active_contracts": active_contracts,
        "persistence_allowed": consent_tracker.persistence_allowed if consent_tracker else True,
        "guest_present": consent_tracker.phase.value != "no_guest" if consent_tracker else False,
        "consent_phase": consent_tracker.phase.value if consent_tracker else "no_guest",
        # Bayesian presence
        "presence_state": str(_bval("presence_state", "")),
        "presence_probability": float(_bval("presence_probability", 0.0) or 0.0),
        "guest_count": int(_bval("guest_count", 0) or 0),
        # Biometrics (Batch E)
        "heart_rate_bpm": heart_rate,
        "stress_elevated": stress_elevated,
        "physiological_load": physiological_load,
        "sleep_quality": sleep_quality,
        "watch_activity_state": watch_activity,
        # Phone media (AVRCP via Bluetooth)
        "phone_media_playing": bool(_bval("phone_media_playing", False)),
        "phone_media_title": str(_bval("phone_media_title", "")),
        "phone_media_artist": str(_bval("phone_media_artist", "")),
        "phone_sms_unread": int(_bval("phone_sms_unread", 0) or 0),
        "phone_sms_latest_sender": str(_bval("phone_sms_latest_sender", "")),
        "phone_sms_latest_text": str(_bval("phone_sms_latest_text", "")),
        "phone_call_active": bool(_bval("phone_call_active", False)),
        "phone_call_incoming": bool(_bval("phone_call_incoming", False)),
        "phone_call_number": str(_bval("phone_call_number", "")),
        # KDE Connect phone awareness
        "phone_battery_pct": int(_bval("phone_battery_pct", 0) or 0),
        "phone_battery_charging": bool(_bval("phone_battery_charging", False)),
        "phone_network_type": str(_bval("phone_network_type", "")),
        "phone_notification_count": int(_bval("phone_notification_count", 0) or 0),
        "phone_media_app": str(_bval("phone_media_app", "")),
        "phone_kde_connected": bool(_bval("phone_kde_connected", False)),
        # Scene inventory (persistent object tracking)
        "scene_inventory": _parse_scene_inventory(_bval("scene_inventory", "{}")),
        # Cognitive loop (turn phase + temperature)
        "turn_phase": str(_bval("turn_phase", "")),
        "cognitive_readiness": float(_bval("cognitive_readiness", 0.0) or 0.0),
        "conversation_temperature": float(_bval("conversation_temperature", 0.0) or 0.0),
        "predicted_tier": str(_bval("predicted_tier", "")),
        # Voice session (Batch A)
        "voice_session": _snapshot_voice_session(session, pipeline),
        # Supplementary content (Batch B)
        "voice_content": _get_live_content(),
        # WS2: aggregate perception confidence
        "aggregate_confidence": _compute_aggregate_confidence(perception),
        "timestamp": time.time(),
    }

    # Consent curtailment: when guest is present without consent,
    # redact person-adjacent fields from the persisted snapshot.
    # The compositor still gets non-person data (flow state, activity, etc).
    if not (consent_tracker.persistence_allowed if consent_tracker else True):
        _PERSON_ADJACENT_KEYS = {
            "voice_session",  # contains last_utterance, last_response
            "top_emotion",
            "gaze_direction",
            "hand_gesture",
            "posture",
            "pose_summary",
        }
        for key in _PERSON_ADJACENT_KEYS:
            if key in state:
                state[key] = "[curtailed]" if isinstance(state[key], str) else {}
        state["consent_curtailed"] = True

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
