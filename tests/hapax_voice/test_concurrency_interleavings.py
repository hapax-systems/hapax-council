"""Concurrency interleaving tests for wake word ↔ perception loop races.

These tests simulate the exact interleaving the daemon performs under its
asyncio cooperative scheduling model. The races are logical (cross-await-boundary
state inconsistency), not physical (cross-thread data races).

Root cause: _on_wake_word() fires synchronously, sets governor.wake_word_active,
and schedules pipeline start via create_task. The perception loop can tick in the
gap between the task being scheduled and it actually running.

The fix has two parts:
1. Governor grace period: _wake_word_grace_remaining counter protects the
   session for N ticks after wake word, preventing meeting/conversation
   modes from overriding the wake word intent.
2. Async wake word processor: _on_wake_word() sets an asyncio.Event,
   _wake_word_processor() awaits it and atomically starts the pipeline.
"""

from __future__ import annotations

import time

from agents.hapax_voice.frame_gate import FrameGate
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState


def _make_state(
    *,
    activity_mode: str = "idle",
    face_count: int = 1,
    guest_count: int = 0,
    operator_present: bool = True,
    speech_detected: bool = False,
    vad_confidence: float = 0.0,
) -> EnvironmentState:
    """Build an EnvironmentState with test defaults."""
    return EnvironmentState(
        timestamp=time.monotonic(),
        activity_mode=activity_mode,
        face_count=face_count,
        guest_count=guest_count,
        operator_present=operator_present,
        speech_detected=speech_detected,
        vad_confidence=vad_confidence,
    )


class TestGraceProtectsAgainstMeetingMode:
    """R1: wake_word → perception_tick(meeting) should NOT pause during grace."""

    def test_grace_period_overrides_meeting_mode(self):
        """After wake word, meeting-mode perception tick cannot pause the pipeline."""
        gov = PipelineGovernor()

        # Wake word fires
        gov.wake_word_active = True
        result = gov.evaluate(_make_state())
        assert result == "process"

        # Perception tick with meeting mode — grace period protects
        result = gov.evaluate(_make_state(activity_mode="meeting"))
        assert result == "process"
        assert gov.last_selected.selected_by == "wake_word_grace"

    def test_grace_period_lasts_three_ticks(self):
        """Grace period protects for exactly 3 ticks after wake word."""
        gov = PipelineGovernor()
        gov.wake_word_active = True

        # Tick 0: wake word consumed
        assert gov.evaluate(_make_state()) == "process"

        # Ticks 1-3: grace period
        for i in range(3):
            result = gov.evaluate(_make_state(activity_mode="meeting"))
            assert result == "process", f"Grace tick {i + 1} should be 'process'"

        # Tick 4: grace expired, meeting mode takes effect
        result = gov.evaluate(_make_state(activity_mode="meeting"))
        assert result == "pause"

    def test_grace_period_decrements_each_tick(self):
        """Each evaluate() call decrements grace by 1."""
        gov = PipelineGovernor()
        gov.wake_word_active = True
        gov.evaluate(_make_state())  # consumes wake_word_active, sets grace=3

        assert gov._wake_word_grace_remaining == 3

        gov.evaluate(_make_state())
        assert gov._wake_word_grace_remaining == 2

        gov.evaluate(_make_state())
        assert gov._wake_word_grace_remaining == 1

        gov.evaluate(_make_state())
        assert gov._wake_word_grace_remaining == 0


class TestGraceProtectsAgainstConversationDebounce:
    """R2: wake_word → perception_tick(conversation) should NOT re-accumulate debounce."""

    def test_conversation_during_grace_does_not_pause(self):
        """Conversation detected during grace period cannot trigger debounce pause."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)  # instant debounce

        gov.wake_word_active = True
        gov.evaluate(_make_state())  # consume wake word

        # Conversation tick during grace — should still process
        result = gov.evaluate(
            _make_state(face_count=2, guest_count=1, speech_detected=True, vad_confidence=0.9)
        )
        assert result == "process"
        assert gov.last_selected.selected_by == "wake_word_grace"

    def test_conversation_debounce_resumes_after_grace(self):
        """After grace expires, conversation debounce functions normally."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)  # instant debounce

        gov.wake_word_active = True
        gov.evaluate(_make_state())  # consume wake word

        # Exhaust grace period
        for _ in range(3):
            gov.evaluate(_make_state())

        # Now conversation should trigger debounce → pause
        conv_state = _make_state(
            face_count=2, guest_count=1, speech_detected=True, vad_confidence=0.9
        )
        result = gov.evaluate(conv_state)
        assert result == "pause"


