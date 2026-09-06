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


async def _run(*, phases=(1, 2, 3, 4, 5), failures=(), scores=(1, 1, 5, 5), threshold=1.0):
    calls = []

    async def call_member(alias, prompt, *, output_type=None, **_kwargs):
        index = _ALIASES.index(alias)
        if output_type is not None:
            calls.append(1)
            score = scores[index]
            if score is None:
                raise RuntimeError("synthetic scoring failure")
            return (
                Phase1Output(scores={axis.name: score for axis in _RUBRIC.axes}),
                [],
                _SERVED[index],
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
                phases=phases, model_aliases=_ALIASES, shortcircuit_iqr_threshold=threshold
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
    return verdict, calls


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
    "scores", [(4, None, None, None), (None, None, None, None)], ids=["below_quorum", "all_failed"]
)
async def test_below_quorum_stays_refused_and_later_phases_are_not_claimed_completed(scores):
    verdict, calls = await _run(scores=scores)

    assert set(calls) == {1}
    assert verdict.convergence_status == ConvergenceStatus.REFUSED
    assert verdict.scores == {}
    assert verdict.receipt["council_health"]["below_quorum"] is True
    assert verdict.receipt["council_health"]["quorum_floor_members"] == 4
    assert verdict.receipt["council_health"]["quorum_floor_families"] == 4
    assert verdict.receipt["phases_attempted"] == [1]
    any_valid = any(score is not None for score in scores)
    assert verdict.receipt["phases_completed"] == ([1] if any_valid else [])
    assert verdict.receipt["phases_failed"] == (
        [] if any_valid else [{"phase": 1, "reason": "no_valid_member_results"}]
    )
    assert verdict.receipt["phases_not_attempted"] == [
        {
            "phase": phase,
            "reason": "below_quorum_or_family_floor" if any_valid else "all_models_failed",
        }
        for phase in (2, 3, 4, 5)
    ]
    assert derive_verdict(verdict) == DisconfirmationVerdict.INSUFFICIENT_EVIDENCE


async def test_documented_no_exchange_path_completes_phase_three_but_skips_revision():
    # A negative configurable threshold reaches the existing equal-scorer skip.
    verdict, calls = await _run(scores=(4, 4, 4, 4), threshold=-1.0)

    assert set(calls) == {1, 2}
    assert verdict.evidence_matrix is not None
    assert verdict.adversarial_exchanges == ()
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
