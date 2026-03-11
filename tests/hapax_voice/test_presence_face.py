"""Tests for PresenceDetector face detection fusion."""

import time

from agents.hapax_voice.presence import PresenceDetector


def test_presence_record_face_event():
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    p.record_face_event(detected=True, count=1)
    assert p.face_detected is True


def test_presence_face_decay():
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    p._face_decay_s = 1.0  # Short decay for testing
    p.record_face_event(detected=True, count=1)
    assert p.face_detected is True
    # Simulate time passing beyond decay
    p._last_face_time = time.monotonic() - 2.0
    assert p.face_detected is False


def test_presence_face_not_detected_stays_false():
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    p.record_face_event(detected=False, count=0)
    assert p.face_detected is False


def test_presence_composite_both_present():
    """VAD likely_present + face = definitely_present."""
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    # Add enough VAD events for likely_present
    for _ in range(6):
        p.record_vad_event(confidence=0.9)
    p.record_face_event(detected=True, count=1)
    assert p.score == "definitely_present"


def test_presence_composite_vad_only():
    """VAD likely_present + no face = likely_present (unchanged)."""
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    for _ in range(6):
        p.record_vad_event(confidence=0.9)
    assert p.score == "likely_present"


def test_presence_composite_face_only():
    """No VAD + face = likely_present."""
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    p.record_face_event(detected=True, count=1)
    assert p.score == "likely_present"


def test_presence_composite_uncertain_plus_face():
    """VAD uncertain + face = likely_present."""
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    for _ in range(3):
        p.record_vad_event(confidence=0.9)
    p.record_face_event(detected=True, count=1)
    assert p.score == "likely_present"


def test_presence_composite_absent():
    """No VAD + no face = likely_absent."""
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    assert p.score == "likely_absent"


def test_presence_guest_count():
    """Multiple faces detected = guest count available."""
    p = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    p.record_face_event(detected=True, count=3)
    assert p.face_count == 3
