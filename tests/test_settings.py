"""Tests for shared.settings — typed configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def test_default_settings_load():
    """Settings model loads with defaults when no env vars set."""
    from shared.settings import CouncilSettings

    with patch.dict(os.environ, {}, clear=True):
        s = CouncilSettings()
    assert s.litellm.base_url == "http://localhost:4000"
    assert s.qdrant.url == "http://localhost:6333"
    assert s.engine.debounce_ms >= 50


def test_settings_override_from_env():
    """Env vars override defaults."""
    from shared.settings import CouncilSettings

    env = {"LITELLM_API_BASE": "http://example:9000", "QDRANT_URL": "http://qdrant:6334"}
    with patch.dict(os.environ, env, clear=True):
        s = CouncilSettings()
    assert s.litellm.base_url == "http://example:9000"
    assert s.qdrant.url == "http://qdrant:6334"


def test_settings_rejects_invalid_port():
    """Negative debounce_ms rejected."""
    from shared.settings import CouncilSettings

    with patch.dict(os.environ, {"ENGINE_DEBOUNCE_MS": "-5"}, clear=True):
        with pytest.raises(Exception):
            CouncilSettings()


def test_secret_str_hides_api_key():
    """API keys use SecretStr to prevent accidental logging."""
    from shared.settings import CouncilSettings

    env = {"LITELLM_API_KEY": "sk-secret-key-123"}
    with patch.dict(os.environ, env, clear=True):
        s = CouncilSettings()
    assert "sk-secret-key-123" not in str(s.litellm)
    assert s.litellm.api_key.get_secret_value() == "sk-secret-key-123"
