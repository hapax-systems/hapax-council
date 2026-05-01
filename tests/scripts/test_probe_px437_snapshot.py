"""Tests for the ``scripts/probe-px437-snapshot.py`` probe.

The probe is the cc-task ``visual-quality-px437-live-snapshot-fixture``
deliverable: a deterministic, FX-free Px437 capture that proves the
text renderer itself produces clean pixel-grid edges. These tests pin
the determinism contract (same input → same ARGB pixel bytes) and the
output-format contract (PNG written, dimensions match the laid-out
text plus padding).

The probe is loaded by file path rather than by import name because
its shebang-prefixed filename ``probe-px437-snapshot.py`` is not a
valid Python identifier (hyphens). Loading via
``importlib.util.spec_from_file_location`` keeps the script's CLI
entry point as the canonical surface while letting the tests drive
the helpers directly.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "scripts" / "probe-px437-snapshot.py"


def _load_probe_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("probe_px437_snapshot", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    return _load_probe_module()


def _surface_argb_bytes(probe: ModuleType, text: str, font: str) -> bytes:
    style = probe.make_style(text=text, font=font)
    from agents.studio_compositor.text_render import render_text_to_surface

    surface, _w, _h = render_text_to_surface(style, padding_px=8)
    return bytes(surface.get_data())


class TestDeterminism:
    """Same input must yield the same pixel bytes across runs."""

    def test_same_text_same_bytes(self, probe: ModuleType) -> None:
        a = _surface_argb_bytes(probe, "ABCxyz 0123", "Px437 IBM VGA 8x16 32")
        b = _surface_argb_bytes(probe, "ABCxyz 0123", "Px437 IBM VGA 8x16 32")
        assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()

    def test_different_text_different_bytes(self, probe: ModuleType) -> None:
        a = _surface_argb_bytes(probe, "ABCxyz", "Px437 IBM VGA 8x16 32")
        b = _surface_argb_bytes(probe, "DEFxyz", "Px437 IBM VGA 8x16 32")
        assert hashlib.sha256(a).hexdigest() != hashlib.sha256(b).hexdigest()


class TestStyle:
    def test_default_style_uses_px437(self, probe: ModuleType) -> None:
        style = probe.make_style()
        assert "Px437" in style.font_description
        assert "VGA" in style.font_description

    def test_default_style_has_no_outline(self, probe: ModuleType) -> None:
        # Outline pass is irrelevant to the smearing question; the probe
        # captures the foreground glyph grid only.
        style = probe.make_style()
        assert style.outline_offsets == ()

    def test_default_style_is_white(self, probe: ModuleType) -> None:
        style = probe.make_style()
        assert style.color_rgba == (1.0, 1.0, 1.0, 1.0)


class TestRenderProbePng:
    def test_writes_png_to_path(self, probe: ModuleType, tmp_path: Path) -> None:
        out = tmp_path / "probe.png"
        w, h = probe.render_probe_png(out, text="HELLO", font="Px437 IBM VGA 8x16 16")
        assert out.exists()
        # PNG magic.
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert w > 0
        assert h > 0

    def test_creates_parent_dir(self, probe: ModuleType, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "dir" / "probe.png"
        probe.render_probe_png(nested, text="x")
        assert nested.exists()

    def test_dimensions_grow_with_padding(self, probe: ModuleType, tmp_path: Path) -> None:
        small = tmp_path / "small.png"
        large = tmp_path / "large.png"
        ws, hs = probe.render_probe_png(small, text="X", padding_px=4)
        wl, hl = probe.render_probe_png(large, text="X", padding_px=32)
        assert wl > ws
        assert hl > hs


class TestCli:
    def test_main_writes_artifact_and_returns_zero(self, probe: ModuleType, tmp_path: Path) -> None:
        rc = probe.main(
            [
                "--text",
                "smoke",
                "--output-dir",
                str(tmp_path),
                "--output-filename",
                "smoke.png",
            ]
        )
        assert rc == 0
        assert (tmp_path / "smoke.png").exists()
