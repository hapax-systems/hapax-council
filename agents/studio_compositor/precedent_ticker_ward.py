"""Precedent-ticker Cairo source — BitchX axiom-precedent history ward.

Closes cc-task ``ward-precedent-ticker-bitchx`` (the
Enlightenment-GTK + BitchX HOMAGE Ward hybrid epic). Surfaces the
operator-ratified axiom precedent history as a slow-scrolling
ticker rendered in BitchX grammar:

    »»» [precedent]
      MM-DD  sp-su-001  T1  ✓compliant
      MM-DD  sp-su-004  T0  ✗violation
      MM-DD  sp-arch-001 T1  ✓compliant

The ticker is purely declarative — it shows the *most recent N
precedents* by ratification date, drawn from
``axioms/precedents/seed/*.yaml`` + ``axioms/precedents/*.yaml``.
Per memory ``feedback_show_dont_tell_director``, the ward does not
narrate compositor actions; it surfaces axiom case-law that already
exists.

Aesthetics flow through the active ``HomagePackage``
(``get_active_package()``) so the BitchX-authentic mIRC palette +
Px437 IBM VGA typography land via the homage swap, not via
hardcoded hex / font names. The HomageTransitionalSource base owns
the transition FSM; we only implement ``render_content()``.

Feature-flag OFF by default (``HAPAX_LORE_PRECEDENT_TICKER_ENABLED``)
so the operator can flip after live visual sign-off, mirroring the
chronicle-ticker rollout pattern.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.axiom_registry import AXIOMS_PATH, Precedent, _build_precedent
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

_DEFAULT_NATURAL_W: int = 460
_DEFAULT_NATURAL_H: int = 140

_MAX_ROWS: int = 3

# 0.5 Hz cadence per cc-task spec — the ward refreshes its precedent
# list at most once per 2 s. Precedent files mutate rarely (operator
# ratifies new ones manually), so 2 s is generous; the cap exists to
# keep the per-frame budget predictable.
_REFRESH_INTERVAL_S: float = 2.0

_FEATURE_FLAG_ENV: str = "HAPAX_LORE_PRECEDENT_TICKER_ENABLED"

# Decision glyph map — BitchX-grammar emphasis without inventing
# "vote tallies" the underlying schema doesn't carry. The check / x
# read at-a-glance and the colour role differentiates them by stance.
_DECISION_GLYPH: dict[str, str] = {
    "compliant": "✓",
    "non-compliant": "✗",
    "violation": "✗",
    "compliant-with-conditions": "≈",
}


@dataclass(frozen=True)
class _PrecedentRow:
    """One ticker row pre-rendering.

    Keeps text composition out of the render path so unit tests can
    assert structure without standing up Pango.
    """

    precedent_id: str
    created: str
    tier: str
    decision: str
    glyph: str


def _all_precedent_files(precedents_dir: Path) -> list[Path]:
    """Return every YAML under ``precedents/`` (seed + standalone).

    Sorted for deterministic discovery order; the precedents
    themselves carry an authoritative ``created`` date that drives
    the eventual ticker order.
    """

    if not precedents_dir.is_dir():
        return []
    files: list[Path] = []
    seed_dir = precedents_dir / "seed"
    if seed_dir.is_dir():
        files.extend(sorted(seed_dir.glob("*.yaml")))
    files.extend(sorted(precedents_dir.glob("*.yaml")))
    return files


def _load_all_precedents(precedents_dir: Path) -> list[Precedent]:
    """Load every precedent across all axioms and both file shapes.

    Mirrors :func:`shared.axiom_registry.load_precedents` minus the
    per-axiom filter. Malformed files are skipped silently — a single
    bad YAML must not silence the entire ticker.
    """

    out: list[Precedent] = []
    for f in _all_precedent_files(precedents_dir):
        try:
            data = yaml.safe_load(f.read_text())
        except Exception:
            log.debug("precedent file %s unreadable", f, exc_info=True)
            continue
        if not isinstance(data, dict):
            continue

        if "precedents" in data:
            parent_axiom_id = data.get("axiom_id", "")
            for entry in data.get("precedents") or []:
                if not isinstance(entry, dict) or "id" not in entry:
                    continue
                axiom_id = entry.get("axiom_id") or parent_axiom_id
                if not axiom_id:
                    continue
                try:
                    out.append(_build_precedent(entry, default_axiom_id=axiom_id))
                except Exception:
                    log.debug("precedent row malformed in %s", f, exc_info=True)
            continue

        if "precedent_id" in data:
            entry = dict(data)
            entry["id"] = entry.pop("precedent_id")
            try:
                out.append(_build_precedent(entry, default_axiom_id=entry.get("axiom_id", "")))
            except Exception:
                log.debug("standalone precedent malformed in %s", f, exc_info=True)
    return out


def _decision_glyph(decision: str) -> str:
    """Map a precedent decision to its BitchX-grammar glyph.

    Falls back to a neutral ``·`` for unknown decisions so the column
    keeps its width without lying about the stance.
    """

    return _DECISION_GLYPH.get(decision.strip().lower(), "·")


def _short_date(created: str) -> str:
    """Render an ISO-8601 ``YYYY-MM-DD`` as ``MM-DD`` for the ticker.

    Inputs without the expected shape pass through truncated to 5
    chars so the grid stays aligned even when an operator ratifies a
    precedent with an unusual date string.
    """

    if len(created) >= 10 and created[4] == "-" and created[7] == "-":
        return created[5:10]
    return created[:5]


def _row_for(precedent: Precedent) -> _PrecedentRow:
    """Build a `_PrecedentRow` from a Precedent."""

    return _PrecedentRow(
        precedent_id=precedent.id,
        created=_short_date(precedent.created),
        tier=precedent.tier or "—",
        decision=precedent.decision or "?",
        glyph=_decision_glyph(precedent.decision),
    )


def _collect_rows(precedents_dir: Path = AXIOMS_PATH / "precedents") -> list[_PrecedentRow]:
    """Return up to ``_MAX_ROWS`` precedents, newest ratification first.

    Stable secondary sort on precedent id keeps the rendered set
    deterministic when several precedents share a ``created`` date —
    important so the ticker doesn't strobe between equally-recent
    rows on each refresh.
    """

    precedents = _load_all_precedents(precedents_dir)
    if not precedents:
        return []
    precedents.sort(key=lambda p: (p.created, p.id), reverse=True)
    return [_row_for(p) for p in precedents[:_MAX_ROWS]]


def _feature_flag_enabled() -> bool:
    """Read ``HAPAX_LORE_PRECEDENT_TICKER_ENABLED``. Default OFF."""

    raw = os.environ.get(_FEATURE_FLAG_ENV, "0")
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _fallback_package() -> HomagePackage:
    """Compiled-in BitchX package when registry resolution fails."""

    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _bitchx_font_description(pkg: HomagePackage, size: int, *, bold: bool = False) -> str:
    """Build a Pango font-description string for the active package."""

    weight = " Bold" if bold else ""
    return f"{pkg.typography.primary_font_family}{weight} {int(size)}"


def _resolve(pkg: HomagePackage, role: str) -> tuple[float, float, float, float]:
    """Resolve a package palette role with a muted fallback.

    The chronicle-ticker reference uses the same pattern: fall back
    to ``muted`` so a missing role never crashes the render path.
    """

    try:
        return pkg.resolve_colour(role)
    except Exception:
        log.debug("palette role %s unresolved on %s", role, pkg.id, exc_info=True)
        return pkg.resolve_colour("muted")


class PrecedentTickerCairoSource(HomageTransitionalSource):
    """Three-row precedent-history ticker.

    Default natural size: 460×140. Composition:

        »»» [precedent]                             (header)
          MM-DD  sp-su-001  T1  ✓compliant         (per-row)
          MM-DD  sp-su-004  T0  ✗violation
          MM-DD  sp-arch-001 T1  ✓compliant

    No background, no border — same zero-container-opacity directive
    as the chronicle ticker. The chevron is the only emphasis; rest
    is colour-role differentiation (cyan id, default decision text,
    muted date/tier).
    """

    source_id: str = "precedent_ticker"

    def __init__(self) -> None:
        super().__init__(source_id=self.source_id)
        self._cached_rows: list[_PrecedentRow] = []
        self._last_refresh_ts: float = 0.0

    def _maybe_refresh(self, now: float) -> None:
        if now - self._last_refresh_ts >= _REFRESH_INTERVAL_S:
            self._cached_rows = _collect_rows()
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

        import time

        self._maybe_refresh(time.time())

        # Late import — keeps the module importable in CI harnesses
        # without Pango/PangoCairo typelibs.
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
        id_role = _resolve(pkg, "accent_cyan")
        decision_role = _resolve(pkg, pkg.grammar.content_colour_role)
        muted_role = _resolve(pkg, "muted")

        # Header row.
        chevron = TextStyle(
            text="»»» ",
            font_description=header_font,
            color_rgba=chevron_role,
        )
        cw, ch = measure_text(cr, chevron)
        render_text(cr, chevron, x=8.0, y=8.0)

        bracket = TextStyle(
            text="[precedent]",
            font_description=header_font,
            color_rgba=bracket_role,
        )
        render_text(cr, bracket, x=8.0 + cw, y=8.0)

        line_height = 20.0
        row_y = 8.0 + max(ch, 14.0) + 6.0

        for row in self._cached_rows[:_MAX_ROWS]:
            # Date column: muted.
            date_style = TextStyle(
                text=f"  {row.created}  ",
                font_description=row_font,
                color_rgba=muted_role,
            )
            dw, _dh = measure_text(cr, date_style)
            render_text(cr, date_style, x=8.0, y=row_y)

            # ID column: cyan emphasis.
            id_style = TextStyle(
                text=row.precedent_id,
                font_description=row_font,
                color_rgba=id_role,
            )
            iw, _ih = measure_text(cr, id_style)
            render_text(cr, id_style, x=8.0 + dw, y=row_y)

            # Tier column: muted.
            tier_style = TextStyle(
                text=f"  {row.tier}  ",
                font_description=row_font,
                color_rgba=muted_role,
            )
            tw, _th = measure_text(cr, tier_style)
            render_text(cr, tier_style, x=8.0 + dw + iw, y=row_y)

            # Decision: glyph + label in content-colour role.
            decision_style = TextStyle(
                text=f"{row.glyph}{row.decision}",
                font_description=row_font,
                color_rgba=decision_role,
            )
            render_text(cr, decision_style, x=8.0 + dw + iw + tw, y=row_y)

            row_y += line_height

        if not self._cached_rows:
            quiet = TextStyle(
                text="  (no precedents)",
                font_description=row_font,
                color_rgba=bracket_role,
            )
            render_text(cr, quiet, x=8.0, y=row_y)


__all__ = ["PrecedentTickerCairoSource"]
