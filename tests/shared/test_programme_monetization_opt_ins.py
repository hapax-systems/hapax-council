"""Programme.monetization_opt_ins — demonet Phase 5 integration tests.

Exercises the full path:
Programme.constraints.monetization_opt_ins (envelope field) →
Programme.monetization_opt_ins (Programme-level property) →
MonetizationRiskGate.assess (Phase 1 gate) → RiskAssessment
(allowed when opt-in matches, blocked when absent).

Phase 1 of the plan shipped the gate with ``_ProgrammeLike`` Protocol
expecting ``.monetization_opt_ins`` on the programme object. Phase 5
(this cycle) makes the Programme concrete class satisfy that Protocol.
Together they close the medium-risk opt-in path.

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §5
    - docs/governance/monetization-risk-classification.md §medium
    - shared/governance/monetization_safety.py (Phase 1 gate)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.governance.monetization_safety import GATE
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeRole,
)


class _MockCandidate:
    """Minimal Candidate-shaped object matching ``_CandidateLike`` Protocol."""

    def __init__(self, name: str, risk: str, reason: str = "") -> None:
        self.capability_name = name
        self.payload: dict[str, str] = {"monetization_risk": risk}
        if reason:
            self.payload["risk_reason"] = reason


def _programme_with_opt_ins(opt_ins: set[str]) -> Programme:
    return Programme(
        programme_id="test",
        role=ProgrammeRole.SHOWCASE,
        planned_duration_s=60.0,
        parent_show_id="test-show",
        constraints=ProgrammeConstraintEnvelope(monetization_opt_ins=opt_ins),
    )


class TestEnvelopeField:
    def test_default_empty_set(self) -> None:
        env = ProgrammeConstraintEnvelope()
        assert env.monetization_opt_ins == set()

    def test_accepts_capability_names(self) -> None:
        env = ProgrammeConstraintEnvelope(
            monetization_opt_ins={"knowledge.web_search", "world.news_headlines"}
        )
        assert "knowledge.web_search" in env.monetization_opt_ins

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="must be non-empty"):
            ProgrammeConstraintEnvelope(monetization_opt_ins={""})

    def test_rejects_whitespace(self) -> None:
        with pytest.raises(ValidationError, match="whitespace"):
            ProgrammeConstraintEnvelope(monetization_opt_ins={"  padded  "})


class TestProgrammePropertyDelegation:
    def test_top_level_property_mirrors_envelope(self) -> None:
        p = _programme_with_opt_ins({"knowledge.web_search"})
        assert "knowledge.web_search" in p.monetization_opt_ins

    def test_empty_when_envelope_default(self) -> None:
        p = Programme(
            programme_id="test",
            role=ProgrammeRole.AMBIENT,
            planned_duration_s=60.0,
            parent_show_id="test-show",
        )
        assert p.monetization_opt_ins == set()


class TestEndToEndGate:
    def test_medium_passes_with_opt_in(self) -> None:
        """Medium-risk capability admitted when the Programme opts it in."""
        cand = _MockCandidate(
            name="knowledge.web_search",
            risk="medium",
            reason="Third-party web content; may include trademarks.",
        )
        programme = _programme_with_opt_ins({"knowledge.web_search"})
        result = GATE.assess(cand, programme)
        assert result.allowed is True
        assert "opted in" in result.reason

    def test_medium_blocked_without_opt_in(self) -> None:
        cand = _MockCandidate(name="knowledge.web_search", risk="medium")
        programme = _programme_with_opt_ins(set())
        result = GATE.assess(cand, programme)
        assert result.allowed is False
        assert "opt-in" in result.reason

    def test_medium_blocked_when_different_opt_in(self) -> None:
        """Opt-in is by exact capability name match, not category."""
        cand = _MockCandidate(name="knowledge.web_search", risk="medium")
        programme = _programme_with_opt_ins({"world.news_headlines"})  # different
        assert GATE.assess(cand, programme).allowed is False

    def test_high_blocked_despite_opt_in(self) -> None:
        """High-risk capability stays blocked even on programme opt-in."""
        cand = _MockCandidate(
            name="knowledge.image_search",
            risk="high",
            reason="arbitrary imagery — unconditionally blocked",
        )
        programme = _programme_with_opt_ins({"knowledge.image_search"})
        result = GATE.assess(cand, programme)
        assert result.allowed is False
        assert "unconditional" in result.reason

    def test_low_passes_without_opt_in(self) -> None:
        """Low-risk capabilities pass even without programme opt-in."""
        cand = _MockCandidate(name="knowledge.wikipedia", risk="low")
        programme = _programme_with_opt_ins(set())
        result = GATE.assess(cand, programme)
        assert result.allowed is True

    def test_none_passes_without_programme(self) -> None:
        """Default-risk capabilities need no opt-in and no programme."""
        cand = _MockCandidate(name="env.weather_conditions", risk="none")
        result = GATE.assess(cand, None)
        assert result.allowed is True


class TestFilterIntegration:
    def test_candidate_filter_admits_only_opted_in_medium(self) -> None:
        cands = [
            _MockCandidate("env.weather", "none"),
            _MockCandidate("knowledge.wikipedia", "low"),
            _MockCandidate("knowledge.web_search", "medium"),  # opted in
            _MockCandidate("world.news_headlines", "medium"),  # NOT opted in
            _MockCandidate("knowledge.image_search", "high"),  # blocked
        ]
        programme = _programme_with_opt_ins({"knowledge.web_search"})
        kept = GATE.candidate_filter(cands, programme)
        names = {c.capability_name for c in kept}
        assert names == {
            "env.weather",
            "knowledge.wikipedia",
            "knowledge.web_search",
        }
