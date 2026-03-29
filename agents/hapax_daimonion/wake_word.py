"""Wake word detection wrapper for openwakeword."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path.home() / ".local" / "share" / "hapax-daimonion" / "hapax_wake_word.onnx"
DETECTION_COOLDOWN_S = 1.5  # Suppress duplicate detections from multi-frame triggers
_SCORE_LOG_INTERVAL = 100  # Log peak score every N frames at DEBUG level

# Fallback to a built-in OWW model if the custom model's input shape
# is incompatible with OWW's native predict() (rank 3 vs rank 2).
_FALLBACK_MODEL = "hey_jarvis"


class WakeWordDetector:
    """Detects a wake word using openwakeword.

    Uses OWW's native predict() for both built-in and custom models.
    If the custom ONNX model has incompatible input shape (rank 2 vs
    OWW's rank 3 expectation), falls back to a built-in model.

    The model is loaded lazily via load(). If openwakeword is not
    installed or the model file is missing, the detector logs a warning
    and operates as a no-op.
    """

    def __init__(
        self,
        model_path: Path | None = None,
        threshold: float = 0.3,
    ) -> None:
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.threshold = threshold
        self.on_wake_word: Callable[[], None] | None = None
        self._onnx_session = None  # kept for status check compatibility
        self._model = None
        self._model_name: str | None = None
        self._last_detection: float = 0.0
        self._frame_count: int = 0
        self._peak_score: float = 0.0

    def load(self) -> None:
        """Try to load the openwakeword model."""
        try:
            # OWW already uses CPUExecutionProvider explicitly — no need
            # to set CUDA_VISIBLE_DEVICES (which would break faster-whisper
            # and other GPU consumers in the same process).
            from openwakeword.model import Model  # type: ignore[import-untyped]

            # Try custom model first
            if self.model_path.exists():
                try:
                    model = Model(
                        wakeword_model_paths=[str(self.model_path)],
                    )
                    mdl_name = list(model.models.keys())[0]
                    # Test predict() compatibility
                    test_audio = np.zeros(1280, dtype=np.int16)
                    model.predict(test_audio)
                    self._model = model
                    self._model_name = mdl_name
                    self._onnx_session = model.models[mdl_name]
                    log.info("Wake word model loaded from %s", self.model_path)
                    return
                except Exception as exc:
                    log.warning(
                        "Custom model incompatible with OWW predict(): %s. "
                        "Falling back to built-in '%s'",
                        exc,
                        _FALLBACK_MODEL,
                    )

            # Fall back to built-in model
            model = Model()
            if _FALLBACK_MODEL in model.models:
                self._model = model
                self._model_name = _FALLBACK_MODEL
                self._onnx_session = model.models[_FALLBACK_MODEL]
                log.info(
                    "Using built-in wake word '%s' (say 'Hey Jarvis')",
                    _FALLBACK_MODEL,
                )
            else:
                log.warning("No usable wake word model found")

        except ImportError:
            log.warning(
                "openwakeword not installed — wake word detection disabled. "
                "Install with: uv pip install openwakeword"
            )
        except Exception:
            log.exception("Failed to load wake word model")

    def process_audio(self, audio_chunk: np.ndarray) -> None:
        """Run wake word prediction on an audio chunk.

        Uses OWW's native predict() which handles all feature
        extraction internally via its streaming preprocessor.

        Args:
            audio_chunk: 16kHz int16 audio samples (1280 samples expected).
        """
        if self._model is None:
            return

        try:
            result = self._model.predict(audio_chunk)
            score = float(result.get(self._model_name, 0.0))
            self._handle_detection(score)
        except Exception:
            log.exception("Error during wake word prediction")

    @property
    def is_loaded(self) -> bool:
        return self._onnx_session is not None

    def _handle_detection(self, score: float) -> None:
        """Fire callback if score meets threshold and cooldown has elapsed."""
        # Track peak score for periodic debug logging
        self._frame_count += 1
        if score > self._peak_score:
            self._peak_score = score
        if self._frame_count % _SCORE_LOG_INTERVAL == 0:
            log.info(
                "Wake word score: peak=%.4f over last %d frames (threshold=%.2f)",
                self._peak_score,
                _SCORE_LOG_INTERVAL,
                self.threshold,
            )
            self._peak_score = 0.0

        if score >= self.threshold:
            now = time.monotonic()
            if (now - self._last_detection) < DETECTION_COOLDOWN_S:
                return
            self._last_detection = now
            log.info("Wake word detected (score=%.3f)", score)
            # Reset OWW preprocessor state so stale buffer doesn't
            # suppress the next utterance.
            try:
                self._model.reset()
            except Exception:
                pass
            if self.on_wake_word is not None:
                self.on_wake_word()
