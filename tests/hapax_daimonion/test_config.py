"""Tests for DaimonionConfig observability fields."""

from agents.hapax_daimonion.config import DaimonionConfig


def test_observability_config_defaults():
    cfg = DaimonionConfig()
    assert cfg.observability_events_enabled is True
    assert cfg.observability_langfuse_enabled is True
    assert cfg.observability_events_retention_days == 180


def test_stt_default_is_streaming_nemotron():
    cfg = DaimonionConfig()
    assert cfg.local_stt_model == "nvidia/nemotron-speech-streaming-en-0.6b"
