"""shared/config.py — Central configuration for all agents.

Provides model aliases, factory functions for LiteLLM-backed models,
Qdrant client, embedding via Ollama, and canonical path constants.
"""

import functools
import logging
import os
import warnings
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
LITELLM_KEY: str = os.environ.get("LITELLM_API_KEY", "")
if not LITELLM_KEY:
    warnings.warn(
        "LITELLM_API_KEY is not set — LLM calls will fail until a valid key is provided",
        stacklevel=1,
    )
QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LOGOS_API_URL: str = os.environ.get("COCKPIT_BASE_URL", "http://localhost:8051/api")

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
LOGOS_STATE_DIR: Path = HAPAX_CACHE_DIR / "logos"
HEALTH_STATE_DIR: Path = HAPAX_CACHE_DIR / "health-watchdog"
RAG_INGEST_STATE_DIR: Path = HAPAX_CACHE_DIR / "rag-ingest"
TAKEOUT_STATE_DIR: Path = HAPAX_CACHE_DIR / "takeout-ingest"
AUDIO_PROCESSOR_CACHE_DIR: Path = HAPAX_CACHE_DIR / "audio-processor"
HAPAX_TMP_WAV_DIR: Path = HAPAX_CACHE_DIR / "hapax" / "tmp-wav"

# Studio ingestion paths
AUDIO_RAW_DIR: Path = HAPAX_HOME / "audio-recording" / "raw"
AUDIO_ARCHIVE_DIR: Path = HAPAX_HOME / "audio-recording" / "archive"
AUDIO_RAG_DIR: Path = HAPAX_HOME / "documents" / "rag-sources" / "audio"

# Project directories (for agents that reference other repos)
# Current 4-repo structure (2026-03-13)
HAPAX_COUNCIL_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-council"
HAPAX_CONSTITUTION_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-constitution"
HAPAX_OFFICIUM_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-officium"
DISTRO_WORK_DIR: Path = HAPAX_PROJECTS_DIR / "distro-work"
OBSIDIAN_HAPAX_DIR: Path = HAPAX_PROJECTS_DIR / "obsidian-hapax"

# Legacy aliases — migrate callers to new names, then remove
AI_AGENTS_DIR: Path = HAPAX_COUNCIL_DIR
HAPAXROMANA_DIR: Path = HAPAX_CONSTITUTION_DIR
LOGOS_WEB_DIR: Path = HAPAX_COUNCIL_DIR / "hapax-logos"
HAPAX_SYSTEM_DIR: Path = HAPAX_COUNCIL_DIR
HAPAX_VSCODE_DIR: Path = HAPAX_COUNCIL_DIR / "vscode"

# ── Model aliases (LiteLLM route names) ─────────────────────────────────────

MODELS: dict[str, str] = {
    "fast": "gemini-flash",
    "balanced": "claude-sonnet",
    "long-context": "gemini-flash",  # 1M context, for prompts that exceed 200K
    "reasoning": "reasoning",
    "coding": "coding",
    "local-fast": "local-fast",
    "local-research-instruct": "local-research-instruct",
    # Gemini 3 family — Phase A substrate, ADD-ONLY (do not migrate
    # `fast`/`long-context` until smoke + 14d observability shows parity).
    # Per docs/research/2026-05-01-litellm-gemini-3-route-evaluation.md.
    "fast-3": "gemini-3-flash-preview",
    "long-context-3": "gemini-3-flash-preview",
    "extraction": "gemini-3.1-flash-lite-preview",
    "scouting": "gemini-3.1-flash-lite-preview",
    # Vision route — cc-task jr-gemini-3-flash-vision-router-update.
    # Gemini 3 Flash with media_resolution="low" is the price-performance
    # leader for 10fps DMN per-tick vision (~$0.00014/frame at low-res
    # 280-token mode). Callers MUST pass `media_resolution: "low"` in
    # extra_body alongside the existing `budget_tokens: 0` invariant.
    "vision-fast": "gemini-3-flash-preview",
    # Perplexity Sonar family — search-grounded web models. ADD-ONLY.
    # Per docs/superpowers/specs/2026-05-15-perplexity-api-integration-design.md.
    "web-scout": "web-scout",
    "web-research": "web-research",
    "web-reason": "web-reason",
    "web-deep": "web-deep",
}

EMBEDDING_MODEL: str = "nomic-embed-cpu"
EXPECTED_EMBED_DIMENSIONS: int = 768

