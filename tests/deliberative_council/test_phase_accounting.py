"""Execution accounting must describe real phase output and preserved outcomes."""

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
    PhaseOneResult,
    sanitize_execution_receipt,
)
from agents.deliberative_council.modes.disconfirmation import (
    DisconfirmationVerdict,
    derive_verdict,
)
from agents.deliberative_council.rubrics import DisconfirmationRubric

_ALIASES = ("synthetic-amber", "synthetic-blue", "synthetic-copper", "synthetic-dusk")
_SERVED = ("claude-synthetic", "gemini-synthetic", "mistral-synthetic", "sonar-synthetic")
_RUBRIC = DisconfirmationRubric()
_AXIS = _RUBRIC.axes[0].name


async def _run(
    *,
    phases=(1, 2, 3, 4, 5),
    failures=(),
    scores=(1, 1, 5, 5),
    threshold=1.0,
    revision_payloads=None,
    aliases=_ALIASES,
    served=_SERVED,
):
    calls = []

    async def call_member(alias, prompt, *, output_type=None, **_kwargs):
        index = aliases.index(alias)
        if output_type is not None:
            calls.append(1)
            score = scores[index]
            if score is None:
                raise RuntimeError("synthetic scoring failure")
            return (
                Phase1Output(scores={axis.name: score for axis in _RUBRIC.axes}),
                [],
                served[index],
            )
        if "building an Analysis" in prompt:
            calls.append(2)
            if 2 in failures:
                raise RuntimeError("synthetic matrix failure")
            return json.dumps({"axes": {_AXIS: {"least_inconsistent_score": 3}}}), [], ""
        if "This is an adversarial challenge" in prompt:
            calls.append(3)
            if 3 in failures or ("partial_exchange" in failures and f"'{_AXIS}'" in prompt):
                raise RuntimeError("synthetic exchange failure")
            return "synthetic challenge response", [], ""
        if prompt.startswith("You are revising your scores"):
            calls.append(4)
            if revision_payloads is not None:
                payload = revision_payloads[index]
                if isinstance(payload, Exception):
                    raise payload
                return payload, [], f"synthetic-revision-{alias}"
            # Keep genuine disagreement through aggregation.
            return (
                json.dumps({"revised_scores": {axis.name: scores[index] for axis in _RUBRIC.axes}}),
                [],
                f"synthetic-revision-{alias}",
            )
        return "synthetic findings", [], ""

    with (
        patch.object(engine, "build_member", side_effect=lambda alias, **_kwargs: alias),
        patch.object(engine, "member_capability_admission", return_value=None),
        patch.object(engine, "_call_member", side_effect=call_member),
    ):
        verdict = await engine.deliberate(
            CouncilInput(
                text="synthetic claim", source_ref="synthetic:source", source_context="ctx"
            ),
            CouncilMode.DISCONFIRMATION,
            _RUBRIC,
            CouncilConfig(
                phases=phases, model_aliases=aliases, shortcircuit_iqr_threshold=threshold
            ),
        )
    # Assert the publication schema keeps all phase accounting fields intact.
    round_trip = CouncilVerdict.model_validate_json(verdict.model_dump_json())
    for field in (
        "phases_requested",
        "phases_attempted",
        "phases_completed",
        "phases_failed",
        "phases_not_attempted",
    ):
        assert round_trip.execution_receipt[field] == verdict.receipt[field]
    for field in ("phases_failed", "phases_not_attempted"):
        assert all(re.fullmatch("[a-z_]+", row["reason"]) for row in verdict.receipt[field])
    if "phase4_revisions" in verdict.receipt:
        assert (
            round_trip.execution_receipt["phase4_revisions"] == verdict.receipt["phase4_revisions"]
        )
    return verdict, calls


def _scores(value):
    return {axis.name: value for axis in _RUBRIC.axes}


def _assert_revision_records(verdict, statuses, expected_scores, *, retained_axes=()):
    records = verdict.execution_receipt["phase4_revisions"]
    transcript = verdict.receipt["phase4_transcript"]
    assert len(records) == len(transcript) == len(_ALIASES)
    assert [record["status"] for record in records] == statuses
    assert [row["scores"] for row in transcript] == expected_scores
    for index, record in enumerate(records):
        assert record["model_alias"] == _ALIASES[index]
        assert record["attempted"] is (statuses[index] != "not_attempted")
        assert record["original_retained"] is (statuses[index] != "revised")
        assert all(transcript[index][key] == value for key, value in record.items())
        if statuses[index] == "revised":
            assert record["retained_axes"] == list(retained_axes)
            assert record["revised_axes"] == sorted(_scores(1).keys() - set(retained_axes))
    return records


