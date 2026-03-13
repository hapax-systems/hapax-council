"""SampleBank — pre-loaded WAV samples organized by action and energy level.

Loads WAVs from a directory structure:
  samples/vocal_throw/high_001.wav
  samples/ad_lib/medium_001.wav
  samples/ad_lib/low_001.wav

Selects samples by action + energy RMS, cycling to avoid repetition.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_ENERGY_THRESHOLDS = {"high": 0.7, "medium": 0.3, "low": 0.0}


@dataclass(frozen=True)
class SampleEntry:
    """A pre-loaded audio sample."""

    name: str
    action: str
    energy_tag: str
    pcm_data: bytes
    sample_rate: int
    channels: int


class SampleBank:
    """Pre-loads WAVs from directory, organized by action/energy.

    Directory layout:
      {base_dir}/{action}/{energy_tag}_{index}.wav

    select(action, energy_rms) maps energy RMS to an energy tag,
    then cycles through matching samples to avoid repetition.
    """

    def __init__(self, base_dir: Path, sample_rate: int = 44100) -> None:
        self._base_dir = Path(base_dir).expanduser()
        self._expected_rate = sample_rate
        # action → energy_tag → list[SampleEntry]
        self._samples: dict[str, dict[str, list[SampleEntry]]] = {}
        # action → energy_tag → cycle index
        self._cycle_idx: dict[str, dict[str, int]] = {}

    def load(self) -> int:
        """Load all WAVs from the directory. Returns count of samples loaded."""
        if not self._base_dir.is_dir():
            log.warning("Sample directory does not exist: %s", self._base_dir)
            return 0

        count = 0
        for action_dir in sorted(self._base_dir.iterdir()):
            if not action_dir.is_dir():
                continue
            action = action_dir.name
            self._samples.setdefault(action, {})
            self._cycle_idx.setdefault(action, {})

            for wav_path in sorted(action_dir.glob("*.wav")):
                entry = self._load_wav(wav_path, action)
                if entry is not None:
                    self._samples[action].setdefault(entry.energy_tag, [])
                    self._samples[action][entry.energy_tag].append(entry)
                    self._cycle_idx[action].setdefault(entry.energy_tag, 0)
                    count += 1

        log.info("SampleBank loaded %d samples from %s", count, self._base_dir)
        return count

    def _load_wav(self, path: Path, action: str) -> SampleEntry | None:
        """Load a single WAV file. Returns None on failure."""
        try:
            with wave.open(str(path), "rb") as f:
                pcm_data = f.readframes(f.getnframes())
                sample_rate = f.getframerate()
                channels = f.getnchannels()
        except Exception as exc:
            log.warning("Failed to load WAV %s: %s", path.name, exc)
            return None

        # Parse energy tag from filename: e.g. "high_001.wav" → "high"
        stem = path.stem
        energy_tag = stem.split("_")[0] if "_" in stem else "medium"
        if energy_tag not in _ENERGY_THRESHOLDS:
            energy_tag = "medium"

        return SampleEntry(
            name=stem,
            action=action,
            energy_tag=energy_tag,
            pcm_data=pcm_data,
            sample_rate=sample_rate,
            channels=channels,
        )

    def select(self, action: str, energy_rms: float) -> SampleEntry | None:
        """Select a sample matching action and energy level, cycling to avoid repeats.

        Returns None if no matching sample exists (never raises).
        """
        action_samples = self._samples.get(action)
        if not action_samples:
            log.debug("No samples for action: %s", action)
            return None

        tag = self._energy_tag(energy_rms)

        # Try exact tag, then fall back to any available tag
        entries = action_samples.get(tag)
        if not entries:
            for fallback_tag in ("medium", "low", "high"):
                entries = action_samples.get(fallback_tag)
                if entries:
                    tag = fallback_tag
                    break
        if not entries:
            return None

        idx = self._cycle_idx[action].get(tag, 0) % len(entries)
        self._cycle_idx[action][tag] = idx + 1
        return entries[idx]

    @staticmethod
    def _energy_tag(energy_rms: float) -> str:
        """Map energy RMS to tag."""
        if energy_rms >= 0.7:
            return "high"
        if energy_rms >= 0.3:
            return "medium"
        return "low"

    @property
    def sample_count(self) -> int:
        return sum(len(es) for by_tag in self._samples.values() for es in by_tag.values())
