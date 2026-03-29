"""Tests for consent state tracking in the voice daemon perception loop.

Proves: state machine transitions are correct, debounce works,
persistence is blocked during unresolved consent, and the lifecycle
(detect → pending → grant/refuse → clear) is complete.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_daimonion.consent_state import ConsentPhase, ConsentStateTracker


class TestConsentStateTransitions(unittest.TestCase):
    """State machine: NO_GUEST → DETECTED → PENDING → GRANTED/REFUSED."""

    def test_starts_no_guest(self):
        tracker = ConsentStateTracker()
        assert tracker.phase == ConsentPhase.NO_GUEST
        assert tracker.persistence_allowed

    def test_face_count_triggers_detection(self):
        tracker = ConsentStateTracker()
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert tracker.phase == ConsentPhase.GUEST_DETECTED
        assert not tracker.persistence_allowed

    def test_non_operator_speaker_triggers_detection(self):
        tracker = ConsentStateTracker()
        tracker.tick(face_count=1, speaker_is_operator=False, now=0.0)
        assert tracker.phase == ConsentPhase.GUEST_DETECTED

    def test_operator_alone_stays_no_guest(self):
        tracker = ConsentStateTracker()
        tracker.tick(face_count=1, speaker_is_operator=True, now=0.0)
        assert tracker.phase == ConsentPhase.NO_GUEST

    def test_debounce_prevents_immediate_pending(self):
        tracker = ConsentStateTracker(debounce_s=5.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert tracker.phase == ConsentPhase.GUEST_DETECTED
        tracker.tick(face_count=2, speaker_is_operator=True, now=3.0)
        assert tracker.phase == ConsentPhase.GUEST_DETECTED  # still debouncing

    def test_sustained_presence_triggers_pending(self):
        tracker = ConsentStateTracker(debounce_s=5.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=5.0)
        assert tracker.phase == ConsentPhase.CONSENT_PENDING

    def test_transient_presence_clears(self):
        tracker = ConsentStateTracker(debounce_s=5.0, absence_clear_s=10.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert tracker.phase == ConsentPhase.GUEST_DETECTED
        # Guest leaves immediately
        tracker.tick(face_count=1, speaker_is_operator=True, now=1.0)
        tracker.tick(face_count=1, speaker_is_operator=True, now=12.0)
        assert tracker.phase == ConsentPhase.NO_GUEST

    def test_grant_consent(self):
        tracker = ConsentStateTracker(debounce_s=0.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert tracker.phase == ConsentPhase.CONSENT_PENDING
        tracker.grant_consent()
        assert tracker.phase == ConsentPhase.CONSENT_GRANTED
        assert tracker.persistence_allowed

    def test_refuse_consent(self):
        tracker = ConsentStateTracker(debounce_s=0.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        tracker.refuse_consent()
        assert tracker.phase == ConsentPhase.CONSENT_REFUSED
        assert not tracker.persistence_allowed

    def test_guest_leaves_after_grant_clears(self):
        tracker = ConsentStateTracker(debounce_s=0.0, absence_clear_s=10.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        tracker.grant_consent()
        # Guest leaves
        tracker.tick(face_count=1, speaker_is_operator=True, now=5.0)
        tracker.tick(face_count=1, speaker_is_operator=True, now=16.0)
        assert tracker.phase == ConsentPhase.NO_GUEST

    def test_guest_leaves_pending_clears(self):
        tracker = ConsentStateTracker(debounce_s=0.0, absence_clear_s=10.0)
        tracker.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert tracker.phase == ConsentPhase.CONSENT_PENDING
        # Guest leaves without resolving
        tracker.tick(face_count=1, speaker_is_operator=True, now=5.0)
        tracker.tick(face_count=1, speaker_is_operator=True, now=16.0)
        assert tracker.phase == ConsentPhase.NO_GUEST


class TestConsentPersistenceGating(unittest.TestCase):
    """The persistence_allowed property gates data writes."""

    def test_no_guest_allows(self):
        assert ConsentStateTracker().persistence_allowed

    def test_guest_detected_denies(self):
        t = ConsentStateTracker()
        t.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert not t.persistence_allowed

    def test_consent_pending_denies(self):
        t = ConsentStateTracker(debounce_s=0.0)
        t.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert not t.persistence_allowed

    def test_consent_granted_allows(self):
        t = ConsentStateTracker(debounce_s=0.0)
        t.tick(face_count=2, speaker_is_operator=True, now=0.0)
        t.grant_consent()
        assert t.persistence_allowed

    def test_consent_refused_denies(self):
        t = ConsentStateTracker(debounce_s=0.0)
        t.tick(face_count=2, speaker_is_operator=True, now=0.0)
        t.refuse_consent()
        assert not t.persistence_allowed


class TestConsentNotification(unittest.TestCase):
    """The needs_notification flag fires exactly once."""

    def test_no_notification_before_pending(self):
        t = ConsentStateTracker(debounce_s=5.0)
        t.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert not t.needs_notification

    def test_notification_on_pending(self):
        t = ConsentStateTracker(debounce_s=0.0)
        t.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert t.needs_notification

    def test_notification_fires_once(self):
        t = ConsentStateTracker(debounce_s=0.0)
        t.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert t.needs_notification
        assert not t.needs_notification  # second call returns False

    def test_notification_resets_on_clear(self):
        t = ConsentStateTracker(debounce_s=0.0, absence_clear_s=5.0)
        t.tick(face_count=2, speaker_is_operator=True, now=0.0)
        assert t.needs_notification
        # Guest leaves
        t.tick(face_count=1, speaker_is_operator=True, now=1.0)
        t.tick(face_count=1, speaker_is_operator=True, now=7.0)
        assert t.phase == ConsentPhase.NO_GUEST
        # New guest triggers fresh notification
        t.tick(face_count=2, speaker_is_operator=True, now=10.0)
        assert t.needs_notification


class TestConsentStateProperties(unittest.TestCase):
    """Hypothesis properties of the consent state machine."""

    @given(
        ticks=st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=5),  # face_count
                st.booleans(),  # speaker_is_operator
                st.floats(min_value=0.0, max_value=100.0),  # time
            ),
            min_size=1,
            max_size=20,
        )
    )
    @settings(max_examples=100)
    def test_phase_always_valid(self, ticks):
        """∀ tick sequences: phase is always a valid ConsentPhase."""
        tracker = ConsentStateTracker(debounce_s=2.0, absence_clear_s=5.0)
        # Ensure monotonic time
        sorted_ticks = sorted(ticks, key=lambda t: t[2])
        for face_count, speaker_op, t in sorted_ticks:
            phase = tracker.tick(face_count=face_count, speaker_is_operator=speaker_op, now=t)
            assert isinstance(phase, ConsentPhase)

    @given(
        ticks=st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=5),
                st.booleans(),
                st.floats(min_value=0.0, max_value=100.0),
            ),
            min_size=1,
            max_size=20,
        )
    )
    @settings(max_examples=100)
    def test_persistence_iff_safe(self, ticks):
        """∀ tick sequences: persistence_allowed ↔ (no_guest ∨ consent_granted)."""
        tracker = ConsentStateTracker(debounce_s=2.0, absence_clear_s=5.0)
        sorted_ticks = sorted(ticks, key=lambda t: t[2])
        for face_count, speaker_op, t in sorted_ticks:
            tracker.tick(face_count=face_count, speaker_is_operator=speaker_op, now=t)
            safe_phases = {ConsentPhase.NO_GUEST, ConsentPhase.CONSENT_GRANTED}
            assert tracker.persistence_allowed == (tracker.phase in safe_phases)

    @given(
        n_ticks_before=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=50)
    def test_grant_always_allows_persistence(self, n_ticks_before):
        """∀ n: after grant, persistence is allowed regardless of history."""
        tracker = ConsentStateTracker(debounce_s=0.0)
        # Simulate some ticks
        for i in range(n_ticks_before):
            tracker.tick(face_count=2, speaker_is_operator=True, now=float(i))
        # Ensure we're in a grantable state
        if tracker.phase in (ConsentPhase.CONSENT_PENDING, ConsentPhase.GUEST_DETECTED):
            tracker.grant_consent()
            assert tracker.persistence_allowed