# CLAP (audio-text) embedding dimensions
CLAP_EMBED_DIMENSIONS: int = 512

# Qdrant collections
STUDIO_MOMENTS_COLLECTION: str = "studio-moments"


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


def get_model_adaptive(alias: str = "balanced") -> OpenAIChatModel:
    """Stimmung-aware model selection — downgrades when system is stressed.

    Reads live stimmung from /dev/shm. When cost pressure or resource pressure
    is high, routes to cheaper/local models instead of the requested tier.

    Downgrade rules:
    - llm_cost_pressure > 0.6: balanced→fast, fast stays fast
    - resource_pressure > 0.7: balanced→fast, fast→local-fast
    - critical stance: everything→local-fast
    """
    import json
    from pathlib import Path

    try:
        raw = json.loads(Path("/dev/shm/hapax-stimmung/state.json").read_text(encoding="utf-8"))
        stance = raw.get("overall_stance", "nominal")
        cost = raw.get("llm_cost_pressure", {}).get("value", 0.0)
        resource = raw.get("resource_pressure", {}).get("value", 0.0)

        if stance == "critical":
            _log.debug("Stimmung critical → routing to local-fast")
            return get_model("local-fast")

        if resource > 0.7:
            downgraded = {
                "balanced": "fast",
                "fast": "local-fast",
                "reasoning": "local-fast",
                # Gemini 3 family degradation, per the route-evaluation doc.
                "fast-3": "fast",
                "long-context-3": "long-context",
                "extraction": "fast-3",
                "scouting": "fast-3",
                "web-deep": "web-research",
                "web-research": "web-scout",
                "web-reason": "web-scout",
                "web-scout": "balanced",
            }
            if alias in downgraded:
                _log.debug(
                    "Resource pressure %.2f → %s downgraded to %s",
                    resource,
                    alias,
                    downgraded[alias],
                )
                return get_model(downgraded[alias])

        if cost > 0.6:
            downgraded = {
                "balanced": "fast",
                "reasoning": "fast",
                "web-deep": "web-scout",
                "web-research": "web-scout",
            }
            if alias in downgraded:
                _log.debug(
                    "Cost pressure %.2f → %s downgraded to %s", cost, alias, downgraded[alias]
                )
                return get_model(downgraded[alias])

    except Exception:
        pass  # stimmung unavailable → use requested model

    return get_model(alias)


@functools.lru_cache(maxsize=1)
def _get_qdrant_raw() -> QdrantClient:
    """Return the raw (ungated) QdrantClient. For internal use only.

    Callers should use ``get_qdrant()`` which wraps the raw client with
    the consent-gate proxy. The raw client is exposed here for schema
    bootstrapping, tests, and the gate itself (which needs unwrapped
    access to write through).
    """
    return QdrantClient(QDRANT_URL)


@functools.lru_cache(maxsize=1)
def get_qdrant():
    """Return a consent-gated Qdrant client (LRR Phase 6 §3 / FINDING-R).

    Wraps the raw client with ``ConsentGatedQdrant`` so every upsert to
    a person-adjacent collection passes the consent gate. Reads and
    schema operations pass through to the raw client unchanged via
    ``__getattr__`` proxying.

    For schema bootstrapping / tests that explicitly need the ungated
    client, import ``_get_qdrant_raw`` directly.
    """
    from shared.governance.qdrant_gate import ConsentGatedQdrant

    return ConsentGatedQdrant(inner=_get_qdrant_raw())


@functools.lru_cache(maxsize=1)
def _get_qdrant_grpc_raw() -> QdrantClient:
    """Return the raw (ungated) gRPC QdrantClient. For internal use only.

    Same role as ``_get_qdrant_raw``: exposed so ``ConsentGatedQdrant`` can
    write through after its checks, and so schema bootstrapping can reach
    the unwrapped client.
    """
    return QdrantClient(QDRANT_URL, prefer_grpc=True, grpc_port=6334)


@functools.lru_cache(maxsize=1)
def get_qdrant_grpc():
    """Return a consent-gated gRPC QdrantClient (LRR Phase 6 §3 / FINDING-R).

    Identical consent-gating semantics as ``get_qdrant()``; wraps the raw
    gRPC client with ``ConsentGatedQdrant`` so person-adjacent upserts
    filter unconsented points regardless of transport. Reads and schema
    calls proxy through unchanged via ``__getattr__``.

    Closes the follow-up flagged during the initial FINDING-R wire-in:
    gRPC callers in ``agents/hapax_daimonion/tools.py`` and elsewhere
    were bypassing the gate while the HTTP factory was already gated.
    """
    from shared.governance.qdrant_gate import ConsentGatedQdrant

    return ConsentGatedQdrant(inner=_get_qdrant_grpc_raw())


