"""Pins for evidence/process/execution separation in council dossiers."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.deliberative_council.capability_admission import CapabilityAdmissionReceipt
from agents.deliberative_council.engine import _assess_health, deliberate
from agents.deliberative_council.members import cache_policy_for_aliases
from agents.deliberative_council.models import (
    ConvergenceStatus,
    CouncilConfig,
    CouncilInput,
    CouncilMode,
    CouncilVerdict,
    EvidenceMatrix,
    EvidenceMatrixAxis,
    Phase1Output,
    PhaseOneResult,
    sanitize_execution_receipt,
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
    assert dossier["execution_receipt"]["oracle_weight"] == 0
    assert "phase1_transcript" not in dossier["execution_receipt"]
    assert dossier["execution_receipt"]["member_execution"][0]["oracle_weight"] == 0
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
    assert results[0].execution_receipt["oracle_weight"] == 0


def test_legacy_verdict_receipt_is_sanitized_into_execution_receipt() -> None:
    canary = "LEGACY-PROCESS-CANARY"
    legacy_receipt = {
        "input_hash": "fake-hash",
        "phase1_transcript": [{"rationale": canary}],
        "phase2_transcript": {"narration": canary},
        "unclassified_future_field": canary,
        "oracle_weight": 9,
        "member_execution": [
            {
                "model_alias": "fake-member",
                "served_model": "served-fake",
                "phase1_transcript": [{"rationale": canary}],
                "oracle_weight": 9,
            }
        ],
    }

    verdict = CouncilVerdict(
        scores={},
        confidence_bands={},
        convergence_status=ConvergenceStatus.REFUSED,
        disagreement_log=[],
        research_findings=[],
        evidence_matrix=None,
        receipt=legacy_receipt,
    )

    assert verdict.receipt == legacy_receipt
    assert verdict.process_trace["phase1_transcript"] == legacy_receipt["phase1_transcript"]
    assert verdict.execution_receipt == {
        "input_hash": "fake-hash",
        "member_execution": [
            {
                "model_alias": "fake-member",
                "served_model": "served-fake",
                "oracle_weight": 0,
            }
        ],
        "oracle_weight": 0,
    }
    assert canary not in json.dumps(verdict.execution_receipt)


def test_legacy_member_fields_build_a_sanitized_execution_receipt() -> None:
    canary = "LEGACY-MEMBER-PROCESS-CANARY"
    member = PhaseOneResult(
        model_alias="fake-member",
        scores={"a": 4},
        rationale={"a": canary},
        research_findings=["fake-source.md supports the claim"],
        served_model="served-fake",
        capability_receipt_refs=("admission:fake",),
    )

    assert member.execution_receipt == {
        "served_model": "served-fake",
        "capability_receipt_refs": ("admission:fake",),
        "oracle_weight": 0,
    }
    assert canary in json.dumps(member.process_trace)
    assert canary not in json.dumps(member.execution_receipt)


def test_explicit_execution_receipts_are_sanitized_at_both_model_levels() -> None:
    canary = "EXPLICIT-PROCESS-CANARY"
    unsafe_execution = {
        "served_model": "served-fake",
        "phase1_transcript": [{"rationale": canary}],
        "oracle_weight": 9,
    }
    member = PhaseOneResult(
        model_alias="fake-member",
        scores={"a": 4},
        rationale={"a": canary},
        execution_receipt=unsafe_execution,
    )
    verdict = CouncilVerdict(
        scores={},
        confidence_bands={},
        convergence_status=ConvergenceStatus.REFUSED,
        disagreement_log=[],
        research_findings=[],
        evidence_matrix=None,
        execution_receipt=unsafe_execution,
    )

    expected = {"served_model": "served-fake", "oracle_weight": 0}
    assert member.execution_receipt == expected
    assert verdict.execution_receipt == expected
    assert verdict.receipt == expected
    assert canary not in json.dumps(member.execution_receipt)
    assert canary not in json.dumps(verdict.execution_receipt)


@pytest.mark.parametrize("process_key", ("process", "trace", "stdout", "future_unknown"))
def test_nested_execution_fields_are_allowlisted(process_key: str) -> None:
    canary = "NESTED-PROCESS-CANARY"
    failure = {"model_alias": "opus", "reason": "TimeoutError"}
    policy = {"alias": "opus", "family": "anthropic", "cache_control": False}
    admission = {
        "receipt_id": "admission-1",
        "admitted": True,
        "receipt_refs": ["admission:1"],
    }
    receipt = {
        "cache_policy": {"opus": {**policy, process_key: {"text": canary}}},
        "council_health": {
            "members_valid": 3,
            "failed_members": [{**failure, process_key: [canary]}],
            process_key: canary,
        },
        "failed_members": [{**failure, process_key: canary}],
        "capability_admissions": [
            {
                **admission,
                "receipt_refs": ["admission:1", {process_key: canary}],
                process_key: canary,
            }
        ],
        "member_execution": [
            {
                "model_alias": "opus",
                "served_model": "claude-opus",
                "capability_receipt_refs": ["admission:1", {process_key: canary}],
                process_key: canary,
            }
        ],
        "models_used": ["opus", {process_key: canary}],
        "phases_completed": [1, {process_key: canary}],
        # Even an allowed scalar field must not become an arbitrary container.
        "input_hash": {process_key: canary},
    }
    expected = {
        "cache_policy": {"opus": policy},
        "council_health": {"members_valid": 3, "failed_members": [failure]},
        "failed_members": [failure],
        "capability_admissions": [admission],
        "member_execution": [
            {
                "model_alias": "opus",
                "served_model": "claude-opus",
                "capability_receipt_refs": ["admission:1"],
                "oracle_weight": 0,
            }
        ],
        "models_used": ["opus"],
        "phases_completed": [1],
        "oracle_weight": 0,
    }

    assert sanitize_execution_receipt(receipt) == expected
    assert canary not in json.dumps(sanitize_execution_receipt(receipt))


def test_execution_receipt_retains_produced_evidence_without_filling_absences() -> None:
    admission = CapabilityAdmissionReceipt(
        receipt_id="admission-1",
        receipt_ref="admission:1",
        capability_id="cvc.opus",
        route_id="claude-opus",
        provider="anthropic",
        capacity_pool="api_paid_spend",
        admission_action="admitted",
        admitted=True,
        quota_evidence_refs=("quota:1",),
        spend_evidence_refs=("spend:1",),
        resource_evidence_refs=("resource:1",),
        receipt_refs=("admission:1",),
    ).model_dump(mode="json", exclude_none=True, exclude_unset=True)
    policies = cache_policy_for_aliases(("opus", "claude-opus", "custom-route"))
    receipt = {
        "capability_admissions": [admission],
        "cache_policy": policies,
        "council_health": {"members_valid": 0, "below_quorum": True},
        "served_models": ["claude-opus", "claude-opus", "custom-model"],
        "models_used": ["opus", "claude-opus", "custom-route"],
        "shortcircuited": False,
        "phases_completed": [],
    }
    expected = {**receipt, "oracle_weight": 0}
    # Undeclared records cannot ride alongside the model-indexed policies.
    unsafe = {
        **receipt,
        "cache_policy": {
            **policies,
            "stdout": {"alias": "stdout", "family": "PROCESS-CANARY"},
            "trace": ["PROCESS-CANARY"],
        },
    }

    assert sanitize_execution_receipt(unsafe) == expected
    assert sanitize_execution_receipt(expected) == expected


@pytest.mark.parametrize(
    "identities", ({"model_alias": "opus"}, {"failed_members": [{"model_alias": "opus"}]})
)
def test_cache_policy_preserves_named_member_and_failed_model_evidence(identities: dict) -> None:
    receipt = {**identities, "cache_policy": {"opus": {"cache_control": False}}}

    assert sanitize_execution_receipt(receipt) == {**receipt, "oracle_weight": 0}


async def test_deliberate_sanitizes_nested_receipts_at_publication() -> None:
    canary = "PUBLISHED-NESTED-PROCESS-CANARY"
    results = [_member(alias) for alias in _ALIASES]
    # model_copy bypasses validation: the verdict boundary must still sanitize.
    results[0] = results[0].model_copy(
        update={
            "execution_receipt": {
                "served_model": "served-opus",
                "cache_policy": {"opus": {"phase1_transcript": canary}},
                "capability_receipt_refs": ["admission:opus", {"stdout": canary}],
            }
        }
    )
    policy = {"opus": {"alias": "opus", "cache_control": False, "trace": canary}}
    with (
        patch("agents.deliberative_council.engine.run_phase1", return_value=results),
        patch("agents.deliberative_council.engine.cache_policy_for_aliases", return_value=policy),
    ):
        verdict = await deliberate(
            _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), _config()
        )

    receipt = verdict.model_dump(mode="json")["execution_receipt"]
    assert canary not in json.dumps(receipt)
    assert receipt["cache_policy"] == {"opus": {"alias": "opus", "cache_control": False}}
    assert receipt["member_execution"][0]["capability_receipt_refs"] == ["admission:opus"]


@pytest.mark.parametrize(
    "provenance",
    (
        {},
        {
            "served_model": "",
            "capability_id": "",
            "route_id": "",
            "capability_admission_action": "",
            "capability_receipt_refs": (),
        },
    ),
)
def test_missing_member_provenance_serializes_as_absent(provenance: dict) -> None:
    member = PhaseOneResult(model_alias="opus", scores={"a": 4}, rationale={}, **provenance)

    assert member.model_dump(mode="json")["execution_receipt"] == {"oracle_weight": 0}
    assert PhaseOneResult.model_validate_json(member.model_dump_json()).execution_receipt == {
        "oracle_weight": 0
    }


@pytest.mark.parametrize("served_models", (("", "", "", ""), ("claude-opus", "", "", "")))
async def test_unavailable_provenance_producer_does_not_publish_placeholders(served_models) -> None:
    output = Phase1Output(scores={"a": 4}, research_findings=["source.md supports claim"])
    calls = iter(served_models)

    async def call_member(_member, _prompt, *, output_type=None, **_kwargs):
        if output_type is None:
            return "source.md supports claim", [], ""
        return output, [], next(calls)

    with (
        patch("agents.deliberative_council.engine.build_member", return_value=object()),
        patch("agents.deliberative_council.engine._call_member", side_effect=call_member),
        patch("agents.deliberative_council.engine.member_capability_admission", return_value=None),
    ):
        verdict = await deliberate(
            _input(), CouncilMode.DISCONFIRMATION, EpistemicQualityRubric(), _config()
        )

    receipt = verdict.model_dump(mode="json")["execution_receipt"]
    assert receipt["member_execution"] == [
        {"model_alias": alias, "oracle_weight": 0, **({"served_model": served} if served else {})}
        for alias, served in zip(_ALIASES, served_models, strict=True)
    ]
    # A partial positional list would associate served models with the wrong aliases.
    assert "served_models" not in receipt


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
