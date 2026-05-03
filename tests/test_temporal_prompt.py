"""Tests for temporal WCS prompt injection."""

from __future__ import annotations

from unittest.mock import patch

from shared.operator import _read_temporal_block, get_system_prompt_fragment


class TestTemporalPromptInjection:
    def test_temporal_reader_returns_wcs_prompt_gate(self) -> None:
        result = _read_temporal_block()

        assert "Temporal/Perceptual WCS Prompt Gate" in result
        assert "authorizes_current_public_live_available_grounded=false" in result
        assert "<temporal_context>" not in result
        assert "retention = fading past" not in result

    def test_temporal_reader_fails_closed_when_wcs_projection_fails(self) -> None:
        with patch(
            "shared.temporal_shm.render_default_temporal_prompt_block",
            side_effect=ValueError("bad WCS rows"),
        ):
            assert _read_temporal_block() == ""

    def test_fragment_includes_temporal_wcs_gate(self) -> None:
        """get_system_prompt_fragment includes temporal block when available."""
        mock_operator = {
            "operator": {"name": "test", "role": "test", "context": ""},
        }
        temporal_gate = (
            "## Temporal/Perceptual WCS Prompt Gate\n"
            "block_state: blocked\n"
            "authorizes_current_public_live_available_grounded=false"
        )
        with (
            patch("shared.operator._load_operator", return_value=mock_operator),
            patch("shared.operator._read_stimmung_block", return_value=""),
            patch("shared.operator._read_temporal_block", return_value=temporal_gate),
        ):
            fragment = get_system_prompt_fragment("test-agent")

        assert "Temporal/Perceptual WCS Prompt Gate" in fragment
        assert "authorizes_current_public_live_available_grounded=false" in fragment
        assert "<temporal_context>" not in fragment

    def test_drift_detector_temporal_reader_uses_shared_wcs_gate(self) -> None:
        from agents.drift_detector import shm_readers

        with patch(
            "shared.temporal_shm.read_temporal_block",
            return_value="## Temporal/Perceptual WCS Prompt Gate\nsource=WCS",
        ):
            result = shm_readers.read_temporal_block()

        assert "source=WCS" in result
        assert "<temporal_context>" not in result
