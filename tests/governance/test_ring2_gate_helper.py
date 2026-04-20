"""Tests for shared.governance.ring2_gate_helper — one-call wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shared.governance.monetization_safety import RiskAssessment, SurfaceKind
from shared.governance.ring2_gate_helper import (
    default_classifier,
    reset_default_classifier,
    resolve_surface,
    ring2_assess,
)


@dataclass
class _Candidate:
    capability_name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _StubClassifier:
    assessment: RiskAssessment
    call_count: int = 0

    def classify(
        self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
    ) -> RiskAssessment:
        self.call_count += 1
        return self.assessment


class TestResolveSurface:
    @pytest.mark.parametrize(
        ("medium", "expected"),
        [
            ("auditory", SurfaceKind.TTS),
            ("visual", SurfaceKind.WARD),
            ("textual", SurfaceKind.OVERLAY),
            ("notification", SurfaceKind.NOTIFICATION),
        ],
    )
    def test_canonical_mediums(self, medium: str, expected: SurfaceKind) -> None:
        assert resolve_surface(medium) == expected

    def test_none_returns_none(self) -> None:
        assert resolve_surface(None) is None

    def test_empty_returns_none(self) -> None:
        assert resolve_surface("") is None

    def test_unknown_returns_none(self) -> None:
        assert resolve_surface("holographic") is None


class TestDefaultClassifier:
    def test_lazy_construction(self) -> None:
        reset_default_classifier()
        cls = default_classifier()
        # Subsequent calls return the same instance.
        assert default_classifier() is cls

    def test_reset_clears_singleton(self) -> None:
        reset_default_classifier()
        first = default_classifier()
        reset_default_classifier()
        second = default_classifier()
        assert first is not second


class TestRing2Assess:
    def test_degrade_to_ring1_without_medium_or_surface(self) -> None:
        """No medium + no surface = Ring 1 only, no classifier."""
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        # Use a stub classifier to prove it's NOT called when surface is absent.
        stub = _StubClassifier(
            assessment=RiskAssessment(allowed=False, risk="high", reason="would block")
        )
        result = ring2_assess(cand, None, classifier=stub)
        assert result.allowed is True
        assert result.risk == "low"
        assert stub.call_count == 0

    def test_auditory_medium_invokes_ring2(self) -> None:
        """Medium=auditory → TTS surface → classifier called."""
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        stub = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="low", reason="safe excerpt")
        )
        result = ring2_assess(cand, None, medium="auditory", classifier=stub)
        assert result.allowed is True
        assert stub.call_count == 1

    def test_explicit_surface_overrides_medium(self) -> None:
        """Explicit surface= wins over medium-derived surface."""
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        stub = _StubClassifier(assessment=RiskAssessment(allowed=True, risk="low", reason="ok"))
        result = ring2_assess(
            cand,
            None,
            medium="auditory",  # would map to TTS
            surface=SurfaceKind.WARD,  # explicit override
            classifier=stub,
        )
        assert result.allowed is True
        assert result.surface == SurfaceKind.WARD

    def test_notification_surface_skips_classifier(self) -> None:
        """notification medium → NOTIFICATION surface → internal, no LLM."""
        cand = _Candidate("system.notify_operator", payload={"monetization_risk": "none"})
        stub = _StubClassifier(
            assessment=RiskAssessment(allowed=False, risk="high", reason="would block")
        )
        result = ring2_assess(cand, None, medium="notification", classifier=stub)
        assert result.allowed is True
        assert stub.call_count == 0  # NOTIFICATION is internal

    def test_textual_medium_classifier_escalates(self) -> None:
        """medium=textual → OVERLAY → classifier can escalate."""
        cand = _Candidate(
            "world.news_headlines",
            payload={"monetization_risk": "medium", "risk_reason": "brand mention"},
        )
        stub = _StubClassifier(
            assessment=RiskAssessment(
                allowed=False, risk="high", reason="political firebrand content"
            )
        )
        result = ring2_assess(
            cand,
            None,
            medium="textual",
            rendered_payload="Headline: [political figure] commits crime (unverified)",
            classifier=stub,
        )
        assert result.allowed is False
        assert result.risk == "high"
        assert "ring2 escalated" in result.reason


class TestModuleLevelIntegration:
    def test_default_classifier_used_when_none_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ring2_assess falls back to default_classifier() when no classifier kwarg."""
        # The default classifier raises ClassifierBackendDown (Phase 1
        # skeleton body is gone but Agent construction without LITELLM_API_KEY
        # still works — just the classify() call would fail at invocation).
        # Instead test that a classifier is resolved.
        reset_default_classifier()
        cand = _Candidate("knowledge.web_search", payload={"monetization_risk": "medium"})
        # Monkeypatch default_classifier to our stub.
        stub = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="medium", reason="safe")
        )
        monkeypatch.setattr("shared.governance.ring2_gate_helper.default_classifier", lambda: stub)
        result = ring2_assess(cand, None, medium="auditory")
        # Medium-risk with no programme opt-in → blocked.
        assert result.allowed is False
        assert stub.call_count == 1
