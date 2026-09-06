"""Tests for MonetizationRiskGate Ring 2 integration (#202 Phase 3 / D-13).

Covers the optional ring2_classifier + surface + rendered_payload path
in MonetizationRiskGate.assess(). Verifies:

- Ring 2 not called when kwargs missing (backward compat).
- Ring 2 not called on internal surfaces (CHRONICLE / NOTIFICATION / LOG).
- Ring 1 high short-circuits Ring 2 (no GPU round-trip on unsafe caps).
- Ring 2 ESCALATES (catalog medium → ring2 high → block).
- Ring 2 cannot DE-ESCALATE (catalog high → blocked regardless of ring2).
- Ring 2 agreement with catalog keeps Programme opt-in logic intact.
- Classifier failure → fail-closed block (degraded path).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shared.governance.classifier_degradation import ClassifierBackendDown
from shared.governance.monetization_safety import (
    GATE,
    MonetizationRiskGate,
    RiskAssessment,
    SurfaceKind,
    _max_risk,
)

# ── Test scaffolding ───────────────────────────────────────────────────


@dataclass
class _Candidate:
    """Minimal candidate matching the _CandidateLike Protocol."""

    capability_name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Programme:
    """Minimal Programme matching the _ProgrammeLike Protocol."""

    monetization_opt_ins: set[str] = field(default_factory=set)


@dataclass
class _StubClassifier:
    """Returns a scripted RiskAssessment on every call."""

    assessment: RiskAssessment
    call_count: int = 0

    def classify(
        self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
    ) -> RiskAssessment:
        self.call_count += 1
        return self.assessment


@dataclass
class _FailingClassifier:
    """Raises ClassifierBackendDown on every call."""

    call_count: int = 0

    def classify(
        self, *, capability_name: str, rendered_payload: Any, surface: SurfaceKind
    ) -> RiskAssessment:
        self.call_count += 1
        raise ClassifierBackendDown("simulated classifier down")


# ── _max_risk helper ───────────────────────────────────────────────────


class TestMaxRiskHelper:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            ("none", "low", "low"),
            ("low", "none", "low"),
            ("low", "medium", "medium"),
            ("medium", "high", "high"),
            ("high", "medium", "high"),
            ("none", "none", "none"),
            ("high", "high", "high"),
        ],
    )
    def test_stricter_wins(self, a: str, b: str, expected: str) -> None:
        assert _max_risk(a, b) == expected


# ── Backward compat — no Ring 2 kwargs ─────────────────────────────────


class TestBackwardCompat:
    def test_no_ring2_kwargs_preserves_existing_behavior(self) -> None:
        """assess(candidate, programme) without Ring 2 kwargs is unchanged."""
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        result = GATE.assess(cand)
        assert result.allowed is True
        assert result.risk == "low"
        assert result.surface is None  # no surface reported when Ring 2 skipped

    def test_none_classifier_does_not_call(self) -> None:
        """Passing ring2_classifier=None (explicit) skips Ring 2."""
        cand = _Candidate("knowledge.web_search", payload={"monetization_risk": "medium"})
        # Without Programme opt-in, medium blocks.
        result = GATE.assess(cand, None, ring2_classifier=None, surface=SurfaceKind.TTS)
        assert result.allowed is False
        assert result.risk == "medium"


# ── High-risk short-circuit ────────────────────────────────────────────


class TestHighRiskShortCircuit:
    def test_ring1_high_skips_ring2(self) -> None:
        """Ring 1 high = unconditional block, no Ring 2 call."""
        cand = _Candidate(
            "knowledge.image_search",
            payload={"monetization_risk": "high", "risk_reason": "Content-ID"},
        )
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="none", reason="harmless")
        )
        result = GATE.assess(
            cand,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="anything",
        )
        assert result.allowed is False
        assert result.risk == "high"
        assert classifier.call_count == 0  # Ring 2 not consulted


# ── Internal surface pass ──────────────────────────────────────────────


class TestInternalSurfaceSkipsRing2:
    @pytest.mark.parametrize(
        "surface", [SurfaceKind.CHRONICLE, SurfaceKind.NOTIFICATION, SurfaceKind.LOG]
    )
    def test_internal_surface_does_not_call_classifier(self, surface: SurfaceKind) -> None:
        cand = _Candidate("knowledge.web_search", payload={"monetization_risk": "medium"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="high", reason="would block")
        )
        # Without Programme opt-in medium blocks, but the classifier should NOT
        # have been consulted — Ring 1 logic applies unchanged on internal surfaces.
        GATE.assess(
            cand,
            ring2_classifier=classifier,
            surface=surface,
            rendered_payload="sensitive text",
        )
        assert classifier.call_count == 0


# ── Ring 2 escalation ──────────────────────────────────────────────────


class TestRing2Escalates:
    def test_medium_to_high_escalation_blocks(self) -> None:
        """Catalog=medium, Ring 2=high → block regardless of Programme."""
        cand = _Candidate("knowledge.web_search", payload={"monetization_risk": "medium"})
        programme = _Programme(monetization_opt_ins={"knowledge.web_search"})  # opted in
        classifier = _StubClassifier(
            assessment=RiskAssessment(
                allowed=False, risk="high", reason="rendered payload contains slur"
            )
        )
        result = GATE.assess(
            cand,
            programme,
            ring2_classifier=classifier,
            surface=SurfaceKind.OVERLAY,
            rendered_payload="offensive content redacted",
        )
        assert result.allowed is False
        assert result.risk == "high"
        assert "ring2 escalated" in result.reason
        assert classifier.call_count == 1

    def test_low_to_medium_escalation_requires_opt_in(self) -> None:
        """Catalog=low, Ring 2=medium → now requires Programme opt-in."""
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(
                allowed=False, risk="medium", reason="quoted copyrighted excerpt"
            )
        )
        # No programme → blocked (medium needs opt-in).
        result = GATE.assess(
            cand,
            None,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="quote with brand name",
        )
        assert result.allowed is False
        assert result.risk == "medium"
        assert "opt-in" in result.reason
        # Escalation detail should be in the reason.
        assert "ring2" in result.reason

    def test_low_to_medium_with_opt_in_admits(self) -> None:
        """Catalog=low, Ring 2=medium, Programme opts in → admit."""
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        programme = _Programme(monetization_opt_ins={"knowledge.wikipedia"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="medium", reason="borderline")
        )
        result = GATE.assess(
            cand,
            programme,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="borderline paraphrase",
        )
        assert result.allowed is True
        assert result.risk == "medium"


# ── Ring 2 agreement ───────────────────────────────────────────────────


class TestRing2Agreement:
    def test_catalog_medium_ring2_medium_needs_opt_in(self) -> None:
        cand = _Candidate("knowledge.web_search", payload={"monetization_risk": "medium"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="medium", reason="brand in context")
        )
        # No programme → blocked.
        result = GATE.assess(
            cand,
            None,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="normal web content",
        )
        assert result.allowed is False
        assert result.risk == "medium"

    def test_catalog_low_ring2_low_admits(self) -> None:
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="low", reason="factual statement")
        )
        result = GATE.assess(
            cand,
            None,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="The Eiffel Tower is 330m tall.",
        )
        assert result.allowed is True
        assert result.risk == "low"


# ── Ring 2 cannot de-escalate below catalog ────────────────────────────


class TestRing2CannotDeEscalate:
    def test_catalog_medium_ring2_none_stays_medium(self) -> None:
        """Ring 2 saying 'none' does NOT drop below catalog's medium floor."""
        cand = _Candidate("social.phone_media", payload={"monetization_risk": "medium"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="none", reason="operator voice memo only")
        )
        # No programme → blocked, still at medium.
        result = GATE.assess(
            cand,
            None,
            ring2_classifier=classifier,
            surface=SurfaceKind.CAPTIONS,
            rendered_payload="Voice memo 2024-03-15",
        )
        assert result.allowed is False
        assert result.risk == "medium"

    def test_catalog_medium_ring2_low_stays_medium(self) -> None:
        cand = _Candidate("world.news_headlines", payload={"monetization_risk": "medium"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="low", reason="weather headline")
        )
        result = GATE.assess(
            cand,
            None,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="Minneapolis, partly cloudy, 72F",
        )
        # Catalog medium + programme opt-in missing = blocked.
        assert result.allowed is False
        assert result.risk == "medium"


