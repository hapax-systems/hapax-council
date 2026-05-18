"""Audio performance context for affordance recruitment boost.

Reads recent audio engine impingements from the DMN bus plus the latest
perception snapshot to determine the operator's current audio performance
mode and turntable intent. Used as context input to AffordancePipeline.select()
so recruitment scores are modulated by what the operator is actively doing.

Performance modes (ordered by activity level):
- idle: no audio engines active
- passive_music: music playing but no operator involvement (streaming)
- active_performance: vinyl spinning OR mixer actively driven
- speaking: operator voice detected (highest priority, dampens music fx)

Vinyl performance intents:
- idle: no current vinyl-spinning signal
- background_playback: vinyl spinning without active hand/contact cues
- scratching: turntable hand/contact cues indicate active DJ performance
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

IMPINGEMENTS_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
VOICE_STATE_PATH = Path("/dev/shm/hapax-compositor/voice-state.json")
PERCEPTION_STATE_PATH = Path.home() / ".cache/hapax-daimonion/perception-state.json"
_MAX_AGE_S = 60.0

AudioPerformanceMode = Literal["idle", "passive_music", "active_performance", "speaking"]
VinylPerformanceIntent = Literal["idle", "background_playback", "scratching"]


@dataclass(frozen=True)
class AudioContextSignal:
    """Current audio-performance context for recruitment and response policy."""

    performance_mode: AudioPerformanceMode
    vinyl_performance_intent: VinylPerformanceIntent = "idle"
    evidence: tuple[str, ...] = ()
    timestamp: float = field(default_factory=time.time)

    def to_context_dict(self) -> dict[str, str]:
        """Render string cues for AffordancePipeline context associations."""
        return {
            "audio_performance_mode": self.performance_mode,
            "vinyl_performance_intent": self.vinyl_performance_intent,
        }


def read_audio_performance_mode() -> str:
    """Return the current audio performance mode string."""
    return read_audio_context_signal().performance_mode


def read_audio_context_signal() -> AudioContextSignal:
    """Return the current audio context signal, including vinyl intent."""
    now = time.time()

    voice_active = _read_voice_active()
    states = _read_recent_audio_states(now)
    perception = _read_perception_state(now)

    music_active = states.get("audio.music_playing") == "ASSERTED"
    vinyl_active = states.get("audio.vinyl_spinning") == "ASSERTED"
    mixer_active = states.get("audio.mixer_input") == "ACTIVE"
    vinyl_intent, vinyl_evidence = classify_vinyl_performance_intent(
        vinyl_spinning=vinyl_active,
        perception=perception,
    )

    evidence = list(vinyl_evidence)
    if voice_active:
        return AudioContextSignal(
            performance_mode="speaking",
            vinyl_performance_intent=vinyl_intent,
            evidence=tuple(["voice_state.operator_speech_active", *evidence]),
            timestamp=now,
        )

    if vinyl_active or mixer_active or vinyl_intent == "scratching":
        if vinyl_active:
            evidence.append("audio.vinyl_spinning=ASSERTED")
        if mixer_active:
            evidence.append("audio.mixer_input=ACTIVE")
        return AudioContextSignal(
            performance_mode="active_performance",
            vinyl_performance_intent=vinyl_intent,
            evidence=tuple(_dedupe(evidence)),
            timestamp=now,
        )
    if music_active:
        return AudioContextSignal(
            performance_mode="passive_music",
            vinyl_performance_intent=vinyl_intent,
            evidence=tuple(["audio.music_playing=ASSERTED", *evidence]),
            timestamp=now,
        )
    return AudioContextSignal(
        performance_mode="idle",
        vinyl_performance_intent=vinyl_intent,
        evidence=tuple(evidence),
        timestamp=now,
    )


def classify_vinyl_performance_intent(
    *,
    vinyl_spinning: bool,
    perception: Mapping[str, Any] | None = None,
) -> tuple[VinylPerformanceIntent, tuple[str, ...]]:
    """Classify turntable intent from vinyl state plus cross-modal cues.

    Scratching wins when contact-mic/IR/vision cues indicate active hand
    performance. Otherwise an asserted vinyl-spinning engine state is treated
    as passive background playback. With neither, the turntable is idle.
    """
    cues = _scratch_cues(perception or {})
    if cues:
        return "scratching", tuple(cues)
    if vinyl_spinning:
        return "background_playback", ("audio.vinyl_spinning=ASSERTED",)
    return "idle", ()


def _read_recent_audio_states(now: float) -> dict[str, str]:
    states: dict[str, str] = {}
    watched = {"audio.music_playing", "audio.vinyl_spinning", "audio.mixer_input"}
    try:
        if not IMPINGEMENTS_PATH.exists():
            return states
        lines = IMPINGEMENTS_PATH.read_text(encoding="utf-8").strip().splitlines()
        for line in reversed(lines[-50:]):
            try:
                imp = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = imp.get("timestamp", 0)
            if not isinstance(ts, (int, float)):
                continue
            if now - float(ts) > _MAX_AGE_S:
                break
            source = str(imp.get("source", ""))
            if source not in watched or source in states:
                continue
            content = imp.get("content", {})
            if not isinstance(content, dict):
                continue
            state = content.get("to_state", content.get("state", ""))
            states[source] = str(state).strip().upper()
            if len(states) == len(watched):
                break
    except (OSError, ValueError):
        log.debug("Failed to read impingements for performance mode", exc_info=True)
    return states


def _read_perception_state(now: float) -> dict[str, Any]:
    try:
        if not PERCEPTION_STATE_PATH.exists():
            return {}
        if now - PERCEPTION_STATE_PATH.stat().st_mtime > _MAX_AGE_S:
            return {}
        data = json.loads(PERCEPTION_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _scratch_cues(perception: Mapping[str, Any]) -> list[str]:
    cues: list[str] = []
    contact = perception.get("contact_mic")
    contact_map = contact if isinstance(contact, Mapping) else {}

    fused_activity = _normalized(
        perception.get("fused_activity") or contact_map.get("fused_activity")
    )
    desk_activity = _normalized(perception.get("desk_activity") or contact_map.get("desk_activity"))
    detected_action = _normalized(perception.get("detected_action"))
    if fused_activity in {"scratch", "scratching"}:
        cues.append("contact_mic_ir.fused_activity=scratching")
    if desk_activity in {"scratch", "scratching"}:
        cues.append("contact_mic.desk_activity=scratching")
    if detected_action in {"scratch", "scratching"}:
        cues.append("vision.detected_action=scratching")

    zone_turntable = _turntable_hand_zone(perception)
    hand_activity = _normalized(perception.get("ir_hand_activity"))
    if zone_turntable and hand_activity in {"scratch", "scratching", "sliding", "tapping"}:
        cues.append(f"vision.turntable_hand_activity={hand_activity}")

    cross_modal = _cross_modal_activity(perception, contact_map)
    if cross_modal == "scratching":
        cues.append("contact_mic_ir.classifier=scratching")

    if zone_turntable and _contact_mic_non_idle(perception, contact_map):
        cues.append("contact_mic_ir.turntable_non_idle")

    return _dedupe(cues)


def _cross_modal_activity(
    perception: Mapping[str, Any],
    contact: Mapping[str, Any],
) -> str:
    energy = _floatish(perception.get("desk_energy", contact.get("desk_energy")))
    onset_rate = _floatish(perception.get("desk_onset_rate", contact.get("desk_onset_rate")))
    centroid = _floatish(
        perception.get("desk_spectral_centroid", contact.get("desk_spectral_centroid"))
    )
    autocorr = _floatish(perception.get("desk_autocorr_peak", contact.get("desk_autocorr_peak")))
    if energy is None or onset_rate is None or centroid is None:
        return ""
    try:
        from agents.hapax_daimonion.backends.contact_mic_ir import _classify_activity_with_ir

        return _classify_activity_with_ir(
            energy=energy,
            onset_rate=onset_rate,
            centroid=centroid,
            autocorr_peak=autocorr or 0.0,
            ir_hand_zone=_normalized(perception.get("ir_hand_zone")),
            ir_hand_activity=_normalized(perception.get("ir_hand_activity")),
        )
    except Exception:
        log.debug("contact_mic_ir classifier failed", exc_info=True)
        return ""


def _turntable_hand_zone(perception: Mapping[str, Any]) -> bool:
    zone = _normalized(perception.get("ir_hand_zone"))
    if "turntable" in zone:
        return True
    zones = perception.get("overhead_hand_zones")
    if isinstance(zones, str):
        return "turntable" in _normalized(zones)
    if isinstance(zones, list):
        return any("turntable" in _normalized(item) for item in zones)
    return False


def _contact_mic_non_idle(perception: Mapping[str, Any], contact: Mapping[str, Any]) -> bool:
    activity = _normalized(perception.get("desk_activity") or contact.get("desk_activity"))
    if activity and activity not in {"idle", "unknown", "none"}:
        return True
    energy = _floatish(perception.get("desk_energy", contact.get("desk_energy")))
    onset_rate = _floatish(perception.get("desk_onset_rate", contact.get("desk_onset_rate")))
    return bool(
        (energy is not None and energy >= 0.1) or (onset_rate is not None and onset_rate >= 0.5)
    )


def _floatish(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


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

    The pipeline's context_boost mechanism uses these string cues to modulate
    recruitment scores for capabilities that have learned associations with
    specific audio modes and vinyl-performance intents.
    """
    return read_audio_context_signal().to_context_dict()


__all__ = [
    "AudioContextSignal",
    "AudioPerformanceMode",
    "VinylPerformanceIntent",
    "build_performance_context",
    "classify_vinyl_performance_intent",
    "read_audio_context_signal",
    "read_audio_performance_mode",
]
