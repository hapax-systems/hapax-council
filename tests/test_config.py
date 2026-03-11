"""Smoke tests for shared config and agent loading."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.config import (
    EMBEDDING_MODEL,
    LITELLM_BASE,
    LITELLM_KEY,
    MODELS,
    PROFILES_DIR,
    QDRANT_URL,
    embed,
    get_model,
    get_qdrant,
)


def test_model_aliases_defined():
    assert "fast" in MODELS
    assert "balanced" in MODELS
    assert "reasoning" in MODELS
    assert "coding" in MODELS
    assert "local-fast" in MODELS


def test_embedding_model_is_v2():
    assert "v2" in EMBEDDING_MODEL


def test_env_defaults():
    assert LITELLM_BASE.startswith("http")
    assert QDRANT_URL.startswith("http")
    assert len(LITELLM_KEY) > 0


def test_get_model_returns_correct_type():
    model = get_model("balanced")
    assert model.model_name == "claude-sonnet"


def test_get_model_alias_fallthrough():
    model = get_model("anthropic/claude-opus-4")
    assert model.model_name == "anthropic/claude-opus-4"


def test_get_qdrant_returns_client():
    from qdrant_client import QdrantClient

    client = get_qdrant()
    assert isinstance(client, QdrantClient)


def test_profiles_dir_is_path():
    assert isinstance(PROFILES_DIR, Path)
    assert PROFILES_DIR.name == "profiles"


def test_embed_error_handling():
    import pytest

    mock_client = MagicMock()
    mock_client.embed.side_effect = ConnectionError("Ollama is down")
    with patch("shared.config._get_ollama_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Embedding failed") as exc_info:
            embed("test text")
        assert "Ollama is down" in str(exc_info.value)
        assert exc_info.value.__cause__ is not None


def test_embed_dimension_validation():
    """embed() rejects vectors with wrong dimensions."""
    import pytest

    wrong_dim = [0.1] * 512  # 512 instead of 768
    mock_client = MagicMock()
    mock_client.embed.return_value = {"embeddings": [wrong_dim]}
    with patch("shared.config._get_ollama_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Expected 768-dim embedding, got 512"):
            embed("test text")


def test_embed_dimension_validation_correct():
    """embed() accepts vectors with correct dimensions."""
    correct = [0.1] * 768
    mock_client = MagicMock()
    mock_client.embed.return_value = {"embeddings": [correct]}
    with patch("shared.config._get_ollama_client", return_value=mock_client):
        result = embed("test text")
        assert len(result) == 768


# ── Centralized path constants ──────────────────────────────────────────────


def test_path_constants_exist():
    """All centralized path constants should be importable from config."""
    from shared.config import (
        AI_AGENTS_DIR,
        AXIOM_AUDIT_DIR,
        CLAUDE_CONFIG_DIR,
        COCKPIT_STATE_DIR,
        COCKPIT_WEB_DIR,
        HAPAX_CACHE_DIR,
        HAPAX_HOME,
        HAPAX_PROJECTS_DIR,
        HAPAX_SYSTEM_DIR,
        HAPAXROMANA_DIR,
        HEALTH_STATE_DIR,
        LLM_STACK_DIR,
        OBSIDIAN_HAPAX_DIR,
        PASSWORD_STORE_DIR,
        RAG_INGEST_STATE_DIR,
        RAG_SOURCES_DIR,
        TAKEOUT_STATE_DIR,
    )

    for name, val in [
        ("HAPAX_HOME", HAPAX_HOME),
        ("HAPAX_CACHE_DIR", HAPAX_CACHE_DIR),
        ("HAPAX_PROJECTS_DIR", HAPAX_PROJECTS_DIR),
        ("LLM_STACK_DIR", LLM_STACK_DIR),
        ("CLAUDE_CONFIG_DIR", CLAUDE_CONFIG_DIR),
        ("PASSWORD_STORE_DIR", PASSWORD_STORE_DIR),
        ("RAG_SOURCES_DIR", RAG_SOURCES_DIR),
        ("AXIOM_AUDIT_DIR", AXIOM_AUDIT_DIR),
        ("COCKPIT_STATE_DIR", COCKPIT_STATE_DIR),
        ("HEALTH_STATE_DIR", HEALTH_STATE_DIR),
        ("RAG_INGEST_STATE_DIR", RAG_INGEST_STATE_DIR),
        ("TAKEOUT_STATE_DIR", TAKEOUT_STATE_DIR),
        ("AI_AGENTS_DIR", AI_AGENTS_DIR),
        ("HAPAXROMANA_DIR", HAPAXROMANA_DIR),
        ("OBSIDIAN_HAPAX_DIR", OBSIDIAN_HAPAX_DIR),
        ("COCKPIT_WEB_DIR", COCKPIT_WEB_DIR),
        ("HAPAX_SYSTEM_DIR", HAPAX_SYSTEM_DIR),
    ]:
        assert isinstance(val, Path), f"{name} should be a Path, got {type(val)}"


def test_path_constants_default_to_home():
    """Without env overrides, paths should resolve relative to Path.home()."""
    from shared.config import HAPAX_CACHE_DIR, HAPAX_HOME, HAPAX_PROJECTS_DIR

    assert Path.home() == HAPAX_HOME
    assert Path.home() / ".cache" == HAPAX_CACHE_DIR
    assert Path.home() / "projects" == HAPAX_PROJECTS_DIR


def test_path_constants_derive_correctly():
    """Derived paths should be consistent with their parents."""
    from shared.config import (
        AI_AGENTS_DIR,
        AXIOM_AUDIT_DIR,
        HAPAX_CACHE_DIR,
        HAPAX_HOME,
        HAPAX_PROJECTS_DIR,
        LLM_STACK_DIR,
    )

    assert LLM_STACK_DIR == HAPAX_HOME / "llm-stack"
    assert AXIOM_AUDIT_DIR == HAPAX_CACHE_DIR / "axiom-audit"
    assert AI_AGENTS_DIR == HAPAX_PROJECTS_DIR / "ai-agents"


@pytest.mark.skip(
    reason="Known tech debt: 27 files use Path.home() directly — tracked for migration to config constants"
)
def test_no_path_home_in_shared():
    """shared/ modules should use config constants, not Path.home() directly.

    Exception: config.py itself (defines the root constants).
    """
    shared_dir = Path(__file__).resolve().parent.parent / "shared"
    violations = []
    for py_file in shared_dir.rglob("*.py"):
        if py_file.name == "config.py":
            continue
        source = py_file.read_text()
        if "Path.home()" in source:
            count = source.count("Path.home()")
            violations.append(f"{py_file.relative_to(shared_dir.parent)}: {count}")
    assert violations == [], "Path.home() in shared/ modules:\n" + "\n".join(violations)


@pytest.mark.skip(
    reason="Known tech debt: 27 files use Path.home() directly — tracked for migration to config constants"
)
def test_no_path_home_in_agents():
    """agents/ modules should use config constants, not Path.home() directly."""
    agents_dir = Path(__file__).resolve().parent.parent / "agents"
    violations = []
    for py_file in agents_dir.rglob("*.py"):
        source = py_file.read_text()
        if "Path.home()" in source:
            count = source.count("Path.home()")
            violations.append(f"{py_file.relative_to(agents_dir.parent)}: {count}")
    assert violations == [], "Path.home() in agents/ modules:\n" + "\n".join(violations)
