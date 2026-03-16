"""Vocal effects processor — VST-style processing chain for TTS output.

Processes raw TTS audio through a configurable effects chain before playback.
Uses pedalboard (Spotify) for both built-in DSP and external VST3 plugins.

Presets are YAML files in ~/.config/hapax-voice/vocal-fx/. Each defines an
ordered chain of effects with parameters. The active preset can be swapped
at runtime — Hapax can call switch_preset() based on context (conversation
vs briefing vs notification) or environmental factors.

Design constraints:
- CPU-only, zero GPU contention (~4ms for a 10-effect chain on 3s audio)
- Lazy-loads VST3 plugins on first use
- Fail-open: if effects fail, returns unprocessed audio
- Thread-safe: process() can be called from the TTS executor thread
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
PRESETS_DIR = Path.home() / ".config" / "hapax-voice" / "vocal-fx"
LSP_VST3 = Path("/usr/lib/vst3/lsp-plugins.vst3")
DRAGONFLY_ROOM_VST3 = Path("/usr/lib/vst3/DragonflyRoomReverb.vst3")
RNNOISE_VST3 = Path("/usr/lib/vst3/rnnoise.vst3")


# ── Built-in effect constructors ─────────────────────────────────────────────

def _build_builtin(name: str, params: dict[str, Any]) -> Any:
    """Construct a pedalboard built-in effect by name."""
    import pedalboard as pb

    constructors = {
        "highpass": pb.HighpassFilter,
        "lowpass": pb.LowpassFilter,
        "high_shelf": pb.HighShelfFilter,
        "low_shelf": pb.LowShelfFilter,
        "peak": pb.PeakFilter,
        "compressor": pb.Compressor,
        "limiter": pb.Limiter,
        "noise_gate": pb.NoiseGate,
        "gain": pb.Gain,
        "reverb": pb.Reverb,
        "distortion": pb.Distortion,
        "chorus": pb.Chorus,
        "delay": pb.Delay,
        "convolution": pb.Convolution,
        "pitch_shift": pb.PitchShift,
    }
    cls = constructors.get(name)
    if cls is None:
        raise ValueError(f"Unknown built-in effect: {name!r}. Available: {sorted(constructors)}")
    return cls(**params)


def _build_vst3(plugin_path: str, plugin_name: str | None, params: dict[str, Any]) -> Any:
    """Load an external VST3 plugin and set parameters."""
    from pedalboard import load_plugin

    kwargs: dict[str, Any] = {}
    if plugin_name:
        kwargs["plugin_name"] = plugin_name

    plugin = load_plugin(plugin_path, **kwargs)

    for key, value in params.items():
        if hasattr(plugin, key) or key in plugin.parameters:
            setattr(plugin, key, value)
        else:
            log.warning("VST3 %s: unknown parameter %r (available: %s)",
                        plugin_name or plugin_path, key,
                        list(plugin.parameters.keys())[:10])
    return plugin


# ── Preset schema ────────────────────────────────────────────────────────────

@dataclass
class EffectSpec:
    """Single effect in a chain."""

    type: str  # "builtin" or "vst3"
    name: str  # effect name or VST3 plugin name
    params: dict[str, Any] = field(default_factory=dict)
    plugin_path: str = ""  # for vst3 only


@dataclass
class VocalPreset:
    """A named effects chain."""

    name: str
    description: str = ""
    effects: list[EffectSpec] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> VocalPreset:
        effects = []
        for fx in data.get("effects", []):
            effects.append(EffectSpec(
                type=fx.get("type", "builtin"),
                name=fx["name"],
                params=fx.get("params", {}),
                plugin_path=fx.get("plugin_path", ""),
            ))
        return VocalPreset(
            name=data["name"],
            description=data.get("description", ""),
            effects=effects,
        )


# ── Default presets (no files needed) ────────────────────────────────────────

_DEFAULT_PRESETS: dict[str, dict] = {
    "warm_conversation": {
        "name": "warm_conversation",
        "description": "Gentle warmth and presence for natural conversation",
        "effects": [
            {"type": "builtin", "name": "highpass", "params": {"cutoff_frequency_hz": 80}},
            {"type": "builtin", "name": "noise_gate", "params": {
                "threshold_db": -40, "release_ms": 100,
            }},
            {"type": "builtin", "name": "compressor", "params": {
                "threshold_db": -18, "ratio": 2.5, "attack_ms": 8, "release_ms": 100,
            }},
            {"type": "builtin", "name": "low_shelf", "params": {
                "cutoff_frequency_hz": 200, "gain_db": 1.5,
            }},
            {"type": "builtin", "name": "peak", "params": {
                "cutoff_frequency_hz": 3000, "gain_db": 2.0, "q": 1.0,
            }},
            {"type": "builtin", "name": "high_shelf", "params": {
                "cutoff_frequency_hz": 8000, "gain_db": 1.5,
            }},
            {"type": "builtin", "name": "reverb", "params": {
                "room_size": 0.12, "wet_level": 0.06,
            }},
            {"type": "builtin", "name": "limiter", "params": {"threshold_db": -1.0}},
            {"type": "builtin", "name": "gain", "params": {"gain_db": -1.0}},
        ],
    },
    "clear_notification": {
        "name": "clear_notification",
        "description": "Crisp and present for short alerts — cuts through ambient",
        "effects": [
            {"type": "builtin", "name": "highpass", "params": {"cutoff_frequency_hz": 120}},
            {"type": "builtin", "name": "compressor", "params": {
                "threshold_db": -14, "ratio": 4.0, "attack_ms": 3, "release_ms": 60,
            }},
            {"type": "builtin", "name": "peak", "params": {
                "cutoff_frequency_hz": 2500, "gain_db": 3.0, "q": 0.8,
            }},
            {"type": "builtin", "name": "high_shelf", "params": {
                "cutoff_frequency_hz": 6000, "gain_db": 2.5,
            }},
            {"type": "builtin", "name": "limiter", "params": {"threshold_db": -0.5}},
            {"type": "builtin", "name": "gain", "params": {"gain_db": -0.5}},
        ],
    },
    "broadcast_briefing": {
        "name": "broadcast_briefing",
        "description": "Radio/podcast quality for longer spoken content",
        "effects": [
            {"type": "builtin", "name": "highpass", "params": {"cutoff_frequency_hz": 80}},
            {"type": "builtin", "name": "noise_gate", "params": {
                "threshold_db": -45, "release_ms": 150,
            }},
            {"type": "builtin", "name": "compressor", "params": {
                "threshold_db": -20, "ratio": 3.0, "attack_ms": 5, "release_ms": 80,
            }},
            {"type": "builtin", "name": "low_shelf", "params": {
                "cutoff_frequency_hz": 180, "gain_db": 2.0,
            }},
            {"type": "builtin", "name": "peak", "params": {
                "cutoff_frequency_hz": 2800, "gain_db": 2.5, "q": 1.2,
            }},
            {"type": "builtin", "name": "peak", "params": {
                "cutoff_frequency_hz": 5000, "gain_db": 1.5, "q": 0.8,
            }},
            {"type": "builtin", "name": "high_shelf", "params": {
                "cutoff_frequency_hz": 10000, "gain_db": 1.0,
            }},
            {"type": "builtin", "name": "distortion", "params": {"drive_db": 1.5}},
            {"type": "builtin", "name": "reverb", "params": {
                "room_size": 0.2, "wet_level": 0.1,
            }},
            {"type": "builtin", "name": "limiter", "params": {"threshold_db": -1.0}},
            {"type": "builtin", "name": "gain", "params": {"gain_db": -1.5}},
        ],
    },
    "bypass": {
        "name": "bypass",
        "description": "No processing — raw TTS output",
        "effects": [],
    },
}

# Map use_case → preset name
_USE_CASE_PRESETS: dict[str, str] = {
    "conversation": "warm_conversation",
    "notification": "clear_notification",
    "briefing": "broadcast_briefing",
    "proactive": "warm_conversation",
}


# ── Processor ────────────────────────────────────────────────────────────────

class VocalFXProcessor:
    """Applies a vocal effects chain to TTS audio.

    Thread-safe for concurrent calls from the TTS executor.
    Fail-open: returns unprocessed audio on any error.
    """

    def __init__(self, presets_dir: Path | None = None) -> None:
        self._presets_dir = presets_dir or PRESETS_DIR
        self._presets: dict[str, VocalPreset] = {}
        self._chains: dict[str, Any] = {}  # preset_name → Pedalboard instance
        self._active_preset: str = "warm_conversation"
        self._load_presets()

    def _load_presets(self) -> None:
        """Load default presets, then override/extend from disk."""
        # Defaults
        for name, data in _DEFAULT_PRESETS.items():
            self._presets[name] = VocalPreset.from_dict(data)

        # Disk overrides
        if self._presets_dir.exists():
            for path in sorted(self._presets_dir.glob("*.yaml")):
                try:
                    data = yaml.safe_load(path.read_text())
                    if data and "name" in data:
                        preset = VocalPreset.from_dict(data)
                        self._presets[preset.name] = preset
                        log.info("Loaded vocal preset: %s from %s", preset.name, path)
                except Exception:
                    log.exception("Failed to load vocal preset from %s", path)

    def _build_chain(self, preset: VocalPreset) -> Any:
        """Build a pedalboard.Pedalboard from a preset spec."""
        from pedalboard import Pedalboard

        effects = []
        for spec in preset.effects:
            try:
                if spec.type == "vst3":
                    fx = _build_vst3(spec.plugin_path, spec.name, spec.params)
                else:
                    fx = _build_builtin(spec.name, spec.params)
                effects.append(fx)
            except Exception:
                log.exception("Failed to build effect %s/%s — skipping", spec.type, spec.name)

        return Pedalboard(effects)

    def _get_chain(self, preset_name: str) -> Any:
        """Get or lazily build the chain for a preset."""
        if preset_name not in self._chains:
            preset = self._presets.get(preset_name)
            if preset is None:
                log.warning("Unknown preset %r, falling back to bypass", preset_name)
                return None
            self._chains[preset_name] = self._build_chain(preset)
        return self._chains[preset_name]

    @property
    def active_preset(self) -> str:
        return self._active_preset

    @property
    def available_presets(self) -> list[str]:
        return sorted(self._presets.keys())

    def switch_preset(self, preset_name: str) -> bool:
        """Switch the active preset. Returns True if successful."""
        if preset_name not in self._presets:
            log.warning("Cannot switch to unknown preset: %s", preset_name)
            return False
        self._active_preset = preset_name
        log.info("Vocal FX preset switched to: %s", preset_name)
        return True

    def preset_for_use_case(self, use_case: str) -> str:
        """Get the default preset for a given use case."""
        return _USE_CASE_PRESETS.get(use_case, self._active_preset)

    def process(self, pcm_bytes: bytes, use_case: str | None = None) -> bytes:
        """Process PCM int16 audio through the active effects chain.

        Args:
            pcm_bytes: Raw PCM int16 bytes at 24kHz mono.
            use_case: If provided, selects preset by use case instead of active preset.

        Returns:
            Processed PCM int16 bytes. Returns input unchanged on error.
        """
        if not pcm_bytes:
            return pcm_bytes

        preset_name = self.preset_for_use_case(use_case) if use_case else self._active_preset
        chain = self._get_chain(preset_name)
        if chain is None or len(chain) == 0:
            return pcm_bytes

        try:
            # PCM int16 → float32 for processing
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32767.0
            audio = audio.reshape(1, -1)  # pedalboard expects (channels, samples)

            processed = chain(audio, SAMPLE_RATE)

            # float32 → PCM int16
            processed = np.clip(processed.squeeze(), -1.0, 1.0)
            return (processed * 32767).astype(np.int16).tobytes()
        except Exception:
            log.exception("Vocal FX processing failed — returning unprocessed audio")
            return pcm_bytes

    def reload_presets(self) -> None:
        """Reload presets from disk and clear cached chains."""
        self._chains.clear()
        self._presets.clear()
        self._load_presets()
        log.info("Vocal FX presets reloaded (%d available)", len(self._presets))
