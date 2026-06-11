"""Tests for legibility surface contracts in the publication registry."""

from __future__ import annotations

from agents.publication_bus.surface_registry import SurfaceContract, lint_surface_contract
from shared.evidence_ledger import ClaimRecord, LegibilityEvidenceRecord


def _evidence(
    evidence_id: str = "EV-PUBLIC",
    *,
    public_safe: bool = True,
    privacy_class: str = "public_registry",
    collected_at_epoch: float = 100.0,
    freshness_ttl_s: float = 60.0,
    status: str = "ok",
) -> LegibilityEvidenceRecord:
    return LegibilityEvidenceRecord(
        evidence_id=evidence_id,
        kind="public_url",
        collected_at_epoch=collected_at_epoch,
        freshness_ttl_s=freshness_ttl_s,
        privacy_class=privacy_class,
        public_safe=public_safe,
        status=status,
        value_summary="public-safe surface evidence",
    )


def _public_claim(
    claim_id: str = "CL-PUBLIC",
    *,
    claim_kind: str = "capability",
    evidence_refs: list[str] | None = None,
    status: str = "approved_public",
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        text="Hapax has a claim/evidence manifest for reviewed public surfaces.",
        claim_kind=claim_kind,
        audience_scope=["public_adopter"],
        evidence_refs=evidence_refs or ["EV-PUBLIC"],
        allowed_surfaces=["public_homepage"],
        status=status,
    )


def test_surface_contract_schema_links_audiences_and_claims() -> None:
    contract = SurfaceContract(
        surface_id="public_refusal_brief",
        surface_type="public_page",
        audience_refs=["public_adopter", "intellectual_audience"],
        allowed_claim_refs=["CL-PUBLIC"],
        source_mode="generated_from_claim_ledger",
        publication_surface_ref="omg-weblog",
    )

    assert contract.audience_refs == ["public_adopter", "intellectual_audience"]
    assert contract.allowed_claim_refs == ["CL-PUBLIC"]
    assert contract.publication_surface_ref == "omg-weblog"


def test_linter_rejects_current_state_count_without_fresh_evidence() -> None:
    contract = SurfaceContract(
        surface_id="operator_snapshot",
        surface_type="internal_snapshot",
        audience_refs=["operator"],
        allowed_claim_refs=["CL-COUNT"],
    )
    claim = ClaimRecord(
        claim_id="CL-COUNT",
        text="The council worktree has 3 dirty paths right now.",
        claim_kind="current_state",
        audience_scope=["operator"],
        evidence_refs=["EV-STALE"],
        allowed_surfaces=["internal_snapshot"],
        status="approved_internal",
    )

    result = lint_surface_contract(
        contract,
        [claim],
        [_evidence("EV-STALE", collected_at_epoch=10.0, freshness_ttl_s=5.0)],
        now=100.0,
    )

    assert not result.allowed
    assert "current_state_count_without_fresh_evidence:CL-COUNT" in result.blockers
    assert "claim_blocked:CL-COUNT:stale_current_state_evidence:EV-STALE" in result.blockers


def test_linter_rejects_public_surface_with_unsupported_claim_id() -> None:
    contract = SurfaceContract(
        surface_id="public_homepage",
        surface_type="public_page",
        audience_refs=["public_adopter"],
        allowed_claim_refs=["CL-MISSING"],
        publication_surface_ref="omg-weblog",
    )

    result = lint_surface_contract(contract, [], [_evidence()], now=110.0)

    assert not result.allowed
    assert result.blockers == ["unsupported_claim_id:CL-MISSING"]


def test_linter_bridges_existing_publication_surface_registry() -> None:
    contract = SurfaceContract(
        surface_id="public_homepage",
        surface_type="public_page",
        audience_refs=["public_adopter"],
        allowed_claim_refs=["CL-PUBLIC"],
        publication_surface_ref="omg-weblog",
    )

    result = lint_surface_contract(contract, [_public_claim()], [_evidence()], now=110.0)

    assert result.allowed
    assert result.blockers == []


def test_linter_rejects_refused_publication_surface() -> None:
    contract = SurfaceContract(
        surface_id="public_thread",
        surface_type="public_page",
        audience_refs=["public_adopter"],
        allowed_claim_refs=["CL-PUBLIC"],
        publication_surface_ref="twitter-x-account",
    )

    result = lint_surface_contract(contract, [_public_claim()], [_evidence()], now=110.0)

    assert not result.allowed
    assert "refused_publication_surface:twitter-x-account" in result.blockers


def test_linter_rejects_unknown_publication_surface_with_registry_override() -> None:
    contract = SurfaceContract(
        surface_id="public_homepage",
        surface_type="public_page",
        audience_refs=["public_adopter"],
        allowed_claim_refs=["CL-PUBLIC"],
        publication_surface_ref="omg-weblog",
    )

    result = lint_surface_contract(
        contract,
        [_public_claim()],
        [_evidence()],
        surface_registry={},
        now=110.0,
    )

    assert not result.allowed
    assert "unknown_publication_surface:omg-weblog" in result.blockers


def test_linter_rejects_legacy_untrusted_surface() -> None:
    contract = SurfaceContract(
        surface_id="old_homepage_copy",
        surface_type="public_page",
        audience_refs=["public_adopter"],
        allowed_claim_refs=["CL-PUBLIC"],
        source_mode="legacy_untrusted",
    )

    result = lint_surface_contract(contract, [_public_claim()], [_evidence()], now=110.0)

    assert not result.allowed
    assert "legacy_untrusted_surface" in result.blockers


def test_linter_emits_claim_evidence_manifest_for_valid_surface() -> None:
    contract = SurfaceContract(
        surface_id="public_homepage",
        surface_type="public_page",
        audience_refs=["public_adopter"],
        allowed_claim_refs=["CL-PUBLIC"],
        publication_surface_ref="omg-weblog",
    )

    result = lint_surface_contract(contract, [_public_claim()], [_evidence()], now=110.0)

    assert result.allowed
    assert result.manifest.surface_id == "public_homepage"
    assert result.manifest.claim_ids == ["CL-PUBLIC"]
    assert result.manifest.evidence_ids == {"CL-PUBLIC": ["EV-PUBLIC"]}
    assert result.manifest.evidence_status == {"CL-PUBLIC": "fresh"}
