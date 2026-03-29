"""Tests for PresenceLevel gradient (Design D)."""

from __future__ import annotations

from unittest.mock import patch

from agents.hapax_daimonion.presence import PresenceDetector, PresenceLevel


class TestPresenceLevel:
    def test_engaged_with_face(self):
        det = PresenceDetector()
        det.record_face_event(True, count=1)
        assert det.presence_level == PresenceLevel.ENGAGED

    def test_engaged_with_high_vad(self):
        det = PresenceDetector()
        # Record 5 VAD events above threshold
        for _ in range(5):
            det.record_vad_event(0.9)
        assert det.presence_level == PresenceLevel.ENGAGED

    @patch("agents.hapax_daimonion.presence.is_watch_connected", return_value=True)
    @patch("agents.hapax_daimonion.presence.is_phone_connected", return_value=False)
    def test_peripheral_with_watch(self, _phone, _watch):
        det = PresenceDetector()
        assert det.presence_level == PresenceLevel.PERIPHERAL

    @patch("agents.hapax_daimonion.presence.is_watch_connected", return_value=False)
    @patch("agents.hapax_daimonion.presence.is_phone_connected", return_value=True)
    def test_ambient_with_phone_only(self, _phone, _watch):
        det = PresenceDetector()
        assert det.presence_level == PresenceLevel.AMBIENT

    @patch("agents.hapax_daimonion.presence.is_watch_connected", return_value=False)
    @patch("agents.hapax_daimonion.presence.is_phone_connected", return_value=False)
    def test_absent_no_signals(self, _phone, _watch):
        det = PresenceDetector()
        assert det.presence_level == PresenceLevel.ABSENT

    def test_presence_level_enum_values(self):
        assert PresenceLevel.ENGAGED == "ENGAGED"
        assert PresenceLevel.PERIPHERAL == "PERIPHERAL"
        assert PresenceLevel.AMBIENT == "AMBIENT"
        assert PresenceLevel.ABSENT == "ABSENT"
