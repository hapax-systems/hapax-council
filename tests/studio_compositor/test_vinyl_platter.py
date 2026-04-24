"""Tests for the vinyl-platter HOMAGE ward.

Task #159. Pins:

- ``render_content`` no-op when ``vinyl_playing`` is False.
- Blur samples scale with rate (0.741 → fewer samples than 1.0).
- HomagePackage palette tint applied inside the disk.
- Circular crop: corners are untouched by the camera frame (background
  / transparent-ish; not camera-coloured pixels).
- Border ``»»»`` cardinal marker positions render through
  ``render_text`` (verified via a mock that records call coordinates).
- Registry registration under the class name ``VinylPlatterCairoSource``.
- Golden image for a deterministic render at rate=1.0.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import patch

import cairo
import pytest

from agents.studio_compositor import vinyl_platter as vp
from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.homage import BITCHX_PACKAGE
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from agents.studio_compositor.vinyl_platter import (
    CANVAS_H,
    CANVAS_W,
    VinylPlatterCairoSource,
    _blur_samples_for_rate,
    _blur_spread_deg,
    _resolve_turntables_camera_frame,
)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def _gate_open(monkeypatch):
    """Default: vinyl playing = True, rate = 1.0, default camera path."""
    monkeypatch.setattr(vp, "_vinyl_playing", lambda: True)
    monkeypatch.setattr(vp, "_read_playback_rate", lambda: 1.0)


@pytest.fixture
def _fake_camera_frame(monkeypatch, tmp_path):
    """Render a solid-red JPEG to stand in for the camera snapshot.

    The brio-synths producer is not available under unit tests — we
    monkeypatch the resolver to return a path we control, containing
    a deterministic image the ImageLoader can decode.
    """
    try:
        from PIL import Image
    except Exception:
        pytest.skip("PIL not available")
    frame = tmp_path / "vinyl-frame.jpg"
    Image.new("RGB", (128, 128), color=(200, 0, 0)).save(frame, "JPEG")

    monkeypatch.setattr(vp, "_resolve_turntables_camera_frame", lambda: frame)

    # Fresh image loader so the test doesn't pick up a previous cache.
    from agents.studio_compositor.image_loader import reset_image_loader_for_tests

    reset_image_loader_for_tests()
    return frame


# ── Registration + inheritance ───────────────────────────────────────────


class TestRegistration:
    def test_registered_in_cairo_sources(self) -> None:
        cls = get_cairo_source_class("VinylPlatterCairoSource")
        assert cls is VinylPlatterCairoSource

    def test_inherits_homage_transitional_source(self) -> None:
        src = VinylPlatterCairoSource()
        assert isinstance(src, HomageTransitionalSource)
        assert src.source_id == "vinyl_platter"

    def test_canvas_size(self) -> None:
        assert CANVAS_W == 360
        assert CANVAS_H == 360


# ── Gate on vinyl_playing ─────────────────────────────────────────────────


class TestVinylPlayingGate:
    def test_render_noop_when_not_playing(self, monkeypatch) -> None:
        monkeypatch.setattr(vp, "_vinyl_playing", lambda: False)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
        cr = cairo.Context(surface)
        VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
        # Unchanged surface = all-zero bytes.
        assert all(byte == 0 for byte in bytes(surface.get_data()[:4096]))

    def test_render_noop_when_consent_safe(self, monkeypatch) -> None:
        monkeypatch.setattr(vp, "_vinyl_playing", lambda: True)
        monkeypatch.setattr(vp, "get_active_package", lambda: None)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
        cr = cairo.Context(surface)
        VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
        assert all(byte == 0 for byte in bytes(surface.get_data()[:4096]))

    def test_vinyl_playing_probe_fail_closed(self, monkeypatch) -> None:
        """Gate returns False when build_perceptual_field raises.

        Pins the fail-CLOSED posture — an error during probing must not
        cause the ward to render a stale frame with the HOMAGE tint.
        """

        def _raise():
            raise RuntimeError("probe failure")

        # Patch the import target inside the wrapper to force failure.
        monkeypatch.setattr(
            vp,
            "_vinyl_playing",
            lambda: (
                vp._vinyl_playing.__wrapped__()
                if hasattr(vp._vinyl_playing, "__wrapped__")
                else False
            ),
        )
        # Use the real _vinyl_playing but monkey-patch the inner import
        # target by removing ``shared.perceptual_field`` from sys.modules
        # and inserting a stub that raises.
        import sys
        import types

        stub = types.ModuleType("shared.perceptual_field")

        def _raise_build():
            raise RuntimeError("probe failure")

        stub.build_perceptual_field = _raise_build  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "shared.perceptual_field", stub)

        # Now the wrapper function should catch the exception and return False.
        from agents.studio_compositor.vinyl_platter import _vinyl_playing

        assert _vinyl_playing() is False


# ── Motion blur / rate scaling ───────────────────────────────────────────


class TestBlurScaling:
    def test_blur_samples_zero_rate(self) -> None:
        # Stopped platter → single stamp, zero spread.
        assert _blur_samples_for_rate(0.0) == 1
        assert _blur_spread_deg(0.0) == 0.0

    def test_blur_samples_nominal_rate(self) -> None:
        # rate=1.0 → max samples, max spread.
        assert _blur_samples_for_rate(1.0) == 6
        assert _blur_spread_deg(1.0) == pytest.approx(18.0)

    def test_blur_samples_45_on_33(self) -> None:
        # rate=0.741 (45-on-33 preset) sits between 0 and max. Must
        # produce fewer samples than nominal so the visual blur is
        # visibly gentler.
        samples_741 = _blur_samples_for_rate(0.741)
        samples_100 = _blur_samples_for_rate(1.0)
        assert samples_741 < samples_100
        assert samples_741 >= 1
        assert _blur_spread_deg(0.741) < _blur_spread_deg(1.0)

    def test_blur_non_finite_rate_clamps(self) -> None:
        assert _blur_samples_for_rate(float("nan")) == 1
        assert _blur_samples_for_rate(float("-inf")) == 1
        assert _blur_spread_deg(float("nan")) == 0.0


# ── Camera classification resolution ──────────────────────────────────────


class TestCameraResolution:
    def test_default_when_classifications_missing(self, monkeypatch, tmp_path) -> None:
        # Point the module at a non-existent classifications file.
        missing = tmp_path / "nonexistent" / "camera-classifications.json"
        monkeypatch.setattr(vp, "_CAMERA_CLASSIFICATIONS", missing)
        path = _resolve_turntables_camera_frame()
        # Falls back to brio-synths.jpg.
        assert path.name == "brio-synths.jpg"

    def test_picks_camera_with_turntables_role(self, monkeypatch, tmp_path) -> None:
        cls_path = tmp_path / "camera-classifications.json"
        cls_path.write_text(
            json.dumps(
                {
                    "brio-operator": {"semantic_role": "operator-face"},
                    "brio-exotic-deck": {"semantic_role": "turntables"},
                }
            )
        )
        monkeypatch.setattr(vp, "_CAMERA_CLASSIFICATIONS", cls_path)
        monkeypatch.setattr(vp, "_SNAPSHOT_DIR", tmp_path)
        path = _resolve_turntables_camera_frame()
        assert path == tmp_path / "brio-exotic-deck.jpg"

    def test_malformed_classifications_fall_back(self, monkeypatch, tmp_path) -> None:
        cls_path = tmp_path / "camera-classifications.json"
        cls_path.write_text("not json {{{")
        monkeypatch.setattr(vp, "_CAMERA_CLASSIFICATIONS", cls_path)
        path = _resolve_turntables_camera_frame()
        assert path.name == "brio-synths.jpg"


# ── Render content (requires PIL + cairo) ─────────────────────────────────


class TestRenderContent:
    def test_circular_crop_corners_untouched_by_camera(
        self, _gate_open, _fake_camera_frame
    ) -> None:
        """Corners of the canvas fall outside the platter disk.

        The camera frame is solid red; the corners after rendering
        must NOT be solid-red — they should show the package background
        (near-black with alpha) because the circular clip excludes
        them. This pins the circular-crop invariant.
        """
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
        cr = cairo.Context(surface)
        VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
        surface.flush()

        data = bytes(surface.get_data())
        stride = surface.get_stride()

        def _pixel(x: int, y: int) -> tuple[int, int, int, int]:
            idx = y * stride + x * 4
            # Cairo FORMAT_ARGB32 is (B, G, R, A) on little-endian.
            return data[idx], data[idx + 1], data[idx + 2], data[idx + 3]

        # Corner pixel — outside the platter disk and outside the 1-px
        # border. Must not be camera-red (R channel dominant).
        b, g, r, _a = _pixel(2, 2)
        assert not (r > 150 and b < 80 and g < 80), (
            f"corner pixel ({r}, {g}, {b}) looks like camera-red — circular crop failed"
        )

    def test_tint_applied_inside_disk(self, _gate_open, _fake_camera_frame) -> None:
        """Centre-of-disk must carry the HOMAGE tint overlay.

        The camera frame is solid red. The BitchX identity-colour
        is near-white (0.9, 0.9, 0.9). The tint overlay at ~0.22 alpha
        lifts the green + blue channels of the centre pixel above what
        a pure red camera frame would produce, which is what we assert.
        """
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
        cr = cairo.Context(surface)
        VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
        surface.flush()

        data = bytes(surface.get_data())
        stride = surface.get_stride()
        cx = CANVAS_W // 2
        cy = CANVAS_H // 2
        idx = cy * stride + cx * 4
        b, g, _r, _a = data[idx], data[idx + 1], data[idx + 2], data[idx + 3]

        # Pure premultiplied red at 100% alpha would be B=0, G=0, R≈200.
        # The identity-colour tint (BitchX ``bright`` = (0.9, 0.9, 0.9))
        # at 0.22 alpha lifts both green and blue to measurable values.
        assert g > 20, f"expected tint to lift green channel, got g={g}"
        assert b > 20, f"expected tint to lift blue channel, got b={b}"

    @pytest.mark.xfail(
        reason=(
            "EMISSIVE-RETIRED-FLASH-FOLLOWUP — pixel-sample assertion "
            "post-#1242 chrome retirement. Surface stays transparent "
            "where chrome bg used to fill. Test should be rewritten to "
            "'renders without raising' rather than 'has non-zero "
            "pixels in first 4096 bytes'."
        ),
        strict=False,
    )
    def test_no_crash_when_camera_frame_missing(self, monkeypatch) -> None:
        """Ward survives a missing camera snapshot by painting a
        placeholder disk — does not raise, does not leave the surface
        entirely blank (the border/labels still render)."""
        monkeypatch.setattr(vp, "_vinyl_playing", lambda: True)
        monkeypatch.setattr(vp, "_read_playback_rate", lambda: 1.0)
        monkeypatch.setattr(
            vp, "_resolve_turntables_camera_frame", lambda: Path("/nonexistent.jpg")
        )

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
        cr = cairo.Context(surface)
        VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
        surface.flush()
        # At least some non-zero pixels (background + placeholder disk).
        assert any(byte != 0 for byte in bytes(surface.get_data()[:4096]))


# ── Cardinal markers (rendered text coordinates) ──────────────────────────


class TestCardinalMarkers:
    def test_renders_markers_at_four_cardinals(self, _gate_open, _fake_camera_frame) -> None:
        """The ``»»»`` marker must be drawn four times — N, E, S, W.

        We intercept ``render_text`` to capture its call arguments
        (text, x, y) so we can verify both the glyph and the cardinal
        placement without relying on Pango being installed under CI.
        """
        from agents.studio_compositor import text_render

        calls: list[tuple[str, float, float]] = []

        real_render_text = text_render.render_text

        def _spy(cr, style, x=0.0, y=0.0):
            calls.append((style.text, x, y))
            return real_render_text(cr, style, x, y)

        with patch.object(text_render, "render_text", _spy):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
            cr = cairo.Context(surface)
            VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})

        marker_calls = [c for c in calls if c[0] == "»»»"]
        assert len(marker_calls) == 4, f"expected 4 »»» calls, got {len(marker_calls)}"

        # Coordinates: top marker should be near y=0; bottom marker
        # near y=CANVAS_H. W/E share a y roughly canvas-centre.
        ys = sorted(round(c[2]) for c in marker_calls)
        assert ys[0] < 10
        assert ys[-1] > CANVAS_H - 30

    def test_renders_now_spinning_header(self, _gate_open, _fake_camera_frame) -> None:
        from agents.studio_compositor import text_render

        texts: list[str] = []
        real_render_text = text_render.render_text

        def _spy(cr, style, x=0.0, y=0.0):
            texts.append(style.text)
            return real_render_text(cr, style, x, y)

        with patch.object(text_render, "render_text", _spy):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
            cr = cairo.Context(surface)
            VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})

        assert "NOW SPINNING" in texts
        # rpm readout uses BitchX grammar: starts with ``[rpm `` and ends
        # with ``]``.
        assert any(t.startswith("[rpm ") and t.endswith("]") for t in texts)


# ── Smoke with BITCHX_PACKAGE (import + render end-to-end) ────────────────


@pytest.mark.xfail(
    reason=(
        "EMISSIVE-RETIRED-FLASH-FOLLOWUP — same chrome-retirement "
        "cascade as TestRenderContent::test_no_crash_when_camera_frame_missing."
    ),
    strict=False,
)
def test_bitchx_package_end_to_end_smoke(_gate_open, _fake_camera_frame) -> None:
    _ = BITCHX_PACKAGE  # imported for its registration side effect.
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
    cr = cairo.Context(surface)
    VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
    surface.flush()
    assert any(byte != 0 for byte in bytes(surface.get_data()[: CANVAS_W * 16]))


# ── Golden-image pin ──────────────────────────────────────────────────────


_GOLDEN_DIR = Path(__file__).parent / "golden_images"
_GOLDEN_PATH = _GOLDEN_DIR / "vinyl_platter_33rpm.png"
_GOLDEN_PIXEL_TOLERANCE = 3


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


@pytest.mark.skipif(not _HAS_GI, reason="GI Pango/PangoCairo typelibs not installed")
@pytest.mark.xfail(
    reason=(
        "EMISSIVE-GOLDEN-PANGO-FOLLOWUP — golden image diverges post-"
        "#1242 chrome retirement + Pango font drift. Same root cause "
        "as the legibility/hothouse goldens."
    ),
    strict=False,
)
def test_vinyl_platter_golden_at_33rpm(tmp_path, monkeypatch) -> None:
    """Deterministic render at rate=1.0 matches the committed golden PNG.

    State control:

    * Vinyl gate forced open.
    * Rate forced to 1.0 (33⅓ preset, no pitch offset).
    * Camera frame is a fixed solid-red JPEG so the decode is byte-stable.
    * HAPAX_HOMAGE_ACTIVE=0 so the transitional source dispatches directly
      to render_content (no FSM-state-dependent transparent surface).

    Update via ``HAPAX_UPDATE_GOLDEN=1``.
    """
    import os as _os

    try:
        from PIL import Image
    except Exception:
        pytest.skip("PIL not available")

    frame = tmp_path / "vinyl-frame.jpg"
    Image.new("RGB", (128, 128), color=(200, 0, 0)).save(frame, "JPEG")

    from agents.studio_compositor.image_loader import reset_image_loader_for_tests

    reset_image_loader_for_tests()

    monkeypatch.setattr(vp, "_vinyl_playing", lambda: True)
    monkeypatch.setattr(vp, "_read_playback_rate", lambda: 1.0)
    monkeypatch.setattr(vp, "_resolve_turntables_camera_frame", lambda: frame)

    with patch.dict(_os.environ, {"HAPAX_HOMAGE_ACTIVE": "0"}):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
        cr = cairo.Context(surface)
        VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
        surface.flush()

    update_requested = _os.environ.get("HAPAX_UPDATE_GOLDEN", "").strip() not in (
        "",
        "0",
        "false",
    )
    if update_requested:
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        surface.write_to_png(str(_GOLDEN_PATH))
        return

    if not _GOLDEN_PATH.is_file():
        # No committed golden yet — skip rather than fail; first-run
        # contributor sets HAPAX_UPDATE_GOLDEN=1 to seed the PNG.
        pytest.skip(
            f"golden image missing at {_GOLDEN_PATH}; set HAPAX_UPDATE_GOLDEN=1 and re-run to seed"
        )

    expected = cairo.ImageSurface.create_from_png(str(_GOLDEN_PATH))
    assert surface.get_width() == expected.get_width()
    assert surface.get_height() == expected.get_height()

    a_bytes = bytes(surface.get_data())
    e_bytes = bytes(expected.get_data())
    assert len(a_bytes) == len(e_bytes)
    max_delta = 0
    for ab, eb in zip(a_bytes, e_bytes, strict=True):
        d = abs(ab - eb)
        if d > max_delta:
            max_delta = d
    assert max_delta <= _GOLDEN_PIXEL_TOLERANCE, (
        f"max per-channel delta {max_delta} exceeds tolerance {_GOLDEN_PIXEL_TOLERANCE}"
    )


# ── Helpers: sanity on BITCHX palette ─────────────────────────────────────


@pytest.mark.xfail(
    reason=(
        "EMISSIVE-RETIRED-FLASH-FOLLOWUP — asserts >200 bg-fill pixels; "
        "post-#1242 the package_background no longer paints chrome "
        "behind the platter ward. Test should be rewritten to assert "
        "the package's palette is being CONSULTED (e.g. via mock "
        "spy on resolve_colour) rather than via pixel-sample."
    ),
    strict=False,
)
def test_platter_uses_package_background(monkeypatch) -> None:
    """Non-disk pixels sit on the package ``background`` colour.

    Regression guard: if a refactor accidentally hardcodes a bg hex,
    the consent-safe variant would break — HOMAGE governance requires
    all colours flow through ``resolve_colour``.
    """
    from agents.studio_compositor import vinyl_platter as _vp

    class _StubPkg:
        name = "stub"

        class _Grammar:
            punctuation_colour_role = "muted"
            identity_colour_role = "bright"
            content_colour_role = "terminal_default"

        class _Typo:
            primary_font_family = "Px437 IBM VGA 8x16"
            size_classes = {"compact": 10, "normal": 14}

        grammar = _Grammar()
        typography = _Typo()

        def resolve_colour(self, role: str):
            if role == "background":
                # Distinctive pink so it's unmistakable on a pixel probe.
                return (1.0, 0.0, 0.5, 1.0)
            if role == "muted":
                return (0.4, 0.4, 0.4, 1.0)
            if role == "bright":
                return (0.9, 0.9, 0.9, 1.0)
            if role == "terminal_default":
                return (0.8, 0.8, 0.8, 1.0)
            return (0.0, 0.0, 0.0, 1.0)

    monkeypatch.setattr(_vp, "get_active_package", lambda: _StubPkg())
    monkeypatch.setattr(_vp, "_vinyl_playing", lambda: True)
    monkeypatch.setattr(_vp, "_read_playback_rate", lambda: 1.0)
    monkeypatch.setattr(_vp, "_resolve_turntables_camera_frame", lambda: Path("/nonexistent.jpg"))

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
    cr = cairo.Context(surface)
    VinylPlatterCairoSource().render_content(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
    surface.flush()

    # Sample a corner pixel — far outside the platter disk and
    # inside the canvas. The stubbed background is bright pink
    # (R≈255, G≈0, B≈128). ARGB32 is (B, G, R, A) little-endian.
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    b, g, r, _a = (
        data[5 * stride + 5 * 4],
        data[5 * stride + 5 * 4 + 1],
        data[5 * stride + 5 * 4 + 2],
        data[5 * stride + 5 * 4 + 3],
    )
    assert r > 200
    assert g < 50
    # Premultiplied pink: B channel ≈ 128.
    assert 80 < b < 180


# ── Quick helpers export smoke ─────────────────────────────────────────────


def test_blur_is_monotonic_in_rate() -> None:
    """Blur spread increases monotonically with rate up to the clamp."""
    rates = [0.0, 0.25, 0.5, 0.741, 0.9, 1.0]
    spreads = [_blur_spread_deg(r) for r in rates]
    for a, b in zip(spreads[:-1], spreads[1:], strict=True):
        assert a <= b + 1e-9


def test_module_exports() -> None:
    """Ensure top-level symbols remain exported."""
    exported = set(vp.__all__)
    for name in (
        "VinylPlatterCairoSource",
        "CANVAS_W",
        "CANVAS_H",
        "_blur_samples_for_rate",
        "_blur_spread_deg",
    ):
        assert name in exported


# Pin pi = math.pi (sanity — unused at runtime but keeps math imported).
assert math.pi > 3.0
