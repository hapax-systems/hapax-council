"""2026-04-23 operator directive: all ward containers have zero opacity.

Visibility must come from text size + font weight + outline contrast
alone. Splattribution (``album_overlay._draw_attrib``) is the positive
reference — text + outline, no background rectangles, no borders.

This test pins that the five shared chrome primitives are no-ops: they
must not call ``cr.rectangle(...) / cr.fill() / cr.stroke()``. If any
future change re-introduces background fills or border strokes through
these primitives, this test fails.

Primitives neutralized:

- ``homage/rendering.py::paint_bitchx_bg`` — gradient/flat bg + accent bar + border
- ``homage/rendering.py::paint_emphasis_border`` — outer glow halo + inner border
- ``homage/emissive_base.py::paint_emissive_bg`` — flat ground fill
- ``ward_properties.py::_paint_emissive_glow`` — four-edge perimeter gradient
- ``ward_properties.py::_paint_border_pulse`` — rectangular outline stroke

Runtime guarantee: calling each with a recording ``MagicMock`` cairo
context produces zero ``fill()`` or ``stroke()`` or ``rectangle()``
calls. Source guarantee: the primitive function bodies contain no
``cr.fill()`` / ``cr.stroke()`` / ``cr.rectangle(...)`` text — only
the vestigial-param sink ``_ = (...)``.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

from agents.studio_compositor.homage.emissive_base import paint_emissive_bg
from agents.studio_compositor.homage.rendering import (
    paint_bitchx_bg,
    paint_emphasis_border,
)
from agents.studio_compositor.ward_properties import (
    _paint_border_pulse,
    _paint_emissive_glow,
)

_REPO_ROOT = Path(__file__).parents[2]
_RENDERING = _REPO_ROOT / "agents" / "studio_compositor" / "homage" / "rendering.py"
_EMISSIVE_BASE = _REPO_ROOT / "agents" / "studio_compositor" / "homage" / "emissive_base.py"
_WARD_PROPERTIES = _REPO_ROOT / "agents" / "studio_compositor" / "ward_properties.py"


def _pkg_stub() -> MagicMock:
    pkg = MagicMock()
    pkg.resolve_colour = MagicMock(return_value=(0.5, 0.5, 0.5, 1.0))
    return pkg


def test_paint_bitchx_bg_draws_nothing() -> None:
    cr = MagicMock()
    paint_bitchx_bg(cr, 100.0, 50.0, _pkg_stub(), ward_id="activity_header")
    assert not cr.fill.called, "paint_bitchx_bg emitted cr.fill() — chrome leaked"
    assert not cr.stroke.called, "paint_bitchx_bg emitted cr.stroke() — chrome leaked"
    assert not cr.rectangle.called, "paint_bitchx_bg emitted cr.rectangle() — chrome leaked"


def test_paint_bitchx_bg_no_ward_id_draws_nothing() -> None:
    cr = MagicMock()
    paint_bitchx_bg(cr, 100.0, 50.0, _pkg_stub())
    assert not cr.fill.called
    assert not cr.stroke.called
    assert not cr.rectangle.called


def test_paint_bitchx_bg_with_border_draws_nothing() -> None:
    cr = MagicMock()
    paint_bitchx_bg(cr, 100.0, 50.0, _pkg_stub(), border_rgba=(1.0, 1.0, 1.0, 1.0), ward_id="foo")
    assert not cr.fill.called
    assert not cr.stroke.called


def test_paint_emphasis_border_draws_nothing() -> None:
    cr = MagicMock()
    paint_emphasis_border(cr, 100.0, 50.0, _pkg_stub(), ward_id="token_pole", t=0.0)
    assert not cr.fill.called, "paint_emphasis_border emitted cr.fill() — chrome leaked"
    assert not cr.stroke.called, "paint_emphasis_border emitted cr.stroke() — chrome leaked"
    assert not cr.rectangle.called


def test_paint_emissive_bg_draws_nothing() -> None:
    cr = MagicMock()
    paint_emissive_bg(cr, 100.0, 50.0)
    assert not cr.fill.called, "paint_emissive_bg emitted cr.fill() — chrome leaked"
    assert not cr.stroke.called
    assert not cr.rectangle.called


def test_paint_emissive_glow_draws_nothing() -> None:
    cr = MagicMock()
    _paint_emissive_glow(cr, 100.0, 50.0, 8.0, (1.0, 1.0, 1.0, 1.0))
    assert not cr.fill.called, "_paint_emissive_glow emitted cr.fill() — chrome leaked"
    assert not cr.stroke.called
    assert not cr.rectangle.called


def test_paint_border_pulse_draws_nothing() -> None:
    cr = MagicMock()
    _paint_border_pulse(cr, 100.0, 50.0, 2.0, (1.0, 1.0, 1.0, 1.0))
    assert not cr.stroke.called, "_paint_border_pulse emitted cr.stroke() — chrome leaked"
    assert not cr.fill.called
    assert not cr.rectangle.called


# ── Source scan — reject any re-introduction of chrome calls in the function bodies ─


_CHROME_CALL = re.compile(r"cr\.(rectangle|fill|stroke|paint|paint_with_alpha)\s*\(")


def _extract_fn_body(src: str, fn_name: str) -> str:
    """Return text from ``def fn_name(...)`` through the next top-level ``def``/``class``/EOF."""
    start = re.search(rf"^def {re.escape(fn_name)}\b", src, re.MULTILINE)
    if start is None:
        raise AssertionError(f"function {fn_name!r} not found in source")
    after = src[start.start() :]
    nxt = re.search(r"^(?:def |class )", after[1:], re.MULTILINE)
    return after if nxt is None else after[: nxt.start() + 1]


def test_rendering_primitives_source_clean() -> None:
    src = _RENDERING.read_text()
    for fn in ("paint_bitchx_bg", "paint_emphasis_border"):
        body = _extract_fn_body(src, fn)
        hits = _CHROME_CALL.findall(body)
        assert not hits, (
            f"{fn} re-introduces chrome calls: {hits}. "
            f"Per 2026-04-23 directive, this primitive must be a no-op."
        )


def test_emissive_bg_source_clean() -> None:
    src = _EMISSIVE_BASE.read_text()
    body = _extract_fn_body(src, "paint_emissive_bg")
    hits = _CHROME_CALL.findall(body)
    assert not hits, f"paint_emissive_bg re-introduces chrome calls: {hits}"


def test_ward_properties_primitives_source_clean() -> None:
    src = _WARD_PROPERTIES.read_text()
    for fn in ("_paint_emissive_glow", "_paint_border_pulse"):
        body = _extract_fn_body(src, fn)
        hits = _CHROME_CALL.findall(body)
        assert not hits, (
            f"{fn} re-introduces chrome calls: {hits}. "
            f"Per 2026-04-23 directive, this primitive must be a no-op."
        )
