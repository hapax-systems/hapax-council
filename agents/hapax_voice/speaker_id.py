"""Speaker identification via embedding cosine similarity."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from shared.governance.consent import ConsentRegistry

log = logging.getLogger(__name__)

# Lazy-loaded pyannote inference singleton
_pyannote_inference = None
_pyannote_load_attempted = False


def _make_waveform_dict(audio: np.ndarray, sample_rate: int) -> dict:
    """Build the input dict expected by pyannote Inference.

    Uses torch tensors when torch is available, falls back to numpy
    (useful for testing with mocked inference).
    """
    try:
        import torch

        if audio.ndim == 1:
            waveform = torch.from_numpy(audio).unsqueeze(0)  # (1, samples)
        else:
            waveform = torch.from_numpy(audio)
    except ImportError:
        # Fallback for environments without torch (e.g. mocked tests)
        if audio.ndim == 1:
            waveform = audio[np.newaxis, :]
        else:
            waveform = audio
    return {"waveform": waveform, "sample_rate": sample_rate}


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


@dataclass
class SpeakerResult:
    """Result of speaker identification."""

    label: str  # "ryan", "not_ryan", or "uncertain"
    confidence: float


class SpeakerIdentifier:
    """Identifies speakers by comparing embeddings against an enrolled reference.

    Not an auth mechanism — used for routing (operator vs guest mode).
    """

    def __init__(self, enrollment_path: Path | None = None) -> None:
        self._enrolled: np.ndarray | None = None
        if enrollment_path is not None and enrollment_path.exists():
            self._enrolled = np.load(enrollment_path)
            log.info("Loaded speaker enrollment from %s", enrollment_path)

    def identify(self, embedding: np.ndarray) -> SpeakerResult:
        """Identify speaker by cosine similarity against enrolled embedding."""
        if self._enrolled is None:
            return SpeakerResult(label="uncertain", confidence=0.0)

        similarity = _cosine_similarity(embedding, self._enrolled)
        if similarity >= 0.75:
            return SpeakerResult(label="ryan", confidence=similarity)
        if similarity < 0.4:
            return SpeakerResult(label="not_ryan", confidence=similarity)
        return SpeakerResult(label="uncertain", confidence=similarity)

    def extract_embedding(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray | None:
        """Extract speaker embedding from audio using pyannote.

        Args:
            audio: float32 numpy array (mono). int16 is auto-converted.
            sample_rate: Sample rate in Hz (default 16000).

        Returns:
            Embedding vector as numpy array, or None if model unavailable.
        """
        global _pyannote_inference, _pyannote_load_attempted

        # Convert int16 to float32 if needed
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0

        # Lazy-load the pyannote model (once)
        if not _pyannote_load_attempted:
            _pyannote_load_attempted = True
            token = os.environ.get("HF_TOKEN", "")
            if not token:
                log.warning("HF_TOKEN not set — pyannote embedding model unavailable")
            else:
                try:
                    import torch
                    from pyannote.audio import Inference, Model

                    model = Model.from_pretrained("pyannote/embedding", use_auth_token=token)
                    model = model.to(torch.device("cpu"))
                    _pyannote_inference = Inference(
                        model, window="whole", device=torch.device("cpu")
                    )
                    log.info("Loaded pyannote embedding model on CPU")
                except Exception:
                    log.warning(
                        "Failed to load pyannote embedding model",
                        exc_info=True,
                    )

        if _pyannote_inference is None:
            return None

        # pyannote Inference expects dict {"waveform": Tensor, "sample_rate": int}
        input_dict = _make_waveform_dict(audio, sample_rate)
        embedding = _pyannote_inference(input_dict)
        return np.array(embedding)

    def identify_audio(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        person_id: str | None = None,
        consent_registry: ConsentRegistry | None = None,
    ) -> SpeakerResult:
        """Extract embedding from audio and identify the speaker.

        Convenience method combining extract_embedding() and identify().
        When person_id is provided and is not the operator, checks
        ConsentRegistry for an active biometric consent contract.
        """
        if person_id is not None and person_id != "operator":
            if consent_registry is None or not consent_registry.contract_check(
                person_id, "biometric"
            ):
                log.warning("Biometric processing blocked: no consent for %s", person_id)
                return SpeakerResult(label="uncertain", confidence=0.0)
        embedding = self.extract_embedding(audio, sample_rate)
        if embedding is None:
            return SpeakerResult(label="uncertain", confidence=0.0)
        return self.identify(embedding)

    def enroll(
        self,
        embedding: np.ndarray,
        save_path: Path,
        person_id: str | None = None,
        consent_registry: ConsentRegistry | None = None,
    ) -> None:
        """Normalize and save a speaker embedding for future identification.

        When person_id is provided and is not the operator, requires an
        active biometric consent contract before persisting embeddings.
        """
        if person_id is not None and person_id != "operator":
            if consent_registry is None or not consent_registry.contract_check(
                person_id, "biometric"
            ):
                raise ValueError(
                    f"Cannot persist biometric data for {person_id}: no consent contract"
                )
        norm = np.linalg.norm(embedding)
        if norm > 0:
            normalized = embedding / norm
        else:
            normalized = embedding
        np.save(save_path, normalized)
        self._enrolled = normalized
        log.info("Enrolled speaker embedding to %s", save_path)