def _assert_phase_four_summary(verdict, *, failure_reason=None):
    receipt = verdict.execution_receipt
    assert receipt["phases_attempted"] == [1, 2, 3, 4, 5]
    assert receipt["phases_completed"] == (
        [1, 2, 3, 4, 5] if failure_reason is None else [1, 2, 3, 5]
    )
    assert receipt["phases_failed"] == (
        [] if failure_reason is None else [{"phase": 4, "reason": failure_reason}]
    )
    assert receipt["phases_not_attempted"] == []


async def test_all_revision_calls_failed_leave_phase_four_incomplete():
    verdict, calls = await _run(revision_payloads=(RuntimeError("synthetic failure"),) * 4)

    records = _assert_revision_records(
        verdict, ["failed"] * 4, [_scores(value) for value in (1, 1, 5, 5)]
    )
    assert [record["reason"] for record in records] == ["revision_call_failed"] * 4
    assert calls.count(4) == 4
    _assert_phase_four_summary(verdict, failure_reason="revision_call_failed")
    assert verdict.convergence_status == ConvergenceStatus.HUNG
    assert verdict.scores == _scores(None)
    assert verdict.confidence_bands == _scores((1, 5))


async def test_all_revisions_rejected_leave_phase_four_incomplete():
    payload = json.dumps({"revised_scores": {_AXIS: 99}})
    verdict, calls = await _run(revision_payloads=(payload,) * 4)

    records = _assert_revision_records(
        verdict, ["rejected"] * 4, [_scores(value) for value in (1, 1, 5, 5)]
    )
    assert [record["reason"] for record in records] == ["revision_score_out_of_range"] * 4
    assert calls.count(4) == 4
    _assert_phase_four_summary(verdict, failure_reason="revision_rejected")
    assert verdict.convergence_status == ConvergenceStatus.HUNG
    assert verdict.scores == _scores(None)
    assert verdict.confidence_bands == _scores((1, 5))


async def test_mixed_revision_outcomes_leave_phase_four_incomplete():
    revised = json.dumps({"revised_scores": _scores(2)})
    rejected = json.dumps({"revised_scores": {_AXIS: 99}})
    original_aggregate = engine.aggregate_scores
    seen = []

    def capture(results, *args, **kwargs):
        seen.extend(results)
        return original_aggregate(results, *args, **kwargs)

    with patch.object(engine, "aggregate_scores", side_effect=capture):
        verdict, calls = await _run(
            revision_payloads=(revised, rejected, rejected, RuntimeError("synthetic failure"))
        )

    expected_scores = [_scores(value) for value in (2, 1, 5, 5)]
    records = _assert_revision_records(
        verdict, ["revised", "rejected", "rejected", "failed"], expected_scores
    )
    assert [result.scores for result in seen] == expected_scores
    assert records[1]["reason"] == records[2]["reason"] == "revision_score_out_of_range"
    assert records[3]["reason"] == "revision_call_failed"
    assert calls.count(4) == 4
    _assert_phase_four_summary(verdict, failure_reason="revision_call_failed")
    assert verdict.convergence_status == ConvergenceStatus.HUNG
    assert verdict.scores == _scores(None)
    assert verdict.confidence_bands == _scores((1, 5))


async def test_all_revisions_accepted_complete_phase_four():
    payload = json.dumps({"revised_scores": _scores(4)})
    verdict, calls = await _run(revision_payloads=(payload,) * 4)

    _assert_revision_records(verdict, ["revised"] * 4, [_scores(4)] * 4)
    assert calls.count(4) == 4
    _assert_phase_four_summary(verdict)
    assert verdict.convergence_status == ConvergenceStatus.CONVERGED
    assert verdict.scores == _scores(4)


async def test_partial_axis_revisions_accepted_complete_phase_four_with_retained_axes():
    payload = json.dumps({"revised_scores": {_AXIS: 3}})
    verdict, calls = await _run(revision_payloads=(payload,) * 4)

    _assert_revision_records(
        verdict,
        ["revised"] * 4,
        [{**_scores(value), _AXIS: 3} for value in (1, 1, 5, 5)],
        retained_axes=sorted(_scores(1).keys() - {_AXIS}),
    )
    assert calls.count(4) == 4
    _assert_phase_four_summary(verdict)
    assert verdict.convergence_status == ConvergenceStatus.HUNG
    assert verdict.scores == {**_scores(None), _AXIS: 3}
    assert verdict.confidence_bands == {**_scores((1, 5)), _AXIS: (3, 3)}


