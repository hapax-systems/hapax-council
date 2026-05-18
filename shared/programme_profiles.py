"""Programme runtime profiles — operational config per programme role.

Each profile defines Reverie intensity, audio ducking, compositor layout,
and conversation parameters. Loaded from config/programme-*-profile.json.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@dataclass(frozen=True)
class ReverieProfile:
    intensity: str = "normal"
    palette: str = "default"
    drift_gain: float = 1.0
    breath_gain: float = 1.0
    feedback_gain: float = 1.0
    noise_gain: float = 1.0


@dataclass(frozen=True)
class AudioProfile:
    music_bed_gain_db: float = -18
    speech_duck_threshold_db: float = -18
    speech_priority: str = "normal"
    reverb_wet: float = 0.05
    noise_gate_threshold_db: float = -40


@dataclass(frozen=True)
class CompositorProfile:
    layout_mode: str = "balanced"
    wards: tuple[str, ...] = ()
    camera_mode: str = "balanced"
    overlay_opacity: float = 0.8


@dataclass(frozen=True)
class ConversationProfile:
    max_turns: int = 20
    silence_timeout_s: float = 30.0
    model_tier: str = "STRONG"
    grounding_directive: bool = False
    effort_modulation: bool = False


@dataclass(frozen=True)
class ProgrammeProfile:
    programme_role: str
    target_duration_s: float = 1800.0
    wind_down_at_s: float = 1500.0
    reverie: ReverieProfile = field(default_factory=ReverieProfile)
    audio: AudioProfile = field(default_factory=AudioProfile)
    compositor: CompositorProfile = field(default_factory=CompositorProfile)
    conversation: ConversationProfile = field(default_factory=ConversationProfile)


def _load_profile_from_file(path: Path) -> ProgrammeProfile | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.debug("Failed to load programme profile %s: %s", path, e)
        return None

    rev = data.get("reverie", {})
    aud = data.get("audio", {})
    comp = data.get("compositor", {})
    conv = data.get("conversation", {})

    return ProgrammeProfile(
        programme_role=data.get("programme_role", path.stem),
        target_duration_s=data.get("target_duration_s", 1800.0),
        wind_down_at_s=data.get("wind_down_at_s", 1500.0),
        reverie=ReverieProfile(
            intensity=rev.get("intensity", "normal"),
            palette=rev.get("palette", "default"),
            drift_gain=rev.get("drift_gain", 1.0),
            breath_gain=rev.get("breath_gain", 1.0),
            feedback_gain=rev.get("feedback_gain", 1.0),
            noise_gain=rev.get("noise_gain", 1.0),
        ),
        audio=AudioProfile(
            music_bed_gain_db=aud.get("music_bed_gain_db", -18),
            speech_duck_threshold_db=aud.get("speech_duck_threshold_db", -18),
            speech_priority=aud.get("speech_priority", "normal"),
            reverb_wet=aud.get("reverb_wet", 0.05),
            noise_gate_threshold_db=aud.get("noise_gate_threshold_db", -40),
        ),
        compositor=CompositorProfile(
            layout_mode=comp.get("layout_mode", "balanced"),
            wards=tuple(comp.get("wards", ())),
            camera_mode=comp.get("camera_mode", "balanced"),
            overlay_opacity=comp.get("overlay_opacity", 0.8),
        ),
        conversation=ConversationProfile(
            max_turns=conv.get("max_turns", 20),
            silence_timeout_s=conv.get("silence_timeout_s", 30.0),
            model_tier=conv.get("model_tier", "STRONG"),
            grounding_directive=conv.get("grounding_directive", False),
            effort_modulation=conv.get("effort_modulation", False),
        ),
    )


_CACHE: dict[str, ProgrammeProfile] = {}


def get_programme_profile(role: str) -> ProgrammeProfile | None:
    """Load the runtime profile for a programme role. Cached after first load."""
    if role in _CACHE:
        return _CACHE[role]

    path = CONFIG_DIR / f"programme-{role}-profile.json"
    if not path.exists():
        return None

    profile = _load_profile_from_file(path)
    if profile is not None:
        _CACHE[role] = profile
    return profile
