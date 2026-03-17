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

    def test_skip_when_confident(self, tmp_path):
        monitor = self._make_monitor()
        state_path = tmp_path / "perception-state.json"
        state_path.write_text(json.dumps({"llm_confidence": 0.85, "llm_activity": "coding"}))
        with patch(
            "pathlib.Path.home",
            return_value=tmp_path / "fake_home",
        ):
            # Create the expected path structure
            cache_dir = tmp_path / "fake_home" / ".cache" / "hapax-voice"
            cache_dir.mkdir(parents=True)
            (cache_dir / "perception-state.json").write_text(
                json.dumps({"llm_confidence": 0.85, "llm_activity": "coding"})
            )
            result = monitor._should_skip_cloud()
        assert result is True
        assert monitor._local_skip_count == 1

    def test_no_skip_when_low_confidence(self, tmp_path):
        monitor = self._make_monitor()
        cache_dir = tmp_path / "fake_home" / ".cache" / "hapax-voice"
        cache_dir.mkdir(parents=True)
        (cache_dir / "perception-state.json").write_text(
            json.dumps({"llm_confidence": 0.3, "llm_activity": "idle"})
        )
        with patch("pathlib.Path.home", return_value=tmp_path / "fake_home"):
            result = monitor._should_skip_cloud()
        assert result is False

    def test_force_cloud_every_n(self, tmp_path):
        monitor = self._make_monitor()
        cache_dir = tmp_path / "fake_home" / ".cache" / "hapax-voice"
        cache_dir.mkdir(parents=True)
        (cache_dir / "perception-state.json").write_text(
            json.dumps({"llm_confidence": 0.95, "llm_activity": "coding"})
        )

        with patch("pathlib.Path.home", return_value=tmp_path / "fake_home"):
            # First 4 should skip (confident)
            for _ in range(4):
                assert monitor._should_skip_cloud() is True

            # 5th should force cloud
            assert monitor._should_skip_cloud() is False

    def test_no_skip_when_file_missing(self):
        monitor = self._make_monitor()
        # No state file → should not skip
        result = monitor._should_skip_cloud()
        assert result is False

    def test_no_skip_when_no_activity(self, tmp_path):
        monitor = self._make_monitor()
        cache_dir = tmp_path / "fake_home" / ".cache" / "hapax-voice"
        cache_dir.mkdir(parents=True)
        (cache_dir / "perception-state.json").write_text(
            json.dumps({"llm_confidence": 0.9, "llm_activity": ""})
        )
        with patch("pathlib.Path.home", return_value=tmp_path / "fake_home"):
            result = monitor._should_skip_cloud()
        assert result is False
