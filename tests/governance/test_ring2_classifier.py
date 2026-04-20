"""Tests for shared.governance.ring2_classifier — Phase 1 real impl (#202)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shared.governance.classifier_degradation import (
    ClassifierBackendDown,
    ClassifierParseError,
    ClassifierTimeout,
)
from shared.governance.monetization_safety import RiskAssessment, SurfaceKind
from shared.governance.ring2_classifier import (
    DISABLED_ENV,
    Ring2Classifier,
    classify_rendered_payload,
    is_disabled,
)
from shared.governance.ring2_prompts import Ring2Verdict

# ── Stub agent for classifier tests ────────────────────────────────────


@dataclass
class _StubRunResult:
    """Mimics pydantic-ai's RunResult — has .output."""

    output: Any


@dataclass
class _StubAgent:
    """Minimal pydantic-ai Agent stand-in — returns scripted verdicts."""

    verdict: Any
    raise_on_run: Exception | None = None
    call_log: list[str] = field(default_factory=list)

    def run_sync(self, prompt: str) -> _StubRunResult:
        self.call_log.append(prompt)
        if self.raise_on_run is not None:
            raise self.raise_on_run
        return _StubRunResult(output=self.verdict)


def _cls_with_stub(stub: _StubAgent, surface: SurfaceKind = SurfaceKind.TTS) -> Ring2Classifier:
    """Build a classifier with the per-surface agent pre-seeded."""
    cls = Ring2Classifier()
    cls._agents_by_surface[surface] = stub
    return cls


# ── Internal-surface pass-through ──────────────────────────────────────


class TestInternalSurfacesPassThrough:
    """CHRONICLE / NOTIFICATION / LOG never invoke the LLM."""

    @pytest.mark.parametrize(
        "surface", [SurfaceKind.CHRONICLE, SurfaceKind.NOTIFICATION, SurfaceKind.LOG]
    )
    def test_default_pass(self, surface: SurfaceKind) -> None:
        # Stub agent that would fail if called — test proves it isn't.
        stub = _StubAgent(
            verdict=Ring2Verdict(allowed=False, risk="high", reason="should never be called")
        )
        cls = _cls_with_stub(stub, surface=surface)
        assessment = cls.classify(
            capability_name="system.cost_pressure",
            rendered_payload={"value": 0.42},
            surface=surface,
        )
        assert assessment.allowed is True
        assert assessment.risk == "none"
        assert "internal surface" in assessment.reason
        assert surface.value in assessment.reason
        assert stub.call_log == []  # LLM never called


# ── Broadcast-surface classify ─────────────────────────────────────────


class TestClassifyBroadcastSurfaces:
    @pytest.mark.parametrize(
        "surface",
        [SurfaceKind.TTS, SurfaceKind.CAPTIONS, SurfaceKind.OVERLAY, SurfaceKind.WARD],
    )
    def test_low_risk_admitted(self, surface: SurfaceKind) -> None:
        stub = _StubAgent(
            verdict=Ring2Verdict(allowed=True, risk="low", reason="wikipedia excerpt; CC-BY-SA")
        )
        cls = _cls_with_stub(stub, surface=surface)
        assessment = cls.classify(
            capability_name="knowledge.wikipedia",
            rendered_payload="The Eiffel Tower was completed in 1889.",
            surface=surface,
        )
        assert assessment.allowed is True
        assert assessment.risk == "low"
        assert assessment.surface == surface
        assert "CC-BY-SA" in assessment.reason
        assert len(stub.call_log) == 1
        assert "wikipedia" in stub.call_log[0]

    def test_high_risk_blocks_even_if_llm_says_allowed(self) -> None:
        """Defensive: if the LLM sets risk=high but allowed=true, we still block."""
        stub = _StubAgent(
            verdict=Ring2Verdict(
                allowed=True,  # bogus — LLM-confused
                risk="high",
                reason="content-id fingerprint risk",
            )
        )
        cls = _cls_with_stub(stub)
        assessment = cls.classify(
            capability_name="knowledge.image_search",
            rendered_payload={"url": "https://example.com/movie-still.jpg"},
            surface=SurfaceKind.TTS,
        )
        # High-risk always blocks regardless of LLM's `allowed`.
        assert assessment.allowed is False
        assert assessment.risk == "high"

    def test_medium_risk_admitted_when_llm_allows(self) -> None:
        stub = _StubAgent(
            verdict=Ring2Verdict(
                allowed=True,
                risk="medium",
                reason="brand name in safe context",
            )
        )
        cls = _cls_with_stub(stub)
        assessment = cls.classify(
            capability_name="world.news_headlines",
            rendered_payload="Apple reports quarterly earnings.",
            surface=SurfaceKind.TTS,
        )
        assert assessment.allowed is True
        assert assessment.risk == "medium"


class TestUnknownRiskRejected:
    def test_invalid_risk_raises_parse_error(self) -> None:
        # Bypass Ring2Verdict's pydantic validation by passing a raw string
        # to _verdict_from_str — simulates LLM emitting garbage risk.
        cls = Ring2Classifier()
        with pytest.raises(ClassifierParseError, match="unknown risk"):
            cls._parse_verdict('{"allowed": false, "risk": "extreme", "reason": "x"}')


