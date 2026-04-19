"""HomageTransitionalSource — FSM base for transition-aware Cairo sources.

HOMAGE spec §4.10. Every ward that participates in HOMAGE inherits
this class (Phase 4+ migrations). The base owns the transition FSM
(``absent``, ``entering``, ``hold``, ``exiting``) and dispatches render
calls to subclass-provided ``render_content()`` only when in ``hold``
(or when a transition is actively using the content as its scrolling
payload).

The FSM is driven by the choreographer: externally-supplied
``apply_transition()`` calls move the state. The source itself does
not emit transitions; it only applies them. This keeps the
"nothing plopped or pasted" invariant enforceable by the
choreographer — a source whose render is called while in ``absent``
state produces a transparent surface and logs a violation.

Subclasses implement ``render_content(cr, canvas_w, canvas_h, t, state)``.
The base's ``render()`` wraps it with FSM dispatch + package-aware
grammar application.

Feature-flag: as of Phase 12 (task #120, 2026-04-18) the flag defaults
to ON. Setting ``HAPAX_HOMAGE_ACTIVE=0`` (or any falsy value) keeps the
transition state pinned at ``hold`` and dispatches directly to
``render_content()`` — the paint-and-hold emergency rollback path.
"""

from __future__ import annotations

import logging
import os
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.cairo_source import CairoSource
from shared.homage_package import HomagePackage, TransitionName

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


class TransitionState(StrEnum):
    """The four FSM states a transitional source can occupy."""

    ABSENT = "absent"
    ENTERING = "entering"
    HOLD = "hold"
    EXITING = "exiting"


def _feature_flag_active() -> bool:
    """Read ``HAPAX_HOMAGE_ACTIVE``. Phase 12 default-ON.

    Unset env (or any truthy value) → active. Explicit disable requires
    ``HAPAX_HOMAGE_ACTIVE=0`` (or ``false``, ``no``, ``off``). Must stay
    in lock-step with ``choreographer._feature_flag_active``.
    """
    raw = os.environ.get("HAPAX_HOMAGE_ACTIVE")
    if raw is None:
        return True
    value = raw.strip().lower()
    if value == "":
        return True
    return value not in ("0", "false", "no", "off")


