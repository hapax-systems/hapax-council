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

_AUDIO_GROUNDING_STATE = Path("/dev/shm/hapax-audio-grounding/state.json")
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

# HOMAGE Phase 9 (task #115): SHM source paths for the homage sub-field.
# Governed by research condition ``cond-phase-a-homage-active-001``.
# The choreographer publishes the active package, current signature-artefact
# selection, and voice-register choice to these SHM files; the consent-safe
# flag comes from studio_compositor state. The director reads these back so
# it can cite homage state in ``grounding_provenance`` under the new
# research condition.
_HOMAGE_ACTIVE_ARTEFACT = Path("/dev/shm/hapax-compositor/homage-active-artefact.json")
_HOMAGE_VOICE_REGISTER = Path("/dev/shm/hapax-compositor/homage-voice-register.json")
_HOMAGE_SUBSTRATE_PACKAGE = Path("/dev/shm/hapax-compositor/homage-substrate-package.json")
_HOMAGE_CONSENT_SAFE_FLAG = Path("/dev/shm/hapax-compositor/consent-safe-active.json")

# Task #135 — camera classification metadata published by the studio
# compositor. Dict keyed by role (``brio-operator``, ``c920-overhead``, …)
# → classification payload (semantic_role / subject_ontology / angle /
# operator_visible / ambient_priority). Read-only for this module.
_CAMERA_CLASSIFICATIONS = Path("/dev/shm/hapax-compositor/camera-classifications.json")

# Companion fleet — watch + phone state files on filesystem-as-bus
_WATCH_STATE_DIR = Path(os.path.expanduser("~/hapax-state/watch"))

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


class SceneClassificationState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene: str | None = None
    scene_label: str | None = None
    scene_confidence: float | None = None
    genre: str | None = None
    music_score: float | None = None


class AudioField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contact_mic: ContactMicState = Field(default_factory=ContactMicState)
    midi: MidiState = Field(default_factory=MidiState)
    studio_ingestion: StudioIngestionState = Field(default_factory=StudioIngestionState)
    vad: VadState = Field(default_factory=VadState)
    scene_classification: SceneClassificationState = Field(default_factory=SceneClassificationState)


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


class HomageField(BaseModel):
    """Active HOMAGE package state (task #115, condition
    ``cond-phase-a-homage-active-001``).

    Lets the narrative director cite homage state in
    ``grounding_provenance`` — e.g. "rotated under package=bitchx,
    register=textmode, consent-safe=False" — without reaching into
    SHM itself. All fields degrade gracefully: when the choreographer
    has not yet published state (boot, test harness), every field is
    None / False and the director simply omits the provenance.

    - ``package_name`` — the active ``HomagePackage.name`` (e.g.
      ``"bitchx"`` or ``"bitchx_consent_safe"``), read from
      ``homage-substrate-package.json``. None when HOMAGE is dormant.
    - ``active_artefact_form`` — the current signature-artefact form
      (``"quit-quip"``, ``"join-banner"``, ``"motd-block"``,
      ``"kick-reason"``), read from ``homage-active-artefact.json``.
      Advances per rotation cycle.
    - ``voice_register`` — the active CPAL register (``"announcing"``,
      ``"conversing"``, ``"textmode"``), read from
      ``homage-voice-register.json``. None when the bridge file is
      missing.
    - ``consent_safe_active`` — True iff
      ``consent-safe-active.json`` exists (studio_compositor's
      consent gate for ``stream_mode.public_research``).
    """

    model_config = ConfigDict(extra="ignore")

    package_name: str | None = None
    active_artefact_form: str | None = None
    voice_register: str | None = None
    consent_safe_active: bool = False


class OperatorBiometricField(BaseModel):
    """Biometric signals from companion devices (watch, phone health summaries)."""

    model_config = ConfigDict(extra="ignore")

    heart_rate_bpm: float | None = None
    heart_rate_confidence: str | None = None
    hrv_rmssd_ms: float | None = None
    skin_temp_c: float | None = None
    eda_event: bool | None = None
    respiration_rate: float | None = None
    spo2_mean: float | None = None
    sleep_duration_min: int | None = None
    resting_hr: float | None = None


class OperatorMobilityField(BaseModel):
    """Mobility and activity signals from companion devices (phone context, health summaries)."""

    model_config = ConfigDict(extra="ignore")

    activity_type: str | None = None
    activity_confidence: float | None = None
    steps: int | None = None
    active_minutes: int | None = None


