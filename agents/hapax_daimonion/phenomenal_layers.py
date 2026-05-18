"""Layer renderers for phenomenal context.

Six progressive-fidelity layers, each rendering one aspect of the
operator's current experiential situation as natural language orientation.
"""

from __future__ import annotations

import time

from agents.hapax_daimonion.phenomenal_parsing import APPERCEPTION_STALE_S, STIMMUNG_STALE_S

_EMPTY = ""
_UNKNOWN_TERMS = {"unknown", "none", "n/a", ""}
_AUDIO_CONTEXT_STALE_S = 60.0
_SEGMENT_CONTEXT_STALE_S = 180.0


def render_stimmung(data: dict | None) -> str:
    """Layer 1: System attunement. Empty when nominal (the common case)."""
    if data is None:
        return _EMPTY
    try:
        if (time.time() - data.get("timestamp", 0)) > STIMMUNG_STALE_S:
            return _EMPTY
        stance = data.get("overall_stance", "nominal")
        if stance == "nominal":
            return _EMPTY
        if stance == "cautious":
            return "System cautious — conserve where possible."
        if stance == "degraded":
            return "System degraded — keep responses brief, avoid heavy processing."
        if stance == "critical":
            return "System critical — minimal responses only, essential information."
        return _EMPTY
    except Exception:
        return _EMPTY


def render_situation(temporal: dict | None) -> str:
    """Layer 2: Coupled situation — operator + environment in one breath."""
    if temporal is None:
        return _EMPTY

    impression = temporal.get("impression", {})

    hour = time.localtime().tm_hour
    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 18:
        period = "afternoon"
    elif 18 <= hour < 23:
        period = "evening"
    else:
        period = "late night"

    activity = impression.get("activity", "")
    flow = impression.get("flow_state", "idle")
    presence = impression.get("presence", "")

    if presence == "away":
        return f"{period.capitalize()}, operator away."

    if activity and activity.lower() not in _UNKNOWN_TERMS and activity != "idle":
        if flow == "active":
            return f"{period.capitalize()}, deep {activity}."
        if flow == "warming":
            return f"{period.capitalize()}, settling into {activity}."
        return f"{period.capitalize()}, {activity}."

    return f"{period.capitalize()}, idle."


def _fresh_enough(data: dict | None, *, max_age_s: float, timestamp_key: str = "timestamp") -> bool:
    if data is None:
        return False
    timestamp = data.get(timestamp_key)
    if isinstance(timestamp, (int, float)):
        return (time.time() - float(timestamp)) <= max_age_s
    return True


def _dim_value(data: dict | None, name: str) -> float | None:
    if not _fresh_enough(data, max_age_s=STIMMUNG_STALE_S):
        return None
    raw = data.get(name, {}) if data else {}
    if not isinstance(raw, dict):
        return None
    value = raw.get("value")
    if not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def _readable_audio_scene(value: object) -> str:
    scene = str(value or "").strip().lower()
    return {
        "speech_over_music": "speech over music",
        "speech": "speech",
        "music": "music",
        "ambient": "ambient audio",
        "silence": "",
        "capture_failed": "",
    }.get(scene, scene.replace("_", " ") if scene not in _UNKNOWN_TERMS else "")


def _audio_activity_label(
    *,
    perception: dict | None,
    audio: dict | None,
    mix_value: float | None,
) -> str:
    perception = perception if _fresh_enough(perception, max_age_s=_AUDIO_CONTEXT_STALE_S) else {}
    audio = audio if audio is not None else {}

    voice_session = perception.get("voice_session", {}) if isinstance(perception, dict) else {}
    if isinstance(voice_session, dict) and voice_session.get("active"):
        voice_state = str(voice_session.get("state", "")).lower()
        if voice_state == "speaking":
            return "system voice speaking"
        if voice_state in {"listening", "transcribing"}:
            return "operator speech channel open"

    scene = _readable_audio_scene(audio.get("scene") if isinstance(audio, dict) else "")
    if scene in {"speech", "speech over music"}:
        return scene

    production = str(perception.get("production_activity", "")).lower()
    desk_activity = str(perception.get("desk_activity", "")).lower()
    midi_transport = str(perception.get("midi_clock_transport", "")).lower()
    mixer_active = bool(perception.get("mixer_active", False))
    mixer_energy = perception.get("mixer_energy", 0.0)
    phone_media = bool(perception.get("phone_media_playing", False))

    if (
        production == "production"
        or desk_activity in {"scratching", "drumming"}
        or midi_transport in {"playing", "play", "running"}
        or mixer_active
    ):
        return "active performance"
    if scene:
        return scene
    if phone_media or (isinstance(mixer_energy, (int, float)) and float(mixer_energy) > 0.01):
        return "music in the room"
    if production == "conversation":
        return "conversation"

    if mix_value is not None:
        if mix_value >= 0.75:
            return "occupied audio field"
        if mix_value >= 0.35:
            return "present audio bed"
        if mix_value >= 0.1:
            return "light room tone"
    return ""


