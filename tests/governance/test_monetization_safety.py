"""Tests for shared.governance.monetization_safety — Phase 1 primitive.

Covers the pure candidate_filter semantics + assess() contract. Pipeline-
integration is exercised in tests/pipeline/test_affordance_pipeline_monetization_filter.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shared.governance.monetization_safety import (
    GATE,
    MonetizationRiskGate,
    RiskAssessment,
    SurfaceKind,
    assess,
    candidate_filter,
)


@dataclass
class _FakeCandidate:
    capability_name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeProgramme:
    monetization_opt_ins: set[str]


class TestOperationalPropertiesDefault:
    def test_risk_defaults_to_unknown(self) -> None:
        from shared.affordance import OperationalProperties

        assert OperationalProperties().monetization_risk == "unknown"
        assert OperationalProperties().risk_reason is None
        assert OperationalProperties().content_risk == "unknown"
        assert OperationalProperties().public_capable is False


class TestAssessHighAlwaysBlocks:
    def test_high_risk_blocked_without_programme(self) -> None:
        cand = _FakeCandidate("mouth.broadcast", {"monetization_risk": "high"})
        r = GATE.assess(cand, programme=None)
        assert r.allowed is False
        assert r.risk == "high"
        assert "high-risk" in r.reason

    def test_high_risk_blocked_even_with_opt_in(self) -> None:
        cand = _FakeCandidate("mouth.broadcast", {"monetization_risk": "high"})
        prog = _FakeProgramme(monetization_opt_ins={"mouth.broadcast"})
        r = GATE.assess(cand, programme=prog)
        assert r.allowed is False  # high CANNOT be opted in


class TestAssessMediumGatedByProgramme:
    def test_medium_blocked_without_programme(self) -> None:
        cand = _FakeCandidate("album_splatter", {"monetization_risk": "medium"})
        r = GATE.assess(cand, programme=None)
        assert r.allowed is False
        assert r.risk == "medium"
        assert "requires programme opt-in" in r.reason

    def test_medium_blocked_with_programme_no_opt_in(self) -> None:
        cand = _FakeCandidate("album_splatter", {"monetization_risk": "medium"})
        prog = _FakeProgramme(monetization_opt_ins={"something_else"})
        r = GATE.assess(cand, programme=prog)
        assert r.allowed is False

    def test_medium_allowed_with_opt_in(self) -> None:
        cand = _FakeCandidate("album_splatter", {"monetization_risk": "medium"})
        prog = _FakeProgramme(monetization_opt_ins={"album_splatter"})
        r = GATE.assess(cand, programme=prog)
        assert r.allowed is True
        assert "opted in" in r.reason


class TestAssessLowAndNonePass:
    def test_low_passes(self) -> None:
        cand = _FakeCandidate("neutral_narrate", {"monetization_risk": "low"})
        r = GATE.assess(cand, programme=None)
        assert r.allowed is True
        assert r.risk == "low"

    def test_none_passes(self) -> None:
        cand = _FakeCandidate("tick", {"monetization_risk": "none"})
        r = GATE.assess(cand, programme=None)
        assert r.allowed is True
        assert r.risk == "none"

    def test_missing_public_risk_treated_as_unknown_and_blocked(self) -> None:
        cand = _FakeCandidate("unlabelled", payload={"public_capable": True})
        r = GATE.assess(cand, programme=None)
        assert r.allowed is False
        assert r.risk == "unknown"
        assert "fail closed" in r.reason

    def test_missing_private_risk_does_not_block_internal_capability(self) -> None:
        cand = _FakeCandidate("internal-only", payload={"public_capable": False})
        r = GATE.assess(cand, programme=None)
        assert r.allowed is True
        assert r.risk == "unknown"

    def test_stale_public_medium_without_risk_fails_closed(self) -> None:
        cand = _FakeCandidate("stale-visual", payload={"medium": "visual"})
        r = GATE.assess(cand, programme=None)
        assert r.allowed is False
        assert r.risk == "unknown"

    def test_unknown_public_risk_blocks(self) -> None:
        cand = _FakeCandidate(
            "public-unknown",
            payload={"public_capable": True, "monetization_risk": "unknown"},
        )
        r = GATE.assess(cand, programme=None)
        assert r.allowed is False
        assert r.risk == "unknown"


class TestCandidateFilter:
    def test_filter_removes_high_always(self) -> None:
        cands = [
            _FakeCandidate("safe", {"monetization_risk": "none"}),
            _FakeCandidate("banned", {"monetization_risk": "high"}),
            _FakeCandidate("safe2", {"monetization_risk": "low"}),
        ]
        kept = GATE.candidate_filter(cands, programme=None)
        assert [c.capability_name for c in kept] == ["safe", "safe2"]

    def test_filter_gates_medium_on_opt_in(self) -> None:
        cands = [
            _FakeCandidate("a", {"monetization_risk": "medium"}),
            _FakeCandidate("b", {"monetization_risk": "medium"}),
            _FakeCandidate("c", {"monetization_risk": "none"}),
        ]
        prog = _FakeProgramme(monetization_opt_ins={"b"})
        kept = GATE.candidate_filter(cands, programme=prog)
        assert [c.capability_name for c in kept] == ["b", "c"]

    def test_filter_is_pure(self) -> None:
        """Running the filter twice yields the same candidates; no mutation."""
        cands = [
            _FakeCandidate("a", {"monetization_risk": "medium"}),
            _FakeCandidate("b", {"monetization_risk": "high"}),
            _FakeCandidate("c", {"monetization_risk": "none"}),
        ]
        first = GATE.candidate_filter(cands, programme=None)
        second = GATE.candidate_filter(cands, programme=None)
        assert [c.capability_name for c in first] == [c.capability_name for c in second]
        # Original list untouched.
        assert [c.capability_name for c in cands] == ["a", "b", "c"]

    def test_filter_empty_list(self) -> None:
        assert GATE.candidate_filter([], programme=None) == []


class TestModuleLevelSingleton:
    def test_module_level_convenience_functions_use_singleton(self) -> None:
        cand = _FakeCandidate("x", {"monetization_risk": "high"})
        assert candidate_filter([cand], programme=None) == []
        assert assess(cand, programme=None).allowed is False

    def test_gate_instance_is_shared(self) -> None:
        assert isinstance(GATE, MonetizationRiskGate)


class TestRiskAssessmentIsFrozen:
    def test_assessment_is_immutable(self) -> None:
        r = RiskAssessment(allowed=True, risk="low", reason="x")
        with pytest.raises(Exception):
            r.allowed = False  # type: ignore[misc]  # noqa: A001


class TestSurfaceKindEnum:
    def test_has_seven_surfaces(self) -> None:
        assert len(list(SurfaceKind)) == 7
        assert SurfaceKind.TTS.value == "tts"
        assert SurfaceKind.CAPTIONS.value == "captions"