# ── Degraded classifier → fail-closed block ────────────────────────────


class TestDegradedClassifier:
    def test_classifier_backend_down_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Classifier unavailable + no fail-open env → fail-closed block."""
        monkeypatch.delenv("HAPAX_CLASSIFIER_FAIL_OPEN", raising=False)
        cand = _Candidate("knowledge.web_search", payload={"monetization_risk": "medium"})
        classifier = _FailingClassifier()
        result = GATE.assess(
            cand,
            None,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="any",
        )
        assert result.allowed is False
        assert "ring2 degraded" in result.reason
        assert classifier.call_count == 1

    def test_classifier_fail_open_admits_if_opted_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fail-open env + Programme opt-in → ring2 synthesizes medium, admitted."""
        monkeypatch.setenv("HAPAX_CLASSIFIER_FAIL_OPEN", "1")
        cand = _Candidate("knowledge.web_search", payload={"monetization_risk": "medium"})
        programme = _Programme(monetization_opt_ins={"knowledge.web_search"})
        classifier = _FailingClassifier()
        result = GATE.assess(
            cand,
            programme,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="any",
        )
        # Under fail-open, classifier_degradation returns allowed=True risk=medium.
        # Then Programme has opted-in so the gate admits.
        assert result.allowed is True
        assert result.risk == "medium"