class CompanionFleetField(BaseModel):
    """Companion device connectivity status."""

    model_config = ConfigDict(extra="ignore")

    watch_connected: bool = False
    watch_last_seen_ago_s: float | None = None
    watch_battery_pct: int | None = None
    phone_connected: bool = False
    phone_last_seen_ago_s: float | None = None
    phone_battery_pct: int | None = None


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
    homage: HomageField = Field(default_factory=HomageField)
    # Task #135 — semantic classification for each configured camera.
    # Keyed by role (``brio-operator``, ``c920-overhead``, …) → dict with
    # ``semantic_role``, ``subject_ontology``, ``angle``,
    # ``operator_visible``, ``ambient_priority``. The director reads this
    # to prefer operator-visible cameras when the operator is speaking
    # and high-ambient-priority cameras for ambient cuts. Empty dict when
    # the compositor hasn't published yet.
    camera_classifications: dict[str, dict] = Field(default_factory=dict)
    operator_biometric: OperatorBiometricField = Field(default_factory=OperatorBiometricField)
    operator_mobility: OperatorMobilityField = Field(default_factory=OperatorMobilityField)
    companion_fleet: CompanionFleetField = Field(default_factory=CompanionFleetField)

    @property
    def vinyl_playing(self) -> bool:
        """Derived signal: is a vinyl actually playing right now?

        #127 SPLATTRIBUTION. Music featuring must be decoupled from raw
        vinyl playback. A single authoritative boolean gates album
        overlay rotation, track-ID attribution emission, and twitch
        director "music is playing" framing. When False, opens the
        Hapax-music-repo path (#130) and SoundCloud passthrough (#131).

        Requires BOTH:
          1. MIDI transport says PLAYING (from OXI One start/stop
             messages, <20ms latency callback-driven in
             ``midi_clock.py::_on_message``).
          2. ``tendency.beat_position_rate`` > 0 — guards against a
             stale transport_state that declares PLAYING when the clock
             source has silently stopped ticking (scratch stop,
             power-bump, clock-source disconnect).

        Fail-safe: returns False when either signal is missing. That
        keeps misattribution out of the stream during cold-start /
        missing-sample windows. Tendency's first-read-after-reset
        returns None for the rate, so initial ticks correctly report
        False until a beat has been observed advancing.
        """
        if self.audio.midi.transport_state != "PLAYING":
            return False
        rate = self.tendency.beat_position_rate
        if rate is None:
            return False
        return rate > 0.0


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


def _read_scene_classification() -> SceneClassificationState:
    data = _safe_load_json(_AUDIO_GROUNDING_STATE) or {}
    if data.get("error"):
        return SceneClassificationState()
    return SceneClassificationState(
        scene=data.get("scene"),
        scene_label=data.get("scene_label"),
        scene_confidence=data.get("scene_confidence"),
        genre=data.get("genre"),
        music_score=data.get("music_score"),
    )


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


def _read_homage() -> HomageField:
    """Aggregate HOMAGE state from the four SHM files.

    Each read is independent and fail-open: a missing or malformed
    file contributes a None (or False, for the consent flag) without
    affecting the other fields. The director's grounding_provenance
    cite rule degrades to "no homage provenance" when HOMAGE is
    dormant — not to a crash.

    Task #115 / research condition cond-phase-a-homage-active-001.
    """
    # Active package name comes from the substrate-package broadcast;
    # this is the single source of truth for "which HomagePackage is
    # active right now," including the consent-safe swap.
    substrate = _safe_load_json(_HOMAGE_SUBSTRATE_PACKAGE) or {}
    package_name = substrate.get("package")
    if not isinstance(package_name, str) or not package_name:
        package_name = None

    # Signature artefact form — may lag the package swap by up to one
    # rotation cycle (the choreographer only re-publishes per cycle).
    artefact = _safe_load_json(_HOMAGE_ACTIVE_ARTEFACT) or {}
    form = artefact.get("form")
    if not isinstance(form, str) or not form:
        form = None

    # Voice register — written by the choreographer on every
    # reconcile tick.
    register_payload = _safe_load_json(_HOMAGE_VOICE_REGISTER) or {}
    register = register_payload.get("register")
    if not isinstance(register, str) or not register:
        register = None

    # Consent-safe flag is file-existence, not payload-parsing. The
    # flag file's presence is the signal; we never trust the contents
    # (studio_compositor writes a stable shape but we don't depend on
    # it here).
    consent_safe_active = False
    try:
        consent_safe_active = _HOMAGE_CONSENT_SAFE_FLAG.exists()
    except OSError:
        consent_safe_active = False

    return HomageField(
        package_name=package_name,
        active_artefact_form=form,
        voice_register=register,
        consent_safe_active=consent_safe_active,
    )


def _read_operator_biometric() -> OperatorBiometricField:
    """Aggregate biometric signals from watch state files and phone health summary."""
    hr_data = _safe_load_json(_WATCH_STATE_DIR / "heartrate.json") or {}
    hrv_data = _safe_load_json(_WATCH_STATE_DIR / "hrv.json") or {}
    skin_data = _safe_load_json(_WATCH_STATE_DIR / "skin_temp.json") or {}
    eda_data = _safe_load_json(_WATCH_STATE_DIR / "eda.json") or {}
    resp_data = _safe_load_json(_WATCH_STATE_DIR / "respiration.json") or {}
    summary = _safe_load_json(_WATCH_STATE_DIR / "phone_health_summary.json") or {}

    hr_current = hr_data.get("current") or {}
    hrv_current = hrv_data.get("current") or {}
    skin_current = skin_data.get("current") or {}
    eda_current = eda_data.get("current") or {}
    resp_current = resp_data.get("current") or {}

    return OperatorBiometricField(
        heart_rate_bpm=hr_current.get("bpm"),
        heart_rate_confidence=hr_current.get("confidence"),
        hrv_rmssd_ms=hrv_current.get("rmssd_ms"),
        skin_temp_c=skin_current.get("temp_c"),
        eda_event=eda_current.get("eda_event"),
        respiration_rate=resp_current.get("breaths_per_min"),
        spo2_mean=summary.get("spo2_mean"),
        sleep_duration_min=summary.get("sleep_duration_min"),
        resting_hr=summary.get("resting_hr"),
    )