async def test_requested_phase_one_is_reported_without_changing_later_execution():
    verdict, calls = await _run(phases=(1,))

    assert set(calls) == {1, 2, 3, 4}
    assert verdict.receipt["phases_requested"] == [1]
    assert verdict.receipt["phases_attempted"] == [1, 2, 3, 4, 5]
    assert verdict.receipt["phases_completed"] == [1, 2, 3, 4, 5]
    assert verdict.receipt["phases_failed"] == []
    assert verdict.receipt["phases_not_attempted"] == []
    assert verdict.convergence_status == ConvergenceStatus.HUNG


@pytest.mark.parametrize("failures", [(2,), (3,), (2, 3)], ids=["matrix", "exchanges", "both"])
async def test_later_phase_failures_are_reported_and_genuine_disagreement_stays_hung(failures):
    verdict, calls = await _run(phases=(1,), failures=failures)

    receipt = verdict.receipt
    assert receipt["phases_requested"] == [1]
    assert receipt["phases_failed"] == [
        {
            "phase": phase,
            "reason": "evidence_matrix_failed" if phase == 2 else "adversarial_exchange_failed",
        }
        for phase in failures
    ]
    assert (verdict.evidence_matrix is None) == (2 in failures)
    assert bool(verdict.adversarial_exchanges) == (3 not in failures)
    assert 2 in calls and 3 in calls  # No new stopping rule on matrix failure.
    if 3 in failures:
        assert 4 not in calls
        assert receipt["phases_attempted"] == [1, 2, 3, 5]
        assert receipt["phases_not_attempted"] == [
            {"phase": 4, "reason": "no_adversarial_exchanges"}
        ]
        assert all(record["status"] == "not_attempted" for record in receipt["phase4_revisions"])
        assert all(record["attempted"] is False for record in receipt["phase4_revisions"])
        assert all(record["original_retained"] is True for record in receipt["phase4_transcript"])
    else:
        assert 4 in calls
        assert receipt["phases_attempted"] == [1, 2, 3, 4, 5]
        assert receipt["phases_not_attempted"] == []
    assert receipt["phases_completed"] == [
        phase for phase in receipt["phases_attempted"] if phase not in failures
    ]
    assert verdict.convergence_status == ConvergenceStatus.HUNG
    assert verdict.scores == {axis.name: None for axis in _RUBRIC.axes}
    assert verdict.confidence_bands == {axis.name: (1, 5) for axis in _RUBRIC.axes}
    assert derive_verdict(verdict) != DisconfirmationVerdict.SURVIVED


async def test_partial_phase_three_failure_is_incomplete_even_with_surviving_exchanges():
    verdict, calls = await _run(failures=("partial_exchange",))

    assert len(verdict.adversarial_exchanges) == len(_RUBRIC.axes) - 1
    assert 4 in calls
    assert verdict.receipt["phases_failed"] == [
        {"phase": 3, "reason": "adversarial_exchange_failed"}
    ]
    assert verdict.receipt["phases_completed"] == [1, 2, 4, 5]
    assert verdict.convergence_status == ConvergenceStatus.HUNG


async def test_shortcircuit_counts_aggregation_and_labels_unattempted_intermediate_phases():
    verdict, calls = await _run(scores=(4, 4, 4, 4))

    assert set(calls) == {1}
    assert verdict.convergence_status == ConvergenceStatus.CONVERGED
    assert verdict.receipt["phases_attempted"] == [1, 5]
    assert verdict.receipt["phases_completed"] == [1, 5]
    assert verdict.receipt["phases_failed"] == []
    assert verdict.receipt["phases_not_attempted"] == [
        {"phase": phase, "reason": "shortcircuited"} for phase in (2, 3, 4)
    ]


