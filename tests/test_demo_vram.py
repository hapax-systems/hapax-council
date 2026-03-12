"""Tests for VRAM management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.demo_pipeline.vram import (
    ensure_vram_available,
    get_vram_free_mb,
    unload_ollama_models,
)


class TestGetVramFree:
    @patch("demo.pipeline.vram.subprocess.run")
    def test_parses_nvidia_smi(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="1024\n",
        )
        free = get_vram_free_mb()
        assert free == 1024

    @patch("demo.pipeline.vram.subprocess.run")
    def test_returns_zero_on_failure(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        free = get_vram_free_mb()
        assert free == 0


class TestUnloadOllamaModels:
    @patch("demo.pipeline.vram.httpx")
    def test_unloads_loaded_models(self, mock_httpx):
        mock_ps_response = MagicMock()
        mock_ps_response.json.return_value = {
            "models": [{"name": "qwen2.5-coder:32b", "size": 20000000000}]
        }
        mock_gen_response = MagicMock(status_code=200)

        mock_httpx.get.return_value = mock_ps_response
        mock_httpx.post.return_value = mock_gen_response

        unloaded = unload_ollama_models()
        assert unloaded == ["qwen2.5-coder:32b"]
        mock_httpx.post.assert_called_once()

    @patch("demo.pipeline.vram.httpx")
    def test_no_models_loaded(self, mock_httpx):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_httpx.get.return_value = mock_response

        unloaded = unload_ollama_models()
        assert unloaded == []


class TestEnsureVramAvailable:
    @patch("demo.pipeline.vram.get_vram_free_mb", return_value=12000)
    def test_enough_vram_already(self, mock_free):
        ensure_vram_available(required_mb=8000)

    @patch("demo.pipeline.vram.time.sleep")
    @patch("demo.pipeline.vram.get_vram_free_mb", side_effect=[2000, 2000, 16000])
    @patch("demo.pipeline.vram.unload_ollama_models", return_value=["qwen:7b"])
    def test_unloads_when_insufficient(self, mock_unload, mock_free, mock_sleep):
        ensure_vram_available(required_mb=8000)
        mock_unload.assert_called_once()
        mock_sleep.assert_called()
