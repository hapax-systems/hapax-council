"""Programme-state Cairo source — lore-surface MVP ward #2.

ytb-LORE-MVP sub-task B (delta, 2026-04-24). Surfaces the active
Programme's role / density / active constraint hint / dwell so
livestream viewers can see the structural arc of the show without
needing the ward to narrate it.

Reads ``shared.programme_store.ProgrammePlanStore.active_programme()``
for the single current-active Programme (planner guarantees at most
one). Empty state: "[IDLE]" when no programme is active.

Rendered form:

    »»» [programme]
      role: SHOWCASE  density: DENSE
      package: bitchx-authentic-v1
      dwell: 00:12:34 / 00:20:00

Palette + typography resolve through the active HomagePackage, so the
authentic-asset swap (mIRC 16-colour via ytb-AUTH-PALETTE, Px437 via
ytb-AUTH1) lands without ward-code changes. Per the 2026-04-24
aesthetic-integration spec, role-type colours map:

    REPAIR      → accent_red
    SHOWCASE    → accent_yellow
    LISTENING   → accent_cyan
    RITUAL      → accent_magenta
    WIND_DOWN   → accent_blue
    others/IDLE → muted

Feature-flagged OFF by default via
``HAPAX_LORE_PROGRAMME_STATE_ENABLED=0``; operator flips after visual
sign-off on a live broadcast. Registered in ``cairo_sources.__init__``.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.homage_package import HomagePackage
from shared.programme import Programme, ProgrammeConstraintEnvelope
from shared.programme_store import ProgrammePlanStore

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

# Natural-size footprint; picked so four rows of 13-14 px text render
# without clipping at the operator's 1080p PiP sizes.
_DEFAULT_NATURAL_W: int = 360
_DEFAULT_NATURAL_H: int = 120

# Refresh cadence. Programme-state changes happen at programme
# boundaries — seconds to minutes — so 2 s is plenty and avoids
# re-reading the store on every 30 fps render.
_REFRESH_INTERVAL_S: float = 2.0

_FEATURE_FLAG_ENV: str = "HAPAX_LORE_PROGRAMME_STATE_ENABLED"

# ProgrammeRole.value → HomagePackage palette role. ``ProgrammeRole``
# is a ``StrEnum`` with lowercase values (see
# ``shared/programme.py::ProgrammeRole``), so keys are lowercase here.
# Roles not in the map → ``muted`` fallback via ``_role_palette_role``.
#
# HomagePalette canonical tokens (`shared/homage_package.ColourRoleName`)
# expose 6 named accent hues (cyan/magenta/green/yellow/red/blue) plus
# `bright` and `muted`. With 19 roles to colour, each segmented-content
# type still gets its own legible accent — some semantic overlap with
# operator-context roles (e.g. RANT shares accent_red with REPAIR;
# both signal high-energy intensity) is accepted because the ward
# header text already disambiguates the role; the accent is a
# secondary recognition signal, not the sole identifier.
_ROLE_PALETTE_ROLE: dict[str, str] = {
    # Operator-context roles (Phase 1)
    "repair": "accent_red",
    "showcase": "accent_yellow",
    "listening": "accent_cyan",
    "ritual": "accent_magenta",
    "wind_down": "accent_blue",
    # Segmented-content roles (operator outcome 2)
    "tier_list": "accent_blue",  # categorical / structured
    "top_10": "accent_yellow",  # countdown / reveal
    "rant": "accent_red",  # high-energy
    "react": "accent_green",  # responsive (unique — only canonical accent not used by op-context)
    "iceberg": "accent_cyan",  # depth / exploration
    "interview": "accent_magenta",  # dialogue
    "lecture": "bright",  # extended / structured discourse (uses the bright role)
}


def _feature_flag_enabled() -> bool:
    """Read ``HAPAX_LORE_PROGRAMME_STATE_ENABLED``. Default OFF."""
    raw = os.environ.get(_FEATURE_FLAG_ENV, "0")
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _fmt_hms(seconds: float) -> str:
    """Format ``seconds`` as ``HH:MM:SS`` clamped to non-negative."""
    x = max(0, int(seconds))
    return f"{x // 3600:02d}:{(x % 3600) // 60:02d}:{x % 60:02d}"


def _fmt_dwell(programme: Programme, now: float) -> str:
    """Render the dwell vs planned duration as ``HH:MM:SS / HH:MM:SS``."""
    started = programme.actual_started_at
    dwell = (now - started) if started is not None else 0.0
    return f"{_fmt_hms(dwell)} / {_fmt_hms(programme.planned_duration_s)}"


def _summarise_constraint(envelope: ProgrammeConstraintEnvelope) -> str:
    """Render one short line summarising the active constraint set.

    MVP surfacing order: homage package name first (the most legible
    aesthetic signal to a viewer), then monetization opt-ins prefixed
    with ``+`` (the explicit policy signal). Falls back to
    ``"(unconstrained)"`` when neither is set — never blank, so the
    row cadence stays stable.
    """
    parts: list[str] = []
    if envelope.homage_package:
        parts.append(str(envelope.homage_package))
    opt_ins = sorted(envelope.monetization_opt_ins)[:3]
    if opt_ins:
        parts.append(" ".join(f"+{x}" for x in opt_ins))
    return "  ".join(parts) if parts else "(unconstrained)"


def _fallback_package() -> HomagePackage:
    """Return the compiled-in BitchX package when registry resolution fails."""
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _bitchx_font_description(pkg: HomagePackage, size: int, *, bold: bool = False) -> str:
    """Build a Pango font-description string for the active package."""
    weight = " Bold" if bold else ""
    return f"{pkg.typography.primary_font_family}{weight} {int(size)}"


def _resolve(pkg: HomagePackage, role: str) -> tuple[float, float, float, float]:
    """Resolve a HomagePackage palette role with a muted fallback."""
    try:
        return pkg.resolve_colour(role)
    except Exception:
        log.debug("palette role %s unresolved on %s", role, pkg.id, exc_info=True)
        return pkg.resolve_colour("muted")


def _role_palette_role(role_value: str) -> str:
    """Map a ProgrammeRole value to a HomagePackage palette role name."""
    return _ROLE_PALETTE_ROLE.get(role_value, "muted")


class ProgrammeStateCairoSource(HomageTransitionalSource):
    """Four-row ward showing active Programme's role / density / package / dwell.

    Instantiated with an optional injected :class:`ProgrammePlanStore`
    to keep the class unit-testable — the default-constructed store
    hits the canonical path the daimonion + logos-api share, which
    tests must not pollute.
    """

    source_id: str = "programme_state"

    def __init__(self, store: ProgrammePlanStore | None = None) -> None:
        super().__init__(source_id=self.source_id)
        self._store = store if store is not None else ProgrammePlanStore()
        self._cached_programme: Programme | None = None
        # Initialise to -inf so the first _maybe_refresh() always fires
        # regardless of the wall-clock `now` the caller passes. Using
        # 0.0 meant "now=0.0" (valid in unit tests) never triggered the
        # initial refresh.
        self._last_refresh_ts: float = -float("inf")

    def _maybe_refresh(self, now: float) -> None:
        if now - self._last_refresh_ts < _REFRESH_INTERVAL_S:
            return
        try:
            self._cached_programme = self._store.active_programme()
        except Exception:
            log.debug("programme_state: store read failed", exc_info=True)
            self._cached_programme = None
        self._last_refresh_ts = now

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        if not _feature_flag_enabled():
            return

        now = time.time()
        self._maybe_refresh(now)

        # Late import so the module is still importable in CI harnesses
        # that lack Pango / PangoCairo typelibs.
        from agents.studio_compositor.text_render import (
            TextStyle,
            measure_text,
            render_text,
        )

        pkg = get_active_package() or _fallback_package()
        header_font = _bitchx_font_description(pkg, 14, bold=True)
        row_font = _bitchx_font_description(pkg, 13)

        chevron_role = _resolve(pkg, "accent_cyan")
        bracket_role = _resolve(pkg, "muted")
        muted_role = _resolve(pkg, "muted")
        content_role = _resolve(pkg, pkg.grammar.content_colour_role)

        # Header row: »»» [programme]
        chevron_style = TextStyle(
            text="»»» ",
            font_description=header_font,
            color_rgba=chevron_role,
        )
        cw, ch = measure_text(cr, chevron_style)
        render_text(cr, chevron_style, x=8.0, y=8.0)
        bracket_style = TextStyle(
            text="[programme]",
            font_description=header_font,
            color_rgba=bracket_role,
        )
        render_text(cr, bracket_style, x=8.0 + cw, y=8.0)

        line_height = 20.0
        row_y = 8.0 + max(ch, 14.0) + 6.0

        programme = self._cached_programme
        if programme is None:
            # Empty state — single "[IDLE]" row in muted; avoids the
            # strobe between "header only" and "fully populated".
            idle_style = TextStyle(
                text="  [IDLE]",
                font_description=row_font,
                color_rgba=muted_role,
            )
            render_text(cr, idle_style, x=8.0, y=row_y)
            return

        # Row 1: role + density
        role_value = programme.role.value
        role_colour = _resolve(pkg, _role_palette_role(role_value))
        density = programme.constraints.display_density
        density_str = density.value if density is not None else "?"

        label_role = TextStyle(
            text="  role: ",
            font_description=row_font,
            color_rgba=muted_role,
        )
        rw, _rh = measure_text(cr, label_role)
        render_text(cr, label_role, x=8.0, y=row_y)
        role_style = TextStyle(
            text=role_value,
            font_description=row_font,
            color_rgba=role_colour,
        )
        rv_w, _rv_h = measure_text(cr, role_style)
        render_text(cr, role_style, x=8.0 + rw, y=row_y)
        density_label = TextStyle(
            text="  density: ",
            font_description=row_font,
            color_rgba=muted_role,
        )
        dw, _dh = measure_text(cr, density_label)
        render_text(cr, density_label, x=8.0 + rw + rv_w, y=row_y)
        density_style = TextStyle(
            text=density_str,
            font_description=row_font,
            color_rgba=content_role,
        )
        render_text(cr, density_style, x=8.0 + rw + rv_w + dw, y=row_y)
        row_y += line_height

        # Row 2: constraint summary (homage package + opt-ins)
        constraint_label = TextStyle(
            text="  constraint: ",
            font_description=row_font,
            color_rgba=muted_role,
        )
        cl_w, _cl_h = measure_text(cr, constraint_label)
        render_text(cr, constraint_label, x=8.0, y=row_y)
        constraint_style = TextStyle(
            text=_summarise_constraint(programme.constraints),
            font_description=row_font,
            color_rgba=content_role,
        )
        render_text(cr, constraint_style, x=8.0 + cl_w, y=row_y)
        row_y += line_height

        # Row 3: dwell / planned
        dwell_label = TextStyle(
            text="  dwell: ",
            font_description=row_font,
            color_rgba=muted_role,
        )
        dl_w, _dl_h = measure_text(cr, dwell_label)
        render_text(cr, dwell_label, x=8.0, y=row_y)
        dwell_style = TextStyle(
            text=_fmt_dwell(programme, now),
            font_description=row_font,
            color_rgba=content_role,
        )
        render_text(cr, dwell_style, x=8.0 + dl_w, y=row_y)


__all__ = ["ProgrammeStateCairoSource"]