@pytest.mark.parametrize(
    "scores, served",
    [
        ((4, None, None, None), _SERVED),
        ((4, 4, 4, 4), (_SERVED[0],) * 4),
        ((None, None, None, None), _SERVED),
    ],
    ids=["below_quorum", "below_family_floor", "all_failed"],
)
async def test_below_quorum_stays_refused_and_later_phases_are_not_claimed_completed(
    scores, served
):
    """Previously any output asserted completion, wrongly ignoring the required quorum."""
    verdict, calls = await _run(scores=scores, served=served)

    assert set(calls) == {1}
    assert verdict.convergence_status == ConvergenceStatus.REFUSED
    assert verdict.scores == {}
    assert verdict.receipt["council_health"]["below_quorum"] is True
    assert verdict.receipt["council_health"]["quorum_floor_members"] == 4
    assert verdict.receipt["council_health"]["quorum_floor_families"] == 4
    assert verdict.receipt["phases_attempted"] == [1]
    any_valid = any(score is not None for score in scores)
    assert verdict.receipt["phases_completed"] == []
    assert verdict.receipt["phases_failed"] == [
        {
            "phase": 1,
            "reason": "below_quorum_or_family_floor" if any_valid else "no_valid_member_results",
        }
    ]
    assert verdict.receipt["phases_not_attempted"] == [
        {
            "phase": phase,
            "reason": "below_quorum_or_family_floor" if any_valid else "all_models_failed",
        }
        for phase in (2, 3, 4, 5)
    ]
    assert derive_verdict(verdict) == DisconfirmationVerdict.INSUFFICIENT_EVIDENCE


async def test_partial_panel_meeting_configured_quorum_completes_phase_one():
    # Four served families survive out of five requested members. Keep the
    # configured default floors (4 members, 4 families); no reduced test quorum.
    verdict, calls = await _run(
        aliases=(*_ALIASES, "synthetic-ember"),
        served=(*_SERVED, "claude-synthetic-extra"),
        scores=(4, 4, 4, 4, None),
    )

    health = verdict.receipt["council_health"]
    config = CouncilConfig()
    assert health["members_requested"] == 5
    assert health["members_valid"] == config.min_valid_members == 4
    assert health["families_valid"] == config.min_valid_families == 4
    assert health["below_quorum"] is False
    assert verdict.receipt["failed_members"] == [
        {"model_alias": "synthetic-ember", "reason": "RuntimeError"}
    ]
    assert set(calls) == {1}
    assert verdict.convergence_status == ConvergenceStatus.CONVERGED
    assert verdict.receipt["phases_attempted"] == [1, 5]
    assert verdict.receipt["phases_completed"] == [1, 5]
    assert verdict.receipt["phases_failed"] == []
    assert verdict.receipt["phases_not_attempted"] == [
        {"phase": phase, "reason": "shortcircuited"} for phase in (2, 3, 4)
    ]


async def test_documented_no_exchange_path_completes_phase_three_but_skips_revision():
    # A negative configurable threshold reaches the existing equal-scorer skip.
    verdict, calls = await _run(scores=(4, 4, 4, 4), threshold=-1.0)

    assert set(calls) == {1, 2}
    assert verdict.evidence_matrix is not None
    assert verdict.adversarial_exchanges == ()
    records = _assert_revision_records(verdict, ["not_attempted"] * 4, [_scores(4)] * 4)
    assert [record["reason"] for record in records] == ["no_adversarial_exchanges"] * 4
    assert verdict.receipt["phases_attempted"] == [1, 2, 3, 5]
    assert verdict.receipt["phases_completed"] == [1, 2, 3, 5]
    assert verdict.receipt["phases_failed"] == []
    assert verdict.receipt["phases_not_attempted"] == [
        {"phase": 4, "reason": "no_adversarial_exchanges"}
    ]


async def test_phase_two_without_contested_axes_returns_documented_no_matrix_result():
    failures = []
    panel = [
        PhaseOneResult(
            model_alias=alias, scores={axis.name: 4 for axis in _RUBRIC.axes}, rationale={}
        )
        for alias in _ALIASES
    ]
    with patch.object(
        engine, "_call_member", side_effect=AssertionError("unexpected call")
    ) as call:
        matrix = await engine._run_phase2(panel, _RUBRIC, CouncilConfig(), failures_out=failures)

    assert matrix is None
    assert failures == []
    call.assert_not_called()


def test_phase_accounting_schema_preserves_named_records_and_excludes_unknown_fields():
    expected = {
        "oracle_weight": 0,
        "phases_requested": [1],
        "phases_attempted": [1, 2, 3, 5],
        "phases_completed": [1, 5],
        "phases_failed": [{"phase": 2, "reason": "evidence_matrix_failed"}],
        "phases_not_attempted": [{"phase": 4, "reason": "no_adversarial_exchanges"}],
    }
    unsafe = {
        **expected,
        "phases_failed": [{**expected["phases_failed"][0], "trace": "narration canary"}],
        "phases_not_attempted": [
            {**expected["phases_not_attempted"][0], "trace": "narration canary"}
        ],
        "phases_attempted": [1, 2, 3, 5, {"trace": "narration canary"}],
    }
    assert sanitize_execution_receipt(unsafe) == expected
    assert sanitize_execution_receipt(expected) == expected
