"""Tests for DaimonionConfig observability fields."""

from agents.hapax_daimonion.config import DaimonionConfig


def test_observability_config_defaults():
    cfg = DaimonionConfig()
    assert cfg.observability_events_enabled is True
    assert cfg.observability_langfuse_enabled is True
    assert cfg.observability_events_retention_days == 14
