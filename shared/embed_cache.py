"""Persistent embedding cache — avoids re-embedding static text across restarts.

Stores text->embedding mappings keyed by SHA-256 of the input text.
Invalidated when model name or dimension changes. File format is JSON
for debuggability (embeddings are 768-dim floats, ~6KB per entry,
~1MB for 150 capabilities).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".cache" / "hapax" / "embed-cache.json"


class DiskEmbeddingCache:
    """Persistent cache mapping text -> embedding vector."""

    def __init__(
        self,
        *,
        cache_path: Path = _DEFAULT_PATH,
        model: str,
        dimension: int,
    ) -> None:
        self._path = cache_path
        self._model = model
        self._dimension = dimension
        self._entries: dict[str, list[float]] = {}
        self._load()

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def get(self, text: str) -> list[float] | None:
        return self._entries.get(self._key(text))

    def put(self, text: str, embedding: list[float]) -> None:
        self._entries[self._key(text)] = embedding

    def bulk_lookup(self, texts: list[str]) -> tuple[dict[int, list[float]], list[int], list[str]]:
        """Check cache for multiple texts at once.

        Returns:
            hits: {index: embedding} for texts found in cache
            miss_indices: indices of texts not in cache
            miss_texts: the texts not in cache
        """
        hits: dict[int, list[float]] = {}
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for i, text in enumerate(texts):
            vec = self.get(text)
            if vec is not None:
                hits[i] = vec
            else:
                miss_indices.append(i)
                miss_texts.append(text)
        return hits, miss_indices, miss_texts

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "model": self._model,
            "dimension": self._dimension,
            "entries": self._entries,
        }
        self._path.write_text(json.dumps(data), encoding="utf-8")

    def _load(self) -> None:
        """Load the embed cache from disk.

        Validates the JSON root is a mapping. ``data.get(\"model\")``
        and the subsequent ``data.get(...)`` calls would raise
        AttributeError on non-dict roots — the
        ``(json.JSONDecodeError, OSError)`` catch missed it. Same
        shape as the other recent SHM-read fixes.
        """
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt embed cache at %s, starting fresh", self._path)
            return
        if not isinstance(data, dict):
            log.warning(
                "Embed cache root is %s, expected mapping; starting fresh",
                type(data).__name__,
            )
            return
        if data.get("model") != self._model or data.get("dimension") != self._dimension:
            log.info(
                "Embed cache invalidated (model/dim changed: %s/%s -> %s/%s)",
                data.get("model"),
                data.get("dimension"),
                self._model,
                self._dimension,
            )
            return
        entries_raw = data.get("entries", {})
        self._entries = entries_raw if isinstance(entries_raw, dict) else {}
        log.info("Loaded %d cached embeddings from %s", len(self._entries), self._path)
