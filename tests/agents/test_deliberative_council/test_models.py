from __future__ import annotations

import json

import pytest

from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
    PhaseOneResult,
)
from agents.deliberative_council.rubrics import (
    DisconfirmationRubric,
    EpistemicQualityRubric,
)


class TestCouncilInput:
    def test_validates_with_required_fields(self) -> None:
        inp = CouncilInput(text="Some claim about X.", source_ref="docs/research/x.md")
        assert inp.text == "Some claim about X."
        assert inp.metadata == {}

    def test_frozen(self) -> None:
        inp = CouncilInput(text="test", source_ref="test")
        with pytest.raises(Exception):
            inp.text = "changed"  # type: ignore[misc]


class TestCouncilMode:
    def test_all_four_modes(self) -> None:
        assert set(CouncilMode) == {"labeling", "scoring", "disconfirmation", "audit"}


class TestConvergenceStatus:
    def test_all_three_statuses(self) -> None:
        assert set(ConvergenceStatus) == {"converged", "contested", "hung"}


class TestPhaseOneResult:
    def test_validates(self) -> None:
        r = PhaseOneResult(
            model_alias="opus",
            scores={"axis_a": 4, "axis_b": 3},
            rationale={"axis_a": "good evidence", "axis_b": "weak source"},
            research_findings=["file exists at path X"],
            tool_calls_log=["read_source('docs/x.md')"],
        )
        assert r.scores["axis_a"] == 4


class TestCouncilVerdict:
    def test_serializes_to_json(self) -> None:
        v = CouncilVerdict(
            scores={"axis_a": 4},
            confidence_bands={"axis_a": (3, 5)},
            convergence_status=ConvergenceStatus.CONVERGED,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            adversarial_exchanges=(),
            receipt={"input_hash": "abc123", "model_versions": {}},
        )
        data = json.loads(v.model_dump_json())
        assert data["convergence_status"] == "converged"

    def test_frozen(self) -> None:
        v = CouncilVerdict(
            scores={},
            confidence_bands={},
            convergence_status=ConvergenceStatus.HUNG,
            disagreement_log=[],
            research_findings=[],
            evidence_matrix=None,
            adversarial_exchanges=(),
            receipt={},
        )
        with pytest.raises(Exception):
            v.scores = {"hacked": 1}  # type: ignore[misc]


class TestRubrics:
    def test_epistemic_quality_rubric_has_4_axes(self) -> None:
        r = EpistemicQualityRubric()
        assert len(r.axes) == 4
        axis_names = {a.name for a in r.axes}
        assert axis_names == {
            "claim_evidence_alignment",
            "hedge_calibration",
            "quantifier_precision",
            "source_grounding",
        }

    def test_disconfirmation_rubric_has_axes(self) -> None:
        r = DisconfirmationRubric()
        assert len(r.axes) >= 3

    def test_rubric_axis_has_scale(self) -> None:
        r = EpistemicQualityRubric()
        for axis in r.axes:
            assert axis.min_score == 1
            assert axis.max_score == 5
            assert axis.description
            assert axis.strong_example
            assert axis.weak_example
