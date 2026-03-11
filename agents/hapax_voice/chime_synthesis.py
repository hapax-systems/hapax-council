"""Synthesize the Crystal Tap chime family as WAV files.

Generates four inharmonic bell-like earcons:
- activation: ascending D6->G6 perfect fourth (350ms)
- deactivation: descending G6->D6 perfect fourth (280ms)
- error: single A5 note (200ms)
- completion: single D6 note (150ms)

All chimes use inharmonic partial ratios (1.0 : 2.406 : 3.758) to create
a metallic bell timbre distinguishable from musical instruments.
"""
from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SAMPLE_RATE = 48000


@dataclass
class NoteSpec:
    """Specification for a single note in a chime."""
    frequency: float
    onset_ms: float
    duration_ms: float
    attack_ms: float = 15.0
    decay_tau_ms: float = 60.0
    peak_amplitude: float = 0.7
    partial_ratios: list[float] = field(default_factory=lambda: [1.0, 2.406, 3.758])
    partial_levels_db: list[float] = field(default_factory=lambda: [0.0, -6.0, -12.0])


@dataclass
class ChimeSpec:
    """Specification for a complete chime."""
    notes: list[NoteSpec]
    total_duration_ms: float


def _db_to_linear(db: float) -> float:
    return 10 ** (db / 20.0)


def _render_note(note: NoteSpec, total_samples: int) -> np.ndarray:
    """Render a single note with inharmonic partials and envelope."""
    audio = np.zeros(total_samples, dtype=np.float64)
    onset_sample = int(note.onset_ms / 1000.0 * SAMPLE_RATE)
    duration_samples = int(note.duration_ms / 1000.0 * SAMPLE_RATE)
    attack_samples = int(note.attack_ms / 1000.0 * SAMPLE_RATE)
    end_sample = min(onset_sample + duration_samples, total_samples)

    if onset_sample >= total_samples:
        return audio

    t = np.arange(duration_samples) / SAMPLE_RATE

    signal = np.zeros(duration_samples, dtype=np.float64)
    for ratio, level_db in zip(note.partial_ratios, note.partial_levels_db):
        freq = note.frequency * ratio
        amplitude = _db_to_linear(level_db)
        signal += amplitude * np.sin(2 * np.pi * freq * t)

    envelope = np.ones(duration_samples, dtype=np.float64)
    if attack_samples > 0:
        envelope[:attack_samples] = np.linspace(0.0, 1.0, attack_samples)
    decay_start = attack_samples
    decay_t = np.arange(duration_samples - decay_start) / SAMPLE_RATE
    tau = note.decay_tau_ms / 1000.0
    envelope[decay_start:] = np.exp(-decay_t / tau)

    signal *= envelope * note.peak_amplitude

    fade_samples = int(0.005 * SAMPLE_RATE)
    if fade_samples > 0 and duration_samples > fade_samples:
        signal[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples)

    actual_len = min(duration_samples, end_sample - onset_sample)
    audio[onset_sample:onset_sample + actual_len] += signal[:actual_len]

    return audio


CHIME_SPECS: dict[str, ChimeSpec] = {
    "activation": ChimeSpec(
        notes=[
            NoteSpec(frequency=1175.0, onset_ms=0, duration_ms=180,
                     attack_ms=15, decay_tau_ms=60, peak_amplitude=0.7),
            NoteSpec(frequency=1568.0, onset_ms=80, duration_ms=270,
                     attack_ms=15, decay_tau_ms=80, peak_amplitude=0.85,
                     partial_levels_db=[0.0, -6.0, -14.0]),
        ],
        total_duration_ms=350,
    ),
    "deactivation": ChimeSpec(
        notes=[
            NoteSpec(frequency=1568.0, onset_ms=0, duration_ms=140,
                     attack_ms=15, decay_tau_ms=40, peak_amplitude=0.6),
            NoteSpec(frequency=1175.0, onset_ms=60, duration_ms=220,
                     attack_ms=15, decay_tau_ms=60, peak_amplitude=0.5,
                     partial_levels_db=[0.0, -6.0, -14.0]),
        ],
        total_duration_ms=280,
    ),
    "error": ChimeSpec(
        notes=[
            NoteSpec(frequency=880.0, onset_ms=0, duration_ms=200,
                     attack_ms=10, decay_tau_ms=50, peak_amplitude=0.5),
        ],
        total_duration_ms=200,
    ),
    "completion": ChimeSpec(
        notes=[
            NoteSpec(frequency=1175.0, onset_ms=0, duration_ms=150,
                     attack_ms=15, decay_tau_ms=40, peak_amplitude=0.4),
        ],
        total_duration_ms=150,
    ),
}


def synthesize_chime(name: str) -> np.ndarray:
    """Synthesize a chime by name, returning int16 PCM samples at 48kHz."""
    spec = CHIME_SPECS[name]
    total_samples = int(spec.total_duration_ms / 1000.0 * SAMPLE_RATE)

    audio = np.zeros(total_samples, dtype=np.float64)
    for note in spec.notes:
        audio += _render_note(note, total_samples)

    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.707

    return (audio * 32767).astype(np.int16)


def generate_all_chimes(output_dir: Path) -> None:
    """Generate all chime WAV files in the given directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for name in CHIME_SPECS:
        audio = synthesize_chime(name)
        path = output_dir / f"{name}.wav"
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SAMPLE_RATE)
            f.writeframes(audio.tobytes())
