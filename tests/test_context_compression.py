"""Tests for shared/context_compression.py — TOON + LLMLingua-2 primitives."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from shared.context_compression import compress_history, to_toon


class SimpleModel(BaseModel):
    app: str
    mode: str
    faces: int = 0


class TestToToon:
    def test_dict_encoding(self):
        result = to_toon({"app": "chrome", "mode": "coding"})
        assert "app: chrome" in result
        assert "mode: coding" in result

    def test_pydantic_model_encoding(self):
        model = SimpleModel(app="firefox", mode="browsing", faces=2)
        result = to_toon(model)
        assert "app: firefox" in result
        assert "faces: 2" in result

    def test_nested_dict(self):
        data = {"status": "ok", "details": {"cpu": 45, "mem": 72}}
        result = to_toon(data)
        assert "status: ok" in result

    def test_array_tabular(self):
        data = {
            "gear": [
                {"id": "sp404", "status": "on"},
                {"id": "mpc", "status": "off"},
            ]
        }
        result = to_toon(data)
        assert "sp404" in result
        assert "mpc" in result

    def test_list_input(self):
        data = [{"a": 1}, {"a": 2}]
        result = to_toon(data)
        assert "1" in result
        assert "2" in result

    def test_empty_dict(self):
        result = to_toon({})
        assert isinstance(result, str)


class TestCompressHistory:
    def test_short_history_unchanged(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = compress_history(messages, keep_recent=5)
        assert result == messages

    def test_no_system_message(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = compress_history(messages, keep_recent=5)
        assert result == messages

    @patch("shared.context_compression._get_compressor")
    def test_compression_with_mock(self, mock_get):
        compressor = MagicMock()
        compressor.compress_prompt_llmlingua2.return_value = {
            "compressed_prompt": "user said hello, assistant said hi"
        }
        mock_get.return_value = compressor

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "Good!"},
            {"role": "user", "content": "Tell me more"},
            {"role": "assistant", "content": "Sure thing"},
            {"role": "user", "content": "Thanks"},
            {"role": "assistant", "content": "Welcome!"},
        ]

        result = compress_history(messages, keep_recent=4)

        # System message preserved
        assert result[0]["role"] == "system"
        # Compressed summary message
        assert "[Earlier conversation, compressed]" in result[1]["content"]
        # Recent messages preserved verbatim
        assert result[-1]["content"] == "Welcome!"
        assert result[-2]["content"] == "Thanks"
        # Total should be system + compressed + 4 recent = 6
        assert len(result) == 6

    @patch("shared.context_compression._get_compressor")
    def test_compressor_unavailable_returns_original(self, mock_get):
        mock_get.return_value = None

        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "3"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "5"},
            {"role": "assistant", "content": "6"},
        ]

        result = compress_history(messages, keep_recent=2)
        assert result == messages

    @patch("shared.context_compression._get_compressor")
    def test_compression_failure_returns_original(self, mock_get):
        compressor = MagicMock()
        compressor.compress_prompt_llmlingua2.side_effect = RuntimeError("boom")
        mock_get.return_value = compressor

        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "3"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "5"},
            {"role": "assistant", "content": "6"},
        ]

        result = compress_history(messages, keep_recent=2)
        assert result == messages
