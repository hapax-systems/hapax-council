"""Tests for the legibility claim/audience validator."""

from __future__ import annotations

from shared.evidence_ledger import (
    ClaimRecord,
    LegibilityEvidenceRecord,
    default_audience_profiles,
    validate_claim_for_audiences,
)


def _evidence(
    evidence_id: str = "EV-FRESH",
    *,
    public_safe: bool = False,
    privacy_class: str = "local_private",
    collected_at_epoch: float = 100.0,
    freshness_ttl_s: float = 60.0,
    status: str = "ok",
) -> LegibilityEvidenceRecord:
    return LegibilityEvidenceRecord(
        evidence_id=evidence_id,
        kind="command",
        collected_at_epoch=collected_at_epoch,
        freshness_ttl_s=freshness_ttl_s,
        privacy_class=privacy_class,
        public_safe=public_safe,
        status=status,
        value_summary="verified claim evidence",
    )


def test_default_profiles_cover_required_audiences() -> None:
    profiles = default_audience_profiles()

    assert set(profiles) == {
        "operator",
        "worker_lane",
        "enterprise_testbed",
        "public_adopter",
        "paid_buyer",
        "security_legal_reviewer",
        "intellectual_audience",
    }
    assert profiles["enterprise_testbed"].enterprise_context
    assert profiles["public_adopter"].public_surface