def _audio_density_label(value: float | None) -> str:
    if value is None:
        return ""
    if value >= 0.75:
        return "dense"
    if value >= 0.45:
        return "present"
    if value >= 0.15:
        return "light"
    return "quiet"


def _segment_binding(segment: dict | None) -> str:
    if not _fresh_enough(
        segment,
        max_age_s=_SEGMENT_CONTEXT_STALE_S,
        timestamp_key="updated_at",
    ):
        return ""
    programme_id = str(segment.get("programme_id", "")).strip() if segment else ""
    if not programme_id:
        return ""

    beat_index_raw = segment.get("current_beat_index", 0)
    total_raw = segment.get("total_beats", 0)
    try:
        beat_index = int(beat_index_raw) + 1
        total_beats = int(total_raw)
    except (TypeError, ValueError):
        beat_index = 1
        total_beats = 0

    topic = str(segment.get("topic", "") or "").strip()
    beat = str(segment.get("current_beat_text", "") or "").strip()
    subject = beat or topic
    if len(subject) > 90:
        subject = subject[:87].rstrip() + "..."

    if total_beats > 0:
        binding = f"bound to segment beat {beat_index}/{total_beats}"
    else:
        binding = "bound to the active segment"
    if subject:
        binding += f", {subject}"
    return binding


def render_audio_context(
    stimmung: dict | None,
    perception: dict | None,
    audio: dict | None,
    segment: dict | None,
) -> str:
    """Layer 2a: Audio activity and its active segment binding."""
    mix_value = _dim_value(stimmung, "audio_content_mix")
    activity = _audio_activity_label(perception=perception, audio=audio, mix_value=mix_value)
    density = _audio_density_label(mix_value)
    binding = _segment_binding(segment)

    if not activity and not binding:
        return _EMPTY

    if activity and density:
        head = f"Audio field {density} with {activity}"
    elif activity:
        head = f"Audio field with {activity}"
    else:
        head = "Audio field quiet"

    if binding:
        return f"{head}; {binding}."
    return f"{head}."


def render_impression(temporal: dict | None) -> str:
    """Layer 3: Present moment + nearest horizon as a coupled phrase.

    Renders metrics as a natural situation description, not decomposed facts.
    """
    if temporal is None:
        return _EMPTY

    impression = temporal.get("impression", {})
    protention = temporal.get("protention", [])

    parts: list[str] = []

    flow_score = impression.get("flow_score", 0.0)
    hr = impression.get("heart_rate", 0)
    genre = impression.get("music_genre", "")
    pp = impression.get("presence_probability")

    # Physiological + music as felt environment
    env_parts: list[str] = []
    if isinstance(hr, int) and hr > 0:
        if hr > 90:
            env_parts.append("elevated heart rate")
        elif hr < 60:
            env_parts.append("resting heart rate")
    if genre and genre.lower() not in _UNKNOWN_TERMS:
        env_parts.append(f"{genre} playing")
    if env_parts:
        parts.append(", ".join(env_parts))

    # Flow as felt momentum
    if isinstance(flow_score, (int, float)) and flow_score > 0:
        if flow_score >= 0.7:
            parts.append("strong flow")
        elif flow_score >= 0.4:
            parts.append("building momentum")

    # Presence uncertainty
    if pp is not None and isinstance(pp, (int, float)):
        if pp < 0.3:
            parts.append("likely away")
        elif pp < 0.7:
            parts.append("uncertain presence")

    # Nearest protention as direction
    if protention:
        best = max(protention, key=lambda p: p.get("confidence", 0))
        conf = best.get("confidence", 0)
        state = best.get("predicted_state", "")
        if conf >= 0.5 and state:
            readable = state.replace("_", " ")
            parts.append(f"→ {readable}")

    if not parts:
        return _EMPTY
    return ", ".join(parts) + "."


