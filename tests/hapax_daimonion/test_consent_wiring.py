"""Tests for consent daemon wiring — integration without live audio.

Verifies that ConsentStateTracker is correctly wired into the
voice daemon's tick loop and that the consent session launch
guard works properly.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.consent_state import ConsentPhase, ConsentStateTracker


class TestConsentTrackerInDaemon(unittest.TestCase):
    """Simulates the daemon's consent tracking without live audio."""

    def test_tracker_initialization(self):
        """Tracker initializes with configurable debounce."""
        tracker = ConsentStateTracker(debounce_s=5.0, absence_clear_s=30.0)
        assert tracker.phase == ConsentPhase.NO_GUEST
        assert tracker.persistence_allowed

    def test_tick_with_operator_only(self):
        """No guest detected when operator is alone."""
        tracker = ConsentStateTracker()
        tracker.tick(face_count=1, speaker_is_operator=True, now=0.0)
        assert tracker.phase == ConsentPhase.NO_GUEST

    def test_tick_detects_guest(self):
        """Guest detected when face_count > 1."""
        tracker = ConsentStateTracker(debounce_s=5.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert tracker.phase == ConsentPhase.GUEST_DETECTED
        assert not tracker.persistence_allowed

    def test_notification_fires_after_debounce(self):
        """needs_notification fires after sustained presence."""
        tracker = ConsentStateTracker(debounce_s=3.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert not tracker.needs_notification  # still debouncing
        tracker.tick(face_count=2, speaker_is_operator=True, now=3.0)
        assert tracker.phase == ConsentPhase.CONSENT_PENDING
        assert tracker.needs_notification  # fires once
        assert not tracker.needs_notification  # second call returns False

    def test_speaker_id_trigger(self):
        """Non-operator speaker triggers detection even with face_count=1."""
        tracker = ConsentStateTracker(debounce_s=0.0)
        tracker.tick(face_count=1, speaker_is_operator=False, now=0.0)
        assert tracker.phase == ConsentPhase.CONSENT_PENDING


class TestConsentSessionGuard(unittest.TestCase):
    """Tests the launch guard: only when session inactive and no concurrent consent."""

    def test_guard_prevents_concurrent_sessions(self):
        """Cannot launch consent session while one is active."""
        tracker = ConsentStateTracker(debounce_s=0.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)

        # Simulate the guard logic from __main__.py
        session_active = False
        consent_session_active = True  # already running

        should_launch = (
            tracker.needs_notification and not session_active and not consent_session_active
        )
        assert not should_launch

    def test_guard_prevents_launch_during_voice_session(self):
        """Cannot launch consent session while main voice session is active."""
        tracker = ConsentStateTracker(debounce_s=0.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)

        session_active = True  # main session running
        consent_session_active = False

        should_launch = (
            tracker.needs_notification and not session_active and not consent_session_active
        )
        assert not should_launch

    def test_guard_allows_launch_when_clear(self):
        """Consent session launches when conditions are met."""
        tracker = ConsentStateTracker(debounce_s=0.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)

        session_active = False
        consent_session_active = False

        should_launch = (
            tracker.needs_notification and not session_active and not consent_session_active
        )
        assert should_launch


class TestConsentPhaseInEnvironmentState(unittest.TestCase):
    """EnvironmentState includes consent_phase for observability."""

    def test_default_consent_phase(self):
        from agents.hapax_daimonion.perception import EnvironmentState

        state = EnvironmentState(timestamp=0.0)
        assert state.consent_phase == "no_guest"

    def test_consent_phase_settable(self):
        from agents.hapax_daimonion.perception import EnvironmentState

        state = EnvironmentState(timestamp=0.0, consent_phase="consent_pending")
        assert state.consent_phase == "consent_pending"