def _read_operator_mobility() -> OperatorMobilityField:
    """Aggregate mobility signals from phone context and health summary."""
    context = _safe_load_json(_WATCH_STATE_DIR / "phone_context.json") or {}
    summary = _safe_load_json(_WATCH_STATE_DIR / "phone_health_summary.json") or {}
    activity = _safe_load_json(_WATCH_STATE_DIR / "activity.json") or {}

    activity_type = context.get("activity_type") or activity.get("state")
    confidence = context.get("activity_confidence")

    return OperatorMobilityField(
        activity_type=activity_type,
        activity_confidence=confidence,
        steps=summary.get("steps"),
        active_minutes=summary.get("active_minutes"),
    )


def _read_companion_fleet() -> CompanionFleetField:
    """Read companion device connectivity status."""
    now = time.time()
    watch_conn = _safe_load_json(_WATCH_STATE_DIR / "connection.json") or {}
    phone_conn = _safe_load_json(_WATCH_STATE_DIR / "phone_connection.json") or {}

    watch_epoch = watch_conn.get("last_seen_epoch", 0)
    watch_age = now - watch_epoch if watch_epoch else None
    phone_epoch = phone_conn.get("last_seen_epoch", 0)
    phone_age = now - phone_epoch if phone_epoch else None

    return CompanionFleetField(
        watch_connected=watch_age is not None and watch_age < 300,
        watch_last_seen_ago_s=watch_age,
        watch_battery_pct=watch_conn.get("battery_pct"),
        phone_connected=phone_age is not None and phone_age < 300,
        phone_last_seen_ago_s=phone_age,
        phone_battery_pct=phone_conn.get("battery_pct"),
    )


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
    scene_classification = _read_scene_classification()
    audio = AudioField(
        contact_mic=contact_mic,
        midi=midi,
        studio_ingestion=ingestion,
        vad=vad,
        scene_classification=scene_classification,
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
    # album-identifier writes /dev/shm/hapax-compositor/album-state.json from
    # IR-vision album-cover recognition; the visual recognition fires whenever
    # a cover is on the deck regardless of whether vinyl is actually spinning.
    # The album-identifier sets ``playing`` from its own ``_vinyl_probably_playing``
    # gate (override flag OR ir_hand_zone=turntable OR ir_hand_activity=scratching),
    # but the gate fires on transient IR misclassifications and the file then
    # holds the stale ``playing: true`` until the album zone changes (which it
    # does not, since the cover keeps sitting on the deck).
    #
    # Operator-reported regression 2026-05-01: the LLM kept emitting present-
    # tense narrations of catalog state ("the bass on this Metal Fingers cut
    # …") because PerceptualField.model_dump_json exposed album.artist and
    # album.title regardless of playing. Refusal gate caught >40 hallucinated
    # narrations in 30 minutes.
    #
    # Fix: when album-state's ``playing`` field is False (or absent), suppress
    # artist/title/current_track/year from the perceptual-field JSON entirely,
    # so the LLM cannot ground in catalog state. ``confidence`` survives —
    # downstream classifiers may still want to know the visual confidence in
    # the cover identification, that's not a present-tense claim.
    album_playing = bool(album.get("playing"))
    album_field = AlbumField(
        artist=album.get("artist") if album_playing else None,
        title=album.get("title") if album_playing else None,
        current_track=album.get("current_track") if album_playing else None,
        year=_as_int(album.get("year")) if album_playing else None,
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

    # ── Homage (task #115, cond-phase-a-homage-active-001) ──────────────
    homage = _read_homage()

    # ── Camera classifications (task #135) ──────────────────────────────
    # Compositor publishes once at startup; failures / missing file =
    # empty dict (director degrades gracefully).
    camera_classifications = _safe_load_json(_CAMERA_CLASSIFICATIONS) or {}
    if not isinstance(camera_classifications, dict):
        camera_classifications = {}

    # ── Companion fleet (biometric + mobility + connectivity) ─────────
    operator_biometric = _read_operator_biometric()
    operator_mobility = _read_operator_mobility()
    companion_fleet = _read_companion_fleet()

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
        homage=homage,
        camera_classifications=camera_classifications,
        operator_biometric=operator_biometric,
        operator_mobility=operator_mobility,
        companion_fleet=companion_fleet,
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
