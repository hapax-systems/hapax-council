"""Tests for temporal bands system prompt injection."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from shared.operator import _read_temporal_block, get_system_prompt_fragment


class TestTemporalPromptInjection:
    def test_missing_file_returns_empty(self):
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert _read_temporal_block() == ""

    def test_stale_bands_returns_empty(self):
        """Temporal bands older than 30s are not injected."""
        data = json.dumps(
            {
                "xml": "<temporal_context>\n  <impression>\n    <flow_state>active</flow_state>\n  </impression>\n</temporal_context>",
                "max_surprise": 0.0,
                "timestamp": time.time() - 60,  # 60s ago > 30s threshold
            }
        )
        with patch("pathlib.Path.read_text", return_value=data):
            assert _read_temporal_block() == ""

    def test_empty_xml_returns_empty(self):
        """Empty temporal context (no data) is not injected."""
        data = json.dumps(
            {
                "xml": "<temporal_context>\n</temporal_context>",
                "max_surprise": 0.0,
                "timestamp": time.time(),
            }
        )
        with patch("pathlib.Path.read_text", return_value=data):
            assert _read_temporal_block() == ""

    def test_valid_bands_injected(self):
        """Fresh temporal bands produce a prompt block with XML."""
        xml = (
            "<temporal_context>\n"
            "  <retention>\n"
            '    <memory age_s="5" flow="active" activity="coding">coding, 78bpm</memory>\n'
            "  </retention>\n"
            "  <impression>\n"
            "    <flow_state>active</flow_state>\n"
            "    <flow_score>0.75</flow_score>\n"
            "  </impression>\n"
            "  <protention>\n"
            '    <prediction state="entering_deep_work" confidence="0.72">'
            "flow score rising steadily</prediction>\n"
            "  </protention>\n"
            "</temporal_context>"
        )
        data = json.dumps(
            {
                "xml": xml,
                "max_surprise": 0.0,
                "timestamp": time.time(),
            }
        )
        with patch("pathlib.Path.read_text", return_value=data):
            result = _read_temporal_block()
        assert "Temporal context" in result
        assert "retention = fading past" in result
        assert "<temporal_context>" in result
        assert "entering_deep_work" in result
        assert "SURPRISE" not in result  # no surprise when max_surprise < 0.3

    def test_surprise_flagged(self):
        """High surprise is flagged in the preamble."""
        xml = (
            "<temporal_context>\n"
            "  <impression>\n"
            '    <flow_state surprise="0.65" expected="active">idle</flow_state>\n'
            "  </impression>\n"
            "</temporal_context>"
        )
        data = json.dumps(
            {
                "xml": xml,
                "max_surprise": 0.65,
                "timestamp": time.time(),
            }
        )
        with patch("pathlib.Path.read_text", return_value=data):
            result = _read_temporal_block()
        assert "SURPRISE detected: 0.65" in result

    def test_corrupt_json_returns_empty(self):
        with patch("pathlib.Path.read_text", return_value="not json{"):
            assert _read_temporal_block() == ""

    def test_fragment_includes_temporal(self):
        """get_system_prompt_fragment includes temporal block when available."""
        xml = (
            "<temporal_context>\n"
            "  <impression>\n"
            "    <flow_state>active</flow_state>\n"
            "  </impression>\n"
            "</temporal_context>"
        )
        mock_operator = {
            "operator": {"name": "test", "role": "test", "context": ""},
        }
        with (
            patch("shared.operator._load_operator", return_value=mock_operator),
            patch("shared.operator._read_stimmung_block", return_value=""),
            patch(
                "shared.operator._read_temporal_block",
                return_value="Temporal context:\n" + xml,
            ),
        ):
            fragment = get_system_prompt_fragment("test-agent")
        assert "<temporal_context>" in fragment
        assert "Temporal context" in fragment
