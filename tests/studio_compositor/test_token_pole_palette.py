"""Palette-swap regression for ``TokenPoleCairoSource``.

HOMAGE follow-on #125. Asserts that the token-pole's aesthetic surface
— identity ring, body, centre, cheeks, eyes and particle explosion —
all resolve colour through the active :class:`HomagePackage`'s
``palette``, not hardcoded RGBA. A stubbed package with distinctive
role colours is swapped in via ``monkeypatch`` and the rendered cells
are sampled: if any component ignores the palette, the sampled pixel
retains BitchX's mIRC-grey / bright-identity palette rather than the
stubbed hues and the test fails.

Geometry invariants (spiral centre, navel anchor, 250 points) stay
under ``test_token_pole_golden_image.py``. This file pins only the
palette-routing contract — the single aesthetic discipline introduced
by the #125 migration.
"""

from __future__ import annotations

import random
from pathlib import Path
from unittest.mock import patch

import cairo
import pytest

from agents.studio_compositor import token_pole as tp
from agents.studio_compositor.homage import BITCHX_PACKAGE

_SURFACE_SIZE = 300


def _distinctive_stub():
    """A fake HomagePackage with visibly distinctive role colours.

    Every load-bearing role used by the token-pole renderer maps to an
    obvious primary hue so the sampled pixel trivially identifies
    which role's RGBA was applied. ``resolve_colour()`` and
    ``palette.<role>`` both work — the renderer uses both surfaces.
    """

    class _StubPalette:
        # Role → RGBA designed so each component is visually traceable.
        muted = (0.20, 0.20, 0.20, 1.00)  # near-black
        bright = (1.00, 1.00, 1.00, 1.00)  # pure white
        accent_cyan = (0.00, 1.00, 1.00, 1.00)
        accent_magenta = (1.00, 0.00, 1.00, 1.00)  # pure magenta for ring
        accent_green = (0.00, 1.00, 0.00, 1.00)
        accent_yellow = (1.00, 1.00, 0.00, 1.00)  # pure yellow for body
        accent_red = (1.00, 0.00, 0.00, 1.00)
        accent_blue = (0.00, 0.00, 1.00, 1.00)
        terminal_default = (0.50, 0.50, 0.50, 1.00)
        background = (0.00, 0.00, 0.10, 1.00)  # dark blue, fully opaque

    class _StubPkg:
        name = "stub-token-pole"
        palette = _StubPalette()

        def resolve_colour(self, role):
            return getattr(self.palette, role)

    return _StubPkg()


def _render_surface(active_package_getter) -> cairo.ImageSurface:
    """Render one tick into a 300x300 ARGB32 surface.

    Patches ``time.monotonic``, the ledger path, and the package
    resolver so the render is deterministic and palette-scoped.

    Forces SPIRAL path mode regardless of the process-level
    ``HAPAX_TOKEN_POLE_PATH`` (task #186 default flipped to
    ``NAVEL_TO_CRANIUM``). The palette-routing contract this suite
    pins is path-agnostic, but the glyph-centre and trail assertions
    are coordinate-specific — they sample the spiral curve. Patching
    the path-mode resolver is lower-churn than rewriting every test
    to accept either coordinate system.
    """
    nonexistent_ledger = Path("/nonexistent/hapax-compositor/token-ledger.json")
    random.seed(0)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, _SURFACE_SIZE, _SURFACE_SIZE)
    cr = cairo.Context(surface)
    with (
        patch.object(tp, "LEDGER_FILE", nonexistent_ledger),
        patch.object(tp.time, "monotonic", return_value=1_000_000.0),
        patch.object(tp, "get_active_package", active_package_getter),
        patch.object(tp, "_resolve_path_mode", return_value=tp.PathMode.SPIRAL),
    ):
        source = tp.TokenPoleCairoSource()
        # Advance along the spiral so a trail + glyph exist to sample.
        source._target_position = 0.6
        source._position = 0.6
        source.render_content(cr, _SURFACE_SIZE, _SURFACE_SIZE, t=0.0, state={})
    surface.flush()
    return surface


def _sample(surface: cairo.ImageSurface, x: int, y: int) -> tuple[int, int, int, int]:
    """Return (B, G, R, A) for the pixel at ``(x, y)``.

    Cairo ``FORMAT_ARGB32`` is little-endian BGRA, premultiplied.
    """
    stride = surface.get_stride()
    data = surface.get_data()
    idx = y * stride + x * 4
    return (data[idx], data[idx + 1], data[idx + 2], data[idx + 3])


# -- Palette-substitution contract -----------------------------------------


