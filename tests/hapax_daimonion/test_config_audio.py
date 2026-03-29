"""Tests for audio_input_source config field."""

from agents.hapax_daimonion.config import DaimonionConfig


def test_default_audio_input_source():
    """Default audio_input_source is echo_cancel_capture."""
    cfg = DaimonionConfig()
    assert cfg.audio_input_source == "echo_cancel_capture"


def test_custom_audio_input_source():
    """audio_input_source can be overridden."""
    cfg = DaimonionConfig(audio_input_source="my_custom_mic")
    assert cfg.audio_input_source == "my_custom_mic"
