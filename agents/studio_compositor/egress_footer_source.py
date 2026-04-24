"""Anti-personification egress footer ward — ef7b-165 Phase 9 Part 2.

Companion cairo surface for :mod:`shared.governance.egress_footer`.
Renders a persistent, low-prominence footer strip framing the channel
for advertiser review as a *research instrument* rather than an
agent. Intended placement: full-width strip at the bottom of the
1080p livestream frame (1920×30 default natural size).

Design:

* **Static text.** The footer string is composed once at construction
  from env vars (`HAPAX_OPERATOR_NAME`, `HAPAX_RESEARCH_HOME_URL`)
  with safe defaults, and cached for the life of the process.
* **Ring 2 validation.** Runs once on first render via the shared
  :func:`shared.governance.egress_footer.validate_footer_once`
  helper. A non-allowed verdict logs and switches the ward to the
  "withheld" empty state; the ward does not raise.
* **Muted.** Text renders at alpha ≤ 0.55 against zero background
  (no container), matching the 2026-04-23 "zero container opacity"
  directive. Uses the HOMAGE ``muted`` colour role so it always
  reads as chrome rather than content.
* **Feature-flagged OFF by default.** Flipped by the operator via
  ``HAPAX_EGRESS_FOOTER_ENABLED=1`` after visual sign-off on a live
  broadcast. Registered in ``cairo_sources.__init__`` so the ward is
  declarable in layout JSON before flip.

Not in scope this PR:

* Compositor ``default.json`` layout registration — operator decides
  when to flip.
* Startup-time validate call — the ward handles this lazily on first
  render.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.governance.egress_footer import (
    render_footer_text,
    validate_footer_once,
)
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

_FEATURE_FLAG_ENV: str = "HAPAX_EGRESS_FOOTER_ENABLED"

_DEFAULT_NATURAL_W: int = 1920
_DEFAULT_NATURAL_H: int = 30

#: Alpha ceiling for the text. Keeps the footer present but not
#: prominent — spec §Phase 9 requires ≤ 0.55.
_MUTED_ALPHA: float = 0.55


def _feature_flag_enabled() -> bool:
    return os.environ.get(_FEATURE_FLAG_ENV, "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _fallback_package() -> HomagePackage:
    """Return the compiled-in BitchX package when registry resolution fails.

    Matches :func:`chronicle_ticker._fallback_package` so the module stays
    importable in CI harnesses that don't boot the compositor far enough
    to load the active HomagePackage.
    """
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _bitchx_font_description(pkg: HomagePackage, size: int) -> str:
    return f"{pkg.typography.primary_font_family} {int(size)}"


def _resolve_muted(pkg: HomagePackage) -> tuple[float, float, float, float]:
    """Resolve HOMAGE ``muted`` colour role with the ward's alpha ceiling."""
    try:
        r, g, b, _ = pkg.resolve_colour("muted")
    except Exception:
        log.debug("muted role unresolved on %s", pkg.id, exc_info=True)
        r, g, b = 0.5, 0.5, 0.5
    return (r, g, b, _MUTED_ALPHA)


class EgressFooterCairoSource(HomageTransitionalSource):
    """Static anti-personification footer.

    Default natural size: 1920×30 px. Single line of muted BitchX-
    grammar text naming the channel as a research instrument plus
    operator + research-home URL from env.

    The text is validated exactly once via Ring 2 on first render.
    A failed validation flips ``_withheld`` to True and the ward
    renders empty thereafter — fail-closed on a classifier reject
    without raising into the compositor's render loop.
    """

    source_id: str = "egress_footer"

    def __init__(self) -> None:
        super().__init__(source_id=self.source_id)
        self._text: str = render_footer_text()
        self._validated: bool = False
        self._withheld: bool = False

    def _ensure_validated(self) -> None:
        if self._validated:
            return
        self._validated = True
        try:
            verdict = validate_footer_once(self._text)
        except Exception as exc:  # classifier unavailable → fail-closed
            log.warning(
                "egress footer Ring 2 validation raised %s; withholding footer",
                type(exc).__name__,
            )
            self._withheld = True
            return
        if not verdict.allowed:
            log.warning(
                "egress footer Ring 2 rejected (risk=%s); withholding footer",
                verdict.risk,
            )
            self._withheld = True

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
        self._ensure_validated()
        if self._withheld:
            return

        from agents.studio_compositor.text_render import TextStyle, render_text

        pkg = get_active_package() or _fallback_package()
        font = _bitchx_font_description(pkg, 14)
        colour = _resolve_muted(pkg)

        style = TextStyle(
            text=self._text,
            font_description=font,
            color_rgba=colour,
        )
        # Left-align with a small inset so the footer aligns with the
        # compositor's other BitchX chrome rows.
        render_text(cr, style, x=8.0, y=6.0)
