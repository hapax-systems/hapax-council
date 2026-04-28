"""Tests for the anti-personification egress footer cairo ward.

ef7b-165 Phase 9 Part 2 (delta, 2026-04-24). Pins the always-mounted
render path, Ring 2 validation gating, and registry binding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import cairo

from agents.studio_compositor.egress_footer_source import EgressFooterCairoSource
from shared.governance.monetization_safety import RiskAssessment, SurfaceKind

if TYPE_CHECKING:
    import pytest


@dataclass
class _StubClassifier:
    verdict: RiskAssessment

    def classify(
        self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
    ) -> RiskAssessment:
        return self.verdict


def _surface_ctx() -> tuple[cairo.ImageSurface, cairo.Context]:
    """Create a throwaway cairo surface/context for render_content calls."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 30)
    return surface, cairo.Context(surface)


def _ctx() -> cairo.Context:
    return _surface_ctx()[1]


# ── always-mounted render path ────────────────────────────────────────


def test_render_validates_without_feature_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_EGRESS_FOOTER_ENABLED", raising=False)
    source = EgressFooterCairoSource()
    verdict = RiskAssessment(allowed=True, risk="none", reason="stub", surface=SurfaceKind.OVERLAY)
    with patch(
        "agents.studio_compositor.egress_footer_source.validate_footer_once",
        return_value=verdict,
    ) as m_validate:
        source.render_content(_ctx(), 1920, 30, t=0.0, state={})
    m_validate.assert_called_once_with(source._text)
    assert source._validated is True


def test_render_ignores_legacy_explicit_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_EGRESS_FOOTER_ENABLED", "0")
    source = EgressFooterCairoSource()
    verdict = RiskAssessment(allowed=True, risk="none", reason="stub", surface=SurfaceKind.OVERLAY)
    with patch(
        "agents.studio_compositor.egress_footer_source.validate_footer_once",
        return_value=verdict,
    ) as m_validate:
        source.render_content(_ctx(), 1920, 30, t=0.0, state={})
    m_validate.assert_called_once_with(source._text)


def test_render_paints_footer_pixels_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_EGRESS_FOOTER_ENABLED", "0")
    source = EgressFooterCairoSource()
    verdict = RiskAssessment(allowed=True, risk="none", reason="stub", surface=SurfaceKind.OVERLAY)
    surface, ctx = _surface_ctx()

    with patch(
        "agents.studio_compositor.egress_footer_source.validate_footer_once",
        return_value=verdict,
    ):
        source.render_content(ctx, 1920, 30, t=0.0, state={})

    surface.flush()
    assert any(surface.get_data()), "allowed egress footer should paint visible pixels"


# ── Ring 2 validation gating ──────────────────────────────────────────


def test_render_validates_exactly_once_on_first_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HAPAX_EGRESS_FOOTER_ENABLED", raising=False)
    source = EgressFooterCairoSource()
    verdict = RiskAssessment(allowed=True, risk="none", reason="stub", surface=SurfaceKind.OVERLAY)
    with patch(
        "agents.studio_compositor.egress_footer_source.validate_footer_once",
        return_value=verdict,
    ) as m_validate:
        source.render_content(_ctx(), 1920, 30, t=0.0, state={})
        source.render_content(_ctx(), 1920, 30, t=1.0, state={})
        source.render_content(_ctx(), 1920, 30, t=2.0, state={})

    assert m_validate.call_count == 1
    assert source._validated is True
    assert source._withheld is False


def test_render_withholds_on_ring2_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_EGRESS_FOOTER_ENABLED", raising=False)
    source = EgressFooterCairoSource()
    verdict = RiskAssessment(
        allowed=False, risk="high", reason="stub reject", surface=SurfaceKind.OVERLAY
    )
    with patch(
        "agents.studio_compositor.egress_footer_source.validate_footer_once",
        return_value=verdict,
    ):
        source.render_content(_ctx(), 1920, 30, t=0.0, state={})

    assert source._withheld is True


def test_render_withholds_when_validator_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classifier backend down → fail-closed withhold, no exception bubbles up."""
    monkeypatch.delenv("HAPAX_EGRESS_FOOTER_ENABLED", raising=False)
    source = EgressFooterCairoSource()

    def _boom(text: str, **_: object) -> RiskAssessment:
        raise RuntimeError("classifier unavailable")

    with patch(
        "agents.studio_compositor.egress_footer_source.validate_footer_once",
        side_effect=_boom,
    ):
        # Must not raise into compositor render loop.
        source.render_content(_ctx(), 1920, 30, t=0.0, state={})

    assert source._withheld is True


# ── registry binding ──────────────────────────────────────────────────


def test_ward_registered_under_class_name() -> None:
    """Layout JSON declares this ward via params.class_name."""
    from agents.studio_compositor.cairo_sources import _CAIRO_SOURCE_CLASSES

    assert "EgressFooterCairoSource" in _CAIRO_SOURCE_CLASSES
    assert _CAIRO_SOURCE_CLASSES["EgressFooterCairoSource"] is EgressFooterCairoSource


def test_source_id_matches_registry_convention() -> None:
    """Every CairoSource ships a stable source_id used by SourceRegistry."""
    assert EgressFooterCairoSource.source_id == "egress_footer"
