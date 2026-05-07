"""Phase C3 — comprehensive visual-regression golden suite for HOMAGE.

Consolidates the wave-2 goldens from Phases A2/A3/A4 and extends the
coverage to a full ``16 wards x {emphasis-off, emphasis-on}`` matrix —
32 golden images in total. The runner loads each ward, renders at a
deterministic ``t=0.0`` into a fresh Cairo ImageSurface, and compares
against the committed golden with a per-channel tolerance of ±4
(±6 for emphasis-on variants where the pulse-driven stroke width
straddles a sub-pixel boundary).

On failure the runner emits a side-by-side diff PNG under
``/tmp/homage-visual-regression-diffs/`` so the CI artifacts step can
pick it up.

Regenerate goldens with :envvar:`HAPAX_UPDATE_GOLDEN`:

.. code-block:: bash

    HAPAX_UPDATE_GOLDEN=1 \\
      uv run pytest tests/studio_compositor/test_visual_regression_homage.py -q

Goldens live under ``tests/studio_compositor/golden_images/`` and
``tests/studio_compositor/golden_images/emphasis/``; both directories
are globally gitignored, so the commit must ``git add -f`` the PNGs.

Phase C3 of :doc:`docs/superpowers/plans/2026-04-19-homage-completion-plan`.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ── Cairo / GI capability gates ─────────────────────────────────────────


def _cairo_available() -> bool:
    try:
        import cairo  # noqa: F401
    except ImportError:
        return False
    return True


def _gi_available() -> bool:
    try:
        import gi

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


_HAS_CAIRO = _cairo_available()
_HAS_GI = _gi_available()

requires_cairo_and_gi = pytest.mark.skipif(
    not (_HAS_CAIRO and _HAS_GI),
    reason="pycairo + Pango/PangoCairo typelibs required",
)


def _homage_goldens_marked_stale() -> bool:
    """Opt-in CI skip when the operator knows the golden bank has drifted.

    Set ``HAPAX_HOMAGE_GOLDENS_STALE=1`` to skip the entire suite while a
    refresh is pending — useful when an upstream change (e.g. dataclass
    default flips that propagate into ward chrome) invalidates the
    committed PNGs but the operator hasn't yet had a chance to regenerate
    them with ``HAPAX_UPDATE_GOLDEN=1`` and re-commit. Default: unset →
    tests run as normal so a regression that wasn't operator-acknowledged
    is loud.
    """
    return os.environ.get("HAPAX_HOMAGE_GOLDENS_STALE", "").strip() not in (
        "",
        "0",
        "false",
    )


goldens_acknowledged_stale = pytest.mark.skipif(
    _homage_goldens_marked_stale(),
    reason=(
        "operator marked the homage golden bank as stale via "
        "HAPAX_HOMAGE_GOLDENS_STALE — refresh pending. Unset to run "
        "the suite again."
    ),
)


# ── Paths / tolerances ──────────────────────────────────────────────────

_GOLDEN_DIR = Path(__file__).parent / "golden_images"
_EMPHASIS_DIR = _GOLDEN_DIR / "emphasis"
_DIFF_DIR = Path("/tmp/homage-visual-regression-diffs")

# Per-channel tolerance. Emissive wards pass at 4; Pango-rendered wards
# (captions, chat, stream_overlay, research_marker, album, activity_header,
# grounding_ticker) sometimes drift a couple of bytes across fontconfig
# caches, so we track them on a byte-over-budget ratio rather than a raw
# max-delta — same shape used by the wave-2 content goldens.
_BASE_TOLERANCE = 4
_EMPHASIS_TOLERANCE = 6
# When > 0.0 we use the loose ratio-based comparator. Individual cases can
# escalate via ``loose=True``.
_LOOSE_BYTE_OVER_BUDGET = 0.03


def _update_golden_requested() -> bool:
    return os.environ.get("HAPAX_UPDATE_GOLDEN", "").strip() not in ("", "0", "false")


# ── Ward inventory ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class WardCase:
    """One entry in the 16-ward x 2-state matrix."""

    ward_id: str
    size: tuple[int, int]
    # When True, the comparator uses the byte-over-budget ratio instead
    # of a strict max-delta — required for wards whose text paths go
    # through Pango.
    loose: bool = False


_WARDS: list[WardCase] = [
    WardCase("token_pole", (300, 300), loose=True),
    # HARDM retired 2026-04-23 (GEAL spec §12) — visual regression case
    # removed; GEAL visual goldens ship in Phase 1 (plan Task 1.6).
    WardCase("album_overlay", (300, 450), loose=True),
    WardCase("captions", (1280, 80), loose=True),
    WardCase("chat_ambient", (800, 120), loose=True),
    WardCase("stance_indicator", (100, 40), loose=True),
    WardCase("activity_header", (800, 56), loose=True),
    WardCase("grounding_provenance_ticker", (480, 40), loose=True),
    WardCase("impingement_cascade", (480, 360), loose=False),
    WardCase("recruitment_candidate_panel", (800, 60), loose=True),
    WardCase("thinking_indicator", (170, 44), loose=True),
    WardCase("pressure_gauge", (300, 52), loose=True),
    WardCase("activity_variety_log", (400, 140), loose=True),
    WardCase("whos_here", (230, 46), loose=True),
    WardCase("stream_overlay", (400, 200), loose=True),
    WardCase("research_marker_overlay", (1280, 64), loose=True),
]


def _ward_by_id(ward_id: str) -> WardCase:
    for w in _WARDS:
        if w.ward_id == ward_id:
            return w
    raise KeyError(ward_id)


# ── Emphasis envelope ───────────────────────────────────────────────────


def _emphasis_properties(base_props_cls: Any) -> Any:
    """Return a ``WardProperties`` with the B1 emphasis envelope.

    Matches the envelope the structural-intent fan-out writes:

    - ``glow_radius_px = 14``
    - ``border_pulse_hz = 2.0``
    - ``border_color_rgba = (0.514, 0.647, 0.596, 1.0)``  (Gruvbox
      accent-cyan; deterministic so the golden is stable regardless of
      the active package)
    - ``alpha = 1.0``
    """
    return base_props_cls(
        alpha=1.0,
        glow_radius_px=14.0,
        border_pulse_hz=2.0,
        border_color_rgba=(0.514, 0.647, 0.596, 1.0),
    )


# ── Ward builders ───────────────────────────────────────────────────────
# Each builder returns ``(source_instance, render_ctx)`` where
# ``render_ctx`` is a context manager stacking the mocks/patches needed
# to make the render deterministic at ``t=0.0``.


def _build_token_pole() -> Any:
    from agents.studio_compositor import token_pole as tp

    src = tp.TokenPoleCairoSource()
    return src


def _build_album_overlay() -> Any:
    from agents.studio_compositor.album_overlay import AlbumOverlayCairoSource

    return AlbumOverlayCairoSource()


def _build_captions() -> Any:
    from agents.studio_compositor.captions_source import CaptionsCairoSource

    # Pin a non-existent caption path so the render path is deterministic.
    return CaptionsCairoSource(caption_path=Path("/nonexistent/hapax/caption.txt"))


def _build_chat_ambient() -> Any:
    from agents.studio_compositor.chat_ambient_ward import ChatAmbientWard

    # Deterministic counter state — not empty so the BitchX grammar paints.
    return ChatAmbientWard(
        initial_counters={
            "unique_t4_plus_authors_60s": 3,
            "t4_plus_rate_per_min": 2.0,
            "t5_rate_per_min": 1.0,
            "t6_rate_per_min": 0.4,
            "audience_engagement": 0.5,
        }
    )


def _build_stance_indicator() -> Any:
    from agents.studio_compositor.legibility_sources import StanceIndicatorCairoSource

    return StanceIndicatorCairoSource()


def _build_activity_header() -> Any:
    from agents.studio_compositor.legibility_sources import ActivityHeaderCairoSource

    return ActivityHeaderCairoSource()


def _build_grounding_ticker() -> Any:
    from agents.studio_compositor.legibility_sources import (
        GroundingProvenanceTickerCairoSource,
    )

    return GroundingProvenanceTickerCairoSource()


def _build_impingement() -> Any:
    from agents.studio_compositor.hothouse_sources import ImpingementCascadeCairoSource

    return ImpingementCascadeCairoSource()


def _build_recruitment_panel() -> Any:
    from agents.studio_compositor.hothouse_sources import RecruitmentCandidatePanelCairoSource

    return RecruitmentCandidatePanelCairoSource()


def _build_thinking_indicator() -> Any:
    from agents.studio_compositor.hothouse_sources import ThinkingIndicatorCairoSource

    return ThinkingIndicatorCairoSource()


def _build_pressure_gauge() -> Any:
    from agents.studio_compositor.hothouse_sources import PressureGaugeCairoSource

    return PressureGaugeCairoSource()


def _build_activity_variety_log() -> Any:
    from agents.studio_compositor.hothouse_sources import ActivityVarietyLogCairoSource

    return ActivityVarietyLogCairoSource()


def _build_whos_here() -> Any:
    from agents.studio_compositor.hothouse_sources import WhosHereCairoSource

    return WhosHereCairoSource()


def _build_stream_overlay() -> Any:
    from agents.studio_compositor.stream_overlay import StreamOverlayCairoSource

    return StreamOverlayCairoSource()


def _build_research_marker() -> Any:
    from datetime import UTC, datetime

    from agents.studio_compositor.research_marker_overlay import ResearchMarkerOverlay

    # Freeze "now" so the ward paints its banner deterministically.
    frozen_now = datetime(2026, 4, 19, 0, 0, 0, tzinfo=UTC)
    return ResearchMarkerOverlay(
        marker_path=Path("/nonexistent/hapax/research-marker.json"),
        now_fn=lambda: frozen_now,
    )


_BUILDERS: dict[str, Callable[[], Any]] = {
    "token_pole": _build_token_pole,
    "album_overlay": _build_album_overlay,
    "captions": _build_captions,
    "chat_ambient": _build_chat_ambient,
    "stance_indicator": _build_stance_indicator,
    "activity_header": _build_activity_header,
    "grounding_provenance_ticker": _build_grounding_ticker,
    "impingement_cascade": _build_impingement,
    "recruitment_candidate_panel": _build_recruitment_panel,
    "thinking_indicator": _build_thinking_indicator,
    "pressure_gauge": _build_pressure_gauge,
    "activity_variety_log": _build_activity_variety_log,
    "whos_here": _build_whos_here,
    "stream_overlay": _build_stream_overlay,
    "research_marker_overlay": _build_research_marker,
}


# ── Render helper ───────────────────────────────────────────────────────


def _make_surface(w: int, h: int) -> Any:
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    return surface


def _render_ward_deterministic(
    ward_id: str,
    *,
    emphasis: bool,
) -> Any:
    """Render the named ward into a fresh ARGB32 surface.

    All state that would make the render non-deterministic (SHM files,
    wall clock, monotonic clock, ``ward_properties.json``) is patched
    out. When ``emphasis`` is False the ward's ``resolve_ward_properties``
    returns the default no-op dataclass; when True it returns the B1
    emphasis envelope so :func:`paint_emphasis_border` paints a glow.
    """
    import cairo

    from agents.studio_compositor import homage  # noqa: F401
    from agents.studio_compositor import hothouse_sources as hs
    from agents.studio_compositor import legibility_sources as ls
    from agents.studio_compositor import token_pole as tp
    from agents.studio_compositor import ward_properties as wp
    from agents.studio_compositor.homage import rendering as homage_rendering

    case = _ward_by_id(ward_id)
    w, h = case.size
    surface = _make_surface(w, h)
    cr = cairo.Context(surface)

    base_props = _emphasis_properties(wp.WardProperties) if emphasis else wp.WardProperties()

    def _fake_resolve(_ward_id: str) -> Any:
        return base_props

    nonexistent_ledger = Path("/nonexistent/hapax-compositor/token-ledger.json")
    nonexistent_shm = Path("/nonexistent/hapax/shm")

    # Freeze the legibility-source state readers so the render is
    # content-deterministic (so e.g. ``_activity_flash_started_at``
    # doesn't trigger on a real narrative-state file being present).
    legibility_patches = [
        patch.object(
            ls,
            "_read_narrative_state",
            return_value={"activity": "rendering", "stance": "nominal"},
        ),
        patch.object(
            ls,
            "_read_latest_intent",
            return_value={
                "compositional_impingements": [{"narrative": "stimmung settling", "salience": 0.8}],
                "grounding_provenance": ["chat", "stimmung"],
            },
        ),
        patch.object(ls, "_read_rotation_mode", return_value=None),
    ]

    from agents.studio_compositor import album_overlay as ao
    from agents.studio_compositor import stream_overlay as so

    hothouse_patches = [
        patch.object(hs, "_PERCEPTION_STATE", nonexistent_shm / "perception.json"),
        patch.object(hs, "_STIMMUNG_STATE", nonexistent_shm / "stimmung.json"),
        patch.object(hs, "_LLM_IN_FLIGHT", nonexistent_shm / "inflight.json"),
        patch.object(hs, "_DIRECTOR_INTENT_JSONL", nonexistent_shm / "intents.jsonl"),
        patch.object(hs, "_PRESENCE_STATE", nonexistent_shm / "presence.json"),
        patch.object(hs, "_RECENT_RECRUITMENT", nonexistent_shm / "recent-recruitment.json"),
        patch.object(hs, "_YOUTUBE_VIEWER_COUNT", nonexistent_shm / "youtube-viewer-count.txt"),
        # FINDING-V Phase 6 (aa010c9c9) added _RECENT_IMPINGEMENTS for
        # the cascade overlay; without this isolation the impingement
        # cascade renderer reads the live producer's output and the
        # visual regression drifts.
        patch.object(hs, "_RECENT_IMPINGEMENTS", nonexistent_shm / "recent-impingements.json"),
        # Album overlay reads /dev/shm/hapax-compositor/album-cover.png
        # and music-attribution.txt; the live compositor writes album
        # covers there from streaming music ID. Isolate so the golden
        # render is content-deterministic against the empty-state
        # placeholder rather than whatever album is currently playing.
        patch.object(ao, "COVER_PATH", str(nonexistent_shm / "album-cover.png")),
        patch.object(ao, "ATTRIB_PATH", str(nonexistent_shm / "music-attribution.txt")),
        # Stream overlay reads fx-current, token-ledger, chat-state.
        patch.object(so, "FX_CURRENT_FILE", nonexistent_shm / "fx-current.txt"),
        patch.object(so, "TOKEN_LEDGER_FILE", nonexistent_shm / "token-ledger.json"),
        patch.object(so, "CHAT_STATE_FILE", nonexistent_shm / "chat-state.json"),
    ]

    base_patches = [
        patch.dict(os.environ, {"HAPAX_HOMAGE_ACTIVE": "0"}),
        patch.object(wp, "resolve_ward_properties", _fake_resolve),
        patch.object(tp, "LEDGER_FILE", nonexistent_ledger),
        patch.object(tp.time, "monotonic", return_value=1_000_000.0),
        patch.object(time, "monotonic", return_value=1_000_000.0),
    ]
    # Keep the homage rendering import anchored so the patch on
    # resolve_ward_properties reaches the border painter.
    _ = homage_rendering

    source = _BUILDERS[ward_id]()

    with contextlib.ExitStack() as stack:
        for cm in base_patches + legibility_patches + hothouse_patches:
            stack.enter_context(cm)
        # Two ticks — same timestamp — so any in-source latch settles.
        source.render(cr, w, h, 0.0, {})
        source.render(cr, w, h, 0.0, {})

    surface.flush()
    return surface


# ── Comparator + diff emitter ───────────────────────────────────────────


def _surfaces_match(
    actual: Any,
    expected: Any,
    *,
    tolerance: int,
    byte_over_budget: float,
    loose: bool,
) -> tuple[bool, str, int, int]:
    """Compare two ARGB32 surfaces with per-channel tolerance.

    Returns ``(ok, diagnostic, max_delta, n_over)``. When ``loose`` is
    True the comparator tolerates up to ``byte_over_budget`` fraction of
    bytes exceeding ``tolerance``; otherwise any single byte over the
    tolerance fails.
    """
    if actual.get_width() != expected.get_width():
        return (
            False,
            f"width {actual.get_width()} != {expected.get_width()}",
            0,
            0,
        )
    if actual.get_height() != expected.get_height():
        return (
            False,
            f"height {actual.get_height()} != {expected.get_height()}",
            0,
            0,
        )
    a = bytes(actual.get_data())
    e = bytes(expected.get_data())
    if len(a) != len(e):
        return False, f"byte-len {len(a)} != {len(e)}", 0, 0
    max_delta = 0
    n_over = 0
    for ab, eb in zip(a, e, strict=True):
        d = abs(ab - eb)
        if d > max_delta:
            max_delta = d
        if d > tolerance:
            n_over += 1
    if loose:
        ratio = n_over / max(1, len(a))
        if ratio <= byte_over_budget:
            return (
                True,
                f"max delta {max_delta}; {n_over}/{len(a)} over tol "
                f"({ratio:.3%} within {byte_over_budget:.1%})",
                max_delta,
                n_over,
            )
        return (
            False,
            f"loose: {n_over}/{len(a)} ({ratio:.3%}) exceed tol {tolerance}, "
            f"budget {byte_over_budget:.1%}; max delta {max_delta}",
            max_delta,
            n_over,
        )
    if max_delta > tolerance:
        return (
            False,
            f"strict: max delta {max_delta} > tol {tolerance} ({n_over} bytes over)",
            max_delta,
            n_over,
        )
    return (
        True,
        f"max delta {max_delta} within tol {tolerance}",
        max_delta,
        n_over,
    )


def _emit_diff(
    ward_id: str,
    state: str,
    actual: Any,
    expected: Any,
) -> Path | None:
    """Write a side-by-side ``actual | expected | diff`` PNG.

    Returns the written path, or ``None`` if diff generation itself
    failed (we never want the diff step to mask the original failure).
    """
    import cairo

    try:
        _DIFF_DIR.mkdir(parents=True, exist_ok=True)
        w = actual.get_width()
        h = actual.get_height()
        gap = 8
        out_w = w * 3 + gap * 2
        out_h = h
        out = cairo.ImageSurface(cairo.FORMAT_ARGB32, out_w, out_h)
        cr = cairo.Context(out)
        # Gruvbox bg0 ground so transparent areas are visible.
        cr.set_source_rgba(0.114, 0.125, 0.129, 1.0)
        cr.paint()
        cr.set_source_surface(actual, 0, 0)
        cr.paint()
        cr.set_source_surface(expected, w + gap, 0)
        cr.paint()
        # Diff panel: per-byte absolute difference magnified to fill 8 bits.
        a = bytearray(bytes(actual.get_data()))
        e = bytes(expected.get_data())
        diff = bytearray(len(a))
        for i, (ab, eb) in enumerate(zip(a, e, strict=True)):
            d = abs(ab - eb)
            # Amplify x8 and clamp so even single-byte deltas are visible.
            diff[i] = min(255, d * 8)
        diff_surface = cairo.ImageSurface.create_for_data(
            diff, cairo.FORMAT_ARGB32, w, h, actual.get_stride()
        )
        cr.set_source_surface(diff_surface, 2 * (w + gap), 0)
        cr.paint()
        path = _DIFF_DIR / f"{ward_id}__{state}.png"
        out.write_to_png(str(path))
        return path
    except Exception:
        return None


# ── Parametrization ─────────────────────────────────────────────────────


def _golden_path(ward_id: str, emphasis: bool) -> Path:
    case = _ward_by_id(ward_id)
    w, h = case.size
    filename = f"{ward_id}_{w}x{h}.png"
    if emphasis:
        return _EMPHASIS_DIR / filename
    return _GOLDEN_DIR / "wards" / filename


def _cases() -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for ward in _WARDS:
        out.append((ward.ward_id, False))
        out.append((ward.ward_id, True))
    return out


@requires_cairo_and_gi
@goldens_acknowledged_stale
@pytest.mark.parametrize("ward_id,emphasis", _cases())
def test_homage_visual_regression(ward_id: str, emphasis: bool) -> None:
    """Render ward ``ward_id`` and compare against its golden image.

    When :envvar:`HAPAX_UPDATE_GOLDEN` is set the current render is
    written back to disk and the test short-circuits so the contributor
    can audit the new golden before committing.
    """
    import cairo

    case = _ward_by_id(ward_id)
    state = "emphasis_on" if emphasis else "emphasis_off"
    actual = _render_ward_deterministic(ward_id, emphasis=emphasis)
    path = _golden_path(ward_id, emphasis)

    if _update_golden_requested():
        path.parent.mkdir(parents=True, exist_ok=True)
        actual.write_to_png(str(path))
        return

    assert path.is_file(), (
        f"golden image missing at {path} — set HAPAX_UPDATE_GOLDEN=1 "
        f"and re-run to generate, then audit and commit with "
        f"`git add -f {path}` (PNGs are globally gitignored)"
    )
    expected = cairo.ImageSurface.create_from_png(str(path))
    tolerance = _EMPHASIS_TOLERANCE if emphasis else _BASE_TOLERANCE
    ok, diag, max_delta, n_over = _surfaces_match(
        actual,
        expected,
        tolerance=tolerance,
        byte_over_budget=_LOOSE_BYTE_OVER_BUDGET,
        loose=case.loose,
    )
    if not ok:
        diff_path = _emit_diff(ward_id, state, actual, expected)
        diff_note = f" diff written to {diff_path}" if diff_path else ""
        pytest.fail(f"{ward_id} [{state}] visual regression: {diag}.{diff_note}")


# ── Meta tests ──────────────────────────────────────────────────────────


def test_ward_inventory_count() -> None:
    """Plan §C3 originally pinned 16 wards × 2 states = 32 cases.
    HARDM retired 2026-04-23 (GEAL spec §12); count drops to 15.
    """
    assert len(_WARDS) == 15, f"expected 15 wards, got {len(_WARDS)}"
    assert len(_cases()) == 30


def test_all_ward_ids_have_builders() -> None:
    """Every ward in the inventory must have a corresponding builder."""
    for ward in _WARDS:
        assert ward.ward_id in _BUILDERS, f"ward {ward.ward_id!r} missing builder in _BUILDERS"


def test_all_ward_ids_are_unique() -> None:
    ids = [w.ward_id for w in _WARDS]
    assert len(ids) == len(set(ids)), "duplicate ward_id in inventory"


@requires_cairo_and_gi
def test_render_is_deterministic_across_back_to_back_calls() -> None:
    """Two back-to-back renders of the same ward must be byte-identical.

    Otherwise goldens would be useless even without regressions.
    """
    # Use a simple ward (no Pango) for the stability pin.
    s1 = _render_ward_deterministic("impingement_cascade", emphasis=False)
    s2 = _render_ward_deterministic("impingement_cascade", emphasis=False)
    assert bytes(s1.get_data()) == bytes(s2.get_data())


@requires_cairo_and_gi
def test_emphasis_variant_differs_from_off_variant() -> None:
    """Emphasis-on rendering must produce a visibly different surface
    from the emphasis-off rendering — otherwise the emphasis envelope
    is silently no-op and the test suite misses the regression it was
    built to catch."""
    off = _render_ward_deterministic("impingement_cascade", emphasis=False)
    on = _render_ward_deterministic("impingement_cascade", emphasis=True)
    off_bytes = bytes(off.get_data())
    on_bytes = bytes(on.get_data())
    assert off_bytes != on_bytes, (
        "emphasis-on rendering is byte-identical to emphasis-off — "
        "emphasis envelope is not wired into the render path"
    )


# Re-export for the regenerate script's import check.
__all__ = [
    "WardCase",
    "_WARDS",
    "_cases",
    "test_homage_visual_regression",
]
