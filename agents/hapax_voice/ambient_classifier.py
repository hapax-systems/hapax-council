"""Ambient audio classification via PANNs for context-aware interrupt gating.

Uses Pre-trained Audio Neural Networks (PANNs) with AudioSet labels to
classify ambient audio and determine whether interrupts are appropriate.
For example, blocks interrupts when music is playing or a conversation is
happening nearby.

The model (~300MB) is lazy-loaded on first use and runs on CPU to leave
the GPU free for Ollama/STT workloads.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

# AudioSet labels that indicate the environment should NOT be interrupted.
# These are matched as substrings against the 527 AudioSet class labels.
BLOCK_PATTERNS: list[str] = [
    "Music",
    "Musical instrument",
    "Singing",
    "Song",
    "Guitar",
    "Piano",
    "Drum",
    "Bass",
    "Synthesizer",
    "Organ",
    "Violin",
    "Trumpet",
    "Harmonica",
    "Accordion",
    "Banjo",
    "Mandolin",
    "Ukulele",
    "Harp",
    "Choir",
    "Orchestra",
    "Band",
    "Hip hop music",
    "Jazz",
    "Rock music",
    "Pop music",
    "Electronic music",
    "Techno",
    "Reggae",
    "Blues",
    "Soul music",
    "Funk",
    "Disco",
    "House music",
    "Drum and bass",
    "Dubstep",
    # Speech by others (meetings, calls, podcasts)
    "Speech",
    "Conversation",
    "Narration",
    "Telephone",
    "Video game music",
]

# Subset of block patterns that should be ALLOWED when the source is clearly
# the operator (e.g. the operator speaking to invoke a command).  Speech by
# itself shouldn't block; the context gate has other layers for that.
# We keep Speech in BLOCK_PATTERNS because the ambient classifier operates on
# monitor audio (system output), not the mic — so speech on the monitor means
# a meeting / podcast / video call.

# AudioSet labels that are explicitly ALLOWED (never block).
ALLOW_PATTERNS: list[str] = [
    "Silence",
    "White noise",
    "Pink noise",
    "Typing",
    "Keyboard",
    "Mouse",
    "Click",
    "Computer keyboard",
    "Mechanical fan",
    "Air conditioning",
    "Traffic noise",
]

# Minimum combined probability across all block labels to trigger a block.
DEFAULT_BLOCK_THRESHOLD: float = 0.15

# Audio capture duration in seconds for each classification pass.
CAPTURE_DURATION_S: float = 3.0

# Sample rate expected by PANNs (32kHz).
PANNS_SAMPLE_RATE: int = 32000

# Singleton state for lazy model loading.
_model = None
_labels: list[str] = []
_load_attempted: bool = False


@dataclass
class AmbientResult:
    """Result of ambient audio classification."""

    interruptible: bool
    reason: str = ""
    top_labels: list[tuple[str, float]] = field(default_factory=list)


def _load_model() -> bool:
    """Lazy-load the PANNs CNN14 model.  Returns True on success."""
    global _model, _labels, _load_attempted
    if _load_attempted:
        return _model is not None
    _load_attempted = True

    try:
        from panns_inference import AudioTagging  # type: ignore[import-untyped]
        from panns_inference import labels as panns_labels

        _model = AudioTagging(checkpoint_path=None, device="cpu")
        _labels = panns_labels
        log.info("PANNs model loaded on CPU (%d AudioSet labels)", len(_labels))
        return True
    except ImportError:
        log.warning(
            "panns_inference not installed — ambient classification disabled. "
            "Install with: uv pip install panns-inference"
        )
    except Exception:
        log.exception("Failed to load PANNs model")
    return False


def _build_label_index(
    labels: list[str],
) -> tuple[list[int], list[int]]:
    """Pre-compute index sets for block and allow labels.

    Returns (block_indices, allow_indices) — lists of integer positions
    into the AudioSet labels array.
    """
    block_idx: list[int] = []
    allow_idx: list[int] = []
    for i, label in enumerate(labels):
        label_lower = label.lower()
        if any(pat.lower() in label_lower for pat in BLOCK_PATTERNS):
            block_idx.append(i)
        if any(pat.lower() in label_lower for pat in ALLOW_PATTERNS):
            allow_idx.append(i)
    return block_idx, allow_idx


def _capture_audio_pipewire(duration_s: float = CAPTURE_DURATION_S) -> np.ndarray | None:
    """Capture audio from the PipeWire default monitor source.

    Returns float32 mono audio at PANNS_SAMPLE_RATE, or None on failure.
    Uses synchronous subprocess — call from executor thread to avoid
    blocking the asyncio event loop.
    """
    try:
        result = subprocess.run(
            [
                "pw-record",
                "--format",
                "s16",
                "--rate",
                str(PANNS_SAMPLE_RATE),
                "--channels",
                "1",
                "-",
            ],
            capture_output=True,
            timeout=duration_s + 2,
        )
        if not result.stdout:
            log.warning("pw-record produced no output")
            return None
        # Raw PCM int16 → float32
        audio_int16 = np.frombuffer(result.stdout, dtype=np.int16)
        if len(audio_int16) < PANNS_SAMPLE_RATE:
            log.warning("pw-record captured too little audio (%d samples)", len(audio_int16))
            return None
        return audio_int16.astype(np.float32) / 32768.0
    except subprocess.TimeoutExpired:
        log.warning("pw-record timed out after %.1fs", duration_s + 2)
    except FileNotFoundError:
        log.warning("pw-record not found — PipeWire not available")
    except Exception:
        log.exception("Failed to capture audio via pw-record")
    return None


async def async_classify(
    block_threshold: float = DEFAULT_BLOCK_THRESHOLD,
) -> AmbientResult:
    """Non-blocking classify: runs pw-record + PANNs in executor thread.

    Prevents the 3-5 second blocking window that causes audio queue
    overflow and wake word detection failures.
    """
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, classify, None, block_threshold)


def classify(
    audio: np.ndarray | None = None, block_threshold: float = DEFAULT_BLOCK_THRESHOLD
) -> AmbientResult:
    """Classify ambient audio and return whether the environment is interruptible.

    Args:
        audio: Optional float32 mono audio array at PANNS_SAMPLE_RATE.
               If None, audio is captured from PipeWire.

    Returns:
        AmbientResult with interruptible flag and reasoning.
    """
    if not _load_model():
        return AmbientResult(
            interruptible=False,
            reason="PANNs model unavailable (fail-closed)",
        )

    if audio is None:
        audio = _capture_audio_pipewire()
        if audio is None:
            return AmbientResult(
                interruptible=False,
                reason="Audio capture failed (fail-closed)",
            )

    # PANNs expects (batch, samples) float32 at 32kHz
    if audio.ndim == 1:
        audio = audio[np.newaxis, :]

    try:
        clipwise_output, _ = _model.inference(audio)
    except Exception:
        log.exception("PANNs inference failed")
        return AmbientResult(
            interruptible=False,
            reason="PANNs inference error (fail-closed)",
        )

    probs = clipwise_output[0]  # shape: (527,)

    block_indices, allow_indices = _build_label_index(_labels)

    # Sum probabilities for block categories
    block_prob = float(np.sum(probs[block_indices])) if block_indices else 0.0

    # Get top-5 labels for debugging/logging
    top5_idx = np.argsort(probs)[-5:][::-1]
    top_labels = [(_labels[i], float(probs[i])) for i in top5_idx]

    if block_prob >= block_threshold:
        # Find the dominant block label for the reason string
        dominant_idx = max(block_indices, key=lambda i: probs[i])
        dominant_label = _labels[dominant_idx]
        dominant_prob = float(probs[dominant_idx])
        return AmbientResult(
            interruptible=False,
            reason=f"Ambient audio blocked: {dominant_label} ({dominant_prob:.2f}), total block prob={block_prob:.2f}",
            top_labels=top_labels,
        )

    return AmbientResult(
        interruptible=True,
        reason="Ambient audio clear",
        top_labels=top_labels,
    )


def reset() -> None:
    """Reset the lazy-loaded model state.  Useful for testing."""
    global _model, _labels, _load_attempted
    _model = None
    _labels = []
    _load_attempted = False