# ── Surface propagation ────────────────────────────────────────────────


class TestSurfacePropagation:
    def test_surface_flows_through_to_assessment(self) -> None:
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="low", reason="ok")
        )
        result = GATE.assess(
            cand,
            None,
            ring2_classifier=classifier,
            surface=SurfaceKind.WARD,
            rendered_payload="x",
        )
        assert result.surface == SurfaceKind.WARD


# ── Module-level gate instance reuse ────────────────────────────────────


class TestGateInstanceMethod:
    """Constructing gate instances directly works same as module-level GATE."""

    def test_instance_ring2_path(self) -> None:
        gate = MonetizationRiskGate()
        cand = _Candidate("knowledge.wikipedia", payload={"monetization_risk": "low"})
        classifier = _StubClassifier(
            assessment=RiskAssessment(allowed=True, risk="low", reason="ok")
        )
        result = gate.assess(
            cand,
            None,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="payload",
        )
        assert result.allowed is True


def test_root_sink_flagged_write(tmp_path, monkeypatch):
    import json

    from shared.governance import monetization_safety as safety

    classifier = _StubClassifier(
        RiskAssessment(allowed=False, risk="high", reason="ring2: test block")
    )
    candidate = _Candidate("test.flagged", {"monetization_risk": "low"})
    for reset in (False, True):
        # Exercise both the cached object and lazy reconstruction.
        if reset:
            monkeypatch.setattr(safety, "_FLAGGED_STORE", None)
        assessment = MonetizationRiskGate().assess(
            candidate,
            programme=None,
            ring2_classifier=classifier,
            surface=SurfaceKind.TTS,
            rendered_payload="synthetic blocked payload",
        )
        assert not assessment.allowed
    paths = list((tmp_path / "flagged-payloads").glob("*/*.jsonl"))
    assert len(paths) == 1
    rows = [json.loads(line) for line in paths[0].read_text().splitlines()]
    assert len(rows) == 2
    assert all(row["capability_name"] == candidate.capability_name for row in rows)
    assert all(row["rendered_payload"] == "synthetic blocked payload" for row in rows)


def test_root_sink_subprocess_pin_flagged(sink_subprocess):
    sink_subprocess("flagged")
