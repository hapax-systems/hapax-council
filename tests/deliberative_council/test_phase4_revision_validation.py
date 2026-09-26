"""Revision boundaries exercised through real phases with synthetic member calls."""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest

from agents.deliberative_council import engine
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
    Phase1Output,
    sanitize_execution_receipt,
)
from agents.deliberative_council.rubrics import DisconfirmationRubric, EpistemicQualityRubric

_ALIASES = ("synthetic-amber", "synthetic-blue", "synthetic-copper", "synthetic-dusk")
_SERVED = (
    "claude-synthetic-phase1",
    "gemini-synthetic-phase1",
    "mistral-synthetic-phase1",
    "sonar-synthetic-phase1",
)
_RUBRIC = DisconfirmationRubric()
_AXIS = _RUBRIC.axes[0].name


def _scores(value):
    return {axis.name: value for axis in _RUBRIC.axes}


async def _deliberate_revision(payload, *, rubric=_RUBRIC, scored_axes=None):
    """Only member construction, admission lookup and calls are replaced."""
    calls = []

    async def call_member(alias, prompt, *, output_type=None, **_kwargs):
        calls.append((alias, prompt))
        index = _ALIASES.index(alias)
        if output_type is not None:
            return (
                Phase1Output(
                    scores={
                        axis: 1 if index < 2 else 5
                        for axis in (_scores(1) if scored_axes is None else scored_axes)
                    },
                    research_findings=[f"synthetic:source:{index}"],
                ),
                [],
                _SERVED[index],
            )
        if prompt.startswith("You are revising your scores"):
            if isinstance(payload, Exception):
                raise payload
            return payload, [], f"synthetic-phase4-{alias}"
        if "building an Analysis" in prompt:
            return json.dumps({"axes": {_AXIS: {"least_inconsistent_score": 3}}}), [], ""
        return "synthetic inspectable evidence", [], ""

    with (
        patch.object(engine, "build_member", side_effect=lambda alias, **_kwargs: alias),
        patch.object(engine, "member_capability_admission", return_value=None),
        patch.object(engine, "_call_member", side_effect=call_member),
    ):
        verdict = await engine.deliberate(
            CouncilInput(
                text="synthetic claim",
                source_ref="synthetic:source",
                source_context="synthetic context",
            ),
            CouncilMode.DISCONFIRMATION,
            rubric,
            CouncilConfig(model_aliases=_ALIASES),
        )
    return verdict, calls


def _assert_retained(verdict, reason, *, status="rejected", served=True):
    assert verdict.convergence_status == ConvergenceStatus.HUNG
    assert verdict.scores == _scores(None)
    assert verdict.confidence_bands == _scores((1, 5))
    records = verdict.receipt["phase4_revisions"]
    assert len(records) == len(_ALIASES)
    assert verdict.execution_receipt["phase4_revisions"] == records
    assert verdict.execution_receipt["served_models"] == list(_SERVED)
    for index, record in enumerate(records):
        assert record["model_alias"] == _ALIASES[index]
        assert record["attempted"] is True
        assert record["status"] == status
        assert record["original_retained"] is True
        assert record["reason"] == reason
        assert re.fullmatch("[a-z_]+", record["reason"])
        assert record["phase1_served_model"] == _SERVED[index]
        if served:
            assert record["phase4_served_model"] == f"synthetic-phase4-{_ALIASES[index]}"
        else:
            assert "phase4_served_model" not in record
        transcript = verdict.receipt["phase4_transcript"][index]
        assert transcript["scores"] == _scores(1 if index < 2 else 5)
        assert transcript["status"] == status
        assert transcript["original_retained"] is True
    assert verdict.execution_receipt["phases_attempted"] == [1, 2, 3, 4, 5]
    assert verdict.execution_receipt["phases_completed"] == [1, 2, 3, 5]
    assert verdict.execution_receipt["phases_failed"] == [
        {
            "phase": 4,
            "reason": "revision_call_failed" if status == "failed" else "revision_rejected",
        }
    ]
    assert verdict.execution_receipt["phases_not_attempted"] == []
    return records


