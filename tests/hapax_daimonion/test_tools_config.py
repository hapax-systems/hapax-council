"""Tests for voice tool config fields."""

from agents.hapax_daimonion.config import DaimonionConfig


def test_tools_enabled_default():
    cfg = DaimonionConfig()
    assert cfg.tools_enabled is True


def test_sms_gateway_defaults():
    cfg = DaimonionConfig()
    assert cfg.sms_gateway_host == ""
    assert cfg.sms_contacts == {}
    assert cfg.sms_gateway_pass_key == "sms-gateway/password"


def test_sms_contacts_from_dict():
    cfg = DaimonionConfig(sms_contacts={"Wife": "+15551234567"})
    assert cfg.sms_contacts["Wife"] == "+15551234567"


def test_vision_spontaneous_defaults():
    cfg = DaimonionConfig()
    assert cfg.vision_spontaneous is True
    assert cfg.vision_refresh_interval == 60
