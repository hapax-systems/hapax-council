"""Fast utterance embedding via Model2Vec.

Model2Vec distills sentence transformers into static lookup tables.
potion-base-8M: 256d, ~30MB, ~0.04ms per encode on CPU.
This is the hot path for voice routing — sub-millisecond is mandatory.
"""

from __future__ import annotations

import logging
import time

import numpy as np

log = logging.getLogger(__name__)

# Default model — distilled from bge-base-en-v1.5, 8M params, 256d output
_DEFAULT_MODEL = "minishlab/potion-base-8M"


class Embedder:
    """Fast utterance embedder using Model2Vec static embeddings."""

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None
        self._dim: int = 0
        self._load_model()

    def _load_model(self) -> None:
        """Load the Model2Vec static model."""
        try:
            from model2vec import StaticModel

            t0 = time.monotonic()
            self._model = StaticModel.from_pretrained(self._model_name)
            elapsed = time.monotonic() - t0
            # Get dimensionality from a test encode
            test = self._model.encode(["test"])
            self._dim = test.shape[1]
            log.info(
                "Loaded Model2Vec %s (%dd) in %.1fs",
                self._model_name,
                self._dim,
                elapsed,
            )
        except Exception:
            log.warning("Failed to load Model2Vec model %s", self._model_name, exc_info=True)

    @property
    def dim(self) -> int:
        """Embedding dimensionality (256 for potion-base-8M)."""
        return self._dim

    @property
    def available(self) -> bool:
        return self._model is not None

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text string. Returns (dim,) array.

        Falls back to zero vector if model unavailable.
        """
        if self._model is None:
            return np.zeros(self._dim or 256, dtype=np.float32)
        vec = self._model.encode([text])
        return vec[0]

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed multiple texts. Returns (n, dim) array.

        Used for concern anchor refresh — not on the hot path.
        """
        if self._model is None or not texts:
            d = self._dim or 256
            return np.zeros((len(texts) if texts else 0, d), dtype=np.float32)
        return self._model.encode(texts)