async def test_unrequested_axis_99_is_rejected_before_aggregation_and_labels_retained_original():
    verdict, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {"unrequested_axis": 99}})
    )

    records = _assert_retained(verdict, "revision_axis_not_demanded")
    assert records[0]["detail"] == {
        "scores": [{"axis": "unrequested_axis", "value_json": "99"}],
        "missing_axes": sorted(_scores(1)),
    }
    assert "unrequested_axis" not in verdict.receipt["phase5_convergence"]
    assert all(row["score"] is None for row in verdict.receipt["phase5_convergence"].values())


@pytest.mark.parametrize("value", [0, 99], ids=["below_floor", "above_ceiling"])
async def test_out_of_range_demanded_score_is_rejected_without_clamping(value):
    verdict, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {**_scores(3), _AXIS: value}})
    )

    records = _assert_retained(verdict, "revision_score_out_of_range")
    assert records[0]["detail"]["scores"] == [{"axis": _AXIS, "value_json": json.dumps(value)}]


async def test_partial_revision_merges_and_labels_retained_axes_before_aggregation():
    original_aggregate = engine.aggregate_scores
    seen = []

    def capture(results, *args, **kwargs):
        seen.extend(results)
        return original_aggregate(results, *args, **kwargs)

    with patch.object(engine, "aggregate_scores", side_effect=capture):
        verdict, _ = await _deliberate_revision(json.dumps({"revised_scores": {_AXIS: 3}}))

    expected_scores = [{**_scores(1 if index < 2 else 5), _AXIS: 3} for index in range(4)]
    assert [result.scores for result in seen] == expected_scores
    assert verdict.scores == {**_scores(None), _AXIS: 3}
    assert verdict.confidence_bands == {**_scores((1, 5)), _AXIS: (3, 3)}
    assert set(verdict.receipt["phase5_convergence"]) == set(_scores(1))
    records = verdict.execution_receipt["phase4_revisions"]
    assert records == verdict.receipt["phase4_revisions"]
    assert len(records) == len(_ALIASES)
    for index, record in enumerate(records):
        assert record["status"] == "revised"
        assert record["original_retained"] is False
        assert record["revised_axes"] == [_AXIS]
        assert record["retained_axes"] == sorted(_scores(1).keys() - {_AXIS})
        assert record["phase1_served_model"] == _SERVED[index]
        assert record["phase4_served_model"] == f"synthetic-phase4-{_ALIASES[index]}"
        assert verdict.receipt["phase4_transcript"][index]["scores"] == expected_scores[index]


async def test_single_axis_original_accepts_single_axis_revision_without_retained_axes():
    verdict, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {_AXIS: 2}, "revision_rationale": {}}),
        scored_axes=(_AXIS,),
    )

    assert verdict.scores == {_AXIS: 2}
    assert verdict.confidence_bands == {_AXIS: (2, 2)}
    assert verdict.convergence_status == ConvergenceStatus.CONVERGED
    records = verdict.execution_receipt["phase4_revisions"]
    assert len(records) == len(_ALIASES)
    for index, record in enumerate(records):
        assert record["status"] == "revised"
        assert record["revised_axes"] == [_AXIS]
        assert record["retained_axes"] == []
        assert verdict.receipt["phase4_transcript"][index]["scores"] == {_AXIS: 2}


async def test_empty_revision_is_rejected_and_retains_original():
    verdict, _ = await _deliberate_revision(json.dumps({"revised_scores": {}}))

    _assert_retained(verdict, "revision_empty")


async def test_rubric_axis_not_scored_by_member_is_not_demanded():
    unscored_axis = _RUBRIC.axes[1].name
    verdict, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {_AXIS: 2, unscored_axis: 3}}),
        scored_axes=(_AXIS,),
    )

    assert verdict.scores == {_AXIS: None}
    assert verdict.confidence_bands == {_AXIS: (1, 5)}
    records = verdict.execution_receipt["phase4_revisions"]
    assert len(records) == len(_ALIASES)
    for index, record in enumerate(records):
        assert record["status"] == "rejected"
        assert record["reason"] == "revision_axis_not_demanded"
        assert record["original_retained"] is True
        assert record["detail"] == {
            "scores": [{"axis": unscored_axis, "value_json": "3"}],
            "missing_axes": [],
        }
        assert verdict.receipt["phase4_transcript"][index]["scores"] == {
            _AXIS: 1 if index < 2 else 5
        }


