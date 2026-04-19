"""Mock-based tests for Phase A5 Pango font-availability helpers.

Phase A5 (homage-completion-plan §3.3) added two helpers to
:mod:`agents.studio_compositor.text_render` that probe whether a given
font family is resolvable via Pango (which consults fontconfig) and
emit a loud WARN log when a HOMAGE-required family (e.g.
``Px437 IBM VGA 8x16``) is missing. These tests mock the Pango
``FontMap`` so the suite runs in CI environments without fontconfig.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest  # noqa: TC002 — fixture types referenced at runtime by pytest's introspection

from agents.studio_compositor import text_render


class _FakeFamily:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


def _fake_font_map(families: list[str]) -> SimpleNamespace:
    return SimpleNamespace(list_families=lambda: [_FakeFamily(n) for n in families])


# ── has_font ────────────────────────────────────────────────────────────────


def test_has_font_returns_false_when_pango_unavailable() -> None:
    """In CI without Pango typelibs, ``has_font`` degrades to False."""
    with patch.object(text_render, "_HAS_PANGO", False):
        assert text_render.has_font("Px437 IBM VGA 8x16") is False


def test_has_font_returns_true_when_family_present() -> None:
    """A matching family name in the Pango FontMap → True."""
    fake_map = _fake_font_map(["DejaVu Sans Mono", "Px437 IBM VGA 8x16", "JetBrains Mono"])
    with (
        patch.object(text_render, "_HAS_PANGO", True),
        patch.object(
            text_render,
            "PangoCairo",
            SimpleNamespace(FontMap=SimpleNamespace(get_default=lambda: fake_map)),
        ),
    ):
        assert text_render.has_font("Px437 IBM VGA 8x16") is True


def test_has_font_returns_false_when_family_absent() -> None:
    """A FontMap that does not include the wanted family → False."""
    fake_map = _fake_font_map(["DejaVu Sans Mono", "JetBrains Mono"])
    with (
        patch.object(text_render, "_HAS_PANGO", True),
        patch.object(
            text_render,
            "PangoCairo",
            SimpleNamespace(FontMap=SimpleNamespace(get_default=lambda: fake_map)),
        ),
    ):
        assert text_render.has_font("Px437 IBM VGA 8x16") is False


def test_has_font_is_case_insensitive_and_trims_whitespace() -> None:
    """Font family comparison is normalized (casefold + strip)."""
    fake_map = _fake_font_map(["PX437 ibm vga 8x16"])
    with (
        patch.object(text_render, "_HAS_PANGO", True),
        patch.object(
            text_render,
            "PangoCairo",
            SimpleNamespace(FontMap=SimpleNamespace(get_default=lambda: fake_map)),
        ),
    ):
        assert text_render.has_font("  Px437 IBM VGA 8x16  ") is True


def test_has_font_handles_none_font_map() -> None:
    """When FontMap.get_default returns None, has_font returns False safely."""
    with (
        patch.object(text_render, "_HAS_PANGO", True),
        patch.object(
            text_render,
            "PangoCairo",
            SimpleNamespace(FontMap=SimpleNamespace(get_default=lambda: None)),
        ),
    ):
        assert text_render.has_font("Px437 IBM VGA 8x16") is False


def test_has_font_swallows_enumeration_exceptions() -> None:
    """A raising FontMap must not propagate — has_font returns False."""

    def _raise() -> None:
        raise RuntimeError("pango exploded")

    with (
        patch.object(text_render, "_HAS_PANGO", True),
        patch.object(
            text_render,
            "PangoCairo",
            SimpleNamespace(FontMap=SimpleNamespace(get_default=_raise)),
        ),
    ):
        assert text_render.has_font("Px437 IBM VGA 8x16") is False


def test_has_font_skips_family_whose_get_name_raises() -> None:
    """One misbehaving family must not poison the enumeration."""

    class _BadFamily:
        def get_name(self) -> str:
            raise RuntimeError("bad family")

    fake_map = SimpleNamespace(
        list_families=lambda: [_BadFamily(), _FakeFamily("Px437 IBM VGA 8x16")]
    )
    with (
        patch.object(text_render, "_HAS_PANGO", True),
        patch.object(
            text_render,
            "PangoCairo",
            SimpleNamespace(FontMap=SimpleNamespace(get_default=lambda: fake_map)),
        ),
    ):
        assert text_render.has_font("Px437 IBM VGA 8x16") is True


# ── warn_if_missing_homage_fonts ────────────────────────────────────────────


def test_warn_emits_info_when_pango_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CI path: Pango absent → one info line, no WARNs."""
    caplog.set_level(logging.INFO, logger=text_render.log.name)
    with patch.object(text_render, "_HAS_PANGO", False):
        text_render.warn_if_missing_homage_fonts()
    assert any(
        "Pango unavailable" in rec.getMessage() and rec.levelno == logging.INFO
        for rec in caplog.records
    )
    assert not any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_warn_emits_warning_when_required_font_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A missing HOMAGE-required font triggers a loud WARN with the family name."""
    caplog.set_level(logging.WARNING, logger=text_render.log.name)
    fake_map = _fake_font_map(["DejaVu Sans Mono"])  # Px437 absent
    with (
        patch.object(text_render, "_HAS_PANGO", True),
        patch.object(
            text_render,
            "PangoCairo",
            SimpleNamespace(FontMap=SimpleNamespace(get_default=lambda: fake_map)),
        ),
    ):
        text_render.warn_if_missing_homage_fonts()
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert warnings, "expected a WARN for the missing HOMAGE font"
    assert any(
        "Px437 IBM VGA 8x16" in rec.getMessage() and "NOT FOUND" in rec.getMessage()
        for rec in warnings
    )


def test_warn_emits_info_when_all_fonts_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When every required font resolves, only info-level probe lines fire."""
    caplog.set_level(logging.INFO, logger=text_render.log.name)
    fake_map = _fake_font_map(list(text_render.HOMAGE_REQUIRED_FONTS))
    with (
        patch.object(text_render, "_HAS_PANGO", True),
        patch.object(
            text_render,
            "PangoCairo",
            SimpleNamespace(FontMap=SimpleNamespace(get_default=lambda: fake_map)),
        ),
    ):
        text_render.warn_if_missing_homage_fonts()
    assert not any(rec.levelno == logging.WARNING for rec in caplog.records)
    assert any(
        "available" in rec.getMessage() and rec.levelno == logging.INFO for rec in caplog.records
    )


def test_homage_required_fonts_contains_px437() -> None:
    """Regression pin: BitchX primary font must remain in the required list."""
    assert "Px437 IBM VGA 8x16" in text_render.HOMAGE_REQUIRED_FONTS
