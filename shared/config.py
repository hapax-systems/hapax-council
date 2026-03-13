"""shared/config.py — Central configuration for all agents.

Provides model aliases, factory functions for LiteLLM-backed models,
Qdrant client, embedding via Ollama, and canonical path constants.
"""

import logging
import os
from pathlib import Path

from opentelemetry import trace
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.litellm import LiteLLMProvider
from qdrant_client import QdrantClient

# ── Environment ──────────────────────────────────────────────────────────────

LITELLM_BASE: str = os.environ.get(
    "LITELLM_API_BASE",
    os.environ.get("LITELLM_BASE_URL", "http://localhost:4000"),
)
LITELLM_KEY: str = os.environ.get("LITELLM_API_KEY", "changeme")
QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://localhost:6333")

# ── Canonical paths ─────────────────────────────────────────────────────────

PROFILES_DIR: Path = Path(__file__).resolve().parent.parent / "profiles"
WORK_VAULT_PATH: Path = Path(
    os.environ.get("WORK_VAULT_PATH", str(Path.home() / "Documents" / "Work"))
)
PERSONAL_VAULT_PATH: Path = Path(
    os.environ.get("PERSONAL_VAULT_PATH", str(Path.home() / "Documents" / "Personal"))
)

# Backwards compat — most agents write to the work vault
VAULT_PATH: Path = WORK_VAULT_PATH

# ── Centralized path constants ─────────────────────────────────────────────
# All default to current filesystem layout. Override HAPAX_HOME to relocate
# the entire tree (e.g. for testing or multi-instance deployment).

HAPAX_HOME: Path = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
HAPAX_CACHE_DIR: Path = HAPAX_HOME / ".cache"
HAPAX_PROJECTS_DIR: Path = HAPAX_HOME / "projects"
LLM_STACK_DIR: Path = HAPAX_HOME / "llm-stack"
CLAUDE_CONFIG_DIR: Path = HAPAX_HOME / ".claude"
PASSWORD_STORE_DIR: Path = HAPAX_HOME / ".password-store"
RAG_SOURCES_DIR: Path = HAPAX_HOME / "documents" / "rag-sources"

# systemd user dir is always relative to real $HOME (not HAPAX_HOME)
SYSTEMD_USER_DIR: Path = Path.home() / ".config" / "systemd" / "user"

# State directories under ~/.cache/
AXIOM_AUDIT_DIR: Path = HAPAX_CACHE_DIR / "axiom-audit"
COCKPIT_STATE_DIR: Path = HAPAX_CACHE_DIR / "cockpit"
HEALTH_STATE_DIR: Path = HAPAX_CACHE_DIR / "health-watchdog"
RAG_INGEST_STATE_DIR: Path = HAPAX_CACHE_DIR / "rag-ingest"
TAKEOUT_STATE_DIR: Path = HAPAX_CACHE_DIR / "takeout-ingest"

# Project directories (for agents that reference other repos)
AI_AGENTS_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-council"
HAPAXROMANA_DIR: Path = HAPAX_PROJECTS_DIR / "hapaxromana"
OBSIDIAN_HAPAX_DIR: Path = HAPAX_PROJECTS_DIR / "obsidian-hapax"
COCKPIT_WEB_DIR: Path = HAPAX_PROJECTS_DIR / "cockpit-web"
HAPAX_SYSTEM_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-system"
HAPAX_VSCODE_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-vscode"

# ── Model aliases (LiteLLM route names) ─────────────────────────────────────

MODELS: dict[str, str] = {
    "fast": "gemini-flash",
    "balanced": "claude-sonnet",
    "reasoning": "qwen3.5:27b",
    "coding": "qwen3.5:27b",
    "local-fast": "qwen3:8b",
}

EMBEDDING_MODEL: str = "nomic-embed-text-v2-moe"
EXPECTED_EMBED_DIMENSIONS: int = 768


# ── Factories ────────────────────────────────────────────────────────────────


def get_model(alias_or_id: str = "balanced") -> OpenAIChatModel:
    """Create a LiteLLM-backed chat model.

    Accepts an alias from MODELS dict or a raw LiteLLM model ID.
    """
    model_id = MODELS.get(alias_or_id, alias_or_id)
    return OpenAIChatModel(
        model_id,
        provider=LiteLLMProvider(
            api_base=LITELLM_BASE,
            api_key=LITELLM_KEY,
        ),
    )


