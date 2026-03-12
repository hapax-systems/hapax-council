"""Tests for shared.capabilities — Protocols, Registry, and Adapters."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.capabilities.protocols import (
    AudioCapability,
    CompletionCapability,
    DesktopCapability,
    DesktopResult,
    EmbeddingCapability,
    EmbeddingResult,
    HealthStatus,
    NotificationCapability,
    StorageCapability,
    TTSCapability,
    TranscriptionCapability,
    VectorSearchCapability,
)
from shared.capabilities.registry import CapabilityRegistry


# ------------------------------------------------------------------
# Stub adapters for testing
# ------------------------------------------------------------------


class StubEmbeddingAdapter:
    @property
    def name(self) -> str:
        return "stub-embedding"

    def available(self) -> bool:
        return True

    def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, message="ok")

    def embed(self, text: str) -> EmbeddingResult:
        return EmbeddingResult(vector=[0.1, 0.2, 0.3], model="stub", dimensions=3)


class StubDesktopAdapter:
    @property
    def name(self) -> str:
        return "stub-desktop"

    def available(self) -> bool:
        return True

    def health(self) -> HealthStatus:
        return HealthStatus(healthy=True, message="ok")

    def snapshot(self) -> DesktopResult:
        return DesktopResult(active_window_title="test", workspace_id=1, window_count=5)


class UnhealthyAdapter:
    @property
    def name(self) -> str:
        return "unhealthy"

    def available(self) -> bool:
        return False

    def health(self) -> HealthStatus:
        return HealthStatus(healthy=False, message="service down")


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------


class TestProtocolConformance:
    def test_embedding_adapter_satisfies_protocol(self):
        assert isinstance(StubEmbeddingAdapter(), EmbeddingCapability)

    def test_desktop_adapter_satisfies_protocol(self):
        assert isinstance(StubDesktopAdapter(), DesktopCapability)

    def test_health_status_frozen(self):
        hs = HealthStatus(healthy=True, message="ok", latency_ms=1.5)
        with pytest.raises(AttributeError):
            hs.healthy = False  # type: ignore[misc]


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------


class TestCapabilityRegistry:
    def test_register_and_get(self):
        registry = CapabilityRegistry()
        adapter = StubEmbeddingAdapter()
        registry.register("embedding", adapter)
        assert registry.get("embedding") is adapter
        assert "embedding" in registry
        assert len(registry) == 1

    def test_get_nonexistent_returns_none(self):
        registry = CapabilityRegistry()
        assert registry.get("nonexistent") is None

    def test_duplicate_registration_raises(self):
        registry = CapabilityRegistry()
        registry.register("embedding", StubEmbeddingAdapter())
        with pytest.raises(ValueError, match="already registered"):
            registry.register("embedding", StubEmbeddingAdapter())

    def test_register_invalid_adapter_raises(self):
        registry = CapabilityRegistry()
        with pytest.raises(TypeError, match="available"):
            registry.register("bad", object())

    def test_health_all(self):
        registry = CapabilityRegistry()
        registry.register("embedding", StubEmbeddingAdapter())
        registry.register("desktop", StubDesktopAdapter())
        health = registry.health()
        assert health["embedding"].healthy is True
        assert health["desktop"].healthy is True

    def test_health_unhealthy(self):
        registry = CapabilityRegistry()
        registry.register("broken", UnhealthyAdapter())
        health = registry.health()
        assert health["broken"].healthy is False
        assert "down" in health["broken"].message

    def test_health_exception_caught(self):
        adapter = MagicMock()
        adapter.name = "exploding"
        adapter.available.return_value = True
        adapter.health.side_effect = RuntimeError("boom")
        registry = CapabilityRegistry()
        registry.register("exploding", adapter)
        health = registry.health()
        assert health["exploding"].healthy is False
        assert "boom" in health["exploding"].message

    def test_registered_property(self):
        registry = CapabilityRegistry()
        registry.register("embedding", StubEmbeddingAdapter())
        registry.register("desktop", StubDesktopAdapter())
        registered = registry.registered
        assert registered == {"embedding": "stub-embedding", "desktop": "stub-desktop"}


# ------------------------------------------------------------------
# Adapter functionality
# ------------------------------------------------------------------


class TestStubAdapters:
    def test_embedding_embed(self):
        adapter = StubEmbeddingAdapter()
        result = adapter.embed("hello world")
        assert isinstance(result, EmbeddingResult)
        assert len(result.vector) == 3
        assert result.dimensions == 3

    def test_desktop_snapshot(self):
        adapter = StubDesktopAdapter()
        result = adapter.snapshot()
        assert isinstance(result, DesktopResult)
        assert result.active_window_title == "test"
        assert result.window_count == 5


# ------------------------------------------------------------------
# OllamaEmbeddingAdapter (mocked)
# ------------------------------------------------------------------


class TestOllamaEmbeddingAdapter:
    def test_available_when_reachable(self):
        from shared.capabilities.adapters.embedding import OllamaEmbeddingAdapter

        adapter = OllamaEmbeddingAdapter()
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            assert adapter.available() is True

    def test_unavailable_when_unreachable(self):
        from shared.capabilities.adapters.embedding import OllamaEmbeddingAdapter

        adapter = OllamaEmbeddingAdapter()
        with patch("httpx.get", side_effect=ConnectionError("refused")):
            assert adapter.available() is False

    def test_health_model_not_found(self):
        from shared.capabilities.adapters.embedding import OllamaEmbeddingAdapter

        adapter = OllamaEmbeddingAdapter(model="nonexistent")
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"models": [{"name": "llama3:latest"}]},
            )
            health = adapter.health()
            assert health.healthy is False
            assert "not found" in health.message

    def test_embed_returns_result(self):
        from shared.capabilities.adapters.embedding import OllamaEmbeddingAdapter

        adapter = OllamaEmbeddingAdapter()
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"embeddings": [[0.1, 0.2, 0.3]]},
                raise_for_status=lambda: None,
            )
            result = adapter.embed("test")
            assert isinstance(result, EmbeddingResult)
            assert result.dimensions == 3


# ------------------------------------------------------------------
# HyprlandDesktopAdapter (mocked)
# ------------------------------------------------------------------


class TestHyprlandDesktopAdapter:
    def test_available_when_hyprctl_works(self):
        from shared.capabilities.adapters.desktop import HyprlandDesktopAdapter

        adapter = HyprlandDesktopAdapter()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert adapter.available() is True

    def test_unavailable_when_no_hyprctl(self):
        from shared.capabilities.adapters.desktop import HyprlandDesktopAdapter

        adapter = HyprlandDesktopAdapter()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert adapter.available() is False

    def test_snapshot_returns_desktop_result(self):
        import json as json_mod

        from shared.capabilities.adapters.desktop import HyprlandDesktopAdapter

        adapter = HyprlandDesktopAdapter()
        win_data = json_mod.dumps({"title": "Firefox", "class": "firefox"})
        clients_data = json_mod.dumps([{}, {}, {}])
        ws_data = json_mod.dumps({"id": 2})

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=win_data),
                MagicMock(returncode=0, stdout=clients_data),
                MagicMock(returncode=0, stdout=ws_data),
            ]
            result = adapter.snapshot()
            assert result.active_window_title == "Firefox"
            assert result.active_window_class == "firefox"
            assert result.workspace_id == 2
            assert result.window_count == 3


# ------------------------------------------------------------------
# Nested gating on Candidate
# ------------------------------------------------------------------


class TestCandidateNestedGating:
    def test_candidate_veto_chain_default_none(self):
        from agents.hapax_voice.governance import Candidate

        c = Candidate(name="test", predicate=lambda _: True, action="go")
        assert c.veto_chain is None

    def test_candidate_with_veto_chain(self):
        from agents.hapax_voice.governance import Candidate, Veto, VetoChain

        chain: VetoChain[int] = VetoChain([Veto("blocker", predicate=lambda x: x > 0)])
        c = Candidate(name="test", predicate=lambda _: True, action="go", veto_chain=chain)
        assert c.veto_chain is not None
        assert c.veto_chain.evaluate(5).allowed is True
        assert c.veto_chain.evaluate(-1).allowed is False