class TestPaletteSwap:
    """Pin the #125 migration: every colour lookup flows through the
    active HomagePackage.

    Swap in a stub package with pure-primary roles; the rendered glyph
    centre must be near-white (``palette.bright``). Under the baseline
    BitchX package, the same samples must differ from the stubbed
    renders — confirming the stub actually takes effect and the
    palette routing is live.
    """

    def test_glyph_centre_uses_accent_yellow_role(self) -> None:
        """Phase A4 §1.2: centre dot is ``accent_yellow`` (stub: pure yellow).

        The HOMAGE emissive rewrite moved the centre to accent_yellow so
        the token reads as a point of light (yellow core + magenta halo)
        rather than a flat bright-identity target.
        """
        surface = _render_surface(lambda: _distinctive_stub())
        # The glyph centre sits at the spiral sample for pole_position=0.6.
        cx = _SURFACE_SIZE * tp.SPIRAL_CENTER_X
        cy = _SURFACE_SIZE * tp.SPIRAL_CENTER_Y
        max_r = _SURFACE_SIZE * tp.SPIRAL_MAX_R
        spiral = tp._build_spiral(cx, cy, max_r, tp.NUM_POINTS)
        idx = int(0.6 * (tp.NUM_POINTS - 1))
        gx, gy = spiral[idx]
        # Sample the glyph centre. Stub ``accent_yellow`` = pure yellow.
        b, g, r, _ = _sample(surface, int(gx), int(gy))
        assert r >= 180, f"centre R {r} - accent_yellow not applied"
        assert g >= 180, f"centre G {g} - accent_yellow not applied"
        assert b <= 100, f"centre B {b} - expected near-zero blue for yellow"

    # ytb-TOKEN-POLE-PALETTE-FOLLOWUP: ``test_background_uses_package_background``
    # was retired 2026-04-25 alongside this comment. The contract it pinned —
    # ``palette.background`` flat-fills the surface so corner pixels reflect the
    # active package's background role — was retired by the 2026-04-23 "zero
    # container opacity" directive. ``paint_emissive_bg`` is now a no-op
    # signature-preserving stub; corner pixels are dominated by the Vitruvian
    # PNG plus the multiply-tint pass (gray ~59, alpha ~119), so any non-zero-
    # rgba background role would fail the original ``r < 40`` assertion.
    #
    # The other two tests in this class (``test_glyph_centre_uses_accent_yellow_role``
    # + ``test_bitchx_baseline_is_distinct_from_stub``) keep the live palette-
    # routing contract pinned for the roles still wired through Cairo paint
    # paths.

    def test_bitchx_baseline_is_distinct_from_stub(self) -> None:
        """Under the real BitchX package the sample colours differ from
        the stub - confirms the palette routing is actually live and
        the stub swap isn't a no-op."""
        bitchx_surface = _render_surface(lambda: BITCHX_PACKAGE)
        stub_surface = _render_surface(lambda: _distinctive_stub())
        b_bytes = bytes(bitchx_surface.get_data())
        s_bytes = bytes(stub_surface.get_data())
        assert b_bytes != s_bytes, (
            "BitchX and stub packages produced identical renders - palette routing is not active"
        )


# -- Anti-regression: geometry constants stay pinned -----------------------


class TestGeometryInvariants:
    """Spec Preservation-Invariants - these constants must not drift."""

    def test_spiral_centre_navel(self) -> None:
        assert tp.SPIRAL_CENTER_X == 0.50
        assert tp.SPIRAL_CENTER_Y == 0.52

    def test_spiral_extent(self) -> None:
        assert tp.SPIRAL_MAX_R == 0.45
        assert tp.NUM_POINTS == 250

    def test_natural_size(self) -> None:
        assert tp.NATURAL_SIZE == 300

    def test_source_id(self) -> None:
        source = tp.TokenPoleCairoSource()
        assert source.source_id == "token_pole"


# -- Smoke: render doesn't crash under real BitchX package ------------------


def test_renders_under_bitchx_package_smoke() -> None:
    """End-to-end happy path: render a frame using the real registered
    ``BITCHX_PACKAGE`` and ensure the surface has non-zero content."""
    surface = _render_surface(lambda: BITCHX_PACKAGE)
    data = bytes(surface.get_data())
    assert any(byte != 0 for byte in data[:4096]), "BitchX render produced blank surface"


@pytest.mark.parametrize(
    "role",
    [
        "muted",
        "bright",
        "accent_cyan",
        "accent_magenta",
        "accent_yellow",
        "accent_red",
        "accent_green",
        "background",
    ],
)
def test_bitchx_defines_every_role_used(role: str) -> None:
    """The renderer reaches for these roles; the baseline package must
    define every one of them. Property-style guardrail against a future
    palette refactor that drops a role the token-pole depends on."""
    rgba = BITCHX_PACKAGE.resolve_colour(role)
    assert len(rgba) == 4
    assert all(0.0 <= c <= 1.0 for c in rgba)