@pytest.mark.parametrize("value", [1, 3, 5], ids=["floor", "interior", "ceiling"])
async def test_scored_axis_outside_rubric_accepts_revision_within_default_scale(value):
    """Bound revisions over previously accepted legacy member scores, not demand shapes.

    The dict fixture bypasses native build_phase1_model, which forbids extra axes.
    """
    rubric = EpistemicQualityRubric()
    axis = "a"
    assert axis not in {rubric_axis.name for rubric_axis in rubric.axes}
    verdict, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {axis: value}, "revision_rationale": {}}),
        rubric=rubric,
        scored_axes=(axis,),
    )

    records = verdict.execution_receipt["phase4_revisions"]
    assert records == verdict.receipt["phase4_revisions"]
    assert len(records) == len(_ALIASES)
    for index, record in enumerate(records):
        assert record["status"] == "revised"
        assert record["original_retained"] is False
        assert record["revised_axes"] == [axis]
        assert record["retained_axes"] == []
        assert record["phase1_served_model"] == _SERVED[index]
        assert record["phase4_served_model"] == f"synthetic-phase4-{_ALIASES[index]}"
        assert verdict.receipt["phase4_transcript"][index]["scores"] == {axis: value}
    assert verdict.scores == {axis: value}
    assert verdict.confidence_bands == {axis: (value, value)}
    assert verdict.convergence_status == ConvergenceStatus.CONVERGED


@pytest.mark.parametrize("value", [0, 6], ids=["below_floor", "above_ceiling"])
async def test_scored_axis_outside_rubric_rejects_revision_outside_default_scale(value):
    """Bound legacy member-score revisions; the synthetic axis is no demand-shape evidence."""
    rubric = EpistemicQualityRubric()
    axis = "a"
    assert axis not in {rubric_axis.name for rubric_axis in rubric.axes}
    verdict, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {axis: value}}),
        rubric=rubric,
        scored_axes=(axis,),
    )

    records = verdict.execution_receipt["phase4_revisions"]
    assert records == verdict.receipt["phase4_revisions"]
    assert len(records) == len(_ALIASES)
    for index, record in enumerate(records):
        assert record["status"] == "rejected"
        assert record["reason"] == "revision_score_out_of_range"
        assert record["original_retained"] is True
        assert record["detail"] == {"scores": [{"axis": axis, "value_json": json.dumps(value)}]}
        assert record["phase1_served_model"] == _SERVED[index]
        assert record["phase4_served_model"] == f"synthetic-phase4-{_ALIASES[index]}"
        assert verdict.receipt["phase4_transcript"][index]["scores"] == {
            axis: 1 if index < 2 else 5
        }
    assert verdict.scores == {axis: None}
    assert verdict.confidence_bands == {axis: (1, 5)}
    assert verdict.convergence_status == ConvergenceStatus.HUNG


@pytest.mark.parametrize(
    "value", [True, 3.5, "3", None, [3]], ids=["bool", "float", "string", "null", "list"]
)
async def test_noninteger_revision_score_is_rejected_without_coercion(value):
    verdict, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {**_scores(3), _AXIS: value}})
    )

    records = _assert_retained(verdict, "revision_score_not_integer")
    assert records[0]["detail"]["scores"] == [{"axis": _AXIS, "value_json": json.dumps(value)}]


@pytest.mark.parametrize("payload", ["not json", "[]", "{}", '{"revised_scores": []}'])
async def test_unparseable_revision_is_labelled_and_retains_call_provenance(payload):
    verdict, _ = await _deliberate_revision(payload)

    _assert_retained(verdict, "revision_unparseable", status="failed")


