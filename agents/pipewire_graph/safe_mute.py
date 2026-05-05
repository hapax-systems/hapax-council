"""Safe-mute rail interface for the PipeWire graph daemon.

P2 carries the API shape but never mutates the live graph. Loading,
engage, and disengage methods therefore only update in-memory state and
return an explicit "shadow-mode" result. The active rail that performs
``pw-link`` belongs to P4/P5.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafeMuteResult:
    """Result of a safe-mute rail operation."""

    operation: str
    mutated_live_graph: bool
    message: str


class SafeMuteRail:
    """Observe-only safe-mute rail placeholder.

    ``load_shadow`` represents the P2 "loaded but not engaged" contract.
    ``engage`` and ``disengage`` are safe to call in tests, but they do
    not run ``pactl`` or ``pw-link``.
    """

    def __init__(self) -> None:
        self.loaded = False
        self.engaged = False
        self.engage_attempts = 0

    def load_shadow(self) -> SafeMuteResult:
        self.loaded = True
        return SafeMuteResult(
            operation="load",
            mutated_live_graph=False,
            message="shadow-mode safe-mute rail loaded as API placeholder",
        )

    def engage(self, *, reason: str) -> SafeMuteResult:
        self.engage_attempts += 1
        self.engaged = False
        return SafeMuteResult(
            operation="engage",
            mutated_live_graph=False,
            message=f"shadow-mode would have engaged safe-mute: {reason}",
        )

    def disengage(self) -> SafeMuteResult:
        self.engaged = False
        return SafeMuteResult(
            operation="disengage",
            mutated_live_graph=False,
            message="shadow-mode safe-mute disengage is a no-op",
        )


__all__ = ["SafeMuteRail", "SafeMuteResult"]
