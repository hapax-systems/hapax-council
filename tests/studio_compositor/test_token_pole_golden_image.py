"""Golden-image regression test for ``TokenPoleCairoSource``.

Closes AC-11 of the compositor source-registry completion epic — the
last outstanding acceptance criterion from the Phase 1 verification
report. Pins the token-pole visual output against a committed golden
PNG so unintended renders (colour shifts, spiral geometry drift,
background blit offset regressions) fail loud on CI before they hit
the livestream.

Register: the test renders into a deterministic cairo context with a
fixed random seed, a patched :mod:`time.monotonic`, and a non-existent
ledger file so no explosions spawn and no particles accumulate. Two
render ticks are issued so the pulse phase advances and the background
is painted. The resulting 300×300 ARGB surface is compared against
``golden_images/token_pole_natural_300x300.png`` at a maximum per-pixel
delta of 2 (one least-significant bit) per channel.

The Vitruvian background (``assets/vitruvian_man_overlay.png``, tracked
in the repo) is loaded through the shared image loader the same way
the live pipeline loads it. If the asset file or the GI stack is
missing the test is skipped — matching the pattern in
``tests/test_stream_overlay.py``.

**Updating the golden.** Set ``HAPAX_UPDATE_GOLDEN=1`` and re-run the
test to regenerate the committed PNG, then audit the diff before
committing. The env var gate prevents a regression from silently
rewriting the golden on a normal test run.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_GOLDEN_DIR = Path(__file__).parent / "golden_images"
_GOLDEN_PATH = _GOLDEN_DIR / "token_pole_natural_300x300.png"
_GOLDEN_WIDTH = 300
_GOLDEN_HEIGHT = 300
_GOLDEN_PIXEL_TOLERANCE = 2  # per channel


def _gi_available() -> bool:
    try:
        import gi

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


_HAS_GI = _gi_available()

requires_gi = pytest.mark.skipif(not _HAS_GI, reason="GI Pango/PangoCairo typelibs not installed")


def _update_golden_requested() -> bool:
    return os.environ.get("HAPAX_UPDATE_GOLDEN", "").strip() not in ("", "0", "false")


def _render_source_deterministically() -> Any:
    """Build a fresh source, tick it twice, return the cairo surface.

    State control:

    * ``LEDGER_FILE`` is patched to a non-existent path, so
      ``_read_ledger`` never advances position / spawns explosions.
    * ``random.seed(0)`` — even though the no-explosion path does not
      touch the particle spawner, seeding makes the test robust
      against future callers that add randomness on the main path.
    * ``time.monotonic`` is frozen at ``1_000_000.0`` seconds; the
      two ticks appear at the same timestamp so ``_last_read``
      debouncing suppresses any ledger re-read after the first miss.
    """
    import cairo

    from agents.studio_compositor import token_pole as tp

    random.seed(0)

    nonexistent_ledger = Path("/nonexistent/hapax-compositor/token-ledger.json")

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, _GOLDEN_WIDTH, _GOLDEN_HEIGHT)
    cr = cairo.Context(surface)

    with (
        patch.object(tp, "LEDGER_FILE", nonexistent_ledger),
        patch.object(tp.time, "monotonic", return_value=1_000_000.0),
    ):
        source = tp.TokenPoleCairoSource()
        # Two ticks: first paints the background + one pulse step, the
        # second advances the pulse another 0.1 so any pulse-driven
        # drift between ticks is captured in the golden.
        source.render(cr, _GOLDEN_WIDTH, _GOLDEN_HEIGHT, t=0.0, state={})
        source.render(cr, _GOLDEN_WIDTH, _GOLDEN_HEIGHT, t=0.033, state={})

    surface.flush()
    return surface


def _load_png(path: Path) -> Any:
    import cairo

    return cairo.ImageSurface.create_from_png(str(path))


def _surface_bytes_equal_within_tolerance(
    actual: Any,
    expected: Any,
    tolerance: int,
) -> tuple[bool, str]:
    """Return (ok, diagnostic) for a per-pixel tolerance comparison."""
    if actual.get_width() != expected.get_width():
        return False, (
            f"width mismatch: actual {actual.get_width()} vs expected {expected.get_width()}"
        )
    if actual.get_height() != expected.get_height():
        return False, (
            f"height mismatch: actual {actual.get_height()} vs expected {expected.get_height()}"
        )

    a_data = bytes(actual.get_data())
    e_data = bytes(expected.get_data())
    if len(a_data) != len(e_data):
        return False, f"byte-length mismatch: {len(a_data)} vs {len(e_data)}"

    max_delta = 0
    total_diff_pixels = 0
    for a_byte, e_byte in zip(a_data, e_data, strict=True):
        d = abs(a_byte - e_byte)
        if d > max_delta:
            max_delta = d
        if d > tolerance:
            total_diff_pixels += 1
    if max_delta > tolerance:
        return False, (
            f"max per-channel delta {max_delta} exceeds tolerance "
            f"{tolerance} ({total_diff_pixels} bytes over tolerance out "
            f"of {len(a_data)})"
        )
    return True, f"max delta {max_delta} within tolerance {tolerance}"


@requires_gi
def test_token_pole_natural_render_matches_golden() -> None:
    """Deterministic token-pole render matches the committed golden PNG.

    On golden miss the test fails with instructions. With
    ``HAPAX_UPDATE_GOLDEN=1`` the new PNG is written back to the
    tracked location and the test passes unconditionally so the
    contributor can inspect the diff before committing.
    """
    actual = _render_source_deterministically()

    if _update_golden_requested():
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        actual.write_to_png(str(_GOLDEN_PATH))
        return

    assert _GOLDEN_PATH.is_file(), (
        f"golden image missing at {_GOLDEN_PATH} — set "
        f"HAPAX_UPDATE_GOLDEN=1 and re-run this test to generate it, "
        f"then audit the PNG and commit alongside this test"
    )

    expected = _load_png(_GOLDEN_PATH)
    ok, diagnostic = _surface_bytes_equal_within_tolerance(
        actual, expected, _GOLDEN_PIXEL_TOLERANCE
    )
    assert ok, diagnostic


@requires_gi
def test_token_pole_natural_render_is_stable_across_two_runs() -> None:
    """Two back-to-back deterministic renders produce byte-identical output.

    Sanity check: before the golden comparison can be trusted, the
    deterministic render must itself be reproducible.
    """
    first = _render_source_deterministically()
    second = _render_source_deterministically()
    assert bytes(first.get_data()) == bytes(second.get_data())
