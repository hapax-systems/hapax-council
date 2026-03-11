"""Tests for VoiceConfig observability fields."""

from agents.hapax_voice.config import VoiceConfig


def test_observability_config_defaults():
    cfg = VoiceConfig()
    assert cfg.observability_events_enabled is True
    assert cfg.observability_langfuse_enabled is True
    assert cfg.observability_events_retention_days == 14
