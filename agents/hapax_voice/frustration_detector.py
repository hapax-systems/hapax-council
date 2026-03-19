"""Mechanical rolling frustration scorer for voice conversations.

No LLM calls, no embeddings. Pure signal detection adapted from
Datadog RUM frustration signals + COLING 2025 dialogue breakdown research.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

_CORRECTION_MARKERS = re.compile(
    r"\b(i said|i meant|not that|no i mean|that's not what i)\b",
    flags=re.IGNORECASE,
)
_NEGATION_TOKENS = re.compile(
    r"\b(no|not|don't|doesn't|didn't|won't|can't|never|none|nothing|neither|nor)\b",
    flags=re.IGNORECASE,
)
_ELABORATION_REQUESTS = re.compile(
    r"\b(what do you mean|what\?|huh\??|i don't understand|what are you)\b",
    flags=re.IGNORECASE,
)

SPIKE_THRESHOLD = 5
WINDOW_SIZE = 5


def _word_overlap(a: str, b: str) -> float:
    """Jaccard word overlap between two strings."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


@dataclass
class TurnSignals:
    """Per-signal breakdown for a single turn."""

    repeated_question: int = 0
    correction_marker: int = 0
    negation_density: int = 0
    barge_in: int = 0
    tool_error: int = 0
    system_repetition: int = 0
    fast_follow_up: int = 0
    elaboration_request: int = 0

    @property
    def score(self) -> int:
        return (
            self.repeated_question
            + self.correction_marker
            + self.negation_density
            + self.barge_in
            + self.tool_error
            + self.system_repetition
            + self.fast_follow_up
            + self.elaboration_request
        )

    def breakdown(self) -> dict[str, int]:
        """Return non-zero signals as a dict."""
        result = {}
        for name in (
            "repeated_question",
            "correction_marker",
            "negation_density",
            "barge_in",
            "tool_error",
            "system_repetition",
            "fast_follow_up",
            "elaboration_request",
        ):
            val = getattr(self, name)
            if val > 0:
                result[name] = val
        return result


@dataclass
class FrustrationDetector:
    """Stateful rolling frustration scorer."""

    _prev_user_text: str = ""
    _prev_assistant_text: str = ""
    _window: deque[int] = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))

    def score_turn(
        self,
        user_text: str,
        assistant_text: str = "",
        *,
        barge_in: bool = False,
        tool_error: bool = False,
        follow_up_delay: float = 999.0,
    ) -> TurnSignals:
        """Score a single turn. Returns signal breakdown."""
        signals = TurnSignals()

        # Repeated question: word overlap >0.6 with previous user utterance
        if self._prev_user_text and _word_overlap(user_text, self._prev_user_text) > 0.6:
            signals.repeated_question = 3

        # Correction marker
        if _CORRECTION_MARKERS.search(user_text):
            signals.correction_marker = 2

        # Negation density: >=2 negation tokens in one turn
        neg_count = len(_NEGATION_TOKENS.findall(user_text))
        if neg_count >= 2:
            signals.negation_density = 2

        # Barge-in
        if barge_in:
            signals.barge_in = 2

        # Tool error
        if tool_error:
            signals.tool_error = 2

        # System repetition: response overlap >0.7 with previous response
        if (
            self._prev_assistant_text
            and assistant_text
            and _word_overlap(assistant_text, self._prev_assistant_text) > 0.7
        ):
            signals.system_repetition = 2

        # Fast follow-up: <1s after assistant finished
        if follow_up_delay < 1.0:
            signals.fast_follow_up = 1

        # Elaboration request
        if _ELABORATION_REQUESTS.search(user_text):
            signals.elaboration_request = 1

        # Update state
        self._prev_user_text = user_text
        self._prev_assistant_text = assistant_text
        self._window.append(signals.score)

        return signals

    @property
    def rolling_average(self) -> float:
        """Average frustration score over the rolling window."""
        if not self._window:
            return 0.0
        return sum(self._window) / len(self._window)

    @property
    def is_spiked(self) -> bool:
        """Whether the most recent turn exceeded the spike threshold."""
        if not self._window:
            return False
        return self._window[-1] >= SPIKE_THRESHOLD

    def reset(self) -> None:
        """Reset all state."""
        self._prev_user_text = ""
        self._prev_assistant_text = ""
        self._window.clear()
