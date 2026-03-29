"""SenseVoice speech emotion + audio event detection backend.

Captures 10s audio from PipeWire monitor, runs SenseVoice-Small inference
on GPU (~800MB, ~70ms for 10s audio). VRAMLock coordinates with CLAP and
YOLO for time-sliced GPU access.

Tier: SLOW (~12s cadence). contribute() reads from a thread-safe cache.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior
from agents.hapax_daimonion.vram import VRAMLock

log = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL = 12.0
_DEFAULT_CAPTURE_SECONDS = 10.0

# SenseVoice emotion labels
_EMOTION_MAP = {
    "HAPPY": "happy",
    "SAD": "sad",
    "ANGRY": "angry",
    "NEUTRAL": "neutral",
    "FEARFUL": "fearful",
    "DISGUSTED": "disgusted",
    "SURPRISED": "surprised",
}

# SenseVoice event tags
_EVENT_TAGS = {"<|BGM|>", "<|Speech|>", "<|Applause|>", "<|Laughter|>", "<|Cry|>", "<|Cough|>"}


class _SpeechEmotionCache:
    """Thread-safe cache for SenseVoice inference results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._speech_emotion: str = "neutral"
        self._audio_events: str = ""
        self._speech_language: str = "unknown"
        self._updated_at: float = 0.0

    def update(
        self,
        *,
        speech_emotion: str,
        audio_events: str,
        speech_language: str,
    ) -> None:
        with self._lock:
            self._speech_emotion = speech_emotion
            self._audio_events = audio_events
            self._speech_language = speech_language
            self._updated_at = time.monotonic()

    def read(self) -> dict:
        with self._lock:
            return {
                "speech_emotion": self._speech_emotion,
                "audio_events": self._audio_events,
                "speech_language": self._speech_language,
                "updated_at": self._updated_at,
            }


def _capture_audio(duration_s: float, sample_rate: int = 16000) -> np.ndarray | None:
    """Capture audio from PipeWire monitor source."""
    import subprocess

    tmp_path: str | None = None
    try:
        import soundfile as sf

        from shared.tmp_wav import tmp_wav_path

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
        data, _sr = sf.read(tmp_path, dtype="float32")
        if len(data) == 0:
            return None
        return data if data.ndim == 1 else data[:, 0]
    except Exception as exc:
        log.debug("Audio capture failed: %s", exc)
        return None
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


class SpeechEmotionBackend:
    """PerceptionBackend providing speech emotion and audio event detection.

    Provides:
      - speech_emotion: str (happy/sad/angry/neutral/etc.)
      - audio_events: str (comma-separated: laughter, applause, BGM, etc.)
      - speech_language: str (detected language code)
    """

    def __init__(
        self,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        capture_seconds: float = _DEFAULT_CAPTURE_SECONDS,
    ) -> None:
        self._poll_interval = poll_interval
        self._capture_seconds = capture_seconds
        self._cache = _SpeechEmotionCache()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._vram_lock = VRAMLock()

        self._b_emotion: Behavior[str] = Behavior("neutral")
        self._b_events: Behavior[str] = Behavior("")
        self._b_language: Behavior[str] = Behavior("unknown")

    @property
    def name(self) -> str:
        return "speech_emotion"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"speech_emotion", "audio_events", "speech_language"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        try:
            import funasr  # noqa: F401

            return True
        except ImportError:
            return False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._inference_loop,
            name="speech-emotion-inference",
            daemon=True,
        )
        self._thread.start()
        log.info("Speech emotion backend started (poll=%.1fs)", self._poll_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)
            self._thread = None
        log.info("Speech emotion backend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read from cache and update behaviors."""
        now = time.monotonic()
        cached = self._cache.read()

        self._b_emotion.update(cached["speech_emotion"], now)
        self._b_events.update(cached["audio_events"], now)
        self._b_language.update(cached["speech_language"], now)

        behaviors["speech_emotion"] = self._b_emotion
        behaviors["audio_events"] = self._b_events
        behaviors["speech_language"] = self._b_language

    def _inference_loop(self) -> None:
        """Background thread: capture audio → SenseVoice inference → cache."""
        model = None

        while not self._stop_event.is_set():
            try:
                waveform = _capture_audio(self._capture_seconds)
                if waveform is None or len(waveform) == 0:
                    self._stop_event.wait(self._poll_interval)
                    continue

                # Skip near-silence
                rms = float(np.sqrt(np.mean(waveform**2)))
                if rms < 0.001:
                    self._cache.update(
                        speech_emotion="neutral",
                        audio_events="",
                        speech_language="unknown",
                    )
                    self._stop_event.wait(self._poll_interval)
                    continue

                # Acquire VRAM lock
                if not self._vram_lock.acquire():
                    log.debug("VRAM lock held, skipping speech emotion inference")
                    self._stop_event.wait(self._poll_interval)
                    continue

                try:
                    if model is None:
                        from funasr import AutoModel

                        model = AutoModel(
                            model="iic/SenseVoiceSmall",
                            trust_remote_code=True,
                            device="cuda",
                        )
                        log.info("SenseVoice-Small model loaded")

                    result = model.generate(
                        input=waveform,
                        cache={},
                        language="auto",
                        use_itn=False,
                    )

                    speech_emotion = "neutral"
                    audio_events: list[str] = []
                    speech_language = "unknown"

                    if result and len(result) > 0:
                        text = result[0].get("text", "")

                        # Parse emotion tag
                        for emo_key, emo_val in _EMOTION_MAP.items():
                            if f"<|{emo_key}|>" in text:
                                speech_emotion = emo_val
                                break

                        # Parse event tags
                        for tag in _EVENT_TAGS:
                            if tag in text:
                                event_name = tag.strip("<|>").lower()
                                audio_events.append(event_name)

                        # Parse language tag
                        for lang in ("en", "zh", "ja", "ko", "yue"):
                            if f"<|{lang}|>" in text:
                                speech_language = lang
                                break

                    self._cache.update(
                        speech_emotion=speech_emotion,
                        audio_events=", ".join(audio_events),
                        speech_language=speech_language,
                    )

                finally:
                    self._vram_lock.release()

            except Exception:
                log.exception("Speech emotion inference step failed")

            self._stop_event.wait(self._poll_interval)
