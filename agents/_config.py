"""Vendored config constants for the agents package.

Subset of shared/config.py -- only the symbols used by agents/ modules.
"""

import functools
import logging
import os
import warnings
from pathlib import Path

from opentelemetry import trace
from qdrant_client import QdrantClient

# -- Environment ---------------------------------------------------------------

LITELLM_BASE: str = os.environ.get(
    "LITELLM_API_BASE",
    os.environ.get("LITELLM_BASE_URL", "http://localhost:4000"),
)
LITELLM_KEY: str = os.environ.get("LITELLM_API_KEY", "")
if not LITELLM_KEY:
    warnings.warn(
        "LITELLM_API_KEY is not set -- LLM calls will fail until a valid key is provided",
        stacklevel=1,
    )
QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LOGOS_API_URL: str = os.environ.get("COCKPIT_BASE_URL", "http://localhost:8051/api")

# Legacy alias
COCKPIT_API_URL: str = LOGOS_API_URL

# -- Canonical paths -----------------------------------------------------------

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
PROFILES_DIR: Path = _PROJECT_ROOT / "profiles"
HAPAX_HOME: Path = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
HAPAX_PROJECTS_DIR: Path = HAPAX_HOME / "projects"
HAPAX_CACHE_DIR: Path = HAPAX_HOME / ".cache"
LOGOS_STATE_DIR: Path = HAPAX_CACHE_DIR / "logos"
HAPAX_TMP_WAV_DIR: Path = HAPAX_CACHE_DIR / "hapax" / "tmp-wav"
WORK_VAULT_PATH: Path = Path(
    os.environ.get("WORK_VAULT_PATH", str(Path.home() / "Documents" / "Work"))
)
VAULT_PATH: Path = WORK_VAULT_PATH
PERSONAL_VAULT_PATH: Path = Path(
    os.environ.get("PERSONAL_VAULT_PATH", str(Path.home() / "Documents" / "Personal"))
)
HAPAX_CONSTITUTION_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-constitution"
HAPAXROMANA_DIR: Path = HAPAX_CONSTITUTION_DIR
HAPAX_COUNCIL_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-council"
AI_AGENTS_DIR: Path = HAPAX_COUNCIL_DIR
HAPAX_OFFICIUM_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-officium"
DISTRO_WORK_DIR: Path = HAPAX_PROJECTS_DIR / "distro-work"
OBSIDIAN_HAPAX_DIR: Path = HAPAX_PROJECTS_DIR / "obsidian-hapax"
LLM_STACK_DIR: Path = HAPAX_HOME / "llm-stack"
CLAUDE_CONFIG_DIR: Path = HAPAX_HOME / ".claude"
PASSWORD_STORE_DIR: Path = HAPAX_HOME / ".password-store"
RAG_SOURCES_DIR: Path = HAPAX_HOME / "documents" / "rag-sources"
SYSTEMD_USER_DIR: Path = Path.home() / ".config" / "systemd" / "user"

# State directories
AXIOM_AUDIT_DIR: Path = HAPAX_CACHE_DIR / "axiom-audit"
HEALTH_STATE_DIR: Path = HAPAX_CACHE_DIR / "health-watchdog"
RAG_INGEST_STATE_DIR: Path = HAPAX_CACHE_DIR / "rag-ingest"
TAKEOUT_STATE_DIR: Path = HAPAX_CACHE_DIR / "takeout-ingest"
AUDIO_PROCESSOR_CACHE_DIR: Path = HAPAX_CACHE_DIR / "audio-processor"

# Studio / audio paths
AUDIO_RAW_DIR: Path = HAPAX_HOME / "audio-recording" / "raw"
AUDIO_ARCHIVE_DIR: Path = HAPAX_HOME / "audio-recording" / "archive"
AUDIO_RAG_DIR: Path = HAPAX_HOME / "documents" / "rag-sources" / "audio"

# Legacy aliases
LOGOS_WEB_DIR: Path = HAPAX_COUNCIL_DIR / "hapax-logos"
HAPAX_SYSTEM_DIR: Path = HAPAX_COUNCIL_DIR
HAPAX_VSCODE_DIR: Path = HAPAX_COUNCIL_DIR / "vscode"