# ── Error-path handling ────────────────────────────────────────────────


class TestBackendFailure:
    def test_timeout_raises_classifier_timeout(self) -> None:
        stub = _StubAgent(
            verdict=Ring2Verdict(allowed=True, risk="none", reason="x"),
            raise_on_run=TimeoutError("request exceeded budget"),
        )
        cls = _cls_with_stub(stub)
        with pytest.raises(ClassifierTimeout, match="timed out"):
            cls.classify(
                capability_name="x",
                rendered_payload="y",
                surface=SurfaceKind.TTS,
            )

    def test_generic_exception_raises_backend_down(self) -> None:
        stub = _StubAgent(
            verdict=Ring2Verdict(allowed=True, risk="none", reason="x"),
            raise_on_run=RuntimeError("TabbyAPI 502"),
        )
        cls = _cls_with_stub(stub)
        with pytest.raises(ClassifierBackendDown, match="TabbyAPI 502"):
            cls.classify(
                capability_name="x",
                rendered_payload="y",
                surface=SurfaceKind.TTS,
            )


# ── _parse_verdict + _verdict_from_str ─────────────────────────────────


class TestParseVerdict:
    """_parse_verdict is kept for backward compat + ad-hoc benchmark use."""

    def _cls(self) -> Ring2Classifier:
        return Ring2Classifier()

    def test_valid_json(self) -> None:
        assessment = self._cls()._parse_verdict(
            '{"allowed": true, "risk": "low", "reason": "fair-use snippet"}'
        )
        assert assessment.allowed is True
        assert assessment.risk == "low"
        assert "fair-use" in assessment.reason

    def test_fenced_json_tolerated(self) -> None:
        """LiteLLM local-fast sometimes wraps JSON in markdown fences."""
        fenced = '```json\n{"allowed": true, "risk": "none", "reason": "ok"}\n```'
        assessment = self._cls()._parse_verdict(fenced)
        assert assessment.risk == "none"
        assert assessment.allowed is True

    def test_fenced_no_lang_tag(self) -> None:
        fenced = '```\n{"allowed": false, "risk": "high", "reason": "block"}\n```'
        assessment = self._cls()._parse_verdict(fenced)
        assert assessment.risk == "high"
        # high always blocks regardless of llm allowed.
        assert assessment.allowed is False

    def test_invalid_json_raises_parse_error(self) -> None:
        with pytest.raises(ClassifierParseError, match="non-JSON"):
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


# ── Coerce-verdict input-shape tolerance ───────────────────────────────


class TestCoerceVerdict:
    """Multiple stub shapes all resolve to Ring2Verdict."""

    def test_direct_verdict(self) -> None:
        verdict = Ring2Verdict(allowed=True, risk="low", reason="ok")
        out = Ring2Classifier._coerce_verdict(verdict)
        assert out is verdict

    def test_run_result_with_verdict_output(self) -> None:
        class _Res:
            output = Ring2Verdict(allowed=True, risk="none", reason="x")

        out = Ring2Classifier._coerce_verdict(_Res())
        assert out.risk == "none"

    def test_run_result_with_dict_output(self) -> None:
        class _Res:
            output = {"allowed": True, "risk": "low", "reason": "y"}

        out = Ring2Classifier._coerce_verdict(_Res())
        assert out.risk == "low"

    def test_run_result_with_string_output(self) -> None:
        class _Res:
            output = '{"allowed": true, "risk": "none", "reason": "z"}'

        out = Ring2Classifier._coerce_verdict(_Res())
        assert out.risk == "none"

    def test_direct_dict(self) -> None:
        out = Ring2Classifier._coerce_verdict({"allowed": False, "risk": "high", "reason": "block"})
        assert out.risk == "high"

    def test_direct_string(self) -> None:
        out = Ring2Classifier._coerce_verdict(
            '{"allowed": true, "risk": "medium", "reason": "opt-in"}'
        )
        assert out.risk == "medium"

    def test_unexpected_type_raises(self) -> None:
        with pytest.raises(ClassifierParseError, match="unexpected"):
            Ring2Classifier._coerce_verdict(42)


# ── Env overrides ──────────────────────────────────────────────────────


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

    def test_returns_decision_with_stub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Injectable classifier — full round-trip through fail-closed wrapper."""
        monkeypatch.delenv(DISABLED_ENV, raising=False)
        monkeypatch.delenv("HAPAX_CLASSIFIER_FAIL_OPEN", raising=False)

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

    def test_internal_surface_pass_without_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Real classifier on internal surface — no LLM, no fallback."""
        monkeypatch.delenv(DISABLED_ENV, raising=False)
        result = classify_rendered_payload(
            capability_name="system.cost_pressure",
            rendered_payload={"value": 0.5},
            surface=SurfaceKind.LOG,
        )
        assert result is not None
        assert result.used_fallback is False
        assert result.assessment.risk == "none"
        assert result.assessment.allowed is True
