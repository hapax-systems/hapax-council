"""Unit tests for agents.metadata_composer.redaction."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

from agents.metadata_composer import redaction


@dataclass
class _FakeAssessment:
    risk: str


def test_no_backticks_returns_unchanged():
    prose = "Plain prose with no capability mentions."
    assert redaction.redact_capabilities(prose, programme=None) == prose


def test_low_risk_capability_passes_through():
    prose = "Currently recruiting `safe_capability`."
    with patch(
        "shared.governance.monetization_safety.assess",
        return_value=_FakeAssessment(risk="none"),
    ):
        out = redaction.redact_capabilities(prose, programme=None)
    assert "safe_capability" in out


def test_medium_risk_capability_redacted():
    prose = "Currently recruiting `borderline_capability`."
    with patch(
        "shared.governance.monetization_safety.assess",
        return_value=_FakeAssessment(risk="medium"),
    ):
        out = redaction.redact_capabilities(prose, programme=None)
    assert "borderline_capability" not in out
    assert "creative-expression" in out


def test_high_risk_capability_redacted():
    prose = "Currently recruiting `risky_capability`."
    with patch(
        "shared.governance.monetization_safety.assess",
        return_value=_FakeAssessment(risk="high"),
    ):
        out = redaction.redact_capabilities(prose, programme=None)
    assert "risky_capability" not in out
    assert "creative-expression" in out


def test_unreachable_gate_returns_input():
    prose = "Currently recruiting `something`."
    with patch(
        "shared.governance.monetization_safety.assess",
        side_effect=RuntimeError("module gone"),
    ):
        out = redaction.redact_capabilities(prose, programme=None)
    assert out == prose


def test_multiple_capabilities_redacted_independently():
    prose = "Recruiting `safe_one` and `risky_two`."

    def assess(candidate, _programme):
        if "risky" in candidate.capability_name:
            return _FakeAssessment(risk="high")
        return _FakeAssessment(risk="none")

    with patch("shared.governance.monetization_safety.assess", side_effect=assess):
        out = redaction.redact_capabilities(prose, programme=None)
    assert "safe_one" in out
    assert "risky_two" not in out
    assert "creative-expression" in out


def test_non_identifier_backticks_untouched():
    prose = "See `quoted phrase with spaces` for details."
    out = redaction.redact_capabilities(prose, programme=None)
    assert out == prose
