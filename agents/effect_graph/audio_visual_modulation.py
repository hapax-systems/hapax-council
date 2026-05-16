"""Source-role-aware audio visual modulation governor.

The governor keeps audio reactivity expressive while preventing source role
signals from becoming truth, public-safety, rights, or monetization authority.
It is deliberately local to the effect graph: it classifies modulation
bindings, resolves namespaced source aliases, and applies an anti-visualizer
coupling gain only to audio-driven geometry bindings.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .types import ModulationBinding


class AudioVisualSourceRole(StrEnum):
    """Programme-level role for an audio modulation source."""

    NON_AUDIO = "non_audio"
    PROGRAMME_MUSIC = "programme_music"
    OPERATOR_VOICE = "operator_voice"
    HAPAX_TTS = "hapax_tts"
    YOUTUBE = "youtube"
    BROADCAST = "broadcast"
    DESK = "desk"
    LEGACY_MIXER = "legacy_mixer"
    UNKNOWN_AUDIO = "unknown_audio"


class AudioSignalClass(StrEnum):
    """Signal-shape class used to keep audio reactivity legible."""

    NON_AUDIO = "non_audio"
    LOW_SUSTAINED = "low_sustained"
    MID_SUSTAINED = "mid_sustained"
    HIGH_SUSTAINED = "high_sustained"
    BROADBAND_SUSTAINED = "broadband_sustained"
    LOW_TRANSIENT = "low_transient"
    MID_TRANSIENT = "mid_transient"
    HIGH_TRANSIENT = "high_transient"
    SPECTRAL_CENTROID = "spectral_centroid"
    ONSET_RATE = "onset_rate"
    UNKNOWN_AUDIO = "unknown_audio"


class VisualModulationAxis(StrEnum):
    """Visual axis a binding can influence."""

    COLOR = "color"
    TEXTURE = "texture"
    DEPTH = "depth"
    GEOMETRY = "geometry"
    TRANSITION = "transition"
    FOCUS = "focus"
    CLAIM_POSTURE = "claim_posture"
    UNKNOWN = "unknown"


class AudioVisualizerRegister(StrEnum):
    """Register classification for anti-visualizer policy."""

    NONE = "none"
    BROADBAND_COLOR = "broadband_color"
    STRUCTURAL_TEXTURE = "structural_texture"
    STRUCTURAL_MOTION = "structural_motion"
    RADIAL_PULSE = "radial_pulse"
    WAVEFORM = "waveform"
    FFT = "fft"
    SPECTRUM_BARS = "spectrum_bars"
    BEAT_ICONOGRAPHY = "beat_iconography"


class PublicClaimPolicy(StrEnum):
    """Authority ceiling for modulation decisions."""

    NO_CLAIM_AUTHORITY = "no_claim_authority"


FORBIDDEN_VISUALIZER_REGISTERS = frozenset(
    {
        AudioVisualizerRegister.RADIAL_PULSE,
        AudioVisualizerRegister.WAVEFORM,
        AudioVisualizerRegister.FFT,
        AudioVisualizerRegister.SPECTRUM_BARS,
        AudioVisualizerRegister.BEAT_ICONOGRAPHY,
    }
)

AUDIO_GEOMETRY_AXES = frozenset({VisualModulationAxis.DEPTH, VisualModulationAxis.GEOMETRY})

AUDIO_REACTIVE_BANNED_PARAMS = frozenset(
    {
        # Global luma/alpha controls. Audio may add color/detail/motion, not
        # dim, flash, pulse, or pump the entire frame.
        "brightness",
        "intensity",
        "opacity",
        "alpha",
        "master_opacity",
        "strength",
        "flash",
        "dim",
        "pulse",
        # Static/fade/threshold controls that turn programme audio into a
        # visualizer gate instead of a bounded scene modulation.
        "active",
        "enabled",
        "fade",
        "freeze_chance",
        "freeze_min",
        "freeze_max",
        "replay_frames",
        "check_interval",
        "threshold",
        "threshold_low",
        "threshold_high",
    }
)

NAMESPACED_AUDIO_SOURCE_ALIASES: Mapping[str, tuple[str, ...]] = {
    "music.rms": ("mixer_energy", "audio_rms"),
    "music.energy": ("mixer_energy", "audio_rms"),
    "music.bass": ("mixer_bass",),
    "music.mid": ("mixer_mid",),
    "music.treble": ("mixer_high",),
    "music.centroid": ("spectral_centroid",),
    "music.onset": ("sidechain_kick", "onset_kick", "audio_beat"),
    "music.kick_onset": ("sidechain_kick", "onset_kick"),
    "music.snare_onset": ("onset_snare",),
    "music.hat_onset": ("onset_hat",),
    "operator_voice.rms": ("voice.rms", "voice_rms"),
    "operator_voice.onset": ("voice.onset", "voice_onset"),
    "tts.rms": ("hapax_tts.rms", "broadcast_tts.rms"),
    "tts.onset": ("hapax_tts.onset", "broadcast_tts.onset"),
    "youtube.rms": ("yt.rms", "yt.energy", "youtube-bed.rms"),
    "youtube.onset": ("yt.onset", "youtube-bed.onset"),
    "broadcast.rms": ("broadcast_master.rms", "mixer_energy", "audio_rms"),
    "broadcast.onset": ("broadcast_master.onset", "sidechain_kick", "audio_beat"),
    "desk.rms": ("desk_energy", "contact_mic", "desk_activity"),
    "desk.onset_rate": ("desk_onset_rate", "desk_activity"),
}


@dataclass(frozen=True)
class SourceRolePolicy:
    """Allow-list policy for one audio source role."""

    role: AudioVisualSourceRole
    allowed_axes: frozenset[VisualModulationAxis]
    source_refs: tuple[str, ...]
    health_refs: tuple[str, ...]
    public_claim_policy: PublicClaimPolicy = PublicClaimPolicy.NO_CLAIM_AUTHORITY


SOURCE_ROLE_POLICIES: Mapping[AudioVisualSourceRole, SourceRolePolicy] = {
    AudioVisualSourceRole.PROGRAMME_MUSIC: SourceRolePolicy(
        role=AudioVisualSourceRole.PROGRAMME_MUSIC,
        allowed_axes=frozenset(
            {
                VisualModulationAxis.COLOR,
                VisualModulationAxis.TEXTURE,
                VisualModulationAxis.DEPTH,
                VisualModulationAxis.GEOMETRY,
                VisualModulationAxis.TRANSITION,
            }
        ),
        source_refs=("source:audio-reactivity:programme_music",),
        health_refs=("health:scrim:anti_visualizer",),
    ),
    AudioVisualSourceRole.OPERATOR_VOICE: SourceRolePolicy(
        role=AudioVisualSourceRole.OPERATOR_VOICE,
        allowed_axes=frozenset(
            {
                VisualModulationAxis.FOCUS,
                VisualModulationAxis.TEXTURE,
                VisualModulationAxis.TRANSITION,
            }
        ),
        source_refs=("source:audio-reactivity:operator_voice",),
        health_refs=("health:voice:intelligibility", "health:scrim:anti_visualizer"),
    ),
    AudioVisualSourceRole.HAPAX_TTS: SourceRolePolicy(
        role=AudioVisualSourceRole.HAPAX_TTS,
        allowed_axes=frozenset(
            {
                VisualModulationAxis.CLAIM_POSTURE,
                VisualModulationAxis.FOCUS,
                VisualModulationAxis.TEXTURE,
                VisualModulationAxis.TRANSITION,
            }
        ),
        source_refs=("source:audio-reactivity:hapax_tts",),
        health_refs=("health:voice:private_leak_guard", "health:scrim:anti_visualizer"),
    ),
    AudioVisualSourceRole.YOUTUBE: SourceRolePolicy(
        role=AudioVisualSourceRole.YOUTUBE,
        allowed_axes=frozenset(
            {
                VisualModulationAxis.COLOR,
                VisualModulationAxis.TEXTURE,
                VisualModulationAxis.DEPTH,
                VisualModulationAxis.TRANSITION,
            }
        ),
        source_refs=("source:audio-reactivity:youtube",),
        health_refs=("health:rights:content_source_provenance", "health:scrim:anti_visualizer"),
    ),
    AudioVisualSourceRole.BROADCAST: SourceRolePolicy(
        role=AudioVisualSourceRole.BROADCAST,
        allowed_axes=frozenset(
            {
                VisualModulationAxis.COLOR,
                VisualModulationAxis.TEXTURE,
                VisualModulationAxis.DEPTH,
                VisualModulationAxis.GEOMETRY,
                VisualModulationAxis.TRANSITION,
            }
        ),
        source_refs=("source:audio-reactivity:broadcast_master",),
        health_refs=("health:broadcast:audio_safe_for_broadcast", "health:scrim:anti_visualizer"),
    ),
    AudioVisualSourceRole.DESK: SourceRolePolicy(
        role=AudioVisualSourceRole.DESK,
        allowed_axes=frozenset(
            {
                VisualModulationAxis.FOCUS,
                VisualModulationAxis.TEXTURE,
                VisualModulationAxis.TRANSITION,
            }
        ),
        source_refs=("source:audio-reactivity:desk",),
        health_refs=("health:studio:desk_contact_mic", "health:scrim:anti_visualizer"),
    ),
    AudioVisualSourceRole.LEGACY_MIXER: SourceRolePolicy(
        role=AudioVisualSourceRole.LEGACY_MIXER,
        allowed_axes=frozenset(
            {
                VisualModulationAxis.COLOR,
                VisualModulationAxis.TEXTURE,
                VisualModulationAxis.DEPTH,
                VisualModulationAxis.GEOMETRY,
                VisualModulationAxis.TRANSITION,
            }
        ),
        source_refs=("source:audio-reactivity:legacy_mixer",),
        health_refs=("health:scrim:anti_visualizer",),
    ),
    AudioVisualSourceRole.UNKNOWN_AUDIO: SourceRolePolicy(
        role=AudioVisualSourceRole.UNKNOWN_AUDIO,
        allowed_axes=frozenset({VisualModulationAxis.COLOR, VisualModulationAxis.TEXTURE}),
        source_refs=("source:audio-reactivity:unknown",),
        health_refs=("health:scrim:anti_visualizer",),
    ),
}


@dataclass(frozen=True)
class ResolvedSignal:
    """Concrete signal value after direct lookup or explicit legacy fallback."""

    requested_source: str
    resolved_source: str
    value: float
    fallback_used: bool


@dataclass(frozen=True)
class AntiVisualizerObservation:
    """One anti-visualizer health observation for the coupling governor."""

    score: float
    audio_rms: float
    fresh: bool
    reason_ref: str = "health:scrim:anti_visualizer"


@dataclass(frozen=True)
class AudioVisualGovernorState:
    """Current dampening state exposed for health/audit surfaces."""

    coupling_gain: float
    dampening_active: bool
    consecutive_offending_windows: int
    consecutive_recovery_windows: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ModulationDecision:
    """Inspectable per-binding modulation decision."""

    binding_key: tuple[str, str]
    source: str
    resolved_source: str
    source_role: AudioVisualSourceRole
    signal_class: AudioSignalClass
    visual_axis: VisualModulationAxis
    register: AudioVisualizerRegister
    raw_value: float
    scale: float
    offset: float
    coupling_gain: float
    target: float
    allowed: bool
    fallback_used: bool
    reason_codes: tuple[str, ...]
    source_refs: tuple[str, ...]
    health_refs: tuple[str, ...]
    public_claim_policy: PublicClaimPolicy = PublicClaimPolicy.NO_CLAIM_AUTHORITY

    def to_dict(self) -> dict[str, object]:
        """Serialize for audit/log surfaces without granting authority."""

        return {
            "binding_key": self.binding_key,
            "source": self.source,
            "resolved_source": self.resolved_source,
            "source_role": self.source_role.value,
            "signal_class": self.signal_class.value,
            "visual_axis": self.visual_axis.value,
            "register": self.register.value,
            "raw_value": self.raw_value,
            "scale": self.scale,
            "offset": self.offset,
            "coupling_gain": self.coupling_gain,
            "target": self.target,
            "allowed": self.allowed,
            "fallback_used": self.fallback_used,
            "reason_codes": self.reason_codes,
            "source_refs": self.source_refs,
            "health_refs": self.health_refs,
            "public_claim_policy": self.public_claim_policy.value,
        }


class AudioVisualModulationGovernor:
    """Resolve source-role modulation and dampen visualizer-register drift."""

    def __init__(
        self,
        *,
        threshold: float = 0.45,
        recovery_delta: float = 0.10,
        hysteresis_windows: int = 3,
        recovery_windows: int = 1,
        minimum_coupling_gain: float = 0.30,
        dampen_rate: float = 0.85,
        recovery_rate: float = 1.15,
        silence_floor: float = 1e-4,
    ) -> None:
        self.threshold = threshold
        self.recovery_delta = recovery_delta
        self.hysteresis_windows = hysteresis_windows
        self.recovery_windows = recovery_windows
        self.minimum_coupling_gain = minimum_coupling_gain
        self.dampen_rate = dampen_rate
        self.recovery_rate = recovery_rate
        self.silence_floor = silence_floor
        self._coupling_gain = 1.0
        self._offending_windows = 0
        self._recovery_windows = 0
        self._reason_codes: tuple[str, ...] = ("nominal",)

    @property
    def state(self) -> AudioVisualGovernorState:
        """Return current dampening state."""

        return AudioVisualGovernorState(
            coupling_gain=self._coupling_gain,
            dampening_active=self._coupling_gain < 1.0,
            consecutive_offending_windows=self._offending_windows,
            consecutive_recovery_windows=self._recovery_windows,
            reason_codes=self._reason_codes,
        )

    def observe(self, observation: AntiVisualizerObservation) -> AudioVisualGovernorState:
        """Update coupling gain from anti-visualizer health."""

        if not observation.fresh:
            self._offending_windows = 0
            self._recovery_windows = 0
            self._coupling_gain = self.minimum_coupling_gain
            self._reason_codes = ("stale_anti_visualizer_state", observation.reason_ref)
            return self.state

        if observation.audio_rms <= self.silence_floor:
            self._offending_windows = 0
            self._recovery_windows += 1
            self._reason_codes = ("silence_guard", observation.reason_ref)
            return self.state

        if observation.score > self.threshold:
            self._offending_windows += 1
            self._recovery_windows = 0
            if self._offending_windows >= self.hysteresis_windows:
                self._coupling_gain = max(
                    self.minimum_coupling_gain,
                    self._coupling_gain * self.dampen_rate,
                )
                self._reason_codes = ("anti_visualizer_score_high", observation.reason_ref)
            else:
                self._reason_codes = ("anti_visualizer_score_pending_hysteresis",)
            return self.state

        if observation.score < self.threshold - self.recovery_delta:
            self._offending_windows = 0
            self._recovery_windows += 1
            if self._recovery_windows >= self.recovery_windows:
                self._coupling_gain = min(1.0, self._coupling_gain * self.recovery_rate)
                self._reason_codes = (
                    "anti_visualizer_score_recovering" if self._coupling_gain < 1.0 else "nominal",
                )
            return self.state

        self._reason_codes = ("anti_visualizer_score_hold",)
        return self.state

    def resolve_signal(
        self,
        source: str,
        signals: Mapping[str, float],
    ) -> ResolvedSignal | None:
        """Resolve a namespaced source against live signals and legacy aliases."""

        direct = self._finite_signal(source, signals)
        if direct is not None:
            return ResolvedSignal(source, source, direct, False)
        for alias in NAMESPACED_AUDIO_SOURCE_ALIASES.get(source, ()):
            fallback = self._finite_signal(alias, signals)
            if fallback is not None:
                return ResolvedSignal(source, alias, fallback, True)
        return None

    def evaluate_binding(
        self,
        binding: ModulationBinding,
        signal: ResolvedSignal,
    ) -> ModulationDecision:
        """Return the governed target for one binding and signal value."""

        role = infer_source_role(signal.requested_source)
        signal_class = infer_audio_signal_class(signal.requested_source)
        axis = infer_visual_axis(binding.node, binding.param)
        register = infer_visualizer_register(binding.node, binding.param, signal.requested_source)
        policy = SOURCE_ROLE_POLICIES.get(role)
        reason_codes = ["no_claim_authority"]
        source_refs: tuple[str, ...] = ()
        health_refs: tuple[str, ...] = ()

        if policy is not None:
            source_refs = policy.source_refs
            health_refs = policy.health_refs
            if axis not in policy.allowed_axes:
                reason_codes.append("axis_not_allowed_for_source_role")
        elif role is AudioVisualSourceRole.NON_AUDIO:
            reason_codes.append("non_audio_untouched")
        else:
            reason_codes.append("unknown_audio_source_role")

        if signal.fallback_used:
            reason_codes.append(f"legacy_source_alias:{signal.resolved_source}")

        if register in FORBIDDEN_VISUALIZER_REGISTERS:
            reason_codes.append("forbidden_visualizer_register")

        if role is not AudioVisualSourceRole.NON_AUDIO and binding.scale < 0.0:
            reason_codes.append("audio_reactivity_negative_scale_not_amplification")

        if (
            role is not AudioVisualSourceRole.NON_AUDIO
            and binding.param.lower() in AUDIO_REACTIVE_BANNED_PARAMS
        ):
            reason_codes.append("audio_reactivity_param_banned")

        allowed = role is AudioVisualSourceRole.NON_AUDIO or (
            policy is not None
            and axis in policy.allowed_axes
            and register not in FORBIDDEN_VISUALIZER_REGISTERS
            and binding.scale >= 0.0
            and binding.param.lower() not in AUDIO_REACTIVE_BANNED_PARAMS
        )
        gain = self.state.coupling_gain if _is_audio_geometry(role, axis) else 1.0
        if gain < 1.0 and _is_audio_geometry(role, axis):
            reason_codes.append("audio_geometry_gain_dampened")

        target = binding.offset
        if allowed:
            target = signal.value * binding.scale * gain + binding.offset

        return ModulationDecision(
            binding_key=(binding.node, binding.param),
            source=signal.requested_source,
            resolved_source=signal.resolved_source,
            source_role=role,
            signal_class=signal_class,
            visual_axis=axis,
            register=register,
            raw_value=signal.value,
            scale=binding.scale,
            offset=binding.offset,
            coupling_gain=gain,
            target=target,
            allowed=allowed,
            fallback_used=signal.fallback_used,
            reason_codes=tuple(reason_codes),
            source_refs=source_refs,
            health_refs=health_refs,
        )

    @staticmethod
    def _finite_signal(source: str, signals: Mapping[str, float]) -> float | None:
        value = signals.get(source)
        if value is None:
            return None
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        return numeric


def infer_source_role(source: str) -> AudioVisualSourceRole:
    """Infer role from a namespaced or legacy modulation source name."""

    if source.startswith(("music.", "programme_music.")):
        return AudioVisualSourceRole.PROGRAMME_MUSIC
    if source.startswith("operator_voice."):
        return AudioVisualSourceRole.OPERATOR_VOICE
    if source.startswith(("tts.", "hapax_tts.")):
        return AudioVisualSourceRole.HAPAX_TTS
    if source.startswith(("youtube.", "yt.")):
        return AudioVisualSourceRole.YOUTUBE
    if source.startswith("broadcast."):
        return AudioVisualSourceRole.BROADCAST
    if source.startswith("desk."):
        return AudioVisualSourceRole.DESK
    if source in {
        "audio_beat",
        "audio_rms",
        "mixer",
        "mixer_bass",
        "mixer_energy",
        "mixer_high",
        "mixer_master",
        "mixer_mid",
        "onset_hat",
        "onset_kick",
        "onset_snare",
        "sidechain_kick",
        "spectral_centroid",
    }:
        return AudioVisualSourceRole.LEGACY_MIXER
    if "." in source and source.split(".", 1)[0] in {
        "voice",
        "audio",
        "source",
        "input",
    }:
        return AudioVisualSourceRole.UNKNOWN_AUDIO
    return AudioVisualSourceRole.NON_AUDIO


def infer_audio_signal_class(source: str) -> AudioSignalClass:
    """Classify audio source names by band and temporal shape."""

    role = infer_source_role(source)
    if role is AudioVisualSourceRole.NON_AUDIO:
        return AudioSignalClass.NON_AUDIO

    token = source.lower()
    if "centroid" in token:
        return AudioSignalClass.SPECTRAL_CENTROID
    if "onset_rate" in token:
        return AudioSignalClass.ONSET_RATE
    if any(name in token for name in ("kick", "bass_onset", "low_onset")):
        return AudioSignalClass.LOW_TRANSIENT
    if "snare" in token:
        return AudioSignalClass.MID_TRANSIENT
    if any(name in token for name in ("hat", "treble_onset", "high_onset")):
        return AudioSignalClass.HIGH_TRANSIENT
    if any(name in token for name in ("bass", "low")):
        return AudioSignalClass.LOW_SUSTAINED
    if any(name in token for name in ("mid", "voice")):
        return AudioSignalClass.MID_SUSTAINED
    if any(name in token for name in ("treble", "high")):
        return AudioSignalClass.HIGH_SUSTAINED
    if any(name in token for name in ("rms", "energy", "master")):
        return AudioSignalClass.BROADBAND_SUSTAINED
    if any(name in token for name in ("onset", "beat")):
        return AudioSignalClass.LOW_TRANSIENT
    return AudioSignalClass.UNKNOWN_AUDIO


def infer_visual_axis(node: str, param: str) -> VisualModulationAxis:
    """Classify a node/param binding into a bounded visual axis."""

    token = f"{node}.{param}".lower()
    if any(
        name in token
        for name in (
            "hue",
            "color",
            "saturation",
            "brightness",
            "contrast",
            "palette",
            "gamma",
            "sepia",
            "rgb_split",
            "chromatic",
            "edge_glow",
            "blend",
        )
    ):
        return VisualModulationAxis.COLOR
    if any(
        name in token
        for name in (
            "noise",
            "texture",
            "grain",
            "pixel_sort",
            "sort_length",
            "cell_size",
            "dot_size",
            "color_levels",
            "levels",
            "feed_rate",
            "kill_rate",
            "n_bands",
        )
    ):
        return VisualModulationAxis.TEXTURE
    if any(
        name in token
        for name in (
            "bloom",
            "vignette",
            "trail.opacity",
            "refraction",
            "decay",
            "decay_curve",
            "frame_count",
            "feedback",
            "trace",
        )
    ):
        return VisualModulationAxis.DEPTH
    if any(
        name in token
        for name in (
            "drift",
            "amplitude",
            "radius",
            "offset",
            "warp",
            "speed",
            "rotation",
            "position",
            "displacement",
            "strength_x",
            "strength_y",
            "twist",
            "tri_scale",
            "line_width",
            "scale",
        )
    ):
        return VisualModulationAxis.GEOMETRY
    if any(name in token for name in ("cut", "transition", "crossfade", "strobe")):
        return VisualModulationAxis.TRANSITION
    if any(name in token for name in ("focus", "foreground", "attention")):
        return VisualModulationAxis.FOCUS
    if any(name in token for name in ("claim", "posture", "boundary")):
        return VisualModulationAxis.CLAIM_POSTURE
    return VisualModulationAxis.UNKNOWN


def infer_visualizer_register(
    node: str,
    param: str,
    source: str,
) -> AudioVisualizerRegister:
    """Detect forbidden visualizer trope registers from binding names."""

    token = f"{node}.{param}.{source}".lower()
    if "waveform" in token or "oscilloscope" in token:
        return AudioVisualizerRegister.WAVEFORM
    if "fft" in token:
        return AudioVisualizerRegister.FFT
    if "spectrum" in token or "mel_bar" in token:
        return AudioVisualizerRegister.SPECTRUM_BARS
    if "beat_icon" in token or "beat_iconography" in token:
        return AudioVisualizerRegister.BEAT_ICONOGRAPHY
    if ("radial" in token or "ring" in token) and any(
        onset in source for onset in ("onset", "kick", "beat")
    ):
        return AudioVisualizerRegister.RADIAL_PULSE
    if infer_visual_axis(node, param) is VisualModulationAxis.COLOR:
        return AudioVisualizerRegister.BROADBAND_COLOR
    if infer_visual_axis(node, param) in AUDIO_GEOMETRY_AXES:
        return AudioVisualizerRegister.STRUCTURAL_MOTION
    if infer_visual_axis(node, param) is VisualModulationAxis.TEXTURE:
        return AudioVisualizerRegister.STRUCTURAL_TEXTURE
    return AudioVisualizerRegister.NONE


def _is_audio_geometry(role: AudioVisualSourceRole, axis: VisualModulationAxis) -> bool:
    return role is not AudioVisualSourceRole.NON_AUDIO and axis in AUDIO_GEOMETRY_AXES


__all__ = [
    "AUDIO_GEOMETRY_AXES",
    "AUDIO_REACTIVE_BANNED_PARAMS",
    "FORBIDDEN_VISUALIZER_REGISTERS",
    "NAMESPACED_AUDIO_SOURCE_ALIASES",
    "SOURCE_ROLE_POLICIES",
    "AntiVisualizerObservation",
    "AudioSignalClass",
    "AudioVisualGovernorState",
    "AudioVisualModulationGovernor",
    "AudioVisualSourceRole",
    "AudioVisualizerRegister",
    "ModulationDecision",
    "PublicClaimPolicy",
    "ResolvedSignal",
    "SourceRolePolicy",
    "VisualModulationAxis",
    "infer_audio_signal_class",
    "infer_source_role",
    "infer_visual_axis",
    "infer_visualizer_register",
]
