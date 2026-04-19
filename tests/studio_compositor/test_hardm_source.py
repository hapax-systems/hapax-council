"""Tests for the HARDM dot-matrix Cairo source.

HOMAGE follow-on #121. Spec:
``docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md``.

Pins:
- Geometry (256×256 surface, 16×16 cells) — package-invariant.
- Missing signals file → every cell renders idle (``muted``).
- Sample signals payload → active cells resolve to family-accent RGBA.
- Palette swap (package ``resolve_colour`` override) → cell colours follow.
- Registry registration under name ``"HardmDotMatrix"``.
- Class inherits ``HomageTransitionalSource``.
"""

from __future__ import annotations

import json
import time

import cairo
import pytest

from agents.studio_compositor import hardm_source as hs
from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.hardm_source import (
    CELL_SIZE_PX,
    GRID_COLS,
    GRID_ROWS,
    SIGNAL_NAMES,
    STALENESS_CUTOFF_S,
    SURFACE_H,
    SURFACE_W,
    TOTAL_CELLS,
    HardmDotMatrix,
    _classify_cell,
    _read_signals,
)
from agents.studio_compositor.homage import BITCHX_PACKAGE
from agents.studio_compositor.homage.transitional_source import (
    HomageTransitionalSource,
    TransitionState,
)


@pytest.fixture(autouse=True)
def _redirect_signal_file(monkeypatch, tmp_path):
    """Isolate tests from the real /dev/shm signals file."""
    monkeypatch.setattr(hs, "SIGNAL_FILE", tmp_path / "hardm-cell-signals.json")
    return tmp_path


def _write_signals(tmp_path, signals: dict, generated_at: float | None = None) -> None:
    ts = time.time() if generated_at is None else generated_at
    (tmp_path / "hardm-cell-signals.json").write_text(
        json.dumps({"generated_at": ts, "signals": signals})
    )


