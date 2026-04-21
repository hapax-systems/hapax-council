"""Phase C2 — utterance-boundary sticky semantics (spec §6.5).

When TTS goes silent between utterances, the active tier should STICK
for a configurable window (default 10 s) rather than immediately
reverting to stance-default. This keeps a multi-sentence narrative
passage acoustically coherent — the character doesn't reset between
the operator's breaths.

Operator CLI override (``hapax-voice-tier <n> --sticky``) persists
indefinitely until explicit ``--release``. Impingements during the
silence window can re-trigger tier shifts (sticky is a weak default,
not a lock).

The tracker is stateful — the router keeps a single instance and
calls it each tick. Hardware-independent; pure state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

DEFAULT_STICK_WINDOW_S: Final[float] = 10.0


@dataclass
class StickyTracker:
    """Tracks sticky tier state across TTS utterances.

    Three regimes compose:

    1. **Active TTS emission** — the arbitrated tier is written via
       ``on_tts_emission``. The tracker remembers this as the sticky
       tier.

    2. **Silence window** — after ``on_tts_silence_start``, the sticky
       tier remains active for ``stick_window_s``. ``active_tier_at(now)``
       returns the sticky tier. Impingements can still be modulated
       via the arbiter's normal path.

    3. **Post-silence** — after the window elapses, ``active_tier_at``
       returns ``None`` (caller falls back to stance default).

    The operator override is the fourth regime: when ``sticky=True``
    on ``operator_override``, the tier is pinned until
    ``operator_release`` is called. In that case ``active_tier_at``
    always returns the override tier regardless of silence state.
    """

    stick_window_s: float = DEFAULT_STICK_WINDOW_S
    _active_tier: int | None = None
    _silence_start: float | None = None
    _operator_override_tier: int | None = None
    _operator_override_sticky: bool = False

    # Optional history field for debugging / Langfuse event correlation.
    _transitions: list[tuple[float, str]] = field(default_factory=list)

    def on_tts_emission(self, tier: int, now: float) -> None:
        """Called by the router when TTS emits audio (VAD-positive).

        Captures the current tier as the sticky candidate. Clears the
        silence timer — subsequent silence starts a fresh window.
        """
        self._active_tier = tier
        self._silence_start = None
        self._transitions.append((now, f"emission tier={tier}"))

    def on_tts_silence_start(self, now: float) -> None:
        """Called when TTS goes silent (VAD transitions to negative).

        Starts the silence window. ``active_tier_at`` will return the
        sticky tier until ``now + stick_window_s``.
        """
        self._silence_start = now
        self._transitions.append((now, "silence_start"))

    def operator_override(self, tier: int, now: float, *, sticky: bool = False) -> None:
        """Operator CLI override — wins over automatic tier selection.

        When ``sticky=True``, the override persists until ``operator_release``
        is called. When ``sticky=False``, it behaves like a transient
        emission (subject to the silence-window semantics).
        """
        self._operator_override_tier = tier
        self._operator_override_sticky = sticky
        if sticky:
            self._transitions.append((now, f"operator_override_sticky tier={tier}"))
        else:
            self._transitions.append((now, f"operator_override tier={tier}"))
        # Transient operator overrides behave like emissions
        if not sticky:
            self.on_tts_emission(tier, now)

    def operator_release(self, now: float) -> None:
        """Release a sticky operator override — resume automatic behavior."""
        self._operator_override_tier = None
        self._operator_override_sticky = False
        self._transitions.append((now, "operator_release"))

    def active_tier_at(self, now: float) -> int | None:
        """Return the tier the router should emit at this tick, or
        ``None`` if the caller should fall back to stance-default.

        Precedence (highest first):
        1. Sticky operator override — always wins
        2. During active emission (no silence start) — last emitted tier
        3. During silence window — last emitted tier
        4. After silence window — ``None``
        """
        if self._operator_override_sticky:
            return self._operator_override_tier

        if self._active_tier is None:
            return None

        if self._silence_start is None:
            # Currently emitting (or never went silent)
            return self._active_tier

        # In silence window
        elapsed = now - self._silence_start
        if elapsed <= self.stick_window_s:
            return self._active_tier

        # Past the silence window — stick expired
        return None

    def is_in_silence_window(self, now: float) -> bool:
        """Utility — true iff the sticky tier is currently held."""
        if self._silence_start is None:
            return False
        return (now - self._silence_start) <= self.stick_window_s

    def is_operator_overridden(self) -> bool:
        return self._operator_override_sticky
