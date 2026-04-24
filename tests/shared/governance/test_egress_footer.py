"""Tests for the anti-personification egress footer module.

FINDING ef7b-165 Phase 9 (delta, 2026-04-24). Pins the footer text
template + env-driven render + Ring 2 validation wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from shared.governance.egress_footer import (
    DEFAULT_OPERATOR_NAME,
    DEFAULT_RESEARCH_HOME_URL,
    ENV_OPERATOR_NAME,
    ENV_RESEARCH_HOME_URL,
    FOOTER_TEMPLATE,
    render_footer_text,
    validate_footer_once,
)
from shared.governance.monetization_safety import RiskAssessment, SurfaceKind


@dataclass
class _StubClassifier:
    """Minimal Ring2Classifier stand-in. Records calls; returns fixed verdict."""

    verdict: RiskAssessment
    calls: list[dict[str, Any]]

    def classify(
        self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
    ) -> RiskAssessment:
        self.calls.append(
            {
                "capability_name": capability_name,
                "rendered_payload": rendered_payload,
                "surface": surface,
            }
        )
        return self.verdict


# ── render_footer_text ────────────────────────────────────────────────


def test_render_uses_explicit_args_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_OPERATOR_NAME, "env_name")
    monkeypatch.setenv(ENV_RESEARCH_HOME_URL, "env.example.com")

    text = render_footer_text(
        operator_name="explicit_name",
        research_home_url="explicit.example.com",
    )

    assert "explicit_name" in text
    assert "explicit.example.com" in text
    assert "env_name" not in text


def test_render_reads_env_when_args_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_OPERATOR_NAME, "env_name")
    monkeypatch.setenv(ENV_RESEARCH_HOME_URL, "env.example.com")

    text = render_footer_text()

    assert "env_name" in text
    assert "env.example.com" in text


def test_render_falls_back_to_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_OPERATOR_NAME, raising=False)
    monkeypatch.delenv(ENV_RESEARCH_HOME_URL, raising=False)

    text = render_footer_text()

    assert DEFAULT_OPERATOR_NAME in text
    assert DEFAULT_RESEARCH_HOME_URL in text


def test_template_leads_with_research_instrument_framing() -> None:
    """Anti-personification core: first words must frame instrument-not-agent."""
    assert FOOTER_TEMPLATE.startswith(">>> Council research instrument")


def test_template_does_not_claim_sentience() -> None:
    """Regression pin: no footer text ever claims Hapax has a mind/feelings."""
    text = render_footer_text()
    banned = ("I am", "I feel", "sentient", "conscious", "alive")
    lowered = text.lower()
    for phrase in banned:
        assert phrase.lower() not in lowered, (
            f"Footer must not claim personhood — forbidden phrase: {phrase!r}"
        )


# ── validate_footer_once ──────────────────────────────────────────────


def test_validate_sends_overlay_surface_to_classifier() -> None:
    verdict = RiskAssessment(
        allowed=True, risk="none", reason="stub pass", surface=SurfaceKind.OVERLAY
    )
    stub = _StubClassifier(verdict=verdict, calls=[])
    text = render_footer_text()

    result = validate_footer_once(text, classifier=stub)

    assert result is verdict
    assert len(stub.calls) == 1
    assert stub.calls[0]["surface"] is SurfaceKind.OVERLAY
    assert stub.calls[0]["capability_name"] == "egress_footer"
    assert stub.calls[0]["rendered_payload"] == text


def test_validate_returns_non_allowed_verdict_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fail-closed means the *caller* refuses to ship on ``allowed=False``.

    This module logs but does not raise — the policy decision belongs
    to the caller (matching the Ring 2 pattern elsewhere).
    """
    verdict = RiskAssessment(
        allowed=False,
        risk="high",
        reason="stub reject",
        surface=SurfaceKind.OVERLAY,
    )
    stub = _StubClassifier(verdict=verdict, calls=[])

    import logging as _logging

    with caplog.at_level(_logging.WARNING, logger="shared.governance.egress_footer"):
        result = validate_footer_once("does not matter", classifier=stub)

    assert result is verdict
    assert any("rejected by Ring 2" in rec.getMessage() for rec in caplog.records)
