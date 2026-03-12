"""Pipeline governor — maps EnvironmentState to pipeline directives.

Directives:
  - "process": pipeline runs normally, audio flows to STT
  - "pause": FrameGate drops audio frames, pipeline frozen
  - "withdraw": session should close gracefully

Internally uses VetoChain (safety constraints) + FallbackChain (action selection)
from the governance primitives. Wake word overrides both chains.
"""

from __future__ import annotations

import logging
import time

from agents.hapax_voice.governance import (
    Candidate,
    FallbackChain,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)
from agents.hapax_voice.perception import EnvironmentState

log = logging.getLogger(__name__)


class PipelineGovernor:
    """Evaluates EnvironmentState and returns a directive string.

    The governor maintains minimal state for debouncing and absence
    tracking. It does NOT own the perception engine or the frame gate —
    it's a pure evaluator that the daemon calls each tick.

    Governance structure:
    - VetoChain: production/meeting mode, conversation debounce → deny = "pause"
    - FallbackChain: operator absence → "withdraw", default → "process"
    - Wake word: supremacy override, bypasses both chains
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
        self._wake_word_grace_remaining: int = 0

        # Last evaluation results (for observability)
        self.last_veto_result: VetoResult | None = None
        self.last_selected: Selected[str] | None = None

        # Safety constraints: any denial → "pause"
        self._veto_chain: VetoChain[EnvironmentState] = VetoChain(
            [
                Veto(
                    name="activity_mode",
                    predicate=lambda s: s.activity_mode not in ("production", "meeting"),
                ),
                Veto(
                    name="conversation_debounce",
                    predicate=lambda _: not self._paused_by_conversation,
                ),
            ]
        )

        # Action selection: first eligible wins, default "process"
        self._fallback_chain: FallbackChain[EnvironmentState, str] = FallbackChain(
            candidates=[
                Candidate(
                    name="operator_absent",
                    predicate=self._is_operator_absent,
                    action="withdraw",
                ),
            ],
            default="process",
        )

    @property
    def veto_chain(self) -> VetoChain[EnvironmentState]:
        """Expose veto chain for external composition (Phase 3 extension point)."""
        return self._veto_chain

    def evaluate(self, state: EnvironmentState) -> str:
        """Evaluate environment state and return directive.

        Args:
            state: Current EnvironmentState snapshot.

        Returns:
            One of "process", "pause", "withdraw".
        """
        # Wake word always overrides — immediate process + grace period
        if self.wake_word_active:
            self.wake_word_active = False
            self._wake_word_grace_remaining = 3  # 3 ticks × ~2.5s = ~7.5s protection
            self._conversation_first_seen = None
            self._paused_by_conversation = False
            self._conversation_cleared_at = None
            self.last_veto_result = VetoResult(allowed=True)
            self.last_selected = Selected(action="process", selected_by="wake_word_override")
            return "process"

        # Grace period: protect session for N ticks after wake word
        if self._wake_word_grace_remaining > 0:
            self._wake_word_grace_remaining -= 1
            self._track_state(state)
            self.last_veto_result = VetoResult(allowed=True)
            self.last_selected = Selected(action="process", selected_by="wake_word_grace")
            return "process"

        # Update stateful tracking (side effects, before governance evaluation)
        self._track_state(state)

        # Safety: VetoChain — any denial → "pause"
        self.last_veto_result = self._veto_chain.evaluate(state)
        if not self.last_veto_result.allowed:
            return "pause"

        # Selection: FallbackChain — first eligible or default "process"
        self.last_selected = self._fallback_chain.select(state)
        return self.last_selected.action

    def _track_state(self, state: EnvironmentState) -> None:
        """Update internal tracking state from environment snapshot."""
        # Track operator presence for withdraw detection
        if state.operator_present:
            self._last_operator_seen = time.monotonic()

        # Track conversation debounce
        if state.conversation_detected:
            self._conversation_cleared_at = None
            now = time.monotonic()
            if self._conversation_first_seen is None:
                self._conversation_first_seen = now
            elapsed = now - self._conversation_first_seen
            if elapsed >= self.conversation_debounce_s:
                self._paused_by_conversation = True
        else:
            self._conversation_first_seen = None

            # Environment-clear auto-resume
            if self._paused_by_conversation:
                now = time.monotonic()
                if self._conversation_cleared_at is None:
                    self._conversation_cleared_at = now
                clear_elapsed = now - self._conversation_cleared_at
                if clear_elapsed >= self.environment_clear_resume_s:
                    self._paused_by_conversation = False
                    self._conversation_cleared_at = None

    def _is_operator_absent(self, state: EnvironmentState) -> bool:
        """Check if operator has been absent long enough to withdraw."""
        if state.operator_present or state.face_count > 0:
            return False
        absent_s = time.monotonic() - self._last_operator_seen
        return absent_s > self.operator_absent_withdraw_s
