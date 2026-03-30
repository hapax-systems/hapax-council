"""Studio ingestion perception backend — audio classification for EnvironmentState.

Provides production activity, music genre, flow state, emotion, and audio
energy by running CLAP classification on a background thread. The contribute()
method reads from a thread-safe cache only (never blocks on inference).

Tier: SLOW (~12s poll cadence). The background thread runs CLAP inference
independently and updates the cache. contribute() is always <1ms.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

# Default audio capture path (PipeWire monitor source)
_DEFAULT_CAPTURE_SECONDS = 10.0
_DEFAULT_POLL_INTERVAL = 12.0

# CLAP activity labels for zero-shot classification
_ACTIVITY_LABELS = [
    "music production session",
    "sample digging and listening",
    "beat making",
    "recording vocals",
    "mixing and mastering",
    "casual conversation",
    "silence or ambient noise",
]

# CLAP genre labels
_GENRE_LABELS = [
    "hip hop beat",
    "trap beat",
    "boom bap beat",
    "lo-fi hip hop",
    "jazz",
    "soul music",
    "funk music",
    "r&b",
    "electronic music",
    "ambient music",
    "rock music",
    "pop music",
]

# Activity label → production_activity mapping
_ACTIVITY_MAP = {
    "music production session": "production",
    "sample digging and listening": "production",
    "beat making": "production",
    "recording vocals": "production",
    "mixing and mastering": "production",
    "casual conversation": "conversation",
    "silence or ambient noise": "idle",
}


class _InferenceCache:
    """Thread-safe cache for CLAP inference results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._production_activity: str = "idle"
        self._music_genre: str = "unknown"
        self._flow_state_score: float = 0.0
        self._emotion_valence: float = 0.0
        self._emotion_arousal: float = 0.0
        self._audio_energy_rms: float = 0.0
        self._updated_at: float = 0.0

    def update(
        self,
        *,
        production_activity: str,
        music_genre: str,
        flow_state_score: float,
        audio_energy_rms: float,
    ) -> None:
        with self._lock:
            self._production_activity = production_activity
            self._music_genre = music_genre
            self._flow_state_score = flow_state_score
            self._audio_energy_rms = audio_energy_rms
            self._updated_at = time.monotonic()

    def read(self) -> dict:
        with self._lock:
            return {
                "production_activity": self._production_activity,
                "music_genre": self._music_genre,
                "flow_state_score": self._flow_state_score,
                "emotion_valence": self._emotion_valence,
                "emotion_arousal": self._emotion_arousal,
                "audio_energy_rms": self._audio_energy_rms,
                "updated_at": self._updated_at,
            }


def _compute_rms(waveform: np.ndarray) -> float:
    """Compute RMS energy of a waveform."""
    if len(waveform) == 0:
        return 0.0
    return float(np.sqrt(np.mean(waveform**2)))


def _estimate_flow_score(activity: str, energy_rms: float, genre_confidence: float) -> float:
    """Estimate a flow state score from activity + energy.

    Simple heuristic: production activity + audible energy + confident genre
    classification all contribute to a higher flow score.
    """
    score = 0.0
    if activity == "production":
        score += 0.5
    elif activity == "conversation":
        score += 0.1

    # Audio energy above noise floor suggests active work
    if energy_rms > 0.01:
        score += min(0.3, energy_rms * 10)

    # Confident genre classification suggests structured content
    if genre_confidence > 0.3:
        score += 0.2

    return min(1.0, score)


def _capture_audio(duration_s: float, sample_rate: int = 48000) -> np.ndarray | None:
    """Capture audio from the default PipeWire monitor source.

    Returns a 1-D float32 numpy array, or None on failure.
    """
    tmp_path: str | None = None
    try:
        # Use PipeWire's built-in monitor capture via pacat
        import subprocess

        import soundfile as sf

        from agents._tmp_wav import tmp_wav_path

        tmp_path = str(tmp_wav_path())

        with open(tmp_path, "wb") as out_fh:
            subprocess.run(
                [
                    "pacat",
                    "--record",
                    "--format=float32le",
                    "--channels=1",
                    f"--rate={sample_rate}",
                    "--file-format=wav",
                ],
                stdout=out_fh,
                timeout=duration_s + 1,
                check=False,
            )
        data, sr = sf.read(tmp_path, dtype="float32")
        if len(data) == 0:
            return None
        return data if data.ndim == 1 else data[:, 0]
    except Exception as exc:
        log.debug("Audio capture failed: %s", exc)
        return None
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