class InstrumentedQdrantClient:
    """Wrapper that emits flow events on Qdrant operations.

    Per cc-task ``instrumented-qdrant-positional-fix`` (audit Auditor D
    B3 finding #7): wrapped methods MUST accept ``*args, **kwargs`` and
    delegate with full positional+keyword pass-through. The earlier
    shape (``def search(self, collection_name: str, **kwargs)``)
    silently broke any caller passing ``query_vector`` positionally,
    falsifying the "drop-in replacement" claim. MagicMock-based tests
    in #2257 missed this because MagicMock accepts any signature.

    Note on ``query_points`` vs ``search``: modern qdrant-client has
    REPLACED ``QdrantClient.search`` with ``query_points``. The legacy
    ``search`` method does not exist on the underlying client at all;
    invoking it raises ``AttributeError``. Production callers (verified
    via grep across ``agents/`` + ``shared/``) all use ``query_points``
    or ``upsert`` — no live ``.search`` callers remain. This class
    exposes ``query_points`` as the primary read wrapper; the legacy
    ``search`` method is kept as a deprecation-stub that raises a
    clear ``AttributeError`` so callers migrate intentionally.
    """

    def __init__(
        self, client: QdrantClient, event_bus: "EventBus", agent_name: str = "unknown"
    ) -> None:
        self._client = client
        self._bus = event_bus
        self._agent = agent_name

    def __getattr__(self, name: str):
        # Methods we don't explicitly wrap fall through to the
        # underlying client unchanged. `__getattr__` is only invoked
        # for attributes not found via the normal lookup, so wrapped
        # methods (`query_points`, `upsert`, `search`) are NOT affected
        # by this proxy. Missing methods on the underlying client raise
        # `AttributeError` naturally — preserving the underlying API
        # surface as observed by callers.
        return getattr(self._client, name)

    def _emit(self, op: str, collection: str) -> None:
        from logos.event_bus import FlowEvent

        self._bus.emit(
            FlowEvent(
                kind="qdrant.op",
                source=self._agent,
                target="qdrant",
                label=f"{op}/{collection}",
            )
        )

    @staticmethod
    def _resolve_collection(args: tuple, kwargs: dict) -> str:
        """Extract the collection_name for the FlowEvent label. The
        underlying QdrantClient methods accept ``collection_name`` as
        the first positional arg or as a kwarg. Both shapes resolve
        to a stable label."""
        if "collection_name" in kwargs:
            return str(kwargs["collection_name"])
        if args:
            return str(args[0])
        return "unknown"

    def query_points(self, *args, **kwargs):
        """Modern read API; replaces legacy ``search``.

        Accepts the underlying QdrantClient.query_points signature
        verbatim — full positional and keyword pass-through. The
        FlowEvent label uses the resolved collection_name regardless
        of arg shape.
        """
        self._emit("query_points", self._resolve_collection(args, kwargs))
        return self._client.query_points(*args, **kwargs)

    def upsert(self, *args, **kwargs):
        """Write API; full positional+keyword pass-through.

        Per audit Auditor D B3 finding #7: the prior shape
        ``def upsert(self, collection_name: str, **kwargs)`` rejected
        positional ``points`` calls. This shape preserves the
        underlying QdrantClient.upsert signature exactly so the
        wrapper is a true drop-in.
        """
        self._emit("upsert", self._resolve_collection(args, kwargs))
        return self._client.upsert(*args, **kwargs)

    def search(self, *args, **kwargs):
        """LEGACY method — raises AttributeError matching the underlying
        client's API.

        Modern qdrant-client has removed ``QdrantClient.search`` in
        favor of ``query_points``. Production code in ``agents/`` +
        ``shared/`` has migrated. This stub raises a clear, attributable
        AttributeError so any straggling caller migrates intentionally
        rather than getting a confusing wrap-then-attribute-error
        chain. Bypass: use ``query_points`` directly.
        """
        raise AttributeError(
            "InstrumentedQdrantClient.search has been removed: modern qdrant-client "
            "has replaced QdrantClient.search with query_points. Use "
            "InstrumentedQdrantClient.query_points(...) instead. See cc-task "
            "instrumented-qdrant-positional-fix for context."
        )