_qdrant_client: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    """Return a QdrantClient connected to the configured URL (singleton)."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(QDRANT_URL)
    return _qdrant_client


_log = logging.getLogger("shared.config")
_rag_tracer = trace.get_tracer("hapax.rag")

_ollama_client = None


def _get_ollama_client():
    """Return a singleton Ollama client (avoids per-call HTTP client creation)."""
    global _ollama_client
    if _ollama_client is None:
        import ollama

        _ollama_client = ollama.Client(timeout=120)
    return _ollama_client


def embed(text: str, model: str | None = None, prefix: str = "search_query") -> list[float]:
    """Generate embedding via Ollama (local, not routed through LiteLLM).

    Args:
        text: Text to embed.
        model: Ollama model name. Defaults to EMBEDDING_MODEL.
        prefix: nomic prefix — "search_query" for queries, "search_document" for indexing.

    Raises:
        RuntimeError: If the Ollama embed call fails.
    """
    model_name = model or EMBEDDING_MODEL
    with _rag_tracer.start_as_current_span("rag.embed") as span:
        span.set_attribute("rag.embed.model", model_name)
        span.set_attribute("rag.embed.prefix", prefix)
        span.set_attribute("rag.embed.text_length", len(text))
        prefixed = f"{prefix}: {text}" if prefix else text
        _log.debug("embed: model=%s len=%d prefix=%s", model_name, len(text), prefix)
        try:
            client = _get_ollama_client()
            result = client.embed(model=model_name, input=prefixed)
        except Exception as exc:
            span.set_attribute("rag.error", str(exc)[:500])
            raise RuntimeError(f"Embedding failed (model={model_name}): {exc}") from exc
        vec = result["embeddings"][0]
        if len(vec) != EXPECTED_EMBED_DIMENSIONS:
            raise RuntimeError(f"Expected {EXPECTED_EMBED_DIMENSIONS}-dim embedding, got {len(vec)}")
        span.set_attribute("rag.embed.dimensions", len(vec))
        return vec


def embed_batch(
    texts: list[str],
    model: str | None = None,
    prefix: str = "search_document",
) -> list[list[float]]:
    """Generate embeddings for multiple texts via Ollama /api/embed.

    Ollama's embed endpoint accepts a list input, providing 2-5x throughput
    over single-record embedding.

    Args:
        texts: List of texts to embed.
        model: Ollama model name. Defaults to EMBEDDING_MODEL.
        prefix: nomic prefix — "search_query" for queries, "search_document" for indexing.

    Raises:
        RuntimeError: If the Ollama embed call fails.
    """
    if not texts:
        return []
    model_name = model or EMBEDDING_MODEL
    with _rag_tracer.start_as_current_span("rag.embed_batch") as span:
        span.set_attribute("rag.embed_batch.model", model_name)
        span.set_attribute("rag.embed_batch.prefix", prefix)
        span.set_attribute("rag.embed_batch.count", len(texts))
        span.set_attribute("rag.embed_batch.total_chars", sum(len(t) for t in texts))
        prefixed = [f"{prefix}: {t}" if prefix else t for t in texts]
        _log.debug("embed_batch: model=%s count=%d prefix=%s", model_name, len(texts), prefix)
        try:
            client = _get_ollama_client()
            result = client.embed(model=model_name, input=prefixed)
        except Exception as exc:
            span.set_attribute("rag.error", str(exc)[:500])
            raise RuntimeError(f"Batch embedding failed (model={model_name}): {exc}") from exc
        embeddings = result["embeddings"]
        for i, vec in enumerate(embeddings):
            if len(vec) != EXPECTED_EMBED_DIMENSIONS:
                raise RuntimeError(
                    f"Expected {EXPECTED_EMBED_DIMENSIONS}-dim embedding at index {i}, got {len(vec)}"
                )
        span.set_attribute("rag.embed_batch.dimensions", len(embeddings[0]) if embeddings else 0)
        return embeddings


_expected_timers: dict[str, str] | None = None


def load_expected_timers() -> dict[str, str]:
    """Load the expected systemd timer manifest (cached).

    Returns a dict mapping agent_name → timer unit name.
    """
    global _expected_timers
    if _expected_timers is not None:
        return _expected_timers

    import yaml

    manifest = AI_AGENTS_DIR / "systemd" / "expected-timers.yaml"
    data = yaml.safe_load(manifest.read_text())
    _expected_timers = data["timers"]
    return _expected_timers


def validate_embed_dimensions() -> None:
    """Verify embedding model returns expected dimensions.

    Call on startup from agents that depend on correct embedding dimensions.
    Raises RuntimeError if dimensions don't match.
    """
    test = embed("dimension check")
    if len(test) != EXPECTED_EMBED_DIMENSIONS:
        raise RuntimeError(
            f"Embedding model returned {len(test)}d, expected {EXPECTED_EMBED_DIMENSIONS}d. "
            f"Check EMBED_MODEL={EMBEDDING_MODEL}"
        )
