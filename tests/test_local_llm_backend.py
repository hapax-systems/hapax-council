"""Tests for local LLM perception backend (WS5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.hapax_voice.backends.local_llm import LocalLLMBackend
from agents.hapax_voice.primitives import Behavior


class TestParseResponse:
    def test_valid_json(self):
        result = LocalLLMBackend._parse_response(
            '{"activity": "coding", "flow": "deep", "confidence": 0.9}'
        )
        assert result == {"activity": "coding", "flow": "deep", "confidence": 0.9}

    def test_markdown_fenced(self):
        result = LocalLLMBackend._parse_response(
            '```json\n{"activity": "writing", "flow": "light", "confidence": 0.7}\n```'
        )
        assert result == {"activity": "writing", "flow": "light", "confidence": 0.7}

    def test_json_with_surrounding_text(self):
        result = LocalLLMBackend._parse_response(
            'Here is the result: {"activity": "browsing", "flow": "none", "confidence": 0.5}'
        )
        assert result == {"activity": "browsing", "flow": "none", "confidence": 0.5}

    def test_invalid_activity_defaults_to_idle(self):
        result = LocalLLMBackend._parse_response(
            '{"activity": "flying_helicopter", "flow": "deep", "confidence": 0.8}'
        )
        assert result is not None
        assert result["activity"] == "idle"
        assert result["confidence"] == 0.4  # halved

    def test_invalid_flow_defaults_to_none(self):
        result = LocalLLMBackend._parse_response(
            '{"activity": "coding", "flow": "mega", "confidence": 0.8}'
        )
        assert result is not None
        assert result["flow"] == "none"

    def test_confidence_clamped(self):
        result = LocalLLMBackend._parse_response(
            '{"activity": "coding", "flow": "deep", "confidence": 1.5}'
        )
        assert result is not None
        assert result["confidence"] == 1.0

    def test_garbage_returns_none(self):
        assert LocalLLMBackend._parse_response("not json at all") is None

    def test_empty_returns_none(self):
        assert LocalLLMBackend._parse_response("") is None

    def test_missing_fields_default(self):
        result = LocalLLMBackend._parse_response('{"activity": "coding"}')
        assert result is not None
        assert result["flow"] == "none"
        assert result["confidence"] == 0.5


class TestBackendProperties:
    def test_name(self):
        backend = LocalLLMBackend()
        assert backend.name == "local_llm"

    def test_provides(self):
        backend = LocalLLMBackend()
        assert backend.provides == frozenset({"llm_activity", "llm_flow_hint", "llm_confidence"})

    def test_tier_is_slow(self):
        from agents.hapax_voice.perception import PerceptionTier

        backend = LocalLLMBackend()
        assert backend.tier == PerceptionTier.SLOW


class TestAvailability:
    def test_unavailable_when_ollama_down(self):
        backend = LocalLLMBackend()
        with patch("ollama.Client") as mock_client:
            mock_client.side_effect = ConnectionError("no ollama")
            assert not backend.available()

    def test_unavailable_when_model_missing(self):
        backend = LocalLLMBackend(model="nonexistent:1b")
        mock_client = MagicMock()
        mock_client.list.return_value = {"models": [{"name": "qwen2.5:3b"}]}
        with patch("ollama.Client", return_value=mock_client):
            assert not backend.available()

    def test_available_when_model_present(self):
        backend = LocalLLMBackend(model="qwen2.5:3b")
        mock_client = MagicMock()
        mock_client.list.return_value = {"models": [{"name": "qwen2.5:3b"}]}
        with patch("ollama.Client", return_value=mock_client):
            assert backend.available()


class TestClassification:
    def test_classify_with_snapshot(self):
        backend = LocalLLMBackend()
        backend._available = True

        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": '{"activity": "coding", "flow": "deep", "confidence": 0.85}'}
        }

        with patch("ollama.Client", return_value=mock_client):
            result = backend._classify({"activity": "coding", "flow_score": 0.7})
        assert result is not None
        assert result["activity"] == "coding"
        assert result["flow"] == "deep"

    def test_classify_unavailable_returns_none(self):
        backend = LocalLLMBackend()
        backend._available = False
        assert backend._classify({"activity": "coding"}) is None

    def test_classify_error_increments_counter(self):
        backend = LocalLLMBackend()
        backend._available = True

        with patch("ollama.Client", side_effect=Exception("timeout")):
            result = backend._classify({"activity": "coding"})
        assert result is None
        assert backend._consecutive_errors == 1

    def test_backoff_after_3_errors(self):
        backend = LocalLLMBackend()
        backend._available = True
        backend._consecutive_errors = 3
        # Should skip without even calling Ollama
        result = backend._classify({"activity": "coding"})
        assert result is None


class TestContribute:
    def test_contribute_updates_behaviors(self):
        backend = LocalLLMBackend()
        backend._available = True
        backend._last_snapshot = {
            "production_activity": "coding",
            "flow_score": 0.7,
            "audio_energy_rms": 0.01,
        }

        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": '{"activity": "coding", "flow": "deep", "confidence": 0.9}'}
        }

        behaviors: dict[str, Behavior] = {}
        with patch("ollama.Client", return_value=mock_client):
            backend.contribute(behaviors)

        assert "llm_activity" in behaviors
        assert behaviors["llm_activity"].value == "coding"
        assert behaviors["llm_flow_hint"].value == "deep"
        assert behaviors["llm_confidence"].value == 0.9

    def test_contribute_no_snapshot_uses_behaviors(self):
        backend = LocalLLMBackend()
        backend._available = True
        backend._last_snapshot = {}

        behaviors: dict[str, Behavior] = {
            "production_activity": Behavior("writing"),
        }

        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": '{"activity": "writing", "flow": "light", "confidence": 0.7}'}
        }

        with patch("ollama.Client", return_value=mock_client):
            backend.contribute(behaviors)

        assert behaviors["llm_activity"].value == "writing"

    def test_set_perception_snapshot(self):
        backend = LocalLLMBackend()
        snap = {"production_activity": "coding", "flow_score": 0.8}
        backend.set_perception_snapshot(snap)
        assert backend._last_snapshot == snap
