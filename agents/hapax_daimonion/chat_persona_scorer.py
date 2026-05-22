"""Chat persona similarity scorer — operator text fingerprint matching.

Embeds incoming chat messages via nomic-embed-cpu and compares cosine
similarity against an averaged operator fingerprint. Used by
ChatAuthorIsOperatorEngine as the persona_similarity_above_threshold signal.

Fingerprint enrollment: average embedding of operator sidechat messages,
stored as L2-normalized 768-dim vector at profiles/chat-persona-fingerprint.npy.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

FINGERPRINT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "profiles" / "chat-persona-fingerprint.npy"
)
ACCEPT_THRESHOLD = 0.45
REJECT_THRESHOLD = 0.30


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class ChatPersonaScorer:
    """Score chat messages against operator text fingerprint."""

    def __init__(self, fingerprint_path: Path = FINGERPRINT_PATH) -> None:
        self._fingerprint: np.ndarray | None = None
        if fingerprint_path.exists():
            try:
                loaded = np.load(fingerprint_path)
                if loaded.shape == (768,) and np.issubdtype(loaded.dtype, np.floating):
                    self._fingerprint = loaded
                else:
                    log.warning(
                        "Persona fingerprint shape/dtype mismatch: %s %s",
                        loaded.shape,
                        loaded.dtype,
                    )
            except Exception:
                log.debug("Failed to load persona fingerprint", exc_info=True)

    @property
    def enrolled(self) -> bool:
        return self._fingerprint is not None

    def score(self, text: str) -> bool | None:
        """Score a chat message against the operator fingerprint.

        Returns True if similarity >= accept threshold, False if below
        reject threshold, None if uncertain or fingerprint unavailable.
        """
        if self._fingerprint is None:
            return None
        if not text.strip():
            return None
        try:
            from agents._config import embed_safe

            vec = embed_safe(text, prefix="search_document")
        except Exception:
            return None
        if vec is None:
            return None
        sim = _cosine_similarity(np.array(vec), self._fingerprint)
        if sim >= ACCEPT_THRESHOLD:
            return True
        if sim < REJECT_THRESHOLD:
            return False
        return None

    @staticmethod
    def enroll(texts: list[str], output_path: Path = FINGERPRINT_PATH) -> Path:
        """Build operator fingerprint from a list of operator messages."""
        from agents._config import embed_batch

        if not texts:
            raise ValueError("Need at least 1 text to enroll")
        embeddings = embed_batch(texts, prefix="search_document")
        fingerprint = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(fingerprint)
        if norm > 0:
            fingerprint /= norm
        output_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_path, fingerprint)
        log.info("Enrolled chat persona fingerprint (%d texts) to %s", len(texts), output_path)
        return output_path