def _render_hardm() -> cairo.ImageSurface:
    """Render HARDM directly via render_content so the test doesn't depend
    on the FSM entry sequence — we're asserting geometry + palette, not
    the transition pixel effects which ``HomageTransitionalSource`` owns.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SURFACE_W, SURFACE_H)
    cr = cairo.Context(surface)
    src = HardmDotMatrix()
    src.render_content(cr, SURFACE_W, SURFACE_H, t=0.0, state={})
    return surface


def _cell_pixel(surface: cairo.ImageSurface, row: int, col: int) -> tuple[int, int, int, int]:
    """Sample centre pixel of (row, col). Returns (B, G, R, A) — cairo ARGB32 premul."""
    stride = surface.get_stride()
    data = surface.get_data()
    x = col * CELL_SIZE_PX + CELL_SIZE_PX // 2
    y = row * CELL_SIZE_PX + CELL_SIZE_PX // 2
    idx = y * stride + x * 4
    # cairo FORMAT_ARGB32 is (B, G, R, A) little-endian; unsigned ints.
    return (data[idx], data[idx + 1], data[idx + 2], data[idx + 3])


# ── Geometry + registration invariants ──────────────────────────────────


class TestGeometry:
    def test_constants(self) -> None:
        # Spec §2 states 256×256 total over a 16×16 grid. Cell size is 16 px
        # (not 32 — the spec table's "32 px" entry conflicts with its own
        # total surface; honouring the 256×256 total per task brief).
        assert CELL_SIZE_PX == 16
        assert GRID_ROWS == 16
        assert GRID_COLS == 16
        assert TOTAL_CELLS == 256
        assert SURFACE_W == 256
        assert SURFACE_H == 256

    def test_sixteen_primary_signals(self) -> None:
        assert len(SIGNAL_NAMES) == 16
        # Spec §3 first + last
        assert SIGNAL_NAMES[0] == "midi_active"
        assert SIGNAL_NAMES[15] == "homage_package"

    def test_inherits_homage_transitional_source(self) -> None:
        src = HardmDotMatrix()
        assert isinstance(src, HomageTransitionalSource)
        assert src.source_id == "hardm_dot_matrix"

    def test_fsm_transitions(self) -> None:
        src = HardmDotMatrix()
        assert src.transition_state is TransitionState.ABSENT
        src.apply_transition("ticker-scroll-in")
        assert src.transition_state is TransitionState.ENTERING

    def test_registry_registration(self) -> None:
        cls = get_cairo_source_class("HardmDotMatrix")
        assert cls is HardmDotMatrix


# ── Render behaviour ─────────────────────────────────────────────────────


class TestRender:
    def test_render_produces_non_empty_surface(self, tmp_path) -> None:
        # No signals file → still paints background + 256 idle muted cells.
        surface = _render_hardm()
        assert any(b != 0 for b in bytes(surface.get_data()[:4096]))

    def test_all_cells_idle_when_file_missing(self, tmp_path) -> None:
        surface = _render_hardm()
        # Muted RGBA from BitchX is (0.39, 0.39, 0.39, 1.0). Interior pixels
        # should NOT match any accent-cyan / accent-green / accent-red —
        # sample row 0 (midi_active, would be accent_cyan if active).
        b, g, r, a = _cell_pixel(surface, row=0, col=5)
        # Active cyan would push B and G high, R low.  Muted is balanced grey.
        # We only assert here that the cell is not the strong-accent colour.
        assert not (b > 150 and g > 150 and r < 50)

    def test_active_midi_renders_accent_cyan(self, tmp_path) -> None:
        _write_signals(tmp_path, {"midi_active": True})
        surface = _render_hardm()
        # Row 0 = midi_active, family=timing → accent_cyan.
        # BitchX cyan is (0, 0.78, 0.78, 1.0).  Interior should be high in
        # both B and G channels, near-zero R.  Cairo ARGB32 byte order is
        # (B, G, R, A) on little-endian.
        b, g, r, a = _cell_pixel(surface, row=0, col=5)
        assert b > 150
        assert g > 150
        assert r < 50
        assert a > 200

    def test_stress_value_renders_accent_red(self, tmp_path) -> None:
        _write_signals(tmp_path, {"consent_gate": "blocked"})
        surface = _render_hardm()
        # Row 10 = consent_gate.  "blocked" → accent_red.
        b, g, r, a = _cell_pixel(surface, row=10, col=5)
        assert r > 150
        assert g < 50
        assert b < 50

    def test_missing_consent_signal_is_stress(self, tmp_path) -> None:
        # Write a payload with no consent_gate key — spec §3 fails closed.
        _write_signals(tmp_path, {"vad_speech": True})
        surface = _render_hardm()
        b, g, r, a = _cell_pixel(surface, row=10, col=5)
        assert r > 150
        assert g < 50
        assert b < 50

    def test_consent_safe_render_is_noop(self, monkeypatch, tmp_path) -> None:
        # When get_active_package returns None (consent-safe layout),
        # render_content must paint nothing.
        monkeypatch.setattr(hs, "get_active_package", lambda: None)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SURFACE_W, SURFACE_H)
        cr = cairo.Context(surface)
        src = HardmDotMatrix()
        src.render_content(cr, SURFACE_W, SURFACE_H, t=0.0, state={})
        # Untouched surface is all-zero.
        assert all(b == 0 for b in bytes(surface.get_data()[:4096]))


# ── Classifier unit tests ────────────────────────────────────────────────


class TestClassifier:
    def test_bool_true_active(self) -> None:
        role, alpha = _classify_cell("vad_speech", True)
        assert role == "accent_green"
        assert alpha == 1.0

    def test_bool_false_idle(self) -> None:
        role, alpha = _classify_cell("vad_speech", False)
        assert role == "muted"

    def test_none_governance_fails_closed(self) -> None:
        role, _ = _classify_cell("consent_gate", None)
        assert role == "accent_red"

    def test_none_non_governance_is_idle(self) -> None:
        role, _ = _classify_cell("midi_active", None)
        assert role == "muted"

    def test_numeric_level4_alpha_quantisation(self) -> None:
        role, alpha = _classify_cell("stimmung_energy", 0.9)
        assert role == "accent_magenta"
        assert alpha == 1.0
        role, alpha = _classify_cell("stimmung_energy", 0.4)
        assert role == "accent_magenta"
        assert alpha == 0.55

    def test_numeric_overflow_is_stress(self) -> None:
        role, _ = _classify_cell("stimmung_energy", 1.5)
        assert role == "accent_red"

    def test_stance_categorical(self) -> None:
        assert _classify_cell("director_stance", "nominal")[0] == "muted"
        assert _classify_cell("director_stance", "cautious")[0] == "accent_magenta"
        assert _classify_cell("director_stance", "critical")[0] == "accent_red"


# ── Palette swap ─────────────────────────────────────────────────────────


class TestPaletteSwap:
    def test_cell_colours_follow_active_package(self, monkeypatch, tmp_path) -> None:
        """Swap in a stubbed package with a distinctive muted role and
        assert the rendered cell uses that package's RGBA, not BitchX's."""
        _write_signals(tmp_path, {"midi_active": False})  # row 0 idle

        class _StubPkg:
            name = "stub"

            def resolve_colour(self, role):  # noqa: D401 — imitates HomagePackage
                if role == "muted":
                    # Bright pink muted — obviously not BitchX grey.
                    return (1.0, 0.0, 0.5, 1.0)
                if role == "background":
                    return (0.0, 0.0, 0.0, 0.0)
                return (0.0, 0.0, 0.0, 0.0)

        monkeypatch.setattr(hs, "get_active_package", lambda: _StubPkg())

        surface = _render_hardm()
        b, g, r, a = _cell_pixel(surface, row=0, col=5)
        # Pink muted: R=255, G=0, B=128 (cairo premul; check the signature).
        assert r > 200
        assert g < 50


# ── Smoke — default BITCHX_PACKAGE available ─────────────────────────────


def test_bitchx_package_renders_smoke(tmp_path) -> None:
    _ = BITCHX_PACKAGE  # imported for side effects (registry population)
    _write_signals(
        tmp_path,
        {
            "midi_active": True,
            "vad_speech": False,
            "consent_gate": "ok",
            "stimmung_energy": 0.6,
        },
    )
    surface = _render_hardm()
    # 256×256 surface, nonzero data somewhere.
    assert any(b != 0 for b in bytes(surface.get_data()[: SURFACE_W * 16]))


# ── Staleness cutoff regression (beta audit F-AUDIT-1062-2) ──────────────


class TestStaleness:
    """Pins the 3 s staleness cutoff against the 2 s publisher cadence.

    The HARDM publisher timer (``hapax-hardm-publisher.timer``) fires
    every 2 s with ``AccuracySec=500ms``. The consumer's staleness cutoff
    must sit above 2 s + jitter so routine scheduling never drops a
    payload — we pin 3 s (50 % margin) per beta audit F-AUDIT-1062-2.
    """

    def test_cutoff_is_three_seconds(self) -> None:
        # Guard against accidental regression to 1.0 (prior runbook value).
        assert STALENESS_CUTOFF_S == 3.0

    def test_cutoff_exceeds_publisher_cadence(self) -> None:
        # Publisher cadence is 2 s (OnUnitActiveSec=2s). Cutoff must leave
        # comfortable headroom so jitter doesn't flicker cells to idle.
        publisher_cadence_s = 2.0
        assert publisher_cadence_s * 1.25 < STALENESS_CUTOFF_S

    def test_fresh_payload_passes_through(self, tmp_path) -> None:
        now = 1_000_000.0
        _write_signals(tmp_path, {"midi_active": True}, generated_at=now - 0.5)
        signals = _read_signals(tmp_path / "hardm-cell-signals.json", now=now)
        assert signals == {"midi_active": True}

    def test_payload_just_inside_cutoff_passes(self, tmp_path) -> None:
        now = 1_000_000.0
        _write_signals(
            tmp_path, {"midi_active": True}, generated_at=now - (STALENESS_CUTOFF_S - 0.01)
        )
        signals = _read_signals(tmp_path / "hardm-cell-signals.json", now=now)
        assert signals == {"midi_active": True}

    def test_stale_payload_is_dropped(self, tmp_path) -> None:
        now = 1_000_000.0
        _write_signals(
            tmp_path, {"midi_active": True}, generated_at=now - (STALENESS_CUTOFF_S + 0.5)
        )
        signals = _read_signals(tmp_path / "hardm-cell-signals.json", now=now)
        # Past the cutoff → empty dict so every cell renders idle, not stress.
        assert signals == {}

    def test_missing_generated_at_is_not_stale(self, tmp_path) -> None:
        # Legacy / stub payloads without ``generated_at`` shouldn't be
        # misclassified as stale — fall through to the normal path.
        (tmp_path / "hardm-cell-signals.json").write_text(
            json.dumps({"signals": {"midi_active": True}})
        )
        signals = _read_signals(tmp_path / "hardm-cell-signals.json", now=1_000_000.0)
        assert signals == {"midi_active": True}
