"""Tests for local LLM perception tier + cloud gate (WS5)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agents.hapax_voice.backends.local_llm import LocalLLMBackend


class TestLocalLLMBackend:
    def test_model_is_qwen3(self):
        backend = LocalLLMBackend()
        assert backend._model == "qwen3:4b"

    def test_parse_valid_response(self):
        result = LocalLLMBackend._parse_response(
            '{"activity": "coding", "flow": "deep", "confidence": 0.85}'
        )
        assert result == {"activity": "coding", "flow": "deep", "confidence": 0.85}

    def test_parse_markdown_fenced(self):
        result = LocalLLMBackend._parse_response(
            '```json\n{"activity": "browsing", "flow": "light", "confidence": 0.6}\n```'
        )
        assert result["activity"] == "browsing"

    def test_parse_invalid_activity_demoted(self):
        result = LocalLLMBackend._parse_response(
            '{"activity": "skateboarding", "flow": "deep", "confidence": 0.9}'
        )
        assert result["activity"] == "idle"
        assert result["confidence"] == 0.45  # 0.9 * 0.5

    def test_parse_garbage_returns_none(self):
        assert LocalLLMBackend._parse_response("not json at all") is None

    def test_desktop_context_included(self):
        backend = LocalLLMBackend()
        backend._last_snapshot = {
            "production_activity": "coding",
            "flow_score": 0.7,
            "audio_energy_rms": 0.01,
        }
        mock_hyprctl = MagicMock()
        mock_hyprctl.returncode = 0
        mock_hyprctl.stdout = json.dumps({"title": "nvim - foo.py", "class": "kitty"})

        with patch("subprocess.run", return_value=mock_hyprctl):
            ctx = backend._gather_context({})

        assert ctx["active_window"] == "nvim - foo.py"
        assert ctx["active_app"] == "kitty"
        assert ctx["activity"] == "coding"

    def test_desktop_context_missing_graceful(self):
        backend = LocalLLMBackend()
        backend._last_snapshot = {"production_activity": "idle", "flow_score": 0.0}

        with patch("subprocess.run", side_effect=FileNotFoundError):
            ctx = backend._gather_context({})

        assert "active_window" not in ctx or ctx.get("active_window") == ""
        assert ctx["activity"] == "idle"


class TestCloudGate:
    def _make_monitor(self):
        from agents.hapax_voice.workspace_monitor import WorkspaceMonitor

        return WorkspaceMonitor(enabled=False)

    def test_cloud_skip_disabled(self):
        """Cloud-skip feature is currently disabled — method always returns False."""
        monitor = self._make_monitor()
        assert monitor._should_skip_cloud() is False
