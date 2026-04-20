"""Tests for shared.governance.classifier_degradation — fail-closed (#203)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from shared.governance.classifier_degradation import (
    ClassifierBackendDown,
    ClassifierParseError,
    ClassifierTimeout,
    ClassifierUnavailable,
    DegradationMode,
    classify_with_fallback,
)
from shared.governance.monetization_safety import RiskAssessment, SurfaceKind


@dataclass
class _OkClassifier:
    """Returns a scripted assessment on every call."""

    assessment: RiskAssessment

    def classify(
        self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
    ) -> RiskAssessment:
        return self.assessment


@dataclass
class _FailingClassifier:
    """Raises the scripted exception on every call."""

    exc: ClassifierUnavailable

    def classify(
        self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
    ) -> RiskAssessment:
        raise self.exc


class TestExceptionHierarchy:
    def test_timeout_is_unavailable(self) -> None:
        assert issubclass(ClassifierTimeout, ClassifierUnavailable)

    def test_backend_down_is_unavailable(self) -> None:
        assert issubclass(ClassifierBackendDown, ClassifierUnavailable)

    def test_parse_error_is_unavailable(self) -> None:
        assert issubclass(ClassifierParseError, ClassifierUnavailable)

    def test_reason_populated(self) -> None:
        exc = ClassifierBackendDown("TabbyAPI 502")
        assert exc.reason == "TabbyAPI 502"


class TestHappyPath:
    def test_classifier_success_passes_through(self) -> None:
        expected = RiskAssessment(allowed=True, risk="low", reason="wiki ok")
        classifier = _OkClassifier(assessment=expected)
        decision = classify_with_fallback(
            classifier,
            capability_name="knowledge.wikipedia",
            rendered_payload=None,
            surface=SurfaceKind.TTS,
        )
        assert decision.used_fallback is False
        assert decision.assessment is expected


class TestFailClosed:
    def test_backend_down_blocks(self) -> None:
        classifier = _FailingClassifier(exc=ClassifierBackendDown("TabbyAPI 502 bad gateway"))
        decision = classify_with_fallback(
            classifier,
            capability_name="knowledge.web_search",
            rendered_payload=None,
            surface=SurfaceKind.TTS,
            mode=DegradationMode.FAIL_CLOSED,
        )
        assert decision.used_fallback is True
        assert decision.assessment.allowed is False
        assert decision.assessment.risk == "medium"
        assert "fail-closed" in decision.assessment.reason
        assert "TabbyAPI 502" in decision.assessment.reason

    def test_timeout_blocks(self) -> None:
        classifier = _FailingClassifier(exc=ClassifierTimeout("classifier 3.5s > 2.0s budget"))
        decision = classify_with_fallback(
            classifier,
            capability_name="world.news_headlines",
            rendered_payload=None,
            surface=SurfaceKind.OVERLAY,
            mode=DegradationMode.FAIL_CLOSED,
        )
        assert decision.used_fallback is True
        assert decision.assessment.allowed is False

    def test_parse_error_blocks(self) -> None:
        classifier = _FailingClassifier(
            exc=ClassifierParseError("malformed JSON: expecting ',' at line 3")
        )
        decision = classify_with_fallback(
            classifier,
            capability_name="knowledge.web_search",
            rendered_payload=None,
            surface=SurfaceKind.TTS,
        )
        assert decision.used_fallback is True
        assert decision.assessment.allowed is False


class TestFailOpen:
    def test_env_override_admits_medium(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_CLASSIFIER_FAIL_OPEN", "1")
        classifier = _FailingClassifier(exc=ClassifierBackendDown("TabbyAPI 502"))
        decision = classify_with_fallback(
            classifier,
            capability_name="knowledge.web_search",
            rendered_payload=None,
            surface=SurfaceKind.TTS,
        )
        assert decision.used_fallback is True
        assert decision.assessment.allowed is True
        assert "fail-open" in decision.assessment.reason

    def test_env_unset_defaults_to_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HAPAX_CLASSIFIER_FAIL_OPEN", raising=False)
        classifier = _FailingClassifier(exc=ClassifierBackendDown("TabbyAPI 502"))
        decision = classify_with_fallback(
            classifier,
            capability_name="knowledge.web_search",
            rendered_payload=None,
            surface=SurfaceKind.TTS,
        )
        assert decision.assessment.allowed is False  # fail-closed default

    def test_explicit_mode_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit mode= parameter beats env flag."""
        monkeypatch.setenv("HAPAX_CLASSIFIER_FAIL_OPEN", "1")
        classifier = _FailingClassifier(exc=ClassifierBackendDown("TabbyAPI 502"))
        decision = classify_with_fallback(
            classifier,
            capability_name="knowledge.web_search",
            rendered_payload=None,
            surface=SurfaceKind.TTS,
            mode=DegradationMode.FAIL_CLOSED,  # explicit — wins
        )
        assert decision.assessment.allowed is False


class TestTimeoutBudget:
    def test_slow_classifier_triggers_timeout(self) -> None:
        """Classifier returning within budget but taking too long → synthetic Timeout."""
        import time as _time

        @dataclass
        class _SlowClassifier:
            delay_s: float

            def classify(
                self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
            ) -> RiskAssessment:
                _time.sleep(self.delay_s)
                return RiskAssessment(allowed=True, risk="low", reason="slow-but-ok")

        decision = classify_with_fallback(
            _SlowClassifier(delay_s=0.05),
            capability_name="knowledge.web_search",
            rendered_payload=None,
            surface=SurfaceKind.TTS,
            timeout_s=0.01,  # forces timeout path
        )
        assert decision.used_fallback is True
        assert "budget" in decision.underlying_reason


class TestUnderlyingReasonPreserved:
    def test_reason_in_decision(self) -> None:
        classifier = _FailingClassifier(exc=ClassifierBackendDown("TabbyAPI dead"))
        decision = classify_with_fallback(
            classifier,
            capability_name="x",
            rendered_payload=None,
            surface=SurfaceKind.TTS,
        )
        assert decision.underlying_reason == "TabbyAPI dead"
