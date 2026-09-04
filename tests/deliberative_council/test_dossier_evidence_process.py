"""Pins for evidence/process/execution separation in council dossiers."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.deliberative_council.engine import _assess_health, deliberate
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    EvidenceMatrix,
    EvidenceMatrixAxis,
    PhaseOneResult,
)
from agents.deliberative_council.prompts import RESEARCH_SYSTEM_PROMPT, phase1_system_prompt
from agents.deliberative_council.rubrics import EpistemicQualityRubric

_ALIASES = ("opus", "gemini-3-pro", "web-research", "mistral-large")


def _member(alias: str, score: int = 4, *, evidence: bool = True) -> PhaseOneResult:
    findings = (
        [f"claim checked against {alias}.md; test passed; no counter-evidence found"]
        if evidence
        else []
    )
    return PhaseOneResult(
        model_alias=alias,
        scores={"a": score},
        evidentiary_rationale=findings,
        process_trace={},
        execution_receipt={
            "served_model": f"served-{alias}",
            "capability_id": f"cvc.{alias}",
            "route_id": alias,
            "capability_admission_action": "admit",
            "capability_receipt_refs": [f"admission:{alias}"],
        },
    )


def _config() -> CouncilConfig:
    return CouncilConfig(model_aliases=_ALIASES)


def _input(*, requires_reviewable_argument: bool = False) -> CouncilInput:
    return CouncilInput(
        text="claim",
        source_ref="claim.md",
        source_context="already resolved",
        requires_reviewable_argument=requires_reviewable_argument,
    )


def test_empty_process_trace_with_evidence_counts_toward_quorum() -> None:
    results = [_member(alias) for alias in _ALIASES]

    assert all(result.process_trace == {} for result in results)
    health = _assess_health(results, [], _config())

    assert health.members_valid == 4
    assert health.families_valid == 4
    assert health.below_quorum is False


async def test_panel_with_full_evidence_and_no_process_trace_does_not_refuse() -> None:
    results = [_member(alias) for alias in _ALIASES]

    with patch("agents.deliberative_council.engine.run_phase1", return_value=results):
        verdict = await deliberate(
            _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), _config()
        )

    assert verdict.convergence_status == ConvergenceStatus.CONVERGED
    assert verdict.receipt["council_health"]["members_valid"] == 4
    assert verdict.receipt["council_health"]["below_quorum"] is False


async def test_reviewable_argument_flag_alone_controls_empty_evidence_validity() -> None:
    results = [_member(alias, evidence=False) for alias in _ALIASES]

    with patch("agents.deliberative_council.engine.run_phase1", return_value=results):
        ordinary = await deliberate(
            _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), _config()
        )
    with patch("agents.deliberative_council.engine.run_phase1", return_value=results):
        demanded = await deliberate(
            _input(requires_reviewable_argument=True),
            CouncilMode.DISCONFIRMATION,
            EpistemicQualityRubric(),
            _config(),
        )

    assert ordinary.convergence_status == ConvergenceStatus.CONVERGED
    assert ordinary.receipt["council_health"]["members_valid"] == 4
    assert demanded.convergence_status == ConvergenceStatus.REFUSED
    assert demanded.receipt["refusal_reason"] == "all_models_failed"
    assert demanded.receipt["council_health"]["members_valid"] == 0
    assert {failure["reason"] for failure in demanded.receipt["failed_members"]} == {
        "EmptyEvidentiaryRationale"
    }


async def test_serialized_dossier_has_three_sections_and_legacy_names() -> None:
    results = [
        _member("opus", 1),
        _member("gemini-3-pro", 5),
        _member("web-research", 1),
        _member("mistral-large", 5),
    ]
    matrix = EvidenceMatrix(
        axes={"a": EvidenceMatrixAxis(axis="a", least_inconsistent_score=3)},
        built_by="opus",
    )

    with (
        patch("agents.deliberative_council.engine.run_phase1", return_value=results),
        patch("agents.deliberative_council.engine._run_phase2", return_value=matrix),
        patch("agents.deliberative_council.engine._run_phase3", return_value=[]),
        patch("agents.deliberative_council.engine._run_phase4", return_value=results),
    ):
        verdict = await deliberate(
            _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), _config()
        )

    dossier = verdict.model_dump(mode="json")
    assert {"evidentiary_rationale", "process_trace", "execution_receipt"} <= dossier.keys()
    assert dossier["evidentiary_rationale"]["research_findings"] == verdict.research_findings
    assert dossier["evidentiary_rationale"]["evidence_matrix"] == dossier["evidence_matrix"]
    assert dossier["process_trace"]["oracle_weight"] == 0
    assert dossier["process_trace"]["optional"] is True
    assert dossier["execution_receipt"].items() <= dossier["receipt"].items()
    assert "phase1_transcript" not in dossier["execution_receipt"]
    assert dossier["execution_receipt"]["member_execution"][0]["served_model"] == "served-opus"
    assert dossier["execution_receipt"]["member_execution"][0]["capability_receipt_refs"] == [
        "admission:opus"
    ]

    # The member model also resolves both vocabularies in serialized and attribute form.
    member_dump = results[0].model_dump(mode="json")
    assert {"evidentiary_rationale", "process_trace", "execution_receipt"} <= member_dump.keys()
    assert results[0].research_findings == results[0].evidentiary_rationale
    assert results[0].rationale == results[0].process_trace
    assert results[0].served_model == results[0].execution_receipt["served_model"]


async def test_execution_receipt_excludes_process_trace() -> None:
    canary = "PROCESS-TRACE-MUST-NOT-BE-AN-EXECUTION-RECEIPT"
    results = [_member(alias) for alias in _ALIASES]
    results[0] = results[0].model_copy(
        update={"process_trace": {"a": canary}, "rationale": {"a": canary}}
    )

    with patch("agents.deliberative_council.engine.run_phase1", return_value=results):
        verdict = await deliberate(
            _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), _config()
        )

    dossier = verdict.model_dump(mode="json")
    assert canary in json.dumps(dossier["process_trace"])
    assert "phase1_transcript" in dossier["receipt"]
    assert "phase1_transcript" not in dossier["execution_receipt"]
    assert canary not in json.dumps(dossier["execution_receipt"])


def test_prompts_request_inspectable_evidence_not_reasoning_narration() -> None:
    scoring_prompt = phase1_system_prompt(EpistemicQualityRubric())

    for phrase in ("claims checked", "source references", "tests run", "counter-evidence"):
        assert phrase in scoring_prompt
    assert "private reasoning" in scoring_prompt
    assert "zero oracle weight" in scoring_prompt
    assert "counter-evidence" in RESEARCH_SYSTEM_PROMPT


@pytest.mark.parametrize(
    "mode",
    (CouncilMode.DISCONFIRMATION, CouncilMode.INTAKE, CouncilMode.NARRATIVE),
)
async def test_process_trace_cannot_influence_final_oracle_output(mode: CouncilMode) -> None:
    """Phase 3-5 must be invariant when only a member's process trace changes."""
    canary = "PROCESS-TRACE-CANARY"
    scores = (1, 1, 5, 5)

    def panel(low_trace: str) -> list[PhaseOneResult]:
        return [
            PhaseOneResult(
                model_alias=alias,
                scores={"a": score},
                evidentiary_rationale=[f"stable inspectable evidence from {alias}"],
                process_trace={"a": low_trace} if alias == _ALIASES[0] else {},
            )
            for alias, score in zip(_ALIASES, scores, strict=True)
        ]

    matrix = EvidenceMatrix(
        axes={"a": EvidenceMatrixAxis(axis="a", least_inconsistent_score=3)},
        built_by="opus",
    )

    async def trace_sensitive_member(_member, prompt):
        if "You are revising your scores" not in prompt:
            trace_seen = canary in prompt
            return (
                json.dumps(
                    {
                        "revised_score": 3,
                        "response": f"phase-3 trace_seen={trace_seen}",
                    }
                ),
                [],
                "",
            )

        revised_score = 5 if "trace_seen=True" in prompt else 2
        return (
            json.dumps(
                {
                    "revised_scores": {"a": revised_score},
                    "revision_rationale": {},
                    "changed_axes": ["a"],
                }
            ),
            [],
            "",
        )

    async def run(results: list[PhaseOneResult]):
        with (
            patch("agents.deliberative_council.engine.run_phase1", return_value=results),
            patch("agents.deliberative_council.engine._run_phase2", return_value=matrix),
            patch(
                "agents.deliberative_council.engine._call_member",
                side_effect=trace_sensitive_member,
            ),
        ):
            return await deliberate(
                _input(),
                mode,
                EpistemicQualityRubric(),
                _config(),
            )

    baseline = await run(panel("ordinary optional narration"))
    changed_trace = await run(panel(canary))

    assert baseline.scores == changed_trace.scores == {"a": 2}
    assert baseline.confidence_bands == changed_trace.confidence_bands
    assert baseline.convergence_status == changed_trace.convergence_status
    assert baseline.adversarial_exchanges == changed_trace.adversarial_exchanges
