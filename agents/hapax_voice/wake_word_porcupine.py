"""Wake word detection via Picovoice Porcupine v4.

Drop-in replacement for the OpenWakeWord detector. Uses a custom .ppn
model file trained via the Picovoice Console. AccessKey loaded from
``pass show picovoice/access-key`` at startup.

Audio contract: 16 kHz int16 mono, frame size = porcupine.frame_length
(typically 512 samples = 32 ms).
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path.home() / ".local" / "share" / "hapax-voice" / "hapax_porcupine.ppn"
DETECTION_COOLDOWN_S = 1.5


def _load_access_key() -> str | None:
    """Read the Picovoice AccessKey from the pass store."""
    try:
        result = subprocess.run(
            ["pass", "show", "picovoice/access-key"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        key = result.stdout.strip()
        if key and result.returncode == 0:
            return key
        log.warning("pass show picovoice/access-key returned empty or failed")
    except FileNotFoundError:
        log.warning("'pass' not found — cannot load Picovoice AccessKey")
    except subprocess.TimeoutExpired:
        log.warning("Timed out reading Picovoice AccessKey from pass")
    except Exception as exc:
        log.warning("Failed to load Picovoice AccessKey: %s", exc)
    return None


class PorcupineWakeWord:
    """Porcupine-based wake word detector.

    Loads a custom .ppn keyword file and processes 16 kHz int16 audio
    frames. Fires ``on_wake_word`` callback on detection.
    """

    def __init__(
        self,
        model_path: Path | None = None,
        sensitivity: float = 0.5,
    ) -> None:
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.sensitivity = sensitivity
        self.on_wake_word: Callable[[], None] | None = None
        self._handle = None
        self._last_detection: float = 0.0
        self.frame_length: int = 512  # updated after load()

    def load(self) -> None:
        """Initialize Porcupine engine."""
        try:
            import pvporcupine
        except ImportError:
            log.warning(
                "pvporcupine not installed — Porcupine wake word disabled. "
                "Install with: uv pip install pvporcupine"
            )
            return

        if not self.model_path.exists():
            log.warning(
                "Porcupine model not found at %s — wake word disabled. "
                "Download from Picovoice Console.",
                self.model_path,
            )
            return

        access_key = _load_access_key()
        if not access_key:
            log.error(
                "No Picovoice AccessKey — wake word disabled. "
                "Store it with: pass insert picovoice/access-key"
            )
            return

        try:
            self._handle = pvporcupine.create(
                access_key=access_key,
                keyword_paths=[str(self.model_path)],
                sensitivities=[self.sensitivity],
            )
            self.frame_length = self._handle.frame_length

            # Verify the key actually works by processing a test frame.
            # Picovoice silently returns -1 on all frames when the access
            # key is expired or rate-limited — no exception, just dead.
            try:
                test_result = self._handle.process([0] * self.frame_length)
                if test_result == -1:
                    log.info(
                        "Porcupine loaded: model=%s, sensitivity=%.2f, frame_length=%d, sample_rate=%d",
                        self.model_path.name,
                        self.sensitivity,
                        self._handle.frame_length,
                        self._handle.sample_rate,
                    )
                else:
                    # Silence triggered detection — something is wrong
                    log.warning("Porcupine returned %d on silence — model may be corrupt", test_result)
            except pvporcupine.PorcupineActivationLimitError:
                log.error(
                    "Picovoice access key RATE LIMITED — wake word will not work. "
                    "Use Super+H hotkey to trigger sessions manually."
                )
                self._handle.delete()
                self._handle = None
                return
            except pvporcupine.PorcupineActivationError as e:
                log.error(
                    "Picovoice access key INVALID or EXPIRED: %s — wake word disabled. "
                    "Use Super+H hotkey to trigger sessions manually.", e
                )
                self._handle.delete()
                self._handle = None
                return
        except Exception:
            log.exception("Failed to initialize Porcupine")
            self._handle = None

    def process_audio(self, audio_chunk: np.ndarray) -> None:
        """Process a single audio frame.

        Args:
            audio_chunk: 16 kHz int16 mono audio, exactly
                ``self.frame_length`` samples.
        """
        if self._handle is None:
            return

        try:
            keyword_index = self._handle.process(audio_chunk)
            if keyword_index >= 0:
                now = time.monotonic()
                if (now - self._last_detection) < DETECTION_COOLDOWN_S:
                    return
                self._last_detection = now
                log.info("Porcupine wake word detected")
                if self.on_wake_word is not None:
                    self.on_wake_word()
        except Exception:
            log.exception("Error during Porcupine processing")

    def close(self) -> None:
        """Release Porcupine resources."""
        if self._handle is not None:
            self._handle.delete()
            self._handle = None
            log.info("Porcupine engine released")

    @property
    def is_loaded(self) -> bool:
        return self._handle is not None