class TestGraceProtectsSession:
    """R3: wake_word → perception_tick(absent) should NOT withdraw session."""

    def test_absence_during_grace_does_not_withdraw(self):
        """Operator-absent perception during grace cannot withdraw session."""
        gov = PipelineGovernor(operator_absent_withdraw_s=0.0)  # instant withdraw

        gov.wake_word_active = True
        gov.evaluate(_make_state())  # consume wake word

        # Absent tick during grace
        result = gov.evaluate(_make_state(operator_present=False, face_count=0))
        assert result == "process"
        assert gov.last_selected.selected_by == "wake_word_grace"


class TestGraceProtectsFrameGate:
    """R4: wake_word sets gate 'process' → perception cannot overwrite to 'pause' during grace."""

    def test_frame_gate_stays_process_during_grace(self):
        """Simulates the daemon loop: wake word sets gate, perception ticks with meeting mode."""
        gov = PipelineGovernor()
        gate = FrameGate()

        # Wake word fires — sets gate to process
        gov.wake_word_active = True
        gate.set_directive("process")

        # Governor evaluates on wake word tick
        directive = gov.evaluate(_make_state())
        assert directive == "process"

        # Perception tick with meeting mode — grace protects
        directive = gov.evaluate(_make_state(activity_mode="meeting"))
        gate.set_directive(directive)

        assert gate.directive == "process"
        assert directive == "process"


class TestGraceMultiplePerceptionTicks:
    """R5: wake_word → two perception ticks — both protected by grace."""

    def test_two_meeting_ticks_after_wake_word(self):
        """Two rapid perception ticks with meeting mode are both protected."""
        gov = PipelineGovernor()

        gov.wake_word_active = True
        gov.evaluate(_make_state())  # consume wake word

        # Two meeting-mode ticks — both protected
        r1 = gov.evaluate(_make_state(activity_mode="meeting"))
        r2 = gov.evaluate(_make_state(activity_mode="meeting"))

        assert r1 == "process"
        assert r2 == "process"

    def test_mixed_hostile_ticks(self):
        """Mix of meeting + conversation ticks during grace — all protected."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)

        gov.wake_word_active = True
        gov.evaluate(_make_state())

        # Meeting tick
        assert gov.evaluate(_make_state(activity_mode="meeting")) == "process"

        # Conversation tick
        assert (
            gov.evaluate(
                _make_state(face_count=2, guest_count=1, speech_detected=True, vad_confidence=0.9)
            )
            == "process"
        )

        # Absent tick
        assert gov.evaluate(_make_state(operator_present=False, face_count=0)) == "process"


class TestGraceEdgeCases:
    """Edge cases for grace period behavior."""

    def test_second_wake_word_resets_grace(self):
        """A second wake word during grace resets the counter."""
        gov = PipelineGovernor()

        gov.wake_word_active = True
        gov.evaluate(_make_state())  # consume, grace=3

        gov.evaluate(_make_state())  # grace=2

        # Second wake word
        gov.wake_word_active = True
        gov.evaluate(_make_state())  # consume again, grace=3

        assert gov._wake_word_grace_remaining == 3

    def test_grace_plus_meeting_then_clear(self):
        """Grace protects during meeting, normal eval resumes after grace + meeting clears."""
        gov = PipelineGovernor()

        gov.wake_word_active = True
        gov.evaluate(_make_state())

        # Exhaust grace with meeting mode
        for _ in range(3):
            gov.evaluate(_make_state(activity_mode="meeting"))

        # Meeting mode still active — now pauses
        assert gov.evaluate(_make_state(activity_mode="meeting")) == "pause"

        # Meeting clears — back to process
        assert gov.evaluate(_make_state(activity_mode="idle")) == "process"

    def test_grace_still_tracks_state(self):
        """During grace, _track_state is still called (operator presence updated)."""
        gov = PipelineGovernor()

        gov.wake_word_active = True
        gov.evaluate(_make_state())

        # During grace, operator presence should still be tracked
        old_seen = gov._last_operator_seen
        gov.evaluate(_make_state(operator_present=True))

        assert gov._last_operator_seen >= old_seen

    def test_no_grace_without_wake_word(self):
        """Normal evaluation has no grace period protection."""
        gov = PipelineGovernor()

        assert gov._wake_word_grace_remaining == 0

        result = gov.evaluate(_make_state(activity_mode="meeting"))
        assert result == "pause"