def get_qdrant_instrumented(agent_name: str, event_bus: "EventBus | None" = None):
    """Return a consent-gated Qdrant client that ALSO emits FlowEvents per op.

    Closes the wire half of cc-task
    ``r16-langfuse-qdrant-microprobe-agentrunner-wire-delete`` for the
    ``InstrumentedQdrantClient`` surface. The R-16 audit
    (``docs/research/2026-04-26-r16-langfuse-instrumented-qdrant-audit.md``)
    found the wrapper class was correctly structured but had zero
    production callsites — the factory entry point was missing.

    When ``event_bus is None``, returns the existing ``get_qdrant()``
    client unchanged (no FlowEvent emission). This makes the factory a
    safe drop-in: callers that have no bus get the same consent-gated
    client they would have gotten from ``get_qdrant()``.

    When a bus is provided, wraps the consent-gated client with
    ``InstrumentedQdrantClient`` so ``search()`` and ``upsert()`` calls
    emit ``FlowEvent(kind="qdrant.op", source=agent_name, target="qdrant",
    label="<op>/<collection>")`` to the Logos flow-bus before delegating.
    The two ``__getattr__`` layers (instrumentation outer, consent gate
    inner) compose cleanly: instrumented ops go through the gate; non-
    instrumented attribute access proxies through both layers.

    Migration is opt-in per caller — existing ``get_qdrant()`` callers
    keep their current behavior. New observability needs can adopt by
    swapping the factory and passing the agent's bus handle.
    """
    base = get_qdrant()
    if event_bus is None:
        return base
    return InstrumentedQdrantClient(client=base, event_bus=event_bus, agent_name=agent_name)


_log = logging.getLogger("shared.config")
_rag_tracer = trace.get_tracer("hapax.rag")


@functools.lru_cache(maxsize=1)
def _get_ollama_client():
    """Return a singleton Ollama client (avoids per-call HTTP client creation)."""
    import ollama

    return ollama.Client(timeout=120)


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
    # Capture calling agent name from parent span before entering new span
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
        _log.debug("embed: model=%s len=%d prefix=%s", model_name, len(text), prefix)
        try:
            from shared.gpu_semaphore import gpu_slot

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
    """Generate embedding via Ollama with graceful degradation (cb-degrade-001).

    Returns None instead of raising when Ollama is unavailable. Callers
    decide how to handle: skip, cache, or notify.
    """
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
    # Capture calling agent name from parent span before entering new span
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
        _log.debug("embed_batch: model=%s count=%d prefix=%s", model_name, len(texts), prefix)
        try:
            from shared.gpu_semaphore import gpu_slot

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
                    f"Expected {EXPECTED_EMBED_DIMENSIONS}-dim embedding at index {i}, got {len(vec)}"
                )
        span.set_attribute("rag.embed_batch.dimensions", len(embeddings[0]) if embeddings else 0)
        return embeddings


def embed_batch_safe(
    texts: list[str],
    model: str | None = None,
    prefix: str = "search_document",
) -> list[list[float]] | None:
    """Generate batch embeddings with graceful degradation (cb-degrade-001).

    Returns None instead of raising when Ollama is unavailable.
    """
    try:
        return embed_batch(texts, model=model, prefix=prefix)
    except RuntimeError:
        _log.warning("embed_batch_safe: Ollama unavailable, returning None")
        return None


@functools.lru_cache(maxsize=1)
def load_expected_timers() -> dict[str, str]:
    """Load the expected systemd timer manifest (cached).

    Returns a dict mapping agent_name → timer unit name.
    Derived from the agent manifest registry.
    """
    from shared.agent_registry import get_registry

    return get_registry().expected_timers()


def validate_embed_dimensions() -> None:
    """Verify embedding model returns expected dimensions.

    Call on startup from agents that depend on correct embedding dimensions.
    Raises RuntimeError if dimensions don't match.
    """
    test = embed("dimension check", prefix="search_query")
    if len(test) != EXPECTED_EMBED_DIMENSIONS:
        raise RuntimeError(
            f"Embedding model returned {len(test)}d, expected {EXPECTED_EMBED_DIMENSIONS}d. "
            f"Check EMBED_MODEL={EMBEDDING_MODEL}"
        )


def ensure_studio_moments_collection() -> None:
    """Create the studio-moments Qdrant collection if it does not exist.

    Uses CLAP 512-dim vectors with cosine distance. Idempotent.
    """
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
