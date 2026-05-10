"""Tests for the content runner public-mode refusal harness."""

from __future__ import annotations

import pytest

from shared.content_runner_public_mode_refusal import (
    BlockedReasonCode,
    RunnerPublicModeDecision,
    RunnerPublicModeEvidence,
    evaluate_runner_public_mode_refusal,
)


def _ready_public_evidence(**overrides) -> RunnerPublicModeEvidence:
    base = {
        "requested_mode": "public_live",
        "explicit_public_mode_request": True,
        "grounding_question_present": True,
        "claim_shape_declared": True,
        "claim_authority_ceiling": "evidence_bound",
        "unsupported_public_claim": False,
        "wcs_witness_state": "verified",
        "source_freshness_state": "fresh",
        "rights_state": "cleared",
        "privacy_state": "public_safe",
        "consent_state": "granted",
        "audio_egress_state": "ready",
        "public_event_state": "linked",
        "monetization_state": "not_requested",
        "evidence_refs": ("evidence-envelope:runner-public-mode-ready",),
    }
    base.update(overrides)
    return RunnerPublicModeEvidence.model_validate(base)


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    (
        ({"wcs_witness_state": "missing"}, "missing_wcs_witness"),
        ({"source_freshness_state": "stale"}, "stale_source"),
        ({"rights_state": "blocked"}, "rights_hold"),
        ({"privacy_state": "blocked"}, "consent_privacy_hold"),
        ({"audio_egress_state": "unknown"}, "audio_egress_unknown"),
        (
            {
                "requested_mode": "public_monetizable",
                "monetization_state": "blocked",
            },
            "monetization_hold",
        ),
    ),
)
def test_public_modes_refuse_for_each_required_gate(
    overrides: dict[str, object],
    expected_code: BlockedReasonCode,
) -> None:
    decision = evaluate_runner_public_mode_refusal(_ready_public_evidence(**overrides))

    assert isinstance(decision, RunnerPublicModeDecision)
    assert decision.final_status == "refused"
    assert decision.effective_mode == "dry_run"
    assert decision.public_live_allowed is False
    assert decision.public_monetizable_allowed is False
    assert expected_code in decision.machine_readable_blocked_reasons
    assert all(reason.operator_message for reason in decision.blocked_reasons)
    assert {reason.code for reason in decision.blocked_reasons} == set(
        decision.machine_readable_blocked_reasons
    )


def test_refused_public_run_can_emit_public_safe_refusal_artifact() -> None:
    decision = evaluate_runner_public_mode_refusal(
        _ready_public_evidence(
            wcs_witness_state="missing",
            refusal_artifact_kind="refusal",
        )
    )

    assert decision.final_status == "refused"
    assert decision.refusal_artifact is not None
    assert decision.refusal_artifact.artifact_type == "refusal_artifact"
    assert decision.refusal_artifact.public_private_mode == "public_archive"
    assert decision.refusal_artifact.validates_refused_claim is False
    assert decision.refusal_artifact.grants_public_run_authority is False
    assert "missing_wcs_witness" in (decision.refusal_artifact.machine_readable_blocked_reasons)


def test_privacy_or_rights_holds_keep_refusal_artifact_private() -> None:
    privacy = evaluate_runner_public_mode_refusal(_ready_public_evidence(privacy_state="blocked"))
    rights = evaluate_runner_public_mode_refusal(_ready_public_evidence(rights_state="blocked"))

    assert privacy.refusal_artifact is None
    assert "consent_privacy_hold" in privacy.machine_readable_blocked_reasons
    assert rights.refusal_artifact is None
    assert "rights_hold" in rights.machine_readable_blocked_reasons


def test_correction_artifact_is_public_safe_without_validating_refused_claim() -> None:
    decision = evaluate_runner_public_mode_refusal(
        _ready_public_evidence(
            source_freshness_state="stale",
            refusal_artifact_kind="correction",
        )
    )

    assert decision.refusal_artifact is not None
    assert decision.refusal_artifact.artifact_type == "correction_artifact"
    assert decision.refusal_artifact.validates_refused_claim is False
    assert decision.refusal_artifact.grants_monetization_authority is False


def test_dry_run_cannot_be_promoted_to_public_live_by_default_mode() -> None:
    decision = evaluate_runner_public_mode_refusal(
        _ready_public_evidence(
            requested_mode="dry_run",
            configured_default_mode="public_live",
            explicit_public_mode_request=False,
        )
    )

    assert decision.final_status == "dry_run"
    assert decision.effective_mode == "dry_run"
    assert decision.public_live_allowed is False
    assert decision.public_archive_allowed is False
    assert decision.dry_run_cannot_be_promoted_by_default is True
    assert decision.machine_readable_blocked_reasons == ("default_public_mode_ignored",)


def test_missing_mode_config_cannot_fall_through_to_public_default() -> None:
    decision = evaluate_runner_public_mode_refusal(
        _ready_public_evidence(
            requested_mode=None,
            configured_default_mode="public_live",
            explicit_public_mode_request=True,
        )
    )

    assert decision.final_status == "dry_run"
    assert decision.effective_mode == "dry_run"
    assert decision.public_live_allowed is False
    assert "missing_runner_mode_config" in decision.machine_readable_blocked_reasons
    assert "default_public_mode_ignored" in decision.machine_readable_blocked_reasons


def test_public_mode_requires_explicit_request_even_when_all_gates_pass() -> None:
    decision = evaluate_runner_public_mode_refusal(
        _ready_public_evidence(explicit_public_mode_request=False)
    )

    assert decision.final_status == "refused"
    assert decision.effective_mode == "dry_run"
    assert decision.machine_readable_blocked_reasons == ("public_mode_requires_explicit_request",)


def test_no_expert_system_blocks_unsupported_public_claims() -> None:
    decision = evaluate_runner_public_mode_refusal(
        _ready_public_evidence(
            claim_authority_ceiling="expert",
            unsupported_public_claim=True,
        )
    )

    assert decision.final_status == "refused"
    assert decision.no_expert_system_enforced is True
    assert decision.unsupported_public_claim_can_publish is False
    assert "unsupported_public_claim" in decision.machine_readable_blocked_reasons
    assert decision.refusal_artifact is not None
    assert decision.refusal_artifact.validates_refused_claim is False


def test_public_live_and_monetized_modes_allow_only_when_every_gate_passes() -> None:
    live = evaluate_runner_public_mode_refusal(_ready_public_evidence())
    monetized = evaluate_runner_public_mode_refusal(
        _ready_public_evidence(
            requested_mode="public_monetizable",
            monetization_state="ready",
        )
    )

    assert live.final_status == "allowed"
    assert live.effective_mode == "public_live"
    assert live.public_live_allowed is True
    assert live.machine_readable_blocked_reasons == ()

    assert monetized.final_status == "allowed"
    assert monetized.effective_mode == "public_monetizable"
    assert monetized.public_monetizable_allowed is True
    assert monetized.refusal_artifact is None
