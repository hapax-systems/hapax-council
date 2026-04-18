"""PerceptualField — structured environmental input for the director.

Before this module, the director's environmental context was collapsed into
a single stimmung-prose string (`phenomenal_context.render(tier="FAST")`).
Every classifier/detector in the system (Pi NoIR YOLOv8n, studio RGB
YOLO, SCRFD operator match, SigLIP2 scenes, cross-modal `detected_action`,
`overhead_hand_zones`, CLAP genre, contact mic DSP, MIDI clock, etc.) was
producing per-frame / per-tick structured signals — and none of them
reached the director.

This module exposes every existing signal as a first-class field in a
typed `PerceptualField` Pydantic model. The director's prompt serializes
`PerceptualField.model_dump_json(exclude_none=True)` inside a
`<perceptual_field>` block so the grounded LLM can ground moves in
specific perceptual evidence.

No new sensors are added. This is pure aggregation.

Epic: volitional grounded director (PR #1017, spec §3.2, §6 inventory).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.stimmung import Stance

log = logging.getLogger(__name__)

# ── Source paths (existing, not introduced by this module) ────────────────

_PERCEPTION_STATE = Path(os.path.expanduser("~/.cache/hapax-daimonion/perception-state.json"))
_STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
_ALBUM_STATE = Path("/dev/shm/hapax-compositor/album-state.json")
_CHAT_STATE = Path("/dev/shm/hapax-compositor/chat-state.json")
_CHAT_RECENT = Path("/dev/shm/hapax-compositor/chat-recent.json")
_STREAM_LIVE = Path("/dev/shm/hapax-compositor/stream-live")
_PRESENCE_STATE = Path("/dev/shm/hapax-daimonion/presence-state.json")
_WORKING_MODE = Path(os.path.expanduser("~/.cache/hapax/working-mode"))
_CONSENT_CONTRACTS_DIR = Path(os.path.expanduser("~/projects/hapax-council/axioms/contracts"))
_OBJECTIVES_DIR = Path(os.path.expanduser("~/Documents/Personal/30-areas/hapax-objectives"))


# ── Sub-fields ────────────────────────────────────────────────────────────


class ContactMicState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    desk_activity: str | None = None  # idle/typing/tapping/drumming/active
    desk_energy: float | None = None
    desk_onset_rate: float | None = None
    desk_spectral_centroid: float | None = None
    desk_tap_gesture: str | None = None
    fused_activity: str | None = None  # from contact_mic_ir cross-modal


class MidiState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    beat_position: float | None = None
    bar_position: float | None = None
    tempo: float | None = None
    transport_state: Literal["PLAYING", "STOPPED", "PAUSED"] | None = None


class StudioIngestionState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    music_genre: str | None = None
    production_activity: Literal["production", "conversation", "idle"] | None = None
    flow_state_score: float | None = None


class VadState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    operator_speech_active: bool | None = None


class AudioField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contact_mic: ContactMicState = Field(default_factory=ContactMicState)
    midi: MidiState = Field(default_factory=MidiState)
    studio_ingestion: StudioIngestionState = Field(default_factory=StudioIngestionState)
    vad: VadState = Field(default_factory=VadState)


class VisualField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    per_camera_scenes: dict[str, str] = Field(default_factory=dict)
    detected_action: str | None = None
    overhead_hand_zones: list[str] = Field(default_factory=list)
    operator_confirmed: bool | None = None
    top_emotion: str | None = None
    hand_gesture: str | None = None
    gaze_direction: str | None = None
    posture: str | None = None
    ambient_brightness: float | None = None
    color_temperature: float | None = None
    per_camera_person_count: dict[str, int] = Field(default_factory=dict)
    scene_type: str | None = None


class IrField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ir_hand_activity: float | None = None
    ir_hand_zone: str | None = None
    ir_gaze_zone: str | None = None
    ir_posture: str | None = None
    ir_heart_rate_bpm: int | None = None
    ir_heart_rate_confidence: float | None = None
    ir_brightness: float | None = None
    ir_person_count: int | None = None
    ir_screen_looking: bool | None = None
    ir_drowsiness_score: float | None = None


class AlbumField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artist: str | None = None
    title: str | None = None
    current_track: str | None = None
    year: int | None = None
    confidence: float | None = None


class ChatField(BaseModel):
    """Aggregated chat state. Interpersonal_transparency axiom: NO author
    names, NO message bodies. Only counts + tier aggregates."""

    model_config = ConfigDict(extra="ignore")

    tier_counts: dict[str, int] = Field(default_factory=dict)
    recent_message_count: int = 0
    unique_authors: int = 0


class ContextField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    working_mode: Literal["research", "rnd"] | None = None
    stream_mode: Literal["off", "private", "public", "public_research", "fortress"] | None = None
    stream_live: bool = False
    active_objective_ids: list[str] = Field(default_factory=list)
    time_of_day: str | None = None
    recent_reactions: list[str] = Field(default_factory=list)
    active_consent_contract_ids: list[str] = Field(default_factory=list)


class StimmungField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dimensions: dict[str, float] = Field(default_factory=dict)
    overall_stance: Stance | None = None


class PresenceField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state: Literal["PRESENT", "UNCERTAIN", "AWAY"] | None = None
    probability: float | None = None


class StreamHealthField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bitrate: float | None = None
    dropped_frames_pct: float | None = None
    encoding_lag_ms: float | None = None


class TendencyField(BaseModel):
    """Anticipatory signals — rates of change, not instantaneous values.

    S4 audit follow-up: the director only saw frozen instantaneous state
    (current beat position, current desk energy, current chat count), so
    moves landed after transitions rather than during them. Tendency
    fields let the LLM anticipate: ``desk_energy_rate > 0`` means
    operator is *warming up*; ``chat_heating_rate > 0.1/s`` means
    audience interest is *spiking*; ``beat_position_rate`` stays near
    tempo during playback but collapses to 0 when transport stops —
    catching stop/pause faster than a stale ``transport_state`` would.

    All rates in units-per-second. First read after module load returns
    None for every field (no prior sample); subsequent reads within
    ``_SAMPLE_TTL`` produce the diff. Samples older than TTL are
    discarded so a paused director doesn't read multi-minute-old rates.
    """

    model_config = ConfigDict(extra="ignore")

    beat_position_rate: float | None = None
    desk_energy_rate: float | None = None
    chat_heating_rate: float | None = None


class PerceptualField(BaseModel):
    """Unified structured perceptual input for the director."""

    model_config = ConfigDict(extra="ignore")

    audio: AudioField = Field(default_factory=AudioField)
    visual: VisualField = Field(default_factory=VisualField)
    ir: IrField = Field(default_factory=IrField)
    album: AlbumField = Field(default_factory=AlbumField)
    chat: ChatField = Field(default_factory=ChatField)
    context: ContextField = Field(default_factory=ContextField)
    stimmung: StimmungField = Field(default_factory=StimmungField)
    presence: PresenceField = Field(default_factory=PresenceField)
    stream_health: StreamHealthField = Field(default_factory=StreamHealthField)
    tendency: TendencyField = Field(default_factory=TendencyField)


# ── Reader ────────────────────────────────────────────────────────────────


def _safe_load_json(path: Path) -> dict | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("Failed to read %s", path, exc_info=True)
    return None


def _read_perception_state() -> dict:
    return _safe_load_json(_PERCEPTION_STATE) or {}


def _read_stimmung() -> tuple[dict, str | None]:
    data = _safe_load_json(_STIMMUNG_STATE) or {}
    stance = data.get("overall_stance")
    dims = data.get("dimensions") or {}
    # Stimmung may store dimensions as a dict of {name: {reading: float, ...}}
    # or {name: float}. Normalize to float.
    flat: dict[str, float] = {}
    for name, value in dims.items():
        if isinstance(value, (int, float)):
            flat[name] = float(value)
        elif isinstance(value, dict) and "reading" in value:
            try:
                flat[name] = float(value["reading"])
            except (TypeError, ValueError):
                pass
    return flat, stance


def _read_working_mode() -> str | None:
    try:
        if _WORKING_MODE.exists():
            return _WORKING_MODE.read_text(encoding="utf-8").strip() or None
    except Exception:
        pass
    return None


def _read_active_consent_contract_ids() -> list[str]:
    ids: list[str] = []
    try:
        if _CONSENT_CONTRACTS_DIR.exists():
            for p in _CONSENT_CONTRACTS_DIR.glob("*.yaml"):
                ids.append(p.stem)
    except Exception:
        pass
    return sorted(ids)


def _read_active_objective_ids() -> list[str]:
    """Objective markdown files under personal vault. Only return IDs (stem)."""
    ids: list[str] = []
    try:
        if _OBJECTIVES_DIR.exists():
            for p in _OBJECTIVES_DIR.glob("obj-*.md"):
                ids.append(p.stem)
    except Exception:
        pass
    return sorted(ids)


def _read_chat() -> ChatField:
    """Aggregate-only chat read. Strips author names and message bodies."""
    state = _safe_load_json(_CHAT_STATE) or {}
    recent = _safe_load_json(_CHAT_RECENT) or []
    unique_authors = 0
    recent_count = 0
    try:
        unique_authors = int(state.get("unique_authors", 0))
    except (TypeError, ValueError):
        pass
    try:
        recent_count = len(recent) if isinstance(recent, list) else 0
    except Exception:
        pass
    tier_counts = state.get("tier_counts") if isinstance(state.get("tier_counts"), dict) else {}
    return ChatField(
        tier_counts=tier_counts,
        recent_message_count=recent_count,
        unique_authors=unique_authors,
    )


def _read_stream_mode() -> str | None:
    """Stream mode source of truth: shared.stream_mode.read_mode()."""
    try:
        from shared.stream_mode import read_mode

        return read_mode()
    except Exception:
        return None


def _time_of_day(clock: float | None = None) -> str:
    from datetime import datetime

    now = datetime.now() if clock is None else datetime.fromtimestamp(clock)
    h = now.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


# S4: anticipation tendency state. Module-level so repeated reads can
# compute per-second rates without each caller threading history. Reset
# via ``reset_tendency_cache()`` in tests.
_SAMPLE_TTL_S = 10.0
_tendency_cache: dict[str, tuple[float, float]] = {}


def reset_tendency_cache() -> None:
    """Clear S4 tendency sample cache. Tests should call between assertions."""
    _tendency_cache.clear()


def _compute_rate(key: str, value: float | None, clock: float) -> float | None:
    """Update cache for ``key`` and return per-second rate since last sample.

    Returns None when: value missing, no prior sample, or prior sample
    older than ``_SAMPLE_TTL_S``. On success also updates the cache for
    the next call.
    """
    if value is None:
        return None
    prev = _tendency_cache.get(key)
    _tendency_cache[key] = (clock, float(value))
    if prev is None:
        return None
    prev_ts, prev_value = prev
    dt = clock - prev_ts
    if dt <= 0 or dt > _SAMPLE_TTL_S:
        return None
    return (float(value) - prev_value) / dt


def build_perceptual_field(
    recent_reactions: list[str] | None = None,
) -> PerceptualField:
    """Aggregate all existing classifier/detector outputs into one field.

    Every sub-read is wrapped so a missing source yields a None field, never
    a crash. Safe to call from the director's hot path.
    """
    perception = _read_perception_state()
    stimmung_dims, stimmung_stance = _read_stimmung()
    album = _safe_load_json(_ALBUM_STATE) or {}
    presence = _safe_load_json(_PRESENCE_STATE) or {}

    # ── Audio ─────────────────────────────────────────────────────────────
    contact_mic = ContactMicState(
        desk_activity=perception.get("desk_activity"),
        desk_energy=perception.get("desk_energy"),
        desk_onset_rate=perception.get("desk_onset_rate"),
        desk_spectral_centroid=perception.get("desk_spectral_centroid"),
        desk_tap_gesture=perception.get("desk_tap_gesture"),
        fused_activity=perception.get("detected_action"),  # cross-modal label
    )
    midi = MidiState(
        beat_position=perception.get("beat_position"),
        bar_position=perception.get("bar_position"),
        tempo=perception.get("tempo"),
        transport_state=perception.get("transport_state"),
    )
    # production_activity is a strict Literal; older perception-state payloads
    # can contain the empty string which fails validation. Normalize to None.
    _prod_activity_raw = perception.get("production_activity")
    _prod_activity = _prod_activity_raw if _prod_activity_raw else None

    def _as_float(val: object) -> float | None:
        """Coerce perception-state values to float, tolerating legacy strings.

        Older perception-state.json payloads can contain sentinels like
        ``"unknown"`` where the typed Pydantic model expects a number.
        Return None on any non-parseable input so the twitch loop doesn't
        die on malformed upstream data.
        """
        if val is None:
            return None
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    ingestion = StudioIngestionState(
        music_genre=perception.get("music_genre"),
        production_activity=_prod_activity,
        flow_state_score=perception.get("flow_state_score"),
    )
    vad = VadState(
        operator_speech_active=perception.get("operator_speech_active"),
    )
    audio = AudioField(
        contact_mic=contact_mic,
        midi=midi,
        studio_ingestion=ingestion,
        vad=vad,
    )

    # ── Visual ────────────────────────────────────────────────────────────
    visual = VisualField(
        per_camera_scenes=perception.get("per_camera_scenes") or {},
        detected_action=perception.get("detected_action"),
        overhead_hand_zones=_as_list(perception.get("overhead_hand_zones")),
        operator_confirmed=perception.get("operator_confirmed"),
        top_emotion=perception.get("top_emotion"),
        hand_gesture=perception.get("hand_gesture"),
        gaze_direction=perception.get("gaze_direction"),
        posture=perception.get("posture"),
        ambient_brightness=_as_float(perception.get("ambient_brightness")),
        color_temperature=_as_float(perception.get("color_temperature")),
        per_camera_person_count=perception.get("per_camera_person_count") or {},
        scene_type=perception.get("scene_type"),
    )

    # ── IR ────────────────────────────────────────────────────────────────
    def _as_int(val: object) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    ir = IrField(
        ir_hand_activity=_as_float(perception.get("ir_hand_activity")),
        ir_hand_zone=perception.get("ir_hand_zone"),
        ir_gaze_zone=perception.get("ir_gaze_zone"),
        ir_posture=perception.get("ir_posture"),
        ir_heart_rate_bpm=_as_int(perception.get("ir_heart_rate_bpm")),
        ir_heart_rate_confidence=_as_float(perception.get("ir_heart_rate_conf")),
        ir_brightness=_as_float(perception.get("ir_brightness")),
        ir_person_count=_as_int(perception.get("ir_person_count")),
        ir_screen_looking=perception.get("ir_screen_looking"),
        ir_drowsiness_score=_as_float(perception.get("ir_drowsiness_score")),
    )

    # ── Album ─────────────────────────────────────────────────────────────
    album_field = AlbumField(
        artist=album.get("artist"),
        title=album.get("title"),
        current_track=album.get("current_track"),
        year=_as_int(album.get("year")),
        confidence=_as_float(album.get("confidence")),
    )

    # ── Chat ──────────────────────────────────────────────────────────────
    chat = _read_chat()

    # ── Context ───────────────────────────────────────────────────────────
    mode = _read_working_mode()
    context = ContextField(
        working_mode=mode if mode in ("research", "rnd") else None,
        stream_mode=_read_stream_mode(),
        stream_live=_STREAM_LIVE.exists(),
        active_objective_ids=_read_active_objective_ids(),
        time_of_day=_time_of_day(),
        recent_reactions=list(recent_reactions or []),
        active_consent_contract_ids=_read_active_consent_contract_ids(),
    )

    # ── Stimmung ──────────────────────────────────────────────────────────
    try:
        stance_enum = Stance(stimmung_stance) if stimmung_stance else None
    except ValueError:
        stance_enum = None
    stimmung = StimmungField(
        dimensions=stimmung_dims,
        overall_stance=stance_enum,
    )

    # ── Presence ──────────────────────────────────────────────────────────
    presence_field = PresenceField(
        state=_coerce_presence_state(presence.get("state")),
        probability=presence.get("presence_probability"),
    )

    # ── Tendency (S4) ─────────────────────────────────────────────────────
    # Per-second rates derived from diffs against the module-level sample
    # cache. The first call after reset returns None for every rate; after
    # a second call within _SAMPLE_TTL_S the rates carry real information.
    _clock = time.time()
    tendency = TendencyField(
        beat_position_rate=_compute_rate("beat_position", midi.beat_position, _clock),
        desk_energy_rate=_compute_rate("desk_energy", contact_mic.desk_energy, _clock),
        chat_heating_rate=_compute_rate("chat_recent", float(chat.recent_message_count), _clock),
    )

    return PerceptualField(
        audio=audio,
        visual=visual,
        ir=ir,
        album=album_field,
        chat=chat,
        context=context,
        stimmung=stimmung,
        presence=presence_field,
        stream_health=StreamHealthField(),
        tendency=tendency,
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, dict):
        # dict[zone, bool] shape → list of zones with truthy values
        return [str(k) for k, v in value.items() if v]
    if isinstance(value, str):
        return [s for s in value.split(",") if s.strip()]
    return []


def _coerce_presence_state(value) -> str | None:
    if not isinstance(value, str):
        return None
    upper = value.upper()
    if upper in ("PRESENT", "UNCERTAIN", "AWAY"):
        return upper  # type: ignore[return-value]
    return None