def render_surprise(temporal: dict | None) -> str:
    """Layer 4: Prediction errors — the most phenomenologically interesting signal."""
    if temporal is None:
        return _EMPTY

    surprises = temporal.get("surprises", [])
    if not surprises:
        return _EMPTY

    notable = [s for s in surprises if s.get("surprise", 0) > 0.3]
    if not notable:
        return _EMPTY

    parts: list[str] = []
    for s in notable[:2]:
        observed = s.get("observed", "")
        expected = s.get("expected", "")
        field = s.get("field", "")
        if observed and expected:
            parts.append(f"unexpected {field}: {observed} (predicted {expected})")
        elif observed:
            parts.append(f"unexpected: {observed}")

    if not parts:
        return _EMPTY
    return "Surprise: " + "; ".join(parts) + "."


def _qualitative_age(age_s: float) -> str:
    """Convert numeric age to qualitative temporal fading."""
    if age_s < 10:
        return "just now"
    if age_s < 30:
        return "moments ago"
    if age_s < 60:
        return "recently"
    if age_s < 180:
        return "a while back"
    return "earlier"


def render_temporal_depth(temporal: dict | None) -> str:
    """Layer 5: Retention (fading past) + protention details.

    Retention uses qualitative fading rather than numeric timestamps,
    consistent with Husserlian retention as gradually loosening grip.
    Entries with "unknown" summaries are filtered (absence = signal).
    """
    if temporal is None:
        return _EMPTY

    parts: list[str] = []

    retention = temporal.get("retention", [])
    if retention:
        ret_parts: list[str] = []
        for r in retention:
            summary = r.get("summary", "")
            if summary.lower() in _UNKNOWN_TERMS:
                continue
            age = r.get("age_s", 0)
            age_label = _qualitative_age(age)
            note = f"{age_label}: {summary}"
            presence = r.get("presence", "")
            if presence and presence != "present":
                note += f" ({presence})"
            ret_parts.append(note)
        if ret_parts:
            parts.append("Was: " + " → ".join(ret_parts))

    protention = temporal.get("protention", [])
    if len(protention) > 1:
        preds = []
        for p in protention[:3]:
            state = p.get("predicted_state", "").replace("_", " ")
            conf = p.get("confidence", 0)
            if state and conf >= 0.3:
                preds.append(f"{state} ({conf:.0%})")
        if preds:
            parts.append("Next: " + ", ".join(preds))

    return " ".join(parts) if parts else _EMPTY


def render_self_state(data: dict | None) -> str:
    """Layer 6: Apperceptive self-awareness.

    Format follows ACT cognitive defusion: "I notice..." not "I am...".
    """
    if data is None:
        return _EMPTY
    try:
        if (time.time() - data.get("timestamp", 0)) > APPERCEPTION_STALE_S:
            return _EMPTY
    except Exception:
        return _EMPTY

    model = data.get("self_model", {})
    dimensions = model.get("dimensions", {})
    coherence = model.get("coherence", 0.7)
    reflections = model.get("recent_reflections", [])
    pending = data.get("pending_actions", [])

    parts: list[str] = []

    if coherence < 0.4:
        parts.append("Self-coherence low — hedge all observations, avoid confident claims.")
    elif coherence < 0.6:
        parts.append("Self-coherence settling — hedge where uncertain.")

    low_conf = [name for name, d in dimensions.items() if d.get("confidence", 0.5) < 0.35]
    if low_conf:
        domains = ", ".join(d.replace("_", " ") for d in low_conf[:3])
        parts.append(f"Uncertain about: {domains}.")

    if reflections:
        parts.append(reflections[-1])

    if pending:
        parts.append(pending[0])

    if not parts:
        return _EMPTY
    return " ".join(parts)
