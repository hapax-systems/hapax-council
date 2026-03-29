"""shared/beat_tracker.py — Beat tracking via beat_this.

Wraps the beat_this model for beat and downbeat detection on audio.
Returns BPM estimates and beat grid timestamps. GPU model — must
respect VRAMLock for coordination with audio_processor and hapax_daimonion.

The model is lazy-loaded on first call.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

BEAT_THIS_SAMPLE_RATE = 22050

# ── Lazy model singleton ────────────────────────────────────────────────────

_beat_model = None


def _get_model():
    """Load the beat_this model on first call. Requires GPU."""
    global _beat_model
    if _beat_model is not None:
        return _beat_model

    from beat_this.inference import File2Beats

    log.info("Loading beat_this model")
    model = File2Beats(device="cuda", dbn=True)
    _beat_model = model
    log.info("beat_this model loaded")
    return _beat_model


def unload_model() -> None:
    """Release the beat_this model from memory."""
    global _beat_model
    if _beat_model is not None:
        import gc

        import torch

        del _beat_model
        _beat_model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        log.info("beat_this model unloaded")


# ── Data types ───────────────────────────────────────────────────────────────


class BeatGrid:
    """Beat tracking result with BPM and beat timestamps."""

    def __init__(
        self,
        beats: np.ndarray,
        downbeats: np.ndarray,
        bpm: float,
        duration: float,
    ) -> None:
        self.beats = beats  # timestamps in seconds
        self.downbeats = downbeats  # downbeat timestamps in seconds
        self.bpm = bpm
        self.duration = duration

    @property
    def beat_count(self) -> int:
        return len(self.beats)

    @property
    def downbeat_count(self) -> int:
        return len(self.downbeats)

    @property
    def time_signature_guess(self) -> int:
        """Estimate time signature from beats-per-downbeat ratio."""
        if self.downbeat_count < 2 or self.beat_count < 4:
            return 4  # default
        beats_per_bar = self.beat_count / max(1, self.downbeat_count)
        if 2.5 < beats_per_bar < 3.5:
            return 3
        if 5.5 < beats_per_bar < 6.5:
            return 6
        return 4


# ── Public API ───────────────────────────────────────────────────────────────


def estimate_bpm(beats: np.ndarray) -> float:
    """Estimate BPM from beat timestamps.

    Uses median inter-beat interval for robustness against outliers.
    """
    if len(beats) < 2:
        return 0.0
    intervals = np.diff(beats)
    if len(intervals) == 0:
        return 0.0
    median_interval = np.median(intervals)
    if median_interval <= 0:
        return 0.0
    return 60.0 / median_interval


def track_beats(audio_path: str) -> BeatGrid:
    """Run beat tracking on an audio file.

    Args:
        audio_path: Path to audio file (WAV, FLAC, etc.)

    Returns:
        BeatGrid with beat timestamps, downbeats, and BPM.

    Raises:
        RuntimeError: If beat tracking fails.
    """
    import torchaudio

    model = _get_model()

    try:
        beats, downbeats = model(audio_path)
    except Exception as exc:
        raise RuntimeError(f"Beat tracking failed: {exc}") from exc

    # Load duration
    info = torchaudio.info(audio_path)
    duration = info.num_frames / info.sample_rate

    bpm = estimate_bpm(beats)

    log.info(
        "Beat tracked %s: %.1f BPM, %d beats, %d downbeats",
        audio_path,
        bpm,
        len(beats),
        len(downbeats),
    )

    return BeatGrid(
        beats=beats,
        downbeats=downbeats,
        bpm=bpm,
        duration=duration,
    )


def track_beats_from_waveform(
    waveform: np.ndarray,
    sr: int = BEAT_THIS_SAMPLE_RATE,
) -> BeatGrid:
    """Run beat tracking on a waveform array.

    Saves to a temp file and runs track_beats. This is a convenience
    for when the waveform is already in memory.
    """
    import tempfile

    import soundfile as sf

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        sf.write(tmp_path, waveform, sr)
        return track_beats(tmp_path)
    finally:
        from pathlib import Path

        Path(tmp_path).unlink(missing_ok=True)
