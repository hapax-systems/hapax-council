"""Conversational model — persistent cross-turn conversation state.

Tracks conversation temperature (cold→heated), operator engagement,
topic trajectory, and routing history. Updated by the cognitive loop
on each utterance, response, and silence tick.

Temperature: rises on rapid turns + tier escalation, decays exponentially
(τ≈15s) during silence. Engagement: EMA(α=0.3) over inverse response
latency + speech duration.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

_TEMP_DECAY_TAU = 15.0  # exponential decay time constant (seconds)
_ENGAGEMENT_ALPHA = 0.3  # EMA smoothing factor


@dataclass
class ConversationalModel:
    """Persistent cross-turn conversation state."""

    turn_count: int = 0
    conversation_temperature: float = 0.0  # 0=cold, 1=heated
    operator_engagement: float = 0.5  # from latency + turn length
    last_utterance_at: float = 0.0
    last_response_at: float = 0.0
    cumulative_silence_s: float = 0.0
    tier_history: deque[str] = field(default_factory=lambda: deque(maxlen=20))

    def on_utterance(self, transcript: str, tier: str, speech_s: float) -> None:
        """Update state on operator utterance."""
        now = time.monotonic()
        self.turn_count += 1
        self.tier_history.append(tier)

        # Temperature rises on rapid turns
        if self.last_response_at > 0:
            gap = now - self.last_response_at
            if gap < 3.0:
                self.conversation_temperature = min(1.0, self.conversation_temperature + 0.15)
            elif gap < 8.0:
                self.conversation_temperature = min(1.0, self.conversation_temperature + 0.05)

        # Temperature rises on tier escalation
        if len(self.tier_history) >= 2:
            tier_values = {"CANNED": 0, "LOCAL": 1, "FAST": 2, "STRONG": 3, "CAPABLE": 4}
            prev_val = tier_values.get(self.tier_history[-2], 2)
            curr_val = tier_values.get(tier, 2)
            if curr_val > prev_val:
                self.conversation_temperature = min(1.0, self.conversation_temperature + 0.1)

        # Engagement: EMA over speech duration (longer speech = more engaged)
        engagement_signal = min(1.0, speech_s / 5.0)
        self.operator_engagement = (
            _ENGAGEMENT_ALPHA * engagement_signal
            + (1 - _ENGAGEMENT_ALPHA) * self.operator_engagement
        )

        self.last_utterance_at = now
        self.cumulative_silence_s = 0.0

    def on_response(self, response_text: str, response_time_s: float) -> None:
        """Update state after Hapax responds."""
        now = time.monotonic()
        self.last_response_at = now

        # Engagement: fast responses correlate with higher engagement
        latency_signal = min(1.0, 1.0 / max(0.5, response_time_s))
        self.operator_engagement = (
            _ENGAGEMENT_ALPHA * latency_signal + (1 - _ENGAGEMENT_ALPHA) * self.operator_engagement
        )

    def on_silence_tick(self, dt: float) -> None:
        """Decay temperature during silence, accumulate silence time."""
        self.cumulative_silence_s += dt

        # Exponential decay: T(t) = T₀ * e^(-t/τ)
        decay = math.exp(-dt / _TEMP_DECAY_TAU)
        self.conversation_temperature *= decay

        # Clamp near-zero
        if self.conversation_temperature < 0.01:
            self.conversation_temperature = 0.0

    def reset(self) -> None:
        """Reset for new session."""
        self.turn_count = 0
        self.conversation_temperature = 0.0
        self.operator_engagement = 0.5
        self.last_utterance_at = 0.0
        self.last_response_at = 0.0
        self.cumulative_silence_s = 0.0
        self.tier_history.clear()
