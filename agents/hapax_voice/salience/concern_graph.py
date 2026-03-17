"""Concern graph — operator-specific salience anchors.

A flat set of embedding vectors representing what the operator cares about
right now. Refreshed on each perception tick (~2.5s) from existing
infrastructure: workspace analysis, calendar, goals, notifications,
profile dimensions, conversation history.

Two signals extracted per utterance:
  1. Concern overlap (top-down/dorsal): cosine similarity to concern anchors.
     "This is relevant to what I care about."
  2. Novelty (bottom-up/ventral): distance from ALL known patterns.
     "I don't know what this is, but it might matter."
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class ConcernAnchor:
    """A single concern with its embedding and metadata."""

    text: str
    source: str  # workspace, calendar, goal, notification, profile, conversation, consent
    weight: float = 1.0  # salience weight — governance/consent anchors get permanent high weight


class ConcernGraph:
    """Flat set of concern anchors with cosine similarity query."""

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim
        self._anchors: list[ConcernAnchor] = []
        self._matrix: np.ndarray | None = None  # (n, dim) normalized
        self._weights: np.ndarray | None = None  # (n,) salience weights
        self._recent_utterances: list[np.ndarray] = []  # sliding window
        self._max_recent: int = 20
        self._last_refresh: float = 0.0

    @property
    def anchor_count(self) -> int:
        return len(self._anchors)

    def refresh(
        self,
        anchors: list[ConcernAnchor],
        embeddings: np.ndarray,
    ) -> None:
        """Replace all concern anchors with new set.

        Args:
            anchors: List of ConcernAnchor metadata.
            embeddings: (n, dim) array of pre-computed embeddings (from Embedder.embed_batch).
        """
        if len(anchors) == 0 or embeddings.shape[0] == 0:
            self._anchors = []
            self._matrix = None
            self._weights = None
            return

        self._anchors = anchors
        # Normalize for cosine similarity via dot product
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-8)
        self._matrix = (embeddings / norms).astype(np.float32)
        self._weights = np.array([a.weight for a in anchors], dtype=np.float32)
        self._last_refresh = time.monotonic()

        log.debug("Concern graph refreshed: %d anchors", len(anchors))

    def query(self, utterance_embedding: np.ndarray) -> float:
        """Compute concern overlap — weighted max cosine similarity.

        Returns 0.0-1.0 activation score. Higher = more relevant to operator's concerns.
        """
        if self._matrix is None or self._weights is None:
            return 0.0

        # Normalize utterance
        norm = np.linalg.norm(utterance_embedding)
        if norm < 1e-8:
            return 0.0
        utt_norm = utterance_embedding / norm

        # Cosine similarities: (n,)
        sims = self._matrix @ utt_norm

        # Weighted similarities — governance anchors dominate
        weighted = sims * self._weights

        # Return max weighted similarity, clamped to [0, 1]
        return float(np.clip(np.max(weighted), 0.0, 1.0))

    def novelty(self, utterance_embedding: np.ndarray) -> float:
        """Compute novelty score — distance from all known patterns.

        High novelty = the utterance doesn't match any concern anchor OR recent
        utterance. This is the ventral/bottom-up "surprise" signal.

        Returns 0.0-1.0 where 1.0 = completely novel.
        """
        norm = np.linalg.norm(utterance_embedding)
        if norm < 1e-8:
            return 0.5  # zero vector = no information = moderate novelty

        utt_norm = utterance_embedding / norm

        max_sim = 0.0

        # Check against concern anchors
        if self._matrix is not None:
            sims = self._matrix @ utt_norm
            max_sim = max(max_sim, float(np.max(sims)))

        # Check against recent utterances
        for recent in self._recent_utterances:
            r_norm = np.linalg.norm(recent)
            if r_norm < 1e-8:
                continue
            sim = float(np.dot(recent / r_norm, utt_norm))
            max_sim = max(max_sim, sim)

        # Novelty = 1 - max_similarity (completely novel = 1.0)
        return float(np.clip(1.0 - max_sim, 0.0, 1.0))

    def add_recent_utterance(self, embedding: np.ndarray) -> None:
        """Add an utterance to the recent window (for novelty computation)."""
        self._recent_utterances.append(embedding.copy())
        if len(self._recent_utterances) > self._max_recent:
            self._recent_utterances.pop(0)

    def get_anchor_texts(self) -> list[str]:
        """Return all anchor texts for diagnostics."""
        return [a.text for a in self._anchors]

    def get_anchor_sources(self) -> dict[str, int]:
        """Count anchors by source for diagnostics."""
        counts: dict[str, int] = {}
        for a in self._anchors:
            counts[a.source] = counts.get(a.source, 0) + 1
        return counts
