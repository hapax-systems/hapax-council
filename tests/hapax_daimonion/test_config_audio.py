"""Tests for audio_input_source config field.

The field was migrated from `str` to `list[str]` (priority list) for
the AEC source-routing wire-in (#134 Phase 2 — commit ecefe6a22).
The legacy single-string form is wrapped into a single-element list
by a field_validator so existing operator configs round-trip without
edits.
"""

from agents.hapax_daimonion.config import DaimonionConfig


def test_default_audio_input_source_includes_yeti():
    """Default priority list must contain the Yeti ALSA device as a
    fallback even when AEC virtual source is preferred at the head."""
    cfg = DaimonionConfig()
    assert isinstance(cfg.audio_input_source, list)
    # At least one entry in the priority list mentions "Yeti".
    assert any("Yeti" in entry for entry in cfg.audio_input_source), (
        f"no Yeti fallback in default priority list: {cfg.audio_input_source}"
    )


def test_default_priority_list_starts_with_stt_ear_subscription():
    """voice-p2-perception-registry: the default priority is the stt.ear
    subscription resolved over config/perception-registry.yaml — the
    ReSpeaker STT front-end first, AEC view and raw Yeti on the
    fallback ladder."""
    cfg = DaimonionConfig()
    assert cfg.audio_input_source[0].startswith(
        "alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800"
    )
    assert "echo_cancel_capture" in cfg.audio_input_source


def test_custom_string_source_wrapped_into_list():
    """Legacy single-string config is wrapped into a single-element
    list by the field_validator so older operator configs still work."""
    cfg = DaimonionConfig(audio_input_source="my_custom_mic")
    assert cfg.audio_input_source == ["my_custom_mic"]


def test_custom_list_source_preserved():
    """Explicit list pass-through (no wrapping)."""
    cfg = DaimonionConfig(audio_input_source=["primary", "fallback_a", "fallback_b"])
    assert cfg.audio_input_source == ["primary", "fallback_a", "fallback_b"]
