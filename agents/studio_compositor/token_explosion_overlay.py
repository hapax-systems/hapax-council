"""token_explosion_overlay.py — Full-frame human glyph explosion overlay.

Reads from ``token_pole._SHARED_PARTICLES`` (module-level shared list)
and renders the explosion particles at 1920×1080 frame resolution.
This is a separate CairoSource from the token pole so the explosion
can cover 2/3 of the broadcast frame without affecting the 300×300
Vitruvian Man canvas.

Registered in the compositor layout as a full-frame transparent overlay
at z_order=35 (above most wards, below egress footer).
"""

from __future__ import annotations

import logging
import math
import time
from typing import TYPE_CHECKING, Any

from .homage import get_active_package
from .homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    from shared.homage_package import HomagePackage

log = logging.getLogger(__name__)

RENDER_FPS = 30

# Explosion colour roles — same as token_pole.
_EXPLOSION_ROLES: tuple[str, ...] = (
    "bright",
    "accent_yellow",
    "accent_magenta",
    "accent_cyan",
    "terminal_default",
)


def _resolve_package() -> HomagePackage:
    """Return the active HomagePackage, or the BitchX fallback."""
    pkg = get_active_package()
    if pkg is not None:
        return pkg
    from .homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


class TokenExplosionOverlayCairoSource(HomageTransitionalSource):
    """Full-frame transparent overlay that renders human glyph explosions.

    Reads particles from ``token_pole._SHARED_PARTICLES``. When no
    particles are active, the surface is fully transparent (no-op).
    Rendering uses Pango for Unicode glyph support with emissive halos.
    """

    def __init__(self) -> None:
        super().__init__(source_id="token_explosion_overlay")

    def render_content(self, cr: Any, w: int, h: int, t: float, state: dict) -> None:
        """Called by the CairoSourceRunner at RENDER_FPS."""
        from .token_pole import _SHARED_PARTICLES

        if not _SHARED_PARTICLES:
            return

        pkg = _resolve_package()

        self._draw_glyph_particles(cr, pkg, _SHARED_PARTICLES)

    def _draw_glyph_particles(self, cr: Any, pkg: Any, particles: list) -> None:
        """Render human glyph explosion particles via Pango."""
        if not particles:
            return

        t_now = time.monotonic()

        try:
            import gi

            gi.require_version("Pango", "1.0")
            gi.require_version("PangoCairo", "1.0")
            from gi.repository import Pango, PangoCairo
        except Exception:
            # Fallback: render as emissive dots only.
            from .homage.emissive_base import paint_emissive_point

            for p in particles:
                role = _EXPLOSION_ROLES[p.role_index]
                pr, pg, pb, pa = pkg.resolve_colour(role)
                paint_emissive_point(
                    cr,
                    p.x,
                    p.y,
                    (pr, pg, pb, pa * p.alpha),
                    t=t_now,
                    phase=p.born % math.tau,
                    baseline_alpha=1.0,
                    centre_radius_px=max(1.0, p.size * 0.3),
                    halo_radius_px=max(2.0, p.size * 0.6),
                    outer_glow_radius_px=max(3.0, p.size * 0.9),
                    shimmer_hz=1.0,
                )
            return

        from .homage.emissive_base import paint_emissive_point

        for p in particles:
            role = _EXPLOSION_ROLES[p.role_index % len(_EXPLOSION_ROLES)]
            pr, pg, pb, pa = pkg.resolve_colour(role)
            glyph_alpha = p.alpha

            # Emissive halo under the glyph.
            paint_emissive_point(
                cr,
                p.x,
                p.y,
                (pr, pg, pb, pa * glyph_alpha * 0.5),
                t=t_now,
                phase=p.born % math.tau,
                baseline_alpha=1.0,
                centre_radius_px=0.0,
                halo_radius_px=max(2.0, p.size * 0.4),
                outer_glow_radius_px=max(4.0, p.size * 0.8),
                shimmer_hz=1.0,
            )

            # Pango glyph with rotation.
            cr.save()
            cr.translate(p.x, p.y)
            cr.rotate(p.rotation)
            layout = PangoCairo.create_layout(cr)
            font = Pango.FontDescription.from_string(f"Noto Color Emoji {int(p.size)}")
            layout.set_font_description(font)
            layout.set_text(p.glyph, -1)
            _w, _h = layout.get_pixel_size()
            cr.move_to(-_w / 2.0, -_h / 2.0)
            cr.push_group()
            PangoCairo.show_layout(cr, layout)
            cr.pop_group_to_source()
            cr.paint_with_alpha(glyph_alpha)
            cr.restore()
