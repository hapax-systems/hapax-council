"""Tests for shared.governance.ring2_classifier — Phase 0 skeleton (#202)."""

from __future__ import annotations

from typing import Any

import pytest

from shared.governance.classifier_degradation import (
    ClassifierBackendDown,
    ClassifierParseError,
)
from shared.governance.monetization_safety import RiskAssessment, SurfaceKind
from shared.governance.ring2_classifier import (
    DISABLED_ENV,
    Ring2Classifier,
    classify_rendered_payload,
    is_disabled,
)


class TestSkeletonRaisesClassifierUnavailable:
    """Phase 0: classify always raises; fail-closed path handles the rest."""

    def test_raises_backend_down(self) -> None:
        cls = Ring2Classifier()
        with pytest.raises(ClassifierBackendDown) as ei:
            cls.classify(
                capability_name="knowledge.web_search",
                rendered_payload=None,
                surface=SurfaceKind.TTS,
            )
        assert "Phase 0" in str(ei.value) or "skeleton" in str(ei.value)


class TestParseVerdict:
    """_parse_verdict ships the eventual Phase 1 contract."""

    def _cls(self) -> Ring2Classifier:
        return Ring2Classifier()

    def test_valid_json(self) -> None:
        assessment = self._cls()._parse_verdict(
            '{"allowed": true, "risk": "low", "reason": "fair-use snippet"}'
        )
        assert assessment.allowed is True
        assert assessment.risk == "low"
        assert "fair-use" in assessment.reason

    def test_invalid_json_raises_parse_error(self) -> None:
        with pytest.raises(ClassifierParseError):
            self._cls()._parse_verdict("{not json")

    def test_unknown_risk_level(self) -> None:
        with pytest.raises(ClassifierParseError, match="unknown risk"):
            self._cls()._parse_verdict('{"allowed": false, "risk": "extreme", "reason": "x"}')

    def test_non_bool_allowed(self) -> None:
        with pytest.raises(ClassifierParseError, match="allowed not a bool"):
            self._cls()._parse_verdict('{"allowed": "yes", "risk": "low", "reason": "x"}')

    def test_non_object_response(self) -> None:
        with pytest.raises(ClassifierParseError, match="not a JSON object"):
            self._cls()._parse_verdict("[1, 2, 3]")


class TestIsDisabled:
    def test_unset_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(DISABLED_ENV, raising=False)
        assert is_disabled() is False

    def test_one_is_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DISABLED_ENV, "1")
        assert is_disabled() is True

    def test_other_values_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only exact '1' disables; other truthy values don't."""
        monkeypatch.setenv(DISABLED_ENV, "true")
        assert is_disabled() is False


class TestClassifyRenderedPayload:
    def test_returns_none_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DISABLED_ENV, "1")
        result = classify_rendered_payload(
            capability_name="knowledge.web_search",
            rendered_payload="something",
            surface=SurfaceKind.TTS,
        )
        assert result is None

    def test_returns_fallback_decision_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Phase 0 skeleton → fail-closed fires → decision.used_fallback=True."""
        monkeypatch.delenv(DISABLED_ENV, raising=False)
        monkeypatch.delenv("HAPAX_CLASSIFIER_FAIL_OPEN", raising=False)
        result = classify_rendered_payload(
            capability_name="knowledge.web_search",
            rendered_payload="test payload",
            surface=SurfaceKind.TTS,
        )
        assert result is not None
        assert result.used_fallback is True
        assert result.assessment.allowed is False  # fail-closed default
        assert "Phase 0" in result.assessment.reason or "skeleton" in result.assessment.reason

    def test_injectable_classifier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Callers can pass a stub for testing / future Phase 1 impl."""
        monkeypatch.delenv(DISABLED_ENV, raising=False)

        class _StubClassifier:
            def classify(
                self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
            ) -> RiskAssessment:
                return RiskAssessment(allowed=True, risk="low", reason="stub ok")

        result = classify_rendered_payload(
            capability_name="x",
            rendered_payload="y",
            surface=SurfaceKind.TTS,
            classifier=_StubClassifier(),  # type: ignore[arg-type]
        )
        assert result is not None
        assert result.used_fallback is False
        assert result.assessment.allowed is True


class TestPhase1ReadinessGuard:
    """Ensure Phase 1 migration catches this — if someone lands the prompts
    without removing the ``Phase 0`` sentinel, the test forces an update."""

    def test_phase_marker_present(self) -> None:
        """When Phase 1 lands, remove the 'Phase 0 skeleton' language from
        the classify method + delete this test."""
        cls = Ring2Classifier()
        try:
            cls.classify(
                capability_name="x",
                rendered_payload=None,
                surface=SurfaceKind.TTS,
            )
        except ClassifierBackendDown as e:
            assert "Phase 0" in str(e) or "skeleton" in str(e)
