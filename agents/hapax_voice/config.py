"""Configuration for hapax-voice daemon."""

from __future__ import annotations

import logging
import os
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

log = logging.getLogger(__name__)

# Single source of truth for LiteLLM URL within the voice package.
# Avoids importing shared.config (circular dep risk) while satisfying P8.
LITELLM_BASE: str = os.environ.get(
    "LITELLM_API_BASE",
    os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
)


class PerceptionTier(StrEnum):
    """Privacy-aware perception level, switchable via voice or hotkey."""

    FULL = "full"  # cameras + audio + inference
    PRESENCE = "presence"  # face detection only, no analysis
    AUDIO = "audio"  # no cameras, voice only
    DORMANT = "dormant"  # wake word only


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hapax-voice" / "config.yaml"


def _default_socket_path() -> str:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return f"{runtime_dir}/hapax-voice.sock"


class VoiceConfig(BaseModel):
    """All tunables for the voice daemon."""

    # Session
    silence_timeout_s: int = 30
    wake_phrases: list[str] = ["hapax", "hey hapax"]
    hotkey_socket: str = ""

    # Presence detection
    presence_window_minutes: int = 5
    presence_vad_threshold: float = 0.4

    # Context gate
    context_gate_volume_threshold: float = 0.7
    context_gate_ambient_classification: bool = True
    context_gate_ambient_block_threshold: float = 0.15

    # Audio hardware
    # PipeWire's echo-cancel module is broken on PipeWire 1.6.x
    # (ENOTSUP on capture node start). Use raw Yeti with application-level
    # echo suppression: wake word + VAD gated during TTS playback,
    # post-TTS cooldown to let room reflections decay.
    audio_input_source: str = (
        "alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo"
    )

    # Echo cancellation (application-level, replaces broken PipeWire AEC)
    aec_enabled: bool = True
    aec_tail_ms: int = 200

    # Backends
    backend: str = "local"  # "local" or "gemini"
    llm_model: str = "gemini-flash"
    gemini_model: str = "gemini-2.5-flash-preview-native-audio"
    local_stt_model: str = "nvidia/parakeet-tdt-0.6b-v2"
    kokoro_voice: str = "af_heart"

    # Consent
    consent_debounce_s: float = 5.0  # sustained presence before triggering
    consent_absence_clear_s: float = 30.0  # how long guest must be absent to clear
    consent_session_timeout_s: float = 120.0  # max duration for consent conversation

    # Notification queue
    notification_priority_ttls: dict[str, int] = {
        "urgent": 1800,
        "normal": 14400,
        "low": 0,
    }

    # Screen monitor
    screen_monitor_enabled: bool = True
    screen_poll_interval_s: float = 2
    screen_capture_cooldown_s: float = 30
    screen_proactive_min_confidence: float = 0.8
    screen_proactive_cooldown_s: float = 300
    screen_recapture_idle_s: float = 60

    # Webcam settings
    webcam_enabled: bool = True
    webcam_brio_device: str = "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0"
    webcam_c920_device: str = "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0"
    webcam_ir_device: str = ""
    webcam_capture_width: int = 1280
    webcam_capture_height: int = 720
    # Presence face detection
    presence_face_detection: bool = True
    presence_face_interval_s: float = 8.0
    presence_face_decay_s: float = 30.0
    presence_face_min_confidence: float = 0.3
    presence_ir_fallback: bool = True
    # Workspace analysis
    workspace_analysis_cadence_s: float = 45.0
    workspace_hardware_cadence_s: float = 60.0
    workspace_multi_image: bool = True
    # Timelapse
    timelapse_enabled: bool = False
    timelapse_interval_s: float = 60.0
    timelapse_retention_days: int = 7
    timelapse_path: str = "~/.local/share/hapax-voice/timelapse"

    # Perception layer
    perception_tier: PerceptionTier = PerceptionTier.FULL
    perception_fast_tick_s: float = 2.5
    perception_slow_tick_s: float = 12.0
    conversation_debounce_s: float = 3.0
    gaze_resume_clear_s: float = 5.0
    environment_clear_resume_s: float = 15.0
    operator_absent_withdraw_s: float = 60.0

    # Observability
    observability_events_enabled: bool = True
    observability_langfuse_enabled: bool = True
    observability_events_retention_days: int = 14

    # Tools
    tools_enabled: bool = True

    # SMS Gateway
    sms_gateway_host: str = ""
    sms_gateway_user: str = ""
    sms_gateway_pass_key: str = "sms-gateway/password"
    sms_contacts: dict[str, str] = {}

    # Vision tools
    vision_spontaneous: bool = True
    vision_refresh_interval: int = 60

    # Wake word engine
    wake_word_engine: str = "oww"  # "porcupine" or "oww"
    porcupine_sensitivity: float = 0.5

    # Chime settings
    chime_enabled: bool = False
    chime_volume: float = 0.7
    chime_dir: str = "~/.local/share/hapax-voice/chimes"

    # MC actuation
    mc_enabled: bool = False
    mc_sample_dir: str = "~/.local/share/hapax-voice/mc-samples"
    mc_sample_rate: int = 44100
    actuation_tick_ms: int = 10

    # MIDI clock
    midi_port_name: str = "OXI One"
    midi_beats_per_bar: int = 4

    # OBS integration
    obs_enabled: bool = False
    obs_host: str = "localhost"
    obs_port: int = 4455

    # Salience router
    salience_enabled: bool = True  # False = fall back to model_router.py heuristics
    salience_model: str = "minishlab/potion-base-8M"
    salience_thresholds: dict[str, float] = {
        "canned_max": 0.15,
        "local_max": 0.35,
        "fast_max": 0.55,
        "strong_max": 0.75,
    }
    salience_weights: dict[str, float] = {
        "concern_overlap": 0.50,
        "novelty": 0.20,
        "dialog_features": 0.30,
    }
    salience_concern_refresh_cadence_s: float = 2.5  # match perception fast tick

    # TTS hold-and-release
    tts_bar_aligned: bool = True
    tts_lookahead_bars: int = 2

    @model_validator(mode="after")
    def _apply_dynamic_defaults(self) -> VoiceConfig:
        if not self.hotkey_socket:
            self.hotkey_socket = _default_socket_path()
        return self


def load_config(path: Path | None = None) -> VoiceConfig:
    """Load config from YAML, falling back to defaults."""
    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
            return VoiceConfig(**data)
        except Exception as exc:
            log.warning("Failed to load config from %s: %s", config_path, exc)
    return VoiceConfig()
