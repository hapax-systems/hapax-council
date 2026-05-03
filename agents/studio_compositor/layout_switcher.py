"""Dynamic compositor-layout switching driven by stream_mode +
director-intent activity (R9, 2026-05-02 effect+cam orchestration audit).

Until 2026-05-02 the compositor never switched between its layout
templates: ``default`` ran unless ``consent-safe`` tripped, and
``vinyl-focus`` / ``default-legacy`` were reachable only via manual
override. The audit's §5 U6 finding called this out as latent
underutilization — every signal needed for a sensible per-tick
selection (stream_mode transitions, director activity, vinyl-playing
signal) was already being computed.

This module is pure logic + a thin stateful cooldown wrapper. It
mirrors the shape of ``objective_hero_switcher`` — callers pass
inputs, get a recommendation, and apply it via ``LayoutState.mutate``.
A separate Prometheus counter
(``hapax_compositor_layout_switch_total{from_layout, to_layout, trigger}``)
records every applied switch.

Selection policy (priority order):

1. ``consent_safe_active`` → ``consent-safe`` is owned by the
   operator-safety gate, NOT by this switcher. We surface it as
   ``LayoutSelection.layout_name="consent-safe"`` only when the
   caller passes the flag, so the switcher cannot accidentally drop
   the safety layout. The cooldown does NOT apply to consent-safe
   transitions — safety beats aesthetics.
2. ``vinyl_playing`` → ``vinyl-focus``. The §127 SPLATTRIBUTION
   signal: when the music IS the show, the spinning platter ward is
   the centerpiece.
3. ``director_activity in {"vinyl", "react"}`` → ``vinyl-focus``.
   Director activity carries a similar music-centerpiece signal even
   when the deterministic ``vinyl_playing`` flag is False (e.g. live
   reactive sessions where the platter signal hasn't fired yet).
4. ``stream_mode == "deep"`` → ``default-legacy`` (less chrome,
   research-mode focus).
5. Otherwise → ``default``.

Out of scope (follow-up): wiring the switcher into the director-loop
tick or a dedicated systemd timer; ``mobile.json`` (different schema
entirely, used by a separate mobile renderer); operator-editable
config for the priority order. This PR ships the pure-logic +
cooldown + observability counter; integration is deliberately
separate.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

# The 4 layout templates the audit referenced. ``mobile.json`` has a
# different schema and is excluded; ``consent-safe`` is operator-only.
KNOWN_LAYOUTS: frozenset[str] = frozenset(
    {"default", "default-legacy", "consent-safe", "vinyl-focus"}
)

# Audit floor: 8s. Existing cc-task aesthetic guard: 30s. Default to
# the more conservative value so the surface does not chatter.
DEFAULT_COOLDOWN_S: float = 30.0
MIN_COOLDOWN_S: float = 8.0


@dataclass(frozen=True)
class LayoutSelection:
    """Recommended layout + the trigger that named it.

    ``trigger`` is recorded on the Prometheus counter so the operator
    can see WHICH input drove a switch (vinyl, stream-mode, director
    activity, etc.). Useful for tuning the priority order.
    """

    layout_name: str
    trigger: str


def select_layout(
    *,
    consent_safe_active: bool = False,
    vinyl_playing: bool = False,
    director_activity: str | None = None,
    stream_mode: str | None = None,
) -> LayoutSelection:
    """Pure-logic policy. See module docstring for priority order."""
    if consent_safe_active:
        return LayoutSelection("consent-safe", "consent_safe")
    if vinyl_playing:
        return LayoutSelection("vinyl-focus", "vinyl_playing")
    if director_activity in {"vinyl", "react"}:
        return LayoutSelection("vinyl-focus", f"director_activity_{director_activity}")
    if stream_mode == "deep":
        return LayoutSelection("default-legacy", "stream_mode_deep")
    return LayoutSelection("default", "default_fallback")


class LayoutSwitcher:
    """Stateful wrapper that enforces a cooldown between switches.

    Pattern: caller asks ``should_switch(selection)``; if True, caller
    applies the switch (e.g. ``LayoutState.mutate``) and notifies via
    ``record_switch(selection)``. If the layout name has not changed,
    ``should_switch`` returns False without consulting the cooldown
    (no-op transitions cost nothing).

    Consent-safe transitions BYPASS the cooldown — safety beats
    aesthetics. Every other transition honors it.
    """

    def __init__(
        self,
        *,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
        initial_layout: str | None = None,
    ) -> None:
        if cooldown_s < MIN_COOLDOWN_S:
            raise ValueError(
                f"cooldown_s={cooldown_s} below floor {MIN_COOLDOWN_S}; "
                "use a value >= 8s to avoid frantic cuts (R9 acceptance)."
            )
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._current_layout: str | None = initial_layout
        self._last_switch_at: float | None = None

    @property
    def current_layout(self) -> str | None:
        return self._current_layout

    def should_switch(self, selection: LayoutSelection, *, now: float | None = None) -> bool:
        """True iff a switch is appropriate AND cooldown allows it."""
        if selection.layout_name == self._current_layout:
            return False
        if selection.trigger == "consent_safe":
            return True
        if self._last_switch_at is None:
            return True
        when = self._clock() if now is None else now
        return (when - self._last_switch_at) >= self._cooldown_s

    def record_switch(self, selection: LayoutSelection, *, now: float | None = None) -> None:
        """Record an applied switch. Caller has already mutated state."""
        when = self._clock() if now is None else now
        previous = self._current_layout
        self._current_layout = selection.layout_name
        self._last_switch_at = when
        try:
            from agents.studio_compositor import metrics as _metrics

            counter = getattr(_metrics, "HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL", None)
            if counter is not None:
                counter.labels(
                    from_layout=previous or "uninitialised",
                    to_layout=selection.layout_name,
                    trigger=selection.trigger,
                ).inc()
        except Exception:
            log.debug("layout-switch counter increment failed", exc_info=True)