class StudioIngestionBackend:
    """PerceptionBackend that provides studio audio classification.

    Provides:
      - production_activity: str (production/conversation/idle)
      - music_genre: str (top CLAP genre label)
      - flow_state_score: float (0.0-1.0, heuristic)
      - emotion_valence: float (placeholder, 0.0 until HSEmotion in Batch 7)
      - emotion_arousal: float (placeholder, 0.0 until HSEmotion in Batch 7)
      - audio_energy_rms: float (RMS energy of captured audio)
    """

    def __init__(
        self,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        capture_seconds: float = _DEFAULT_CAPTURE_SECONDS,
    ) -> None:
        self._poll_interval = poll_interval
        self._capture_seconds = capture_seconds
        self._cache = _InferenceCache()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._b_activity: Behavior[str] = Behavior("idle")
        self._b_genre: Behavior[str] = Behavior("unknown")
        self._b_flow: Behavior[float] = Behavior(0.0)
        self._b_valence: Behavior[float] = Behavior(0.0)
        self._b_arousal: Behavior[float] = Behavior(0.0)
        self._b_energy: Behavior[float] = Behavior(0.0)

    @property
    def name(self) -> str:
        return "studio_ingestion"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset(
            {
                "production_activity",
                "music_genre",
                "flow_state_score",
                "emotion_valence",
                "emotion_arousal",
                "audio_energy_rms",
            }
        )

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        try:
            import agents._clap  # noqa: F401

            return True
        except ImportError:
            return False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._inference_loop,
            name="studio-ingestion-inference",
            daemon=True,
        )
        self._thread.start()
        log.info("Studio ingestion backend started (poll=%.1fs)", self._poll_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log.info("Studio ingestion backend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read from cache and update behaviors. Never blocks on inference."""
        now = time.monotonic()
        cached = self._cache.read()

        self._b_activity.update(cached["production_activity"], now)
        self._b_genre.update(cached["music_genre"], now)
        self._b_flow.update(cached["flow_state_score"], now)
        self._b_valence.update(cached["emotion_valence"], now)
        self._b_arousal.update(cached["emotion_arousal"], now)
        self._b_energy.update(cached["audio_energy_rms"], now)

        behaviors["production_activity"] = self._b_activity
        behaviors["music_genre"] = self._b_genre
        behaviors["flow_state_score"] = self._b_flow
        behaviors["emotion_valence"] = self._b_valence
        behaviors["emotion_arousal"] = self._b_arousal
        behaviors["audio_energy_rms"] = self._b_energy

    def _inference_loop(self) -> None:
        """Background thread: capture audio → CLAP inference → update cache."""
        while not self._stop_event.is_set():
            try:
                self._run_inference_step()
            except Exception:
                log.exception("Studio ingestion inference step failed")
            self._stop_event.wait(self._poll_interval)

    def _run_inference_step(self) -> None:
        """Single inference step: capture, classify, cache."""
        waveform = _capture_audio(self._capture_seconds)
        if waveform is None or len(waveform) == 0:
            return

        energy_rms = _compute_rms(waveform)

        # Skip classification if audio is near-silence
        if energy_rms < 0.001:
            self._cache.update(
                production_activity="idle",
                music_genre="unknown",
                flow_state_score=0.0,
                audio_energy_rms=energy_rms,
            )
            return

        try:
            from agents._clap import classify_zero_shot

            activity_scores = classify_zero_shot(waveform, _ACTIVITY_LABELS, sr=48000)
            top_activity_label = max(activity_scores, key=activity_scores.get)
            production_activity = _ACTIVITY_MAP.get(top_activity_label, "idle")

            genre_scores = classify_zero_shot(waveform, _GENRE_LABELS, sr=48000)
            top_genre = max(genre_scores, key=genre_scores.get)
            genre_confidence = genre_scores[top_genre]

            flow_score = _estimate_flow_score(production_activity, energy_rms, genre_confidence)

            self._cache.update(
                production_activity=production_activity,
                music_genre=top_genre,
                flow_state_score=flow_score,
                audio_energy_rms=energy_rms,
            )
        except Exception as exc:
            log.warning("CLAP inference failed: %s", exc)
            self._cache.update(
                production_activity="idle",
                music_genre="unknown",
                flow_state_score=0.0,
                audio_energy_rms=energy_rms,
            )
