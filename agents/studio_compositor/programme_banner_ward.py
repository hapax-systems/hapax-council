"""Programme banner ward — Cairo lower-third for active programme state.

cc-task ``programme-banner-ward``. Per alpha research
(``/tmp/wsjf-path-content-programming.md`` §3 G1, 2026-05-03): the programme
planner is emitting role + narrative_beat per programme but the livestream
viewer has no surface that names the active programme. The ambient ward
churn is opaque — operator + viewer can't tell what programme is shaping
the show right now.

This ward renders a 3-line lower-third with the planner's own output:

    Line 1: role (uppercase, accent palette)
    Line 2: narrative_beat (truncated to 80 chars; "" if None)
    Line 3: residual: Mm Ss (planned_duration_s minus elapsed)

It does NOT announce director moves, narrate the show, or generate text.
It surfaces what the programme planner already emitted — projecting
existing state onto the visual surface so the operator and viewer can
perceive what programme is active. Reference operator memory
``feedback_show_dont_tell_director``: the ward shows programme STATE,
which is itself the meta-structural communication; it does not tell.

Reads from :func:`shared.programme_store.default_store` so the ward
shares the same persistence the planner / programme manager write to —
the file IS the source of truth.

Phase 1 follow-ups (separate PR):
- Boundary-fade animation on programme transition.
- Ward-registry wiring in the compositor layout planner.
- Truncation refinement if 80ch is too aggressive at actual broadcast
  narrative_beat lengths.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

#: Maximum chars rendered for narrative_beat. Beyond this the banner
#: would wrap into multi-line territory and overflow the lower-third
#: footprint. Tunable post-smoke per cc-task Phase 1.
NARRATIVE_BEAT_MAX_CHARS: int = 80


def format_residual(residual_s: float) -> str:
    """Format residual seconds as ``"Mm Ss"`` string.

    - Negative residual (programme overrun): renders as ``"0m 0s"`` —
      the visual surface should not display negative time. The runtime
      programme manager handles transition; the ward stays neutral.
    - 0 residual: ``"0m 0s"``.
    - 65s: ``"1m 5s"``.
    - 3600s: ``"60m 0s"``.

    Output is operator-readable rather than HH:MM — the residual is
    always sub-show-arc (programmes are ~5-90 min) so minutes is the
    natural granularity.
    """
    if residual_s <= 0:
        return "0m 0s"
    minutes = int(residual_s // 60)
    seconds = int(residual_s % 60)
    return f"{minutes}m {seconds}s"


def truncate_beat(beat: str | None, *, max_chars: int = NARRATIVE_BEAT_MAX_CHARS) -> str:
    """Truncate narrative_beat to ``max_chars`` with ellipsis.

    None / empty → empty string (banner line 2 renders blank).
    """
    if beat is None:
        return ""
    stripped = beat.strip()
    if not stripped:
        return ""
    if len(stripped) <= max_chars:
        return stripped
    # -1 for the ellipsis char so total length stays at max_chars.
    return stripped[: max_chars - 1].rstrip() + "…"


def compute_residual_s(
    actual_started_at: float | None,
    planned_duration_s: float,
    *,
    now: float | None = None,
) -> float:
    """Compute residual seconds remaining for an active programme.

    actual_started_at is None on a programme that's not actually started
    yet — return planned_duration_s (caller renders "Mm Ss" with the
    full window).
    """
    if actual_started_at is None:
        return planned_duration_s
    now_ts = now if now is not None else time.time()
    elapsed = now_ts - actual_started_at
    return planned_duration_s - elapsed


def _fallback_package() -> HomagePackage:
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


class ProgrammeBannerWard(HomageTransitionalSource):
    """Cairo lower-third surfacing the active programme's role + beat + residual.

    State() snapshots the active programme via ``default_store()`` so a
    swap of underlying persistence (planned for Phase 2 of the programme
    layer) only changes one import. Render() is a pure write into the
    Cairo context — no I/O, no allocations beyond paths.
    """

    def __init__(self, *, max_beat_chars: int = NARRATIVE_BEAT_MAX_CHARS) -> None:
        super().__init__(source_id="programme_banner")
        if max_beat_chars <= 0:
            raise ValueError(f"max_beat_chars must be > 0, got {max_beat_chars}")
        self._max_beat_chars = max_beat_chars

    # ── CairoSource protocol ─────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        """Snapshot the active programme as a render-ready dict.

        Best-effort: any error reading the store yields an empty state
        (banner renders transparent). The store + Programme schema can
        evolve without breaking the ward.
        """
        try:
            from shared.programme_store import default_store
        except Exception:
            log.debug("programme_store import failed; banner clearing", exc_info=True)
            return {"active": None}

        try:
            store = default_store()
            programme = store.active_programme()
        except Exception:
            log.debug("default_store().active_programme() failed", exc_info=True)
            return {"active": None}

        if programme is None:
            return {"active": None}

        return {
            "active": {
                "role": str(programme.role),
                "narrative_beat": programme.content.narrative_beat,
                "actual_started_at": programme.actual_started_at,
                "planned_duration_s": programme.planned_duration_s,
            }
        }

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,  # noqa: ARG002 — HomageTransitionalSource protocol
        state: dict[str, Any],
    ) -> None:
        """Draw the banner; clear transparent if no active programme."""
        import cairo

        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.restore()

        active = state.get("active")
        if active is None:
            return

        role = str(active.get("role") or "").upper()
        if not role:
            return

        beat = truncate_beat(active.get("narrative_beat"), max_chars=self._max_beat_chars)
        residual_s = compute_residual_s(
            active.get("actual_started_at"),
            float(active.get("planned_duration_s") or 0.0),
        )
        residual_text = f"residual: {format_residual(residual_s)}"

        pkg = get_active_package() or _fallback_package()
        self._draw_banner(cr, canvas_w, canvas_h, role, beat, residual_text, pkg)

    # ── Cairo rendering ─────────────────────────────────────────────

    def _draw_banner(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        role: str,
        beat: str,
        residual_text: str,
        pkg: HomagePackage,
    ) -> None:
        """Draw a 3-line lower-third panel anchored bottom-left.

        Layout matches the existing objectives-overlay grammar (semi-
        opaque dark bg, accent bar, line spacing) but without the
        operator-objective semantics. Numbers tuned for a 1920x1080
        canvas; render scales position to canvas dimensions so smaller
        previews still hit a sensible footprint.
        """
        import cairo

        padding = max(16, canvas_h // 60)
        line_h = max(28, canvas_h // 40)
        accent_w = max(4, canvas_w // 480)

        x = padding
        y = canvas_h - padding - (line_h * 3) - padding

        scrim_w = int(canvas_w * 0.6)
        scrim_h = (line_h * 3) + (padding * 2)

        bg_r, bg_g, bg_b, _ = pkg.resolve_colour("background")
        accent_r, accent_g, accent_b, accent_a = pkg.resolve_colour("accent_yellow")
        bright = pkg.resolve_colour("bright")
        muted = pkg.resolve_colour("muted")

        cr.save()
        cr.rectangle(x, y, scrim_w, scrim_h)
        cr.set_source_rgba(bg_r, bg_g, bg_b, 0.78)
        cr.fill()
        cr.restore()

        cr.save()
        cr.rectangle(x, y, accent_w, scrim_h)
        cr.set_source_rgba(accent_r, accent_g, accent_b, accent_a)
        cr.fill()
        cr.restore()

        font_family = pkg.typography.primary_font_family
        cr.save()
        cr.set_source_rgba(*bright)
        cr.select_font_face(font_family, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

        text_x = x + accent_w + padding
        text_y = y + padding + (line_h * 0.7)

        cr.set_font_size(line_h * 0.7)
        cr.move_to(text_x, text_y)
        cr.show_text(role)

        cr.select_font_face(font_family, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(line_h * 0.55)
        text_y += line_h
        cr.move_to(text_x, text_y)
        cr.show_text(beat)

        cr.select_font_face(font_family, cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(line_h * 0.5)
        cr.set_source_rgba(*muted)
        text_y += line_h
        cr.move_to(text_x, text_y)
        cr.show_text(residual_text)

        cr.restore()


__all__ = [
    "NARRATIVE_BEAT_MAX_CHARS",
    "ProgrammeBannerWard",
    "compute_residual_s",
    "format_residual",
    "truncate_beat",
]