# -- Model aliases (LiteLLM route names) --------------------------------------

MODELS: dict[str, str] = {
    "fast": "gemini-flash",
    "balanced": "claude-sonnet",
    "long-context": "gemini-flash",
    "reasoning": "reasoning",
    "coding": "coding",
    "local-fast": "local-fast",
}

EMBEDDING_MODEL: str = "nomic-embed-cpu"
EXPECTED_EMBED_DIMENSIONS: int = 768
CLAP_EMBED_DIMENSIONS: int = 512
STUDIO_MOMENTS_COLLECTION: str = "studio-moments"


# -- Factories -----------------------------------------------------------------


def get_model(alias_or_id: str = "balanced"):
    """Create a LiteLLM-backed chat model."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.litellm import LiteLLMProvider

    model_id = MODELS.get(alias_or_id, alias_or_id)
    return OpenAIChatModel(
        model_id,
        provider=LiteLLMProvider(api_base=LITELLM_BASE, api_key=LITELLM_KEY),
    )


def get_model_adaptive(alias: str = "balanced"):
    """Stimmung-aware model selection -- downgrades when system is stressed."""
    import json
    from pathlib import Path

    try:
        raw = json.loads(Path("/dev/shm/hapax-stimmung/state.json").read_text(encoding="utf-8"))
        stance = raw.get("overall_stance", "nominal")
        cost = raw.get("llm_cost_pressure", {}).get("value", 0.0)
        resource = raw.get("resource_pressure", {}).get("value", 0.0)

        if stance == "critical":
            _log.debug("Stimmung critical -> routing to local-fast")
            return get_model("local-fast")

        if resource > 0.7:
            downgraded = {"balanced": "fast", "fast": "local-fast", "reasoning": "local-fast"}
            if alias in downgraded:
                _log.debug(
                    "Resource pressure %.2f -> %s downgraded to %s",
                    resource,
                    alias,
                    downgraded[alias],
                )
                return get_model(downgraded[alias])

        if cost > 0.6:
            downgraded = {"balanced": "fast", "reasoning": "fast"}
            if alias in downgraded:
                _log.debug(
                    "Cost pressure %.2f -> %s downgraded to %s", cost, alias, downgraded[alias]
                )
                return get_model(downgraded[alias])

    except Exception:
        pass

    return get_model(alias)


@functools.lru_cache(maxsize=1)
def get_qdrant() -> QdrantClient:
    """Return a QdrantClient connected to the configured URL (singleton)."""
    return QdrantClient(QDRANT_URL)


@functools.lru_cache(maxsize=1)
def get_qdrant_grpc() -> QdrantClient:
    """Return a QdrantClient using gRPC transport (lower latency for hot paths)."""
    return QdrantClient(QDRANT_URL, prefer_grpc=True, grpc_port=6334)


_log = logging.getLogger("agents._config")
_rag_tracer = trace.get_tracer("hapax.rag")


@functools.lru_cache(maxsize=1)
def _get_ollama_client():
    """Return a singleton Ollama client."""
    import ollama

    return ollama.Client(timeout=120)


def embed(text: str, model: str | None = None, prefix: str = "search_query") -> list[float]:
    """Generate embedding via Ollama."""
    model_name = model or EMBEDDING_MODEL
    _parent = trace.get_current_span()
    _caller_agent = ""
    if _parent and hasattr(_parent, "attributes") and _parent.attributes:
        _caller_agent = _parent.attributes.get("agent.name", "")
    with _rag_tracer.start_as_current_span("rag.embed") as span:
        if _caller_agent:
            span.set_attribute("agent.name", _caller_agent)
        span.set_attribute("rag.embed.model", model_name)
        span.set_attribute("rag.embed.prefix", prefix)
        span.set_attribute("rag.embed.text_length", len(text))
        prefixed = f"{prefix}: {text}" if prefix else text
        try:
            from agents._gpu_semaphore import gpu_slot

            client = _get_ollama_client()
            with gpu_slot():
                result = client.embed(model=model_name, input=prefixed)
        except Exception as exc:
            span.set_attribute("rag.error", str(exc)[:500])
            raise RuntimeError(f"Embedding failed (model={model_name}): {exc}") from exc
        vec = result["embeddings"][0]
        if len(vec) != EXPECTED_EMBED_DIMENSIONS:
            raise RuntimeError(
                f"Expected {EXPECTED_EMBED_DIMENSIONS}-dim embedding, got {len(vec)}"
            )
        span.set_attribute("rag.embed.dimensions", len(vec))
        return vec


def embed_safe(
    text: str, model: str | None = None, prefix: str = "search_query"
) -> list[float] | None:
    """Generate embedding via Ollama with graceful degradation."""
    try:
        return embed(text, model=model, prefix=prefix)
    except RuntimeError:
        _log.warning("embed_safe: Ollama unavailable, returning None")
        return None


def embed_batch(
    texts: list[str],
    model: str | None = None,
    prefix: str = "search_document",
) -> list[list[float]]:
    """Generate embeddings for multiple texts via Ollama."""
    if not texts:
        return []
    model_name = model or EMBEDDING_MODEL
    _parent = trace.get_current_span()
    _caller_agent = ""
    if _parent and hasattr(_parent, "attributes") and _parent.attributes:
        _caller_agent = _parent.attributes.get("agent.name", "")
    with _rag_tracer.start_as_current_span("rag.embed_batch") as span:
        if _caller_agent:
            span.set_attribute("agent.name", _caller_agent)
        span.set_attribute("rag.embed_batch.model", model_name)
        span.set_attribute("rag.embed_batch.prefix", prefix)
        span.set_attribute("rag.embed_batch.count", len(texts))
        span.set_attribute("rag.embed_batch.total_chars", sum(len(t) for t in texts))
        prefixed = [f"{prefix}: {t}" if prefix else t for t in texts]
        try:
            from agents._gpu_semaphore import gpu_slot

            client = _get_ollama_client()
            with gpu_slot():
                result = client.embed(model=model_name, input=prefixed)
        except Exception as exc:
            span.set_attribute("rag.error", str(exc)[:500])
            raise RuntimeError(f"Batch embedding failed (model={model_name}): {exc}") from exc
        embeddings = result["embeddings"]
        for i, vec in enumerate(embeddings):
            if len(vec) != EXPECTED_EMBED_DIMENSIONS:
                raise RuntimeError(
                    f"Expected {EXPECTED_EMBED_DIMENSIONS}-dim embedding at index {i}, "
                    f"got {len(vec)}"
                )
        span.set_attribute("rag.embed_batch.dimensions", len(embeddings[0]) if embeddings else 0)
        return embeddings


def embed_batch_safe(
    texts: list[str],
    model: str | None = None,
    prefix: str = "search_document",
) -> list[list[float]] | None:
    """Generate batch embeddings with graceful degradation."""
    try:
        return embed_batch(texts, model=model, prefix=prefix)
    except RuntimeError:
        _log.warning("embed_batch_safe: Ollama unavailable, returning None")
        return None


@functools.lru_cache(maxsize=1)
def load_expected_timers() -> dict[str, str]:
    """Load the expected systemd timer manifest (cached)."""
    from agents._agent_registry import get_registry

    return get_registry().expected_timers()


def validate_embed_dimensions() -> None:
    """Verify embedding model returns expected dimensions."""
    test = embed("dimension check", prefix="search_query")
    if len(test) != EXPECTED_EMBED_DIMENSIONS:
        raise RuntimeError(
            f"Embedding model returned {len(test)}d, expected {EXPECTED_EMBED_DIMENSIONS}d. "
            f"Check EMBED_MODEL={EMBEDDING_MODEL}"
        )


def ensure_studio_moments_collection() -> None:
    """Create the studio-moments Qdrant collection if it does not exist."""
    from qdrant_client.models import Distance, VectorParams

    client = get_qdrant()
    collections = [c.name for c in client.get_collections().collections]
    if STUDIO_MOMENTS_COLLECTION not in collections:
        client.create_collection(
            collection_name=STUDIO_MOMENTS_COLLECTION,
            vectors_config=VectorParams(
                size=CLAP_EMBED_DIMENSIONS,
                distance=Distance.COSINE,
            ),
        )
        _log.info(
            "Created Qdrant collection '%s' (%d-dim, cosine)",
            STUDIO_MOMENTS_COLLECTION,
            CLAP_EMBED_DIMENSIONS,
        )
