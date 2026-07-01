"""Tests for the MonDLC M2 freeze artifact contract."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from shared.capdlc_lifecycle import GateStatus
from shared.legal_posture_registry import LegalPostureRegistry
from shared.mdlc_g2_legal import G2LegalRefusal, G2LegalRefusalReason
from shared.mdlc_m2_freeze import (
    M2BudgetEnvelope,
    M2FreezeArtifact,
    M2FreezeRefusal,
    M2FreezeRefusalReason,
    require_m2_commit_admission,
    require_m2_freeze_artifact,
    verify_m2_freeze_artifact,
)
from shared.mdlc_measure import MonDLCLadder

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
HASH = "6bcb5cb7dd30967d20e78d79cb0a470b615f324475bc280062ce5c94e9d14f36"


def _artifact(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "artifact_id": "m2-freeze:test-disposition",
        "budget_envelope": {
            "authority_ref": "authority:CASE-SDLC-REFORM-001",
            "currency": "usd",
            "max_notional": 250.0,
            "max_position": 1.0,
            "purpose": "test disposition freeze",
            "surface": "prediction_market",
            "venue": "test-venue",
            "instrument": "test-instrument",
        },
        "ladder": {
            "ruler_hash": HASH,
            "min_corroboration_count": 2,
            "freshness_ttl_seconds": 3600,
            "as_of": NOW.isoformat(),
            "positive_threshold": 0.0,
            "negative_threshold": -50.0,
        },
        "ruler_hash": HASH,
        "signer": "operator:hapax",
        "signed_at": NOW.isoformat(),
        "signature_ref": "signature:m2-freeze:test-disposition",
        "evidence_refs": ("req:20260628-mdlc-core",),
    }
    data.update(overrides)
    return data


def _legal_registry(*rows: dict[str, object]) -> LegalPostureRegistry:
    return LegalPostureRegistry.from_mapping(
        {
            "schema_version": "1.0.0",
            "schema_doc": "docs/monetization/legal-posture-registry-schema.md",
            "rows": list(rows),
        }
    )


def _legal_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "surface": "prediction_market",
        "venue": "test-venue",
        "instrument": "test-instrument",
        "g2_verdict": "LIT",
        "citation": "test legal citation",
        "authority_basis": "legal_opinion",
        "review_date": "2026-07-01",
        "freshness_ttl_days": 90,
        "operator_signed": True,
        "operator_sign_date": "2026-07-01",
        "notes": "fixture row",
        "open_questions": [],
        "blocks_surfaces": [],
        "source_task": "20260628-registry-phase7-mdlc-g2-gate-wire",
    }
    row.update(overrides)
    return row


def test_signed_freeze_artifact_records_envelope_ladder_hash_signer_and_time() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.LIT
    assert result.ok is True
    assert result.gate_result.verdict is True
    assert result.reason == "m2_freeze_artifact_present"
    assert result.refusal_reason is None
    assert result.expected_ruler_hash == HASH
    assert result.ruler_hash_commit == HASH
    assert result.artifact is not None
    assert result.artifact.budget_envelope.currency == "USD"
    assert result.artifact.budget_envelope.max_notional == 250.0
    assert result.artifact.budget_envelope.surface == "prediction_market"
    assert result.artifact.ladder.ruler_hash == HASH
    assert result.artifact.signer == "operator:hapax"
    assert result.artifact.signed_at == NOW
    assert "m2-freeze:m2-freeze:test-disposition" in result.evidence_refs
    assert "signature:m2-freeze:test-disposition" in result.evidence_refs


def test_freeze_verification_truthiness_is_not_allowed() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit=HASH)

    with pytest.raises(TypeError, match="truthiness is undefined"):
        bool(result)


def test_require_success_returns_freeze_artifact() -> None:
    artifact = require_m2_freeze_artifact(_artifact(), ruler_hash_commit=HASH)

    assert artifact.artifact_id == "m2-freeze:test-disposition"
    assert artifact.ruler_hash == HASH
    assert artifact.ladder.ruler_hash == HASH


def test_require_m2_commit_admission_requires_g2_lit_before_commit() -> None:
    with pytest.raises(G2LegalRefusal) as exc:
        require_m2_commit_admission(
            _artifact(),
            ruler_hash_commit=HASH,
            registry=_legal_registry(),
            today=date(2026, 7, 1),
        )

    assert exc.value.verification.refusal_reason is G2LegalRefusalReason.NO_EXACT_ROW
    assert exc.value.verification.target is not None
    assert exc.value.verification.target.key == (
        "prediction_market",
        "test-venue",
        "test-instrument",
    )


def test_require_m2_commit_admission_propagates_missing_freeze_refusal() -> None:
    with pytest.raises(M2FreezeRefusal) as exc:
        require_m2_commit_admission(
            None,
            ruler_hash_commit=HASH,
            registry=_legal_registry(_legal_row()),
            today=date(2026, 7, 1),
        )

    assert exc.value.verification.refusal_reason is M2FreezeRefusalReason.MISSING_ARTIFACT


def test_require_m2_commit_admission_returns_freeze_and_legal_row() -> None:
    admission = require_m2_commit_admission(
        _artifact(),
        ruler_hash_commit=HASH,
        registry=_legal_registry(_legal_row()),
        today=date(2026, 7, 1),
    )

    assert admission.freeze_artifact.artifact_id == "m2-freeze:test-disposition"
    assert admission.legal_row.key == (
        "prediction_market",
        "test-venue",
        "test-instrument",
    )


def test_require_m2_commit_admission_rejects_g2_target_override() -> None:
    with pytest.raises(M2FreezeRefusal) as exc:
        require_m2_commit_admission(
            _artifact(),
            ruler_hash_commit=HASH,
            g2_target={
                "surface": "bug_bounty",
                "venue": "hackerone",
                "instrument": "universal_jailbreak_bounty",
            },
            registry=_legal_registry(
                _legal_row(
                    surface="bug_bounty",
                    venue="hackerone",
                    instrument="universal_jailbreak_bounty",
                )
            ),
            today=date(2026, 7, 1),
        )

    assert exc.value.verification.refusal_reason is M2FreezeRefusalReason.G2_TARGET_MISMATCH
    assert "differs from the signed freeze envelope" in exc.value.verification.reason


def test_require_m2_commit_admission_refuses_when_freeze_cannot_supply_g2_target() -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget.pop("surface")

    with pytest.raises(G2LegalRefusal) as exc:
        require_m2_commit_admission(
            _artifact(budget_envelope=budget),
            ruler_hash_commit=HASH,
            registry=_legal_registry(_legal_row()),
            today=date(2026, 7, 1),
        )

    assert exc.value.verification.refusal_reason is G2LegalRefusalReason.INVALID_TARGET


def test_require_m2_commit_admission_refuses_legacy_typed_freeze_without_surface() -> None:
    legacy = _artifact()
    budget = dict(legacy["budget_envelope"])
    budget.pop("surface")
    legacy["budget_envelope"] = budget
    artifact = M2FreezeArtifact.from_mapping(legacy)

    assert artifact.budget_envelope.surface == ""
    with pytest.raises(G2LegalRefusal) as exc:
        require_m2_commit_admission(
            artifact,
            ruler_hash_commit=HASH,
            registry=_legal_registry(_legal_row()),
            today=date(2026, 7, 1),
        )

    assert exc.value.verification.refusal_reason is G2LegalRefusalReason.INVALID_TARGET


def test_missing_freeze_artifact_refuses() -> None:
    result = verify_m2_freeze_artifact(None, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_ARTIFACT


def test_boolean_freeze_flag_without_artifact_never_counts_as_presence() -> None:
    result = verify_m2_freeze_artifact(
        {"freeze_lock_fired": True, "ruler_hash": HASH},
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.ok is False
    assert result.gate_result.verdict is None
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_ARTIFACT_ID


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("artifact_id", M2FreezeRefusalReason.MISSING_ARTIFACT_ID),
        ("ruler_hash", M2FreezeRefusalReason.MISSING_RULER_HASH),
    ),
)
def test_artifact_identity_fields_are_required(field: str, reason: M2FreezeRefusalReason) -> None:
    artifact = _artifact()
    artifact.pop(field)

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is reason


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("budget_envelope", M2FreezeRefusalReason.MISSING_BUDGET_ENVELOPE),
        ("ladder", M2FreezeRefusalReason.MISSING_LADDER),
    ),
)
def test_required_mapping_fields_are_required(field: str, reason: M2FreezeRefusalReason) -> None:
    artifact = _artifact()
    artifact.pop(field)

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is reason


def test_invalid_budget_envelope_is_not_reported_as_ladder_failure() -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget["max_notional"] = -1.0

    result = verify_m2_freeze_artifact(
        _artifact(budget_envelope=budget),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_BUDGET_ENVELOPE
    assert result.next_action == "repair the budget envelope fields before commit"


def test_publish_only_without_flood_plan_refuses_at_m2() -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget["publish_only"] = True

    result = verify_m2_freeze_artifact(
        _artifact(budget_envelope=budget),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.PUBLISH_ONLY_WITHOUT_FLOOD_PLAN
    assert (
        result.next_action == "set budget_envelope.flood_plan or mark budget_envelope.non_public/"
        "budget_envelope.no_audience for the publish-only M2 freeze artifact"
    )


def test_legacy_budget_without_flood_fields_loads_private_default() -> None:
    budget = dict(_artifact()["budget_envelope"])
    for field in ("publish_only", "flood_plan", "non_public", "no_audience"):
        budget.pop(field, None)

    envelope = M2BudgetEnvelope.from_mapping(budget)
    artifact = M2FreezeArtifact.from_mapping(_artifact(budget_envelope=budget))

    assert envelope.publish_only is False
    assert envelope.flood_plan == ""
    assert envelope.non_public is False
    assert envelope.no_audience is False
    assert artifact.budget_envelope.flood_plan == ""


def test_flood_envelope_fields_are_serialized() -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget.update(
        {
            "publish_only": True,
            "flood_plan": "flood-plan:public-audience-generation",
            "non_public": False,
            "no_audience": False,
        }
    )

    artifact = M2FreezeArtifact.from_mapping(_artifact(budget_envelope=budget))

    serialized_budget = artifact.to_dict()["budget_envelope"]
    assert serialized_budget["publish_only"] is True
    assert serialized_budget["flood_plan"] == "flood-plan:public-audience-generation"
    assert serialized_budget["non_public"] is False
    assert serialized_budget["no_audience"] is False


def test_budget_envelope_from_mapping_accepts_flood_fields() -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget.update(
        {
            "publish_only": True,
            "flood_plan": "flood-plan:public-audience-generation",
            "non_public": False,
            "no_audience": True,
        }
    )

    envelope = M2BudgetEnvelope.from_mapping(budget)

    assert envelope.publish_only is True
    assert envelope.flood_plan == "flood-plan:public-audience-generation"
    assert envelope.non_public is False
    assert envelope.no_audience is True


@pytest.mark.parametrize("field", ("publish_only", "non_public", "no_audience"))
def test_flood_envelope_bool_fields_must_be_boolean(field: str) -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget[field] = "yes"

    result = verify_m2_freeze_artifact(
        _artifact(budget_envelope=budget),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_BUDGET_ENVELOPE


def test_non_publish_only_freeze_does_not_require_flood_path() -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget["publish_only"] = False

    result = verify_m2_freeze_artifact(
        _artifact(budget_envelope=budget),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.LIT
    assert result.refusal_reason is None


@pytest.mark.parametrize("exemption", ("flood_plan", "non_public", "no_audience"))
def test_publish_only_requires_flood_plan_or_no_audience_exemption(exemption: str) -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget["publish_only"] = True
    if exemption == "flood_plan":
        budget["flood_plan"] = "flood-plan:public-audience-generation"
    else:
        budget[exemption] = True

    result = verify_m2_freeze_artifact(
        _artifact(budget_envelope=budget),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.LIT
    assert result.refusal_reason is None


def test_publish_only_all_private_exemptions_pass() -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget.update({"publish_only": True, "non_public": True, "no_audience": True})

    result = verify_m2_freeze_artifact(
        _artifact(budget_envelope=budget),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.LIT
    assert result.refusal_reason is None


def test_invalid_ladder_refuses_with_ladder_reason() -> None:
    ladder = dict(_artifact()["ladder"])
    ladder["min_corroboration_count"] = 0

    result = verify_m2_freeze_artifact(_artifact(ladder=ladder), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_LADDER
    assert result.next_action == "repair the frozen ruler ladder before commit"


@pytest.mark.parametrize(
    "missing_field",
    (
        "min_corroboration_count",
        "freshness_ttl_seconds",
        "positive_threshold",
        "negative_threshold",
    ),
)
def test_freeze_ladder_must_record_canonical_fields(missing_field: str) -> None:
    ladder = dict(_artifact()["ladder"])
    ladder.pop(missing_field)

    result = verify_m2_freeze_artifact(_artifact(ladder=ladder), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_LADDER


def test_freeze_ladder_does_not_accept_measurement_alias_defaults() -> None:
    artifact = _artifact(
        ladder={
            "ruler_hash": HASH,
            "min_N": 2,
            "freshness_ttl_s": 3600,
            "positive_threshold": 0.0,
            "negative_threshold": -50.0,
        }
    )

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_LADDER


def test_invalid_signed_at_refuses_with_timestamp_reason() -> None:
    result = verify_m2_freeze_artifact(
        _artifact(signed_at="not-a-timestamp"),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_SIGNED_AT


def test_invalid_evidence_refs_has_specific_refusal_reason() -> None:
    result = verify_m2_freeze_artifact(
        _artifact(evidence_refs="not-a-sequence"),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_EVIDENCE_REFS


def test_unrecognized_artifact_value_error_has_generic_artifact_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_unrecognized_value_error(
        cls: type[M2FreezeArtifact],
        raw: object,
    ) -> M2FreezeArtifact:
        raise ValueError("unexpected artifact failure")

    monkeypatch.setattr(
        M2FreezeArtifact,
        "from_mapping",
        classmethod(raise_unrecognized_value_error),
    )

    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_ARTIFACT
    assert result.next_action == "repair the signed M2 freeze artifact"


def test_missing_ruler_hash_commit_refuses_before_m2_commit() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit=None)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_RULER_HASH_COMMIT
    assert result.expected_ruler_hash == HASH
    assert result.next_action == "supply the commit ruler hash from the freeze artifact"


def test_whitespace_ruler_hash_commit_refuses_before_m2_commit() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit="  ")

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_RULER_HASH_COMMIT
    assert result.expected_ruler_hash == HASH
    assert result.next_action == "supply the commit ruler hash from the freeze artifact"


def test_mismatched_ruler_hash_refuses_and_require_raises() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit="different")

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.RULER_HASH_MISMATCH
    assert result.expected_ruler_hash == HASH
    assert "m2-freeze:m2-freeze:test-disposition" in result.gate_result.evidence_refs
    assert "signature:m2-freeze:test-disposition" in result.gate_result.evidence_refs

    with pytest.raises(M2FreezeRefusal) as exc:
        require_m2_freeze_artifact(_artifact(), ruler_hash_commit="different")
    assert exc.value.verification.refusal_reason is M2FreezeRefusalReason.RULER_HASH_MISMATCH


def test_ladder_hash_must_match_artifact_hash() -> None:
    artifact = _artifact(
        ladder={
            "ruler_hash": "ab4a8998e57aef44d6d38d0f3dfc848a690de988f7266a4eba2a224a7c883118",
            "min_corroboration_count": 2,
            "freshness_ttl_seconds": 3600,
            "as_of": NOW.isoformat(),
            "positive_threshold": 0.0,
            "negative_threshold": -50.0,
        }
    )

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.LADDER_RULER_HASH_MISMATCH


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("signer", M2FreezeRefusalReason.MISSING_SIGNER),
        ("signed_at", M2FreezeRefusalReason.MISSING_SIGNED_AT),
        ("signature_ref", M2FreezeRefusalReason.MISSING_SIGNATURE_REF),
    ),
)
def test_signature_fields_are_required(field: str, reason: M2FreezeRefusalReason) -> None:
    artifact = _artifact()
    artifact.pop(field)

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is reason


def test_freeze_artifact_requires_typed_budget_envelope_and_ladder() -> None:
    budget = M2BudgetEnvelope(
        authority_ref="authority:CASE-SDLC-REFORM-001",
        currency="USD",
        max_notional=250.0,
        max_position=1.0,
    )
    ladder = MonDLCLadder(
        ruler_hash=HASH,
        min_corroboration_count=2,
        freshness_ttl_seconds=3600,
        as_of=NOW,
        positive_threshold=0.0,
        negative_threshold=-50.0,
    )

    with pytest.raises(TypeError, match="budget_envelope"):
        M2FreezeArtifact(
            artifact_id="m2-freeze:test-disposition",
            budget_envelope=object(),  # type: ignore[arg-type]
            ladder=ladder,
            ruler_hash=HASH,
            signer="operator:hapax",
            signed_at=NOW,
            signature_ref="signature:m2-freeze:test-disposition",
        )

    with pytest.raises(TypeError, match="ladder"):
        M2FreezeArtifact(
            artifact_id="m2-freeze:test-disposition",
            budget_envelope=budget,
            ladder=object(),  # type: ignore[arg-type]
            ruler_hash=HASH,
            signer="operator:hapax",
            signed_at=NOW,
            signature_ref="signature:m2-freeze:test-disposition",
        )
