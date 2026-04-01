"""Tests for hapax_daimonion configuration loading."""

from pathlib import Path

import yaml


def test_default_config_values():
    import os

    from agents.hapax_daimonion.config import DaimonionConfig

    cfg = DaimonionConfig()
    assert cfg.silence_timeout_s == 30
    assert cfg.wake_phrases == ["hapax", "hey hapax"]
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    assert cfg.hotkey_socket == f"{runtime_dir}/hapax-daimonion.sock"
    assert cfg.presence_window_minutes == 5
    assert cfg.presence_vad_threshold == 0.4
    assert cfg.context_gate_volume_threshold == 0.7
    assert cfg.gemini_model == "gemini-2.5-flash-preview-native-audio"
    assert cfg.local_stt_model == "distil-large-v3"
    assert cfg.voxtral_voice_id == "gb_jane_neutral"
    assert cfg.notification_priority_ttls == {
        "urgent": 1800,
        "normal": 14400,
        "low": 0,
    }


def test_config_from_yaml(tmp_path):
    from agents.hapax_daimonion.config import load_config

    config_file = tmp_path / "config.yaml"
    data = {"silence_timeout_s": 45, "presence_window_minutes": 10}
    config_file.write_text(yaml.dump(data))
    cfg = load_config(config_file)
    assert cfg.silence_timeout_s == 45
    assert cfg.presence_window_minutes == 10
    # defaults preserved
    assert cfg.wake_phrases == ["hapax", "hey hapax"]


def test_config_missing_file_returns_defaults():
    from agents.hapax_daimonion.config import load_config

    cfg = load_config(Path("/nonexistent/config.yaml"))
    assert cfg.silence_timeout_s == 30


def test_perception_config_defaults():
    """Perception fields have sensible defaults."""
    from agents.hapax_daimonion.config import DaimonionConfig

    cfg = DaimonionConfig()
    assert cfg.perception_fast_tick_s == 2.5
    assert cfg.perception_slow_tick_s == 12.0
    assert cfg.conversation_debounce_s == 3.0
    assert cfg.gaze_resume_clear_s == 5.0
    assert cfg.environment_clear_resume_s == 15.0
    assert cfg.operator_absent_withdraw_s == 60.0