class HomageTransitionalSource(CairoSource):
    """FSM-wrapping base class for HOMAGE-participating Cairo sources.

    Subclasses implement ``render_content()``. The base's ``render()``
    handles state dispatch + transition pixel effects per the active
    HomagePackage's TransitionVocab.

    The FSM is ``ABSENT`` until ``apply_transition("ticker-scroll-in")``
    (or the package's default_entry) is called; it then advances through
    ``ENTERING`` → ``HOLD``. An exit transition advances
    ``HOLD`` → ``EXITING`` → ``ABSENT``.
    """

    def __init__(
        self,
        source_id: str,
        *,
        initial_state: TransitionState = TransitionState.HOLD,
        entering_duration_s: float = 0.4,
        exiting_duration_s: float = 0.3,
    ) -> None:
        # HOTFIX 2026-04-18 (delta): HomageTransitionalSource previously
        # defaulted to ``TransitionState.ABSENT``, meaning every Cairo ward
        # that inherits from this base class silently rendered NOTHING
        # until the choreographer (``homage/choreographer.py``) explicitly
        # dispatched an entry transition for that source_id. When the
        # Phase 12 flip (commit a7922e904) made ``HAPAX_HOMAGE_ACTIVE=1``
        # the default, every ward not targeted by the choreographer
        # (token_pole, album, captions, chat_ambient, hardm_dot_matrix,
        # pressure_gauge, thinking_indicator, whos_here, activity_variety_log,
        # impingement_cascade, recruitment_candidate_panel) disappeared
        # from the livestream. ``pip_draw_from_layout`` called
        # ``blit_scaled`` on each of them, but the cached output surface
        # was all-zero (see ``render()`` below: ABSENT returns immediately
        # without painting). Defaulting to HOLD restores the legacy
        # paint-and-hold semantics so the ward renders unconditionally;
        # the choreographer can still emit ``ticker-scroll-out`` /
        # ``ticker-scroll-in`` transitions to temporarily hide or
        # re-introduce wards per the HOMAGE grammar. Subclasses that
        # want the ABSENT-by-default behaviour (e.g. time-limited
        # announcement banners) explicitly pass
        # ``initial_state=TransitionState.ABSENT``.
        self._source_id = source_id
        self._state: TransitionState = initial_state
        self._pending_transition: TransitionName | None = None
        self._transition_started_ts: float | None = None
        self._last_transition_applied_ts: float | None = None
        self._entering_duration_s = entering_duration_s
        self._exiting_duration_s = exiting_duration_s

    # ── Public FSM API ──────────────────────────────────────────────────

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def transition_state(self) -> TransitionState:
        return self._state

    @property
    def pending_transition(self) -> TransitionName | None:
        return self._pending_transition

    @property
    def last_transition_applied_ts(self) -> float | None:
        return self._last_transition_applied_ts

    def apply_transition(
        self, transition: TransitionName, *, now: float | None = None
    ) -> TransitionState:
        """Advance the FSM per the named transition.

        Idempotent at a steady state (HOLD receiving a ``ticker-scroll-in``
        stays in HOLD and returns without error). Raises on meaningless
        transitions (ABSENT receiving a ``ticker-scroll-out``).
        """
        ts = time.monotonic() if now is None else now
        self._pending_transition = transition
        self._transition_started_ts = ts
        self._last_transition_applied_ts = ts

        if transition in _ENTRY_TRANSITIONS:
            prior = self._state
            if prior in (TransitionState.ABSENT, TransitionState.EXITING):
                self._state = TransitionState.ENTERING
                self._on_entry_start()
            elif prior is TransitionState.HOLD:
                # re-entry on hold is a no-op; the choreographer is allowed
                # to schedule redundant entries without crashing the FSM
                pass
            # ENTERING receiving another entry stays ENTERING
            return self._state

        if transition in _EXIT_TRANSITIONS:
            prior = self._state
            if prior in (TransitionState.HOLD, TransitionState.ENTERING):
                self._state = TransitionState.EXITING
                self._on_exit_start()
            elif prior is TransitionState.ABSENT:
                raise ValueError(
                    f"{self._source_id}: cannot apply exit transition {transition!r} from ABSENT"
                )
            return self._state

        # Non-state-changing transitions (topic-change, mode-change,
        # netsplit-burst) leave the state intact but are recorded as the
        # pending transition so the choreographer / renderer can react.
        return self._state

    def tick(self, *, now: float | None = None) -> TransitionState:
        """Advance FSM on a clock tick. Auto-completes entering/exiting."""
        ts = time.monotonic() if now is None else now
        if self._state is TransitionState.ENTERING:
            assert self._transition_started_ts is not None
            if ts - self._transition_started_ts >= self._entering_duration_s:
                self._state = TransitionState.HOLD
                self._on_entry_complete()
        elif self._state is TransitionState.EXITING:
            assert self._transition_started_ts is not None
            if ts - self._transition_started_ts >= self._exiting_duration_s:
                self._state = TransitionState.ABSENT
                self._on_exit_complete()
        return self._state

    # ── Hook points ─────────────────────────────────────────────────────

    def _on_entry_start(self) -> None:
        """Called when FSM transitions ABSENT/EXITING → ENTERING."""

    def _on_entry_complete(self) -> None:
        """Called when FSM transitions ENTERING → HOLD."""

    def _on_exit_start(self) -> None:
        """Called when FSM transitions HOLD/ENTERING → EXITING."""

    def _on_exit_complete(self) -> None:
        """Called when FSM transitions EXITING → ABSENT."""

    # ── Subclass contract ───────────────────────────────────────────────

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:  # pragma: no cover — subclass implements
        """Subclass-authored content render.

        Called when the FSM is in ``HOLD`` (or when a transition is
        actively using the rendered content as its scrolling payload).
        Subclasses apply the active HomagePackage's grammar rules
        (palette roles, line-start marker, container shape) inside this
        method.
        """
        raise NotImplementedError

    def render_entering(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
        progress: float,
    ) -> None:
        """Default entering-state render: delegate to ``render_content``.

        Subclasses may override to supply transition-specific pixel
        effects (scroll, inverse-flash, etc.). ``progress`` is 0.0–1.0
        through the entering duration.

        The base implementation renders the content as-is — packages
        whose entry transition is ``zero-cut-in`` get correct behaviour
        without subclass code.
        """
        self.render_content(cr, canvas_w, canvas_h, t, state)

    def render_exiting(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
        progress: float,
    ) -> None:
        """Default exiting-state render: delegate to ``render_content``."""
        self.render_content(cr, canvas_w, canvas_h, t, state)

    # ── CairoSource.render() override ──────────────────────────────────

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """FSM-dispatching render.

        - When HAPAX_HOMAGE_ACTIVE=0: legacy path — always renders content.
        - When HAPAX_HOMAGE_ACTIVE=1:
          - ABSENT: no-op (transparent surface remains).
          - ENTERING: ``render_entering()`` with progress.
          - HOLD: ``render_content()``.
          - EXITING: ``render_exiting()`` with progress.
          - A violation is logged if the choreographer has not emitted a
            transition for this source in the current tick (spec §4.9).

        Cascade-delta (2026-04-18): after rendering content, paint the
        ward-properties emphasis border if the narrative director's
        structural_intent has nominated this ward. This is what makes
        the structural-intent surface visibly active — the operator's
        "unavoidable evidence of active thoughtful manipulation".
        """
        if not _feature_flag_active():
            self.render_content(cr, canvas_w, canvas_h, t, state)
            self._maybe_paint_emphasis(cr, canvas_w, canvas_h, t)
            return

        self.tick()

        if self._state is TransitionState.ABSENT:
            # Transparent — runner already cleared the surface.
            return

        if self._state is TransitionState.HOLD:
            self.render_content(cr, canvas_w, canvas_h, t, state)
            self._maybe_paint_emphasis(cr, canvas_w, canvas_h, t)
            return

        progress = self._progress(now=time.monotonic())
        if self._state is TransitionState.ENTERING:
            self.render_entering(cr, canvas_w, canvas_h, t, state, progress)
        elif self._state is TransitionState.EXITING:
            self.render_exiting(cr, canvas_w, canvas_h, t, state, progress)
        self._maybe_paint_emphasis(cr, canvas_w, canvas_h, t)

    def _maybe_paint_emphasis(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
    ) -> None:
        """Best-effort glow-border overlay driven by ``ward-properties.json``.

        Called after ``render_content`` / ``render_entering`` /
        ``render_exiting`` so the emphasis border sits on top of the
        ward's own artwork. Cairo or import errors are swallowed —
        emphasis polish must never break a ward's primary render path.
        """
        try:
            from agents.studio_compositor.homage.rendering import (
                active_package,
                paint_emphasis_border,
            )

            paint_emphasis_border(
                cr,
                canvas_w,
                canvas_h,
                active_package(),
                ward_id=self._source_id,
                t=t,
            )
        except Exception:
            log.debug("_maybe_paint_emphasis failed for %s", self._source_id, exc_info=True)

    # ── Utilities ───────────────────────────────────────────────────────

    def _progress(self, *, now: float) -> float:
        """Return transition progress in [0.0, 1.0]. 0.0 if no start."""
        if self._transition_started_ts is None:
            return 0.0
        elapsed = now - self._transition_started_ts
        if self._state is TransitionState.ENTERING:
            if self._entering_duration_s <= 0:
                return 1.0
            return max(0.0, min(1.0, elapsed / self._entering_duration_s))
        if self._state is TransitionState.EXITING:
            if self._exiting_duration_s <= 0:
                return 1.0
            return max(0.0, min(1.0, elapsed / self._exiting_duration_s))
        return 1.0

    def apply_package_grammar(self, cr: cairo.Context, package: HomagePackage) -> None:
        """Subclass utility: apply the active package's grammar to ``cr``.

        Sets the default source colour to the content role, font
        selection to the package's primary + size class "normal", and
        leaves the surface otherwise untouched. Subclasses use this as
        a setup step inside ``render_content()`` so the grammar stays
        DRY across wards.
        """
        r, g, b, a = package.resolve_colour(package.grammar.content_colour_role)
        cr.set_source_rgba(r, g, b, a)
        # Font selection happens via Pango at text-render time; this
        # helper's job is just to normalise colour state.


# Transitions that move the FSM toward HOLD.
_ENTRY_TRANSITIONS: frozenset[str] = frozenset(
    [
        "zero-cut-in",
        "ticker-scroll-in",
        "join-message",
    ]
)


# Transitions that move the FSM toward ABSENT.
_EXIT_TRANSITIONS: frozenset[str] = frozenset(
    [
        "zero-cut-out",
        "ticker-scroll-out",
        "part-message",
    ]
)


__all__ = [
    "HomageTransitionalSource",
    "TransitionState",
]
