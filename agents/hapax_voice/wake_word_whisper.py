"""Wake word detection via Silero VAD + faster-whisper-tiny.

No training required — uses Whisper's vocabulary knowledge to detect
"hapax" (a real English word: hapax legomenon). Architecture:

1. Silero VAD detects speech onset (already running in the audio loop)
2. Buffer 0.5-2s of speech audio
3. Run faster-whisper-tiny on the buffer (~100-200ms on CPU)
4. Check if transcript contains "hapax" (with fuzzy variants)
5. Fire wake word callback if confirmed

Audio contract: 16 kHz int16 mono, 512 samples per frame (32ms).
Same interface as PorcupineWakeWord for drop-in replacement.

Latency: ~300-500ms from speech onset to detection.
CPU: negligible (VAD <1ms per frame, Whisper only on speech segments).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

# Keywords to match in transcript (lowercase). "hapax" + common
# Whisper mis-transcriptions we've observed or can anticipate.
_WAKE_WORDS = frozenset(
    {
        "hapax",
        "hey pax",
        "hay pax",
        "hey packs",
        "ha pax",
        "hepax",
        "hey pacs",
        "hapacs",
        "hey pax,",
        "a pax",
        "hit pax",
        "hip ax",
        "hip pax",
        "he pax",
        "hip hacks",
        "hiphacks",
        "hit x",
        "hitx",
        "high pax",
        "hi pax",
        "hay packs",
        "hey hapaks",
        "hey hapax",
    }
)

# Also match these as substrings (for "hapax" embedded in longer text)
_WAKE_SUBSTRINGS = (
    "hapax",
    "hey pax",
    "hay pax",
    "hepax",
    "hit pax",
    "hip ax",
    "he pax",
    "hiphacks",
    "hitx",
    "high pax",
    "hi pax",
)


def _fuzzy_wake_match(text_clean: str) -> bool:
    """Fuzzy phonetic matching for wake word.

    Whisper-tiny produces wildly varying transcriptions of "hey hapax".
    Instead of enumerating every variant, check if the text sounds like
    it could be the wake phrase using simple heuristics:
    - Starts with h-sound word (hey/hi/high/hay/ha/he/hit/hip)
    - Followed by pax/packs/hacks/ax/x sound
    """
    words = text_clean.split()
    if len(words) < 1 or len(words) > 4:
        return False

    # Single word: check if it's a hapax-like compound
    if len(words) == 1:
        w = words[0]
        return w.startswith("h") and ("pax" in w or "pacs" in w or "hax" in w or "packs" in w)

    # Multi-word: first word h-sound, last word pax-sound
    h_starts = frozenset({"hey", "hi", "high", "hay", "ha", "he", "hit", "hip", "hei", "hie"})
    pax_ends = frozenset(
        {
            "pax",
            "packs",
            "pacs",
            "hacks",
            "ax",
            "x",
            "backs",
            "pacts",
            "pass",
            "pats",
            "pash",
            "patch",
            "pack",
            "paks",
            "hapaks",
            "hapax",
            "hapacs",
            "hapacks",
        }
    )

    first = words[0]
    last = words[-1]

    if first in h_starts and last in pax_ends:
        return True

    # Check if any bigram matches h+pax pattern
    return any(
        words[i] in h_starts and words[i + 1] in pax_ends for i in range(len(words) - 1)
    )


DETECTION_COOLDOWN_S = 1.5

# Audio buffering parameters
_SAMPLE_RATE = 16000
_FRAME_SAMPLES = 512  # matches porcupine frame size
_MIN_SPEECH_FRAMES = 10  # ~320ms minimum before checking
_MAX_SPEECH_FRAMES = 60  # ~1.9s max buffer before forced check
_SILENCE_FRAMES_TO_CHECK = 8  # ~256ms of silence = end of word, check now

# VAD threshold for speech detection within this detector
_VAD_SPEECH_THRESHOLD = 0.5
_VAD_SILENCE_THRESHOLD = 0.2

# Thread pool for whisper inference (single thread, won't starve audio)
_whisper_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wake-whisper")


class WhisperWakeWord:
    """Wake word detector using VAD-gated Whisper transcription.

    Drop-in replacement for PorcupineWakeWord. Requires no training,
    no API keys, no licensing. Uses the existing Silero VAD probability
    fed from the audio loop.

    If a ResidentSTT instance is provided, uses it (distil-large-v3 on GPU)
    instead of loading a separate whisper-tiny. This gives dramatically
    better accuracy (~90%+ vs ~50%) at lower latency (30-80ms GPU vs
    250ms CPU) with zero additional memory.
    """

    def __init__(self, model_size: str = "tiny", resident_stt=None) -> None:
        self._model_size = model_size
        self._model = None
        self._resident_stt = resident_stt  # ResidentSTT | None
        self.on_wake_word: Callable[[], None] | None = None
        self.frame_length: int = _FRAME_SAMPLES
        self._last_detection: float = 0.0

        # Speech buffering state
        self._audio_buf: deque[bytes] = deque(maxlen=_MAX_SPEECH_FRAMES)
        self._speech_active = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._last_vad_prob = 0.0

        # Pending async check
        self._check_pending = False

    def load(self) -> None:
        """Load the Whisper model for wake word detection."""
        if self._resident_stt is not None:
            # Using shared GPU model — no separate load needed
            log.info(
                "Whisper wake word using resident STT (GPU, keywords=%d)",
                len(_WAKE_WORDS),
            )
            return

        try:
            from faster_whisper import WhisperModel

            log.info("Loading whisper-%s for wake word detection...", self._model_size)
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
            )
            log.info(
                "Whisper wake word detector loaded (model=%s, keywords=%d)",
                self._model_size,
                len(_WAKE_WORDS),
            )
        except ImportError:
            log.error(
                "faster-whisper not installed — whisper wake word disabled. "
                "Install with: uv pip install faster-whisper"
            )
        except Exception:
            log.exception("Failed to load whisper wake word model")

    @property
    def is_loaded(self) -> bool:
        return self._model is not None or self._resident_stt is not None

    def set_vad_probability(self, prob: float) -> None:
        """Feed VAD probability from the audio loop's Silero VAD.

        Called each VAD frame (~32ms) so we know when speech starts/stops.
        """
        self._last_vad_prob = prob

    def process_audio(self, audio_chunk: np.ndarray) -> None:
        """Process a single audio frame (512 samples, 16kHz int16).

        Buffers audio during detected speech, then checks for wake word
        when speech ends or buffer is full.
        """
        if not self.is_loaded:
            return

        # Convert numpy to bytes for buffering
        frame_bytes = audio_chunk.tobytes()
        self._audio_buf.append(frame_bytes)

        prob = self._last_vad_prob

        if prob >= _VAD_SPEECH_THRESHOLD:
            if not self._speech_active:
                self._speech_active = True
                self._speech_frames = 0
                self._silence_frames = 0
            self._speech_frames += 1
            self._silence_frames = 0

            # Force check if buffer is full
            if self._speech_frames >= _MAX_SPEECH_FRAMES:
                self._try_check()

        elif prob < _VAD_SILENCE_THRESHOLD and self._speech_active:
            self._silence_frames += 1

            # Speech ended — check if we have enough to analyze
            if self._silence_frames >= _SILENCE_FRAMES_TO_CHECK:
                if self._speech_frames >= _MIN_SPEECH_FRAMES:
                    self._try_check()
                self._speech_active = False
                self._speech_frames = 0
                self._silence_frames = 0

    def _try_check(self) -> None:
        """Submit buffered audio for whisper transcription check."""
        if self._check_pending:
            return  # already checking

        # Cooldown
        now = time.monotonic()
        if (now - self._last_detection) < DETECTION_COOLDOWN_S:
            return

        # Collect buffered audio
        audio_bytes = b"".join(self._audio_buf)
        if len(audio_bytes) < _MIN_SPEECH_FRAMES * _FRAME_SAMPLES * 2:
            return

        self._check_pending = True
        duration_ms = len(audio_bytes) / (_SAMPLE_RATE * 2) * 1000
        log.info(
            "Wake word check: submitting %.0fms audio (%d speech frames)",
            duration_ms,
            self._speech_frames,
        )
        # Run in thread to not block audio loop
        _whisper_executor.submit(self._check_wake_word, audio_bytes, now)

    def _check_wake_word(self, audio_bytes: bytes, submit_time: float) -> None:
        """Transcribe audio and check for wake word. Runs in thread pool."""
        try:
            import numpy as np

            # Convert int16 bytes to float32 for whisper
            samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            t0 = time.monotonic()

            if self._resident_stt is not None:
                # Use shared GPU model — much more accurate for "hapax"
                segments, info = self._resident_stt._model.transcribe(
                    samples,
                    language="en",
                    beam_size=5,  # higher accuracy, negligible GPU cost
                    best_of=3,
                    without_timestamps=True,
                    condition_on_previous_text=False,
                    # Heavy prompt biasing toward "Hapax"
                    initial_prompt=(
                        "Hapax. Hey Hapax. Hapax. Hey Hapax. Hapax is a voice assistant."
                    ),
                )
            else:
                # Fallback: CPU whisper-tiny
                segments, info = self._model.transcribe(
                    samples,
                    language="en",
                    beam_size=1,
                    best_of=1,
                    without_timestamps=True,
                    condition_on_previous_text=False,
                )

            text = " ".join(seg.text for seg in segments).strip().lower()
            elapsed = (time.monotonic() - t0) * 1000

            if not text:
                return

            # Check for wake word — normalize away ALL punctuation first
            import re

            text_clean = re.sub(r"[^\w\s]", "", text).strip()
            text_clean = re.sub(r"\s+", " ", text_clean)  # collapse whitespace

            detected = False

            # Exact full-text match
            if text_clean in _WAKE_WORDS:
                detected = True

            # Token match (individual words or bigrams)
            if not detected:
                words = text_clean.split()
                for w in words:
                    if w in _WAKE_WORDS:
                        detected = True
                        break
                # Check bigrams ("hey pax")
                if not detected:
                    for i in range(len(words) - 1):
                        bigram = f"{words[i]} {words[i + 1]}"
                        if bigram in _WAKE_WORDS:
                            detected = True
                            break

            # Substring match on cleaned text
            if not detected:
                for sub in _WAKE_SUBSTRINGS:
                    if sub in text_clean:
                        detected = True
                        break

            # Fuzzy phonetic match (catches novel whisper-tiny variants)
            if not detected:
                detected = _fuzzy_wake_match(text_clean)

            if detected:
                latency = (time.monotonic() - submit_time) * 1000
                log.info(
                    "Whisper wake word DETECTED: %r (whisper=%.0fms, latency=%.0fms)",
                    text,
                    elapsed,
                    latency,
                )
                self._last_detection = time.monotonic()
                if self.on_wake_word is not None:
                    self.on_wake_word()
            else:
                log.info("Whisper wake word miss: %r (%.0fms)", text, elapsed)

        except Exception:
            log.exception("Whisper wake word check failed")
        finally:
            self._check_pending = False