def test_current_state_claim_blocks_missing_evidence() -> None:
    claim = ClaimRecord(
        claim_id="CL-MISSING",
        text="The council health endpoint is healthy right now.",
        claim_kind="current_state",
        audience_scope=["operator"],
        evidence_refs=["EV-MISSING"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(claim, [], now=110.0)

    assert not result.allowed
    assert result.evidence_status == "missing"
    assert result.blockers == ["missing_evidence:EV-MISSING"]


def test_any_claim_without_evidence_refs_blocks() -> None:
    claim = ClaimRecord(
        claim_id="CL-NO-REFS",
        text="Hapax has a packaged claim validator.",
        claim_kind="capability",
        audience_scope=["operator"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(claim, [], now=110.0)

    assert not result.allowed
    assert result.evidence_status == "missing"
    assert result.blockers == ["missing_evidence"]


def test_current_state_claim_blocks_stale_evidence() -> None:
    claim = ClaimRecord(
        claim_id="CL-STALE",
        text="The public homepage returns 200 right now.",
        claim_kind="current_state",
        audience_scope=["operator"],
        evidence_refs=["EV-STALE"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(
        claim,
        [_evidence("EV-STALE", collected_at_epoch=10.0, freshness_ttl_s=5.0)],
        now=100.0,
    )

    assert not result.allowed
    assert result.evidence_status == "stale"
    assert result.blockers == ["stale_current_state_evidence:EV-STALE"]


def test_current_state_claim_blocks_failed_evidence() -> None:
    claim = ClaimRecord(
        claim_id="CL-FAILED",
        text="The package registry is reachable right now.",
        claim_kind="current_state",
        audience_scope=["operator"],
        evidence_refs=["EV-FAILED"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(
        claim,
        [_evidence("EV-FAILED", status="failed")],
        now=110.0,
    )

    assert not result.allowed
    assert result.evidence_status == "contradictory"
    assert result.blockers == ["failed_evidence:EV-FAILED"]


def test_public_claim_blocks_non_public_safe_evidence() -> None:
    claim = ClaimRecord(
        claim_id="CL-PUBLIC-BLOCKED",
        text="Hapax has a working local council API.",
        claim_kind="capability",
        audience_scope=["public_adopter"],
        evidence_refs=["EV-LOCAL"],
        allowed_surfaces=["public_homepage"],
        status="approved_public",
    )

    result = validate_claim_for_audiences(
        claim,
        [_evidence("EV-LOCAL", public_safe=False, privacy_class="local_private")],
        now=110.0,
    )

    assert not result.allowed
    assert result.blockers == ["public_claim_without_public_safe_evidence:EV-LOCAL"]


def test_public_claim_requires_public_approval() -> None:
    claim = ClaimRecord(
        claim_id="CL-PUBLIC-NOT-APPROVED",
        text="hapax-agentgov is published on PyPI.",
        claim_kind="capability",
        audience_scope=["public_adopter"],
        evidence_refs=["EV-PYPI"],
        allowed_surfaces=["repo_readme"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(
        claim,
        [_evidence("EV-PYPI", public_safe=True, privacy_class="public_registry")],
        now=110.0,
    )

    assert not result.allowed
    assert result.blockers == ["public_claim_not_approved"]


def test_enterprise_testbed_blocks_forbidden_inferences() -> None:
    claim = ClaimRecord(
        claim_id="CL-ENTERPRISE",
        text="Alliant adopted Hapax and it is production-ready.",
        claim_kind="adoption",
        audience_scope=["enterprise_testbed"],
        evidence_refs=["EV-RED"],
        allowed_surfaces=["enterprise_pilot_packet"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(claim, [_evidence("EV-RED")], now=110.0)

    assert not result.allowed
    assert result.blockers == [
        "enterprise_forbidden_inference:employer_endorsement",
        "enterprise_forbidden_inference:production_readiness_without_pilot_evidence",
    ]


def test_internal_current_state_claim_with_fresh_private_evidence_passes() -> None:
    claim = ClaimRecord(
        claim_id="CL-INTERNAL",
        text="The local evidence smoke collected five records at collection time.",
        claim_kind="current_state",
        audience_scope=["operator", "worker_lane"],
        evidence_refs=["EV-FRESH"],
        allowed_surfaces=["internal_snapshot"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(claim, [_evidence("EV-FRESH")], now=110.0)

    assert result.allowed
    assert result.evidence_status == "fresh"
    assert result.audience_ids == ["operator", "worker_lane"]


def test_public_claim_with_public_safe_evidence_passes() -> None:
    claim = ClaimRecord(
        claim_id="CL-PUBLIC",
        text="hapax-agentgov has a public package-registry record.",
        claim_kind="capability",
        audience_scope=["public_adopter"],
        evidence_refs=["EV-PYPI"],
        allowed_surfaces=["repo_readme"],
        status="approved_public",
    )

    result = validate_claim_for_audiences(
        claim,
        [_evidence("EV-PYPI", public_safe=True, privacy_class="public_registry")],
        now=110.0,
    )

    assert result.allowed
    assert result.blockers == []


def test_enterprise_claim_blocks_pii_hidden_in_linked_evidence() -> None:
    # Leak-audit gap: PII in a linked evidence record's free-text (not the
    # claim's own text) must still block an enterprise-audience claim.
    evidence = _evidence(evidence_id="EV-LEAK", public_safe=True).model_copy(
        update={"value_summary": "detail in vault:/30-areas/private-x/notes.md"}
    )
    claim = ClaimRecord(
        claim_id="CL-ENT-LEAK",
        text="A portable governance primitive is available.",
        claim_kind="current_state",
        audience_scope=["enterprise_testbed"],
        evidence_refs=["EV-LEAK"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(claim, [evidence], now=110.0)

    assert not result.allowed
    assert "cross_boundary_pii:private_path" in result.blockers


def test_enterprise_claim_blocks_operator_mental_state_in_linked_evidence() -> None:
    # Operator affect hidden in a linked evidence record must block an
    # enterprise-audience claim (cross-boundary egress, fail-closed).
    evidence = _evidence(evidence_id="EV-AFFECT", public_safe=True).model_copy(
        update={"value_summary": "note: the operator felt exhausted and demoralized here"}
    )
    claim = ClaimRecord(
        claim_id="CL-AFFECT",
        text="A portable governance primitive is available.",
        claim_kind="current_state",
        audience_scope=["enterprise_testbed"],
        evidence_refs=["EV-AFFECT"],
        status="approved_internal",
    )

    result = validate_claim_for_audiences(claim, [evidence], now=110.0)

    assert not result.allowed
    assert "cross_boundary_pii:operator_mental_state" in result.blockers
