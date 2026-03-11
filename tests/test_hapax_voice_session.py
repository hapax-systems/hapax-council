"""Tests for voice session state machine."""
import time


def test_session_starts_idle():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=30)
    assert sm.state == "idle"
    assert not sm.is_active


def test_session_open_close():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="wake_word")
    assert sm.state == "active"
    assert sm.is_active
    assert sm.trigger == "wake_word"
    sm.close(reason="explicit")
    assert sm.state == "idle"
    assert not sm.is_active


def test_session_tracks_speaker():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="hotkey")
    sm.set_speaker("ryan", confidence=0.92)
    assert sm.speaker == "ryan"
    assert sm.speaker_confidence == 0.92


def test_session_guest_mode():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="wake_word")
    sm.set_speaker("unknown", confidence=0.3)
    assert sm.is_guest_mode


def test_session_silence_timeout():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=1)
    sm.open(trigger="hotkey")
    sm.mark_activity()
    time.sleep(1.1)
    assert sm.is_timed_out


def test_session_activity_resets_timeout():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=2)
    sm.open(trigger="hotkey")
    time.sleep(1)
    sm.mark_activity()
    time.sleep(1)
    assert not sm.is_timed_out


def test_open_while_active_is_noop():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=30)
    sm.open(trigger="wake_word")
    sm.open(trigger="hotkey")
    assert sm.state == "active"


def test_close_while_idle_is_noop():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=30)
    sm.close(reason="explicit")
    assert sm.state == "idle"


def test_session_id_generated_on_open():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=10)
    assert sm.session_id is None
    sm.open(trigger="hotkey")
    assert sm.session_id is not None
    assert isinstance(sm.session_id, str)
    assert len(sm.session_id) > 0


def test_session_id_unique_per_session():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=10)
    sm.open(trigger="test")
    id1 = sm.session_id
    sm.close(reason="test")
    assert sm.session_id is None
    sm.open(trigger="test2")
    id2 = sm.session_id
    assert id1 != id2


def test_session_id_stable_during_session():
    from agents.hapax_voice.session import SessionManager
    sm = SessionManager(silence_timeout_s=10)
    sm.open(trigger="test")
    id1 = sm.session_id
    sm.mark_activity()
    id2 = sm.session_id
    assert id1 == id2


def test_pause_stops_timeout_clock():
    """Paused sessions should not time out."""
    from agents.hapax_voice.session import VoiceLifecycle
    session = VoiceLifecycle(silence_timeout_s=1)
    session.open(trigger="wake_word")
    session.pause(reason="conversation")
    assert session.is_paused is True
    time.sleep(1.5)
    assert session.is_timed_out is False  # paused, clock frozen


def test_resume_restarts_timeout_clock():
    """Resuming resets the activity timestamp."""
    from agents.hapax_voice.session import VoiceLifecycle
    session = VoiceLifecycle(silence_timeout_s=1)
    session.open(trigger="wake_word")
    session.pause(reason="conversation")
    time.sleep(0.5)
    session.resume()
    assert session.is_paused is False
    assert session.is_timed_out is False  # just resumed


def test_pause_noop_when_idle():
    """Pausing an idle session does nothing."""
    from agents.hapax_voice.session import VoiceLifecycle
    session = VoiceLifecycle(silence_timeout_s=30)
    session.pause(reason="test")
    assert session.is_paused is False
    assert session.state == "idle"


def test_resume_noop_when_not_paused():
    """Resuming a non-paused session does nothing harmful."""
    from agents.hapax_voice.session import VoiceLifecycle
    session = VoiceLifecycle(silence_timeout_s=30)
    session.open(trigger="wake_word")
    session.resume()  # should not raise
    assert session.is_paused is False
