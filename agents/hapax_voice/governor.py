"""Pipeline governor — maps EnvironmentState to pipeline directives.

Directives:
  - "process": pipeline runs normally, audio flows to STT
  - "pause": FrameGate drops audio frames, pipeline frozen
  - "withdraw": session should close gracefully
"""
from __future__ import annotations

import logging
import time

from agents.hapax_voice.perception import EnvironmentState

log = logging.getLogger(__name__)


class PipelineGovernor:
    """Evaluates EnvironmentState and returns a directive string.

    The governor maintains minimal state for debouncing and absence
    tracking. It does NOT own the perception engine or the frame gate —
    it's a pure evaluator that the daemon calls each tick.
    """

    def __init__(
        self,
        conversation_debounce_s: float = 3.0,
        operator_absent_withdraw_s: float = 60.0,
        environment_clear_resume_s: float = 15.0,
    ) -> None:
        self.conversation_debounce_s = conversation_debounce_s
        self.operator_absent_withdraw_s = operator_absent_withdraw_s
        self.environment_clear_resume_s = environment_clear_resume_s

        # Internal state
        self._last_operator_seen: float = time.monotonic()
        self._conversation_first_seen: float | None = None
        self._paused_by_conversation: bool = False
        self._conversation_cleared_at: float | None = None
        self.wake_word_active: bool = False

    def evaluate(self, state: EnvironmentState) -> str:
        """Evaluate environment state and return directive.

        Args:
            state: Current EnvironmentState snapshot.

        Returns:
            One of "process", "pause", "withdraw".
        """
        # Wake word always overrides — immediate process
        if self.wake_word_active:
            self.wake_word_active = False
            self._conversation_first_seen = None
            self._paused_by_conversation = False
            self._conversation_cleared_at = None
            return "process"

        # Track operator presence for withdraw detection
        if state.operator_present:
            self._last_operator_seen = time.monotonic()

        # Production/meeting mode → pause
        if state.activity_mode in ("production", "meeting"):
            return "pause"

        # Conversation detection with debounce
        if state.conversation_detected:
            self._conversation_cleared_at = None  # reset clear timer
            now = time.monotonic()
            if self._conversation_first_seen is None:
                self._conversation_first_seen = now
            elapsed = now - self._conversation_first_seen
            if elapsed >= self.conversation_debounce_s:
                self._paused_by_conversation = True
                return "pause"
        else:
            self._conversation_first_seen = None

            # Environment-clear auto-resume (resume signal 3)
            if self._paused_by_conversation:
                now = time.monotonic()
                if self._conversation_cleared_at is None:
                    self._conversation_cleared_at = now
                clear_elapsed = now - self._conversation_cleared_at
                if clear_elapsed < self.environment_clear_resume_s:
                    return "pause"  # still within clear delay
                # Clear delay expired — auto-resume
                self._paused_by_conversation = False
                self._conversation_cleared_at = None

        # Operator absence → withdraw
        if not state.operator_present and state.face_count == 0:
            absent_s = time.monotonic() - self._last_operator_seen
            if absent_s > self.operator_absent_withdraw_s:
                return "withdraw"

        return "process"