async def test_valid_revision_applies_and_carries_revision_served_model():
    verdict, _ = await _deliberate_revision(json.dumps({"revised_scores": _scores(4)}))

    assert verdict.convergence_status == ConvergenceStatus.CONVERGED
    assert verdict.scores == _scores(4)
    assert verdict.execution_receipt["served_models"] == list(_SERVED)
    records = verdict.execution_receipt["phase4_revisions"]
    for index, record in enumerate(records):
        assert record == {
            "model_alias": _ALIASES[index],
            "attempted": True,
            "status": "revised",
            "original_retained": False,
            "phase1_served_model": _SERVED[index],
            "phase4_served_model": f"synthetic-phase4-{_ALIASES[index]}",
            "revised_axes": sorted(_scores(4)),
            "retained_axes": [],
        }
        assert verdict.receipt["phase4_transcript"][index]["scores"] == _scores(4)

    # Inspect the actual PhaseOneResult handed to aggregation, not just its receipt.
    original_aggregate = engine.aggregate_scores
    seen = []

    def capture(results, *args, **kwargs):
        seen.extend(results)
        return original_aggregate(results, *args, **kwargs)

    with patch.object(engine, "aggregate_scores", side_effect=capture):
        await _deliberate_revision(json.dumps({"revised_scores": _scores(4)}))
    assert [result.served_model for result in seen] == [
        f"synthetic-phase4-{alias}" for alias in _ALIASES
    ]
    assert all(result.execution_receipt["served_model"] == result.served_model for result in seen)


async def test_revision_call_failure_retains_original_and_records_pure_failure_reason():
    verdict, _ = await _deliberate_revision(RuntimeError("synthetic exception message canary"))

    records = _assert_retained(verdict, "revision_call_failed", status="failed", served=False)
    assert records[0]["detail"] == {"exception_type": "RuntimeError"}
    assert "synthetic exception message canary" not in verdict.model_dump_json()


async def test_revision_validation_uses_each_demanded_axis_scale():
    # Keep Phase 1 within its existing shared scale; vary only the revision bounds.
    rubric = _RUBRIC.model_copy(
        update={
            "axes": (
                _RUBRIC.axes[0],
                _RUBRIC.axes[1].model_copy(update={"min_score": 2, "max_score": 7}),
                *_RUBRIC.axes[2:],
            )
        }
    )
    varied_axis = rubric.axes[1].name
    accepted, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {**_scores(3), varied_axis: 7}}), rubric=rubric
    )
    assert accepted.scores[varied_axis] == 7
    rejected, _ = await _deliberate_revision(
        json.dumps({"revised_scores": {**_scores(3), varied_axis: 1}}), rubric=rubric
    )
    _assert_retained(rejected, "revision_score_out_of_range")


def test_revision_execution_schema_preserves_declared_fields_and_excludes_unknown_narration():
    record = {
        "model_alias": _ALIASES[0],
        "attempted": True,
        "status": "rejected",
        "original_retained": True,
        "phase1_served_model": _SERVED[0],
        "phase4_served_model": "synthetic-revision",
        "reason": "revision_score_out_of_range",
        "detail": {"scores": [{"axis": _AXIS, "value_json": "99"}]},
    }
    revised_record = {
        "model_alias": _ALIASES[1],
        "attempted": True,
        "status": "revised",
        "original_retained": False,
        "phase1_served_model": _SERVED[1],
        "phase4_served_model": "synthetic-revision",
        "revised_axes": [_AXIS],
        "retained_axes": [_RUBRIC.axes[1].name],
    }
    unsafe = {
        "phase4_revisions": [
            {
                **record,
                "rationale": "narration canary",
                "detail": {
                    "scores": [{**record["detail"]["scores"][0], "trace": "narration canary"}],
                    "trace": "narration canary",
                },
            },
            {
                **revised_record,
                "revised_axes": [_AXIS, {"trace": "narration canary"}, 99],
                "retained_axes": [_RUBRIC.axes[1].name, {"trace": "narration canary"}, False],
                "trace": "narration canary",
            },
        ]
    }
    expected = {"phase4_revisions": [record, revised_record], "oracle_weight": 0}
    assert sanitize_execution_receipt(unsafe) == expected
    assert sanitize_execution_receipt(expected) == expected
    verdict = CouncilVerdict(
        scores={},
        confidence_bands={},
        convergence_status=ConvergenceStatus.HUNG,
        disagreement_log=[],
        research_findings=[],
        evidence_matrix=None,
        execution_receipt=unsafe,
    )
    assert (
        CouncilVerdict.model_validate_json(verdict.model_dump_json()).execution_receipt == expected
    )
