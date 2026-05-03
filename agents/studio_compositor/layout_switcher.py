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


def apply_layout_switch(
    layout_state: object,
    loader: object,
    switcher: LayoutSwitcher,
    *,
    consent_safe_active: bool = False,
    vinyl_playing: bool = False,
    director_activity: str | None = None,
    stream_mode: str | None = None,
    now: float | None = None,
) -> bool:
    """One-call adapter: select → gate → load → mutate → record.

    ``layout_state`` must expose ``mutate(fn: Callable[[Layout], Layout])``
    and ``loader`` must expose ``load(name: str) -> Layout`` — typed as
    ``object`` here so callers don't pay an import cycle (the
    layout_state and compositor-model modules import this through a
    different chain in production).

    Returns ``True`` iff a switch was applied. ``False`` covers two
    cases: same-layout no-op, or cooldown-blocked. Unknown layout names
    propagate ``KeyError`` from the loader — the caller decides whether
    to log + skip or escalate. Pipeline-side validation errors
    (pydantic on the loaded JSON) propagate too; an invalid layout file
    on disk is a deploy-side bug, not a runtime fallback.

    Cc-task: ``dynamic-compositor-layout-switching-followup``.
    """
    selection = select_layout(
        consent_safe_active=consent_safe_active,
        vinyl_playing=vinyl_playing,
        director_activity=director_activity,
        stream_mode=stream_mode,
    )
    if not switcher.should_switch(selection, now=now):
        return False
    new_layout = loader.load(selection.layout_name)  # type: ignore[attr-defined]
    layout_state.mutate(lambda _previous: new_layout)  # type: ignore[attr-defined]
    switcher.record_switch(selection, now=now)
    return True


# u6-periodic-tick-driver — periodic driver wrapping apply_layout_switch.
# The compositor's layout selector previously needed a callsite (director-
# loop tick or dedicated timer) to drive it; this is that timer. Runs in
# a thread until stop_event is set; per-iteration cost is one state read
# + (at most) one layout-load + mutate. Cooldown enforcement on the
# switcher prevents storms even if state oscillates rapidly.
DEFAULT_DRIVER_INTERVAL_S: float = 30.0
MIN_DRIVER_INTERVAL_S: float = 10.0


def run_layout_switch_loop(
    *,
    layout_state: object,
    loader: object,
    switcher: LayoutSwitcher,
    state_provider: Callable[[], dict[str, object]],
    interval_s: float = DEFAULT_DRIVER_INTERVAL_S,
    sleep_fn: Callable[[float], None] = time.sleep,
    stop_event: object | None = None,
    now_fn: Callable[[], float] = time.time,
    iterations: int | None = None,
) -> int:
    """Tick `apply_layout_switch` every `interval_s` until `stop_event.is_set()`.

    Parameters
    ----------
    layout_state, loader, switcher:
        Same as `apply_layout_switch` — the targets of each tick's
        recommendation + cooldown gate + observability counter.
    state_provider:
        Zero-arg callable returning a dict with keys:
        ``consent_safe_active`` (bool), ``vinyl_playing`` (bool),
        ``director_activity`` (str | None), ``stream_mode`` (str | None).
        Each tick re-reads via this callable so live state-file
        changes propagate at the next interval. Missing keys default
        to safe values per `apply_layout_switch`.
    interval_s:
        Minimum seconds between ticks. Defaults to 30s
        (`DEFAULT_DRIVER_INTERVAL_S`); MIN_DRIVER_INTERVAL_S = 10s
        floor matches the cooldown debounce so we cannot tick faster
        than the switch can apply.
    sleep_fn:
        Override for tests so they don't have to wait the wall-clock
        interval. Defaults to `time.sleep`.
    stop_event:
        Optional `threading.Event`-shape object with `is_set()`. When
        the event is set the loop exits cleanly at the start of the
        next iteration. None means "never stop" (caller must
        terminate via `iterations`).
    now_fn:
        Override for tests; defaults to `time.time`. Passed through
        to `apply_layout_switch` as the cooldown clock.
    iterations:
        If set, run at most N iterations then return. Useful for
        bounded test runs.

    Returns
    -------
    Count of `apply_layout_switch` calls that returned True (a real
    switch was applied — same-layout no-ops + cooldown-blocks don't
    count). Useful for test assertions.

    Cc-task: ``u6-periodic-tick-driver``.
    """
    if interval_s < MIN_DRIVER_INTERVAL_S:
        interval_s = MIN_DRIVER_INTERVAL_S
    switches = 0
    iter_count = 0
    while True:
        if stop_event is not None:
            try:
                if stop_event.is_set():  # type: ignore[attr-defined]
                    break
            except Exception:
                log.debug("stop_event.is_set() failed; continuing loop", exc_info=True)
        if iterations is not None and iter_count >= iterations:
            break
        try:
            state = state_provider() or {}
        except Exception:
            log.warning("layout_switch state_provider failed; skipping tick", exc_info=True)
            state = {}
        try:
            applied = apply_layout_switch(
                layout_state,
                loader,
                switcher,
                consent_safe_active=bool(state.get("consent_safe_active", False)),
                vinyl_playing=bool(state.get("vinyl_playing", False)),
                director_activity=state.get("director_activity"),  # type: ignore[arg-type]
                stream_mode=state.get("stream_mode"),  # type: ignore[arg-type]
                now=now_fn(),
            )
            if applied:
                switches += 1
        except Exception:
            log.warning("apply_layout_switch tick raised; loop continues", exc_info=True)
        iter_count += 1
        sleep_fn(interval_s)
    return switches
