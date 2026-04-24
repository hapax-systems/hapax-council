"""Moksha .edc theme loader — graceful-fallback + shape pins.

Phase 1 of ``ytb-AUTH-PALETTE`` (Moksha portion). The loader parses a
Moksha (Enlightenment E17) theme ``.edc`` file and extracts the 7
color classes into a dict of LAB triples. If the file is missing or
unparseable, the loader returns None — the compositor can continue
booting without hard-failing on authentic-asset absence.

Phase 2 will wire this loader into compositor boot so that operator-
supplied Moksha .edc files augment the static registry palettes with
byte-exact theme colours. Phase 1 is the skeleton + contract only.

Spec: cc-task ``ytb-AUTH-PALETTE-scrim-extension``.
"""

from __future__ import annotations

from pathlib import Path

from shared.aesthetic_library_loader import (
    DEFAULT_MOKSHA_EDC_PATH,
    MOKSHA_COLOR_CLASSES,
    MokshaThemeLoader,
    load_default_moksha,
)


class TestColorClassContract:
    """Seven canonical Moksha color classes (cc-task design)."""

    def test_seven_classes(self) -> None:
        assert len(MOKSHA_COLOR_CLASSES) == 7

    def test_contains_bg_fg_text(self) -> None:
        assert "bg_color" in MOKSHA_COLOR_CLASSES
        assert "fg_color" in MOKSHA_COLOR_CLASSES
        assert "text_color" in MOKSHA_COLOR_CLASSES

    def test_contains_semantic_accents(self) -> None:
        assert "fg_selected" in MOKSHA_COLOR_CLASSES
        assert "focus_color" in MOKSHA_COLOR_CLASSES
        assert "success_color" in MOKSHA_COLOR_CLASSES
        assert "alert_color" in MOKSHA_COLOR_CLASSES


class TestGracefulFallback:
    """Missing / unparseable .edc must NOT hard-fail the caller."""

    def test_missing_path_returns_none(self, tmp_path: Path) -> None:
        loader = MokshaThemeLoader()
        missing = tmp_path / "does-not-exist.edc"
        result = loader.load(missing)
        assert result is None

    def test_directory_not_file_returns_none(self, tmp_path: Path) -> None:
        loader = MokshaThemeLoader()
        result = loader.load(tmp_path)
        assert result is None

    def test_unparseable_file_returns_none(self, tmp_path: Path) -> None:
        loader = MokshaThemeLoader()
        bogus = tmp_path / "not-an-edc.edc"
        bogus.write_text("this is not valid EDC syntax\n{{{\n")
        result = loader.load(bogus)
        assert result is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        loader = MokshaThemeLoader()
        empty = tmp_path / "empty.edc"
        empty.write_text("")
        result = loader.load(empty)
        assert result is None


class TestHappyPath:
    """Well-formed .edc fixture — extracts all 7 classes as LAB triples."""

    def _fixture(self, tmp_path: Path) -> Path:
        """Minimal EDC-flavoured fixture with 7 color classes declared."""
        f = tmp_path / "moksha-sample.edc"
        f.write_text(
            """\
collections {
  color_classes {
    color_class { name: "bg_color"; color: 37 37 37 255; }
    color_class { name: "fg_color"; color: 204 204 204 255; }
    color_class { name: "text_color"; color: 224 224 224 255; }
    color_class { name: "fg_selected"; color: 255 255 255 255; }
    color_class { name: "focus_color"; color: 100 149 237 255; }
    color_class { name: "success_color"; color: 96 184 96 255; }
    color_class { name: "alert_color"; color: 204 96 96 255; }
  }
}
"""
        )
        return f

    def test_loads_all_seven_classes(self, tmp_path: Path) -> None:
        loader = MokshaThemeLoader()
        result = loader.load(self._fixture(tmp_path))
        assert result is not None
        for cls in MOKSHA_COLOR_CLASSES:
            assert cls in result

    def test_values_are_lab_triples(self, tmp_path: Path) -> None:
        loader = MokshaThemeLoader()
        result = loader.load(self._fixture(tmp_path))
        assert result is not None
        for lab in result.values():
            assert len(lab) == 3
            L, a, b = lab
            # Sanity bounds — L can exceed 100.0 by floating-point
            # epsilon on pure white (D65 reference normalization); the
            # 0.01 slack covers that.
            assert 0.0 <= L <= 100.01
            assert -128.0 <= a <= 128.0
            assert -128.0 <= b <= 128.0

    def test_bg_is_dark(self, tmp_path: Path) -> None:
        """bg_color RGB 37,37,37 → L ≈ 15 (dark)."""
        loader = MokshaThemeLoader()
        result = loader.load(self._fixture(tmp_path))
        assert result is not None
        assert result["bg_color"][0] < 25.0

    def test_fg_selected_is_bright(self, tmp_path: Path) -> None:
        """fg_selected RGB 255,255,255 → L = 100."""
        loader = MokshaThemeLoader()
        result = loader.load(self._fixture(tmp_path))
        assert result is not None
        assert result["fg_selected"][0] > 95.0


class TestInRepoAuthoredPlaceholder:
    """Phase 2 integration: the authored Moksha placeholder ships in-repo."""

    def test_default_path_exists(self) -> None:
        """Authored Moksha EDC placeholder ships at the canonical path."""
        assert DEFAULT_MOKSHA_EDC_PATH.is_file()

    def test_load_default_returns_all_seven_classes(self) -> None:
        """``load_default_moksha()`` yields the 7 canonical classes."""
        result = load_default_moksha()
        assert result is not None
        for cls in MOKSHA_COLOR_CLASSES:
            assert cls in result

    def test_default_bg_is_dark_grey(self) -> None:
        """Authored placeholder bg_color is #252525 → L ≈ 15."""
        result = load_default_moksha()
        assert result is not None
        L, _, _ = result["bg_color"]
        # RGB (37,37,37) → CIE-LAB L ≈ 14.99 at D65.
        assert 12.0 <= L <= 18.0

    def test_default_fg_selected_is_white(self) -> None:
        """Authored placeholder fg_selected is pure white → L ≈ 100."""
        result = load_default_moksha()
        assert result is not None
        L, _, _ = result["fg_selected"]
        assert L >= 95.0

    def test_default_focus_is_blueish(self) -> None:
        """Cornflower-blue #6495ed has negative a* and strongly negative b*."""
        result = load_default_moksha()
        assert result is not None
        _, a, b = result["focus_color"]
        # Blue dominates → b* well below 0.
        assert b < -30.0

    def test_default_extract_is_stable_across_calls(self) -> None:
        """Pure function: same bytes in → same LAB triples out."""
        r1 = load_default_moksha()
        r2 = load_default_moksha()
        assert r1 == r2
