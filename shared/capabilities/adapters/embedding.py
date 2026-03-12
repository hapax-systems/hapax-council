"""Ollama embedding adapter — proof-of-pattern for EmbeddingCapability."""

from __future__ import annotations

import logging

from shared.capabilities.protocols import EmbeddingResult, HealthStatus

log = logging.getLogger(__name__)


class OllamaEmbeddingAdapter:
    """EmbeddingCapability adapter backed by a local Ollama instance.

    Implements the EmbeddingCapability Protocol. Connects to Ollama's
    HTTP API for embedding generation.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
    ) -> None:
        self._base_url = base_url
        self._model = model

    @property
    def name(self) -> str:
        return f"ollama-embedding({self._model})"

    def available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            import httpx

            resp = httpx.get(f"{self._base_url}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def health(self) -> HealthStatus:
        """Check Ollama health and model availability."""
        try:
            import time

            import httpx

            start = time.monotonic()
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=2.0)
            latency = (time.monotonic() - start) * 1000

            if resp.status_code != 200:
                return HealthStatus(healthy=False, message=f"HTTP {resp.status_code}")

            models = resp.json().get("models", [])
            model_names = [m.get("name", "").split(":")[0] for m in models]
            if self._model not in model_names:
                return HealthStatus(
                    healthy=False,
                    message=f"Model {self._model} not found (available: {model_names[:5]})",
                    latency_ms=latency,
                )
            return HealthStatus(healthy=True, message="ok", latency_ms=latency)
        except Exception as e:
            return HealthStatus(healthy=False, message=str(e))

    def embed(self, text: str) -> EmbeddingResult:
        """Generate an embedding vector via Ollama."""
        import httpx

        resp = httpx.post(
            f"{self._base_url}/api/embed",
            json={"model": self._model, "input": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [[]])[0]
        return EmbeddingResult(
            vector=embeddings,
            model=self._model,
            dimensions=len(embeddings),
        )
