"""Tests for the RDLC publication vehicle selector."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from shared.preprint_artifact import ApprovalState, PreprintArtifact
from shared.rdlc_experimental_disposition import (
    RdlcDispositionKind,
    RdlcDispositionReceipt,
    RdlcExperimentalObservation,
    RdlcRiskLevel,
    RdlcTaskConversion,
    build_disposition_receipt,
)
from shared.rdlc_publication_vehicle_selector import (
    VEHICLE_SPECS,
    RdlcPublicationAudienceFamily,
    RdlcPublicationSelectorDecision,
    RdlcPublicationVehicle,
    RdlcPublicationVehicleError,
    RdlcSurfaceRole,
    build_preprint_draft_from_vehicle_selection,
    build_publication_vehicle_selector_receipt,
)


def _observation(**overrides) -> RdlcExperimentalObservation:
    defaults = {
        "observation_id": "obs-pr-4460-merge",
        "source_refs": ("github:hapax-systems/hapax-council#4460",),
        "authority_case": "CASE-RDLC-SDLC-EXPERIMENTAL-CONTEXT-20260704",
        "parent_spec": (
            "/home/hapax/Documents/Personal/30-areas/hapax/"
            "rdlc-sdlc-experimental-loop-publication-program-2026-07-04.md"
        ),
        "observation_kind": "merge_queue_experiment",
        "intervention": "RDLC disposition adapter added to SDLC loop",
        "outcome": "publish-candidate path can be evaluated before egress",
        "claim_ceiling": "case-study candidate, not generalized causal proof",
        "privacy_risk": RdlcRiskLevel.LOW,
        "air_risk": RdlcRiskLevel.LOW,
        "evidence_refs": ("merge-commit:366878783152a317578fc9a4cb55d3e2d7d76083",),
    }
    defaults.update(overrides)
    return RdlcExperimentalObservation(**defaults)


def _publish_candidate(**overrides):
    defaults = {
        "observation": _observation(),
        "disposition": RdlcDispositionKind.PUBLISH_CANDIDATE,
        "rationale": "all custody, assay, and freeze inputs are present",
        "claim_text": "The SDLC can provide adjacent experimental context for the RDLC loop.",
        "claim_ceiling": "case-study candidate, not generalized causal proof",
        "frozen_ruler_ref": "sha256:rdlc-ruler",
        "frozen_ruler_version": "2026-07-08T04:12:33Z",
        "public_safe_evidence_refs": ("public:pr-4460-merge-summary",),
        "freshness_ref": "gh:pr-4460:3668787",
        "currentness_ref": "gh:merge:2026-07-08T04:12:33Z",
    }
    defaults.update(overrides)
    observation = defaults.pop("observation")
    return build_disposition_receipt(observation, **defaults)


def _constructed_publish_candidate(**overrides) -> RdlcDispositionReceipt:
    defaults = {
        "schema_version": 1,
        "receipt_id": "rdlc-disp:constructed:publish_candidate",
        "observation": _observation(),
        "disposition": RdlcDispositionKind.PUBLISH_CANDIDATE,
        "rationale": "constructed receipt for selector-layer gate coverage",
        "claim_text": "The SDLC can provide adjacent experimental context for the RDLC loop.",
        "claim_ceiling": "case-study candidate, not generalized causal proof",
        "frozen_ruler_ref": "sha256:rdlc-ruler",
        "frozen_ruler_version": "2026-07-08T04:12:33Z",
        "public_safe_evidence_refs": ("public:pr-4460-merge-summary",),
        "freshness_ref": "gh:pr-4460:3668787",
        "currentness_ref": "gh:merge:2026-07-08T04:12:33Z",
        "task_conversion": None,
        "blocked_reasons": (),
    }
    defaults.update(overrides)
    return RdlcDispositionReceipt.model_construct(**defaults)


@pytest.mark.parametrize(
    "disposition",
    [
        RdlcDispositionKind.SUPPORT_NON_AUTHORITATIVE,
        RdlcDispositionKind.BLOCKED,
        RdlcDispositionKind.CONVERT_TO_TASK,
    ],
)
def test_non_publish_candidate_dispositions_refuse_before_draft(disposition) -> None:
    kwargs = {}
    if disposition == RdlcDispositionKind.CONVERT_TO_TASK:
        kwargs["task_conversion"] = RdlcTaskConversion(
            title="Follow-up selector evidence task",
            mutation_scope_refs=("shared/rdlc_publication_vehicle_selector.py",),
            acceptance_refs=("selector evidence task exists",),
            rationale="non-public task conversion",
        )
    receipt = build_disposition_receipt(
        _observation(),
        disposition=disposition,
        rationale=f"{disposition.value} is not public egress",
        **kwargs,
    )

    selector = build_publication_vehicle_selector_receipt(
        receipt,
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.REFUSED
    assert any(
        reason == f"missing_publication:disposition:{receipt.disposition.value}"
        for reason in selector.blocked_reasons
    )
    with pytest.raises(RdlcPublicationVehicleError, match="refused selector receipt"):
        build_preprint_draft_from_vehicle_selection(selector, slug="blocked")


def test_publish_candidate_selects_method_note_and_surface_roles() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.SELECTED
    assert selector.recommended_vehicle == RdlcPublicationVehicle.METHOD_NOTE
    roles = {surface.role for surface in selector.selected_surfaces}
    assert {
        RdlcSurfaceRole.CANONICAL_HOME,
        RdlcSurfaceRole.DOI_CITATION,
        RdlcSurfaceRole.SOCIAL_SUMMARY,
        RdlcSurfaceRole.ARCHIVE,
    } <= roles
    assert selector.surface_budget_profile is not None
    assert selector.public_abstract is not None
    assert selector.public_body_md is not None
    assert "Claim ceiling: case-study candidate" in selector.public_body_md
    assert "public:pr-4460-merge-summary" in selector.public_body_md


def test_audience_family_maps_to_vehicle_class() -> None:
    cases = {
        RdlcPublicationAudienceFamily.SYSTEMS_ENGINEERING: RdlcPublicationVehicle.TECHNICAL_NOTE,
        RdlcPublicationAudienceFamily.GOVERNANCE_SAFETY: (
            RdlcPublicationVehicle.GOVERNANCE_SAFETY_NOTE
        ),
        RdlcPublicationAudienceFamily.DATASET_USERS: RdlcPublicationVehicle.DATASET_CARD,
        RdlcPublicationAudienceFamily.ARTIFACT_INDEX: (RdlcPublicationVehicle.ARTIFACT_INDEX_ENTRY),
        RdlcPublicationAudienceFamily.PRODUCT_RESEARCH: (
            RdlcPublicationVehicle.PRODUCT_RESEARCH_UPDATE
        ),
    }

    for audience, vehicle in cases.items():
        selector = build_publication_vehicle_selector_receipt(
            _publish_candidate(),
            audience_family=audience,
        )
        assert selector.decision == RdlcPublicationSelectorDecision.SELECTED
        assert selector.recommended_vehicle == vehicle


def test_high_risk_research_methods_demotes_to_refusal_when_vehicle_mismatches_audience() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(observation=_observation(privacy_risk=RdlcRiskLevel.HIGH)),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
        risk_posture=RdlcRiskLevel.HIGH,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.REFUSED
    assert "vehicle_audience_mismatch:governance_safety_note:research_methods" in (
        selector.blocked_reasons
    )


def test_high_risk_governance_audience_selects_restrained_vehicle() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(observation=_observation(privacy_risk=RdlcRiskLevel.HIGH)),
        audience_family=RdlcPublicationAudienceFamily.GOVERNANCE_SAFETY,
        risk_posture=RdlcRiskLevel.HIGH,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.SELECTED
    assert selector.recommended_vehicle == RdlcPublicationVehicle.GOVERNANCE_SAFETY_NOTE
    assert selector.selected_surface_slugs() == ("omg-weblog", "osf-preprint", "zenodo-doi")


def test_high_risk_defaults_from_observation_when_no_explicit_risk_posture() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(observation=_observation(privacy_risk=RdlcRiskLevel.HIGH)),
        audience_family=RdlcPublicationAudienceFamily.GOVERNANCE_SAFETY,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.SELECTED
    assert selector.selector_input.risk_posture == RdlcRiskLevel.HIGH
    assert selector.recommended_vehicle == RdlcPublicationVehicle.GOVERNANCE_SAFETY_NOTE


def test_high_air_risk_defaults_to_restrained_vehicle() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(
            observation=_observation(
                privacy_risk=RdlcRiskLevel.LOW,
                air_risk=RdlcRiskLevel.HIGH,
            )
        ),
        audience_family=RdlcPublicationAudienceFamily.GOVERNANCE_SAFETY,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.SELECTED
    assert selector.selector_input.risk_posture == RdlcRiskLevel.HIGH
    assert selector.recommended_vehicle == RdlcPublicationVehicle.GOVERNANCE_SAFETY_NOTE


def test_missing_public_safe_or_currentness_evidence_refuses_publication() -> None:
    missing_public_safe = build_publication_vehicle_selector_receipt(
        _constructed_publish_candidate(public_safe_evidence_refs=()),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )
    missing_currentness = build_publication_vehicle_selector_receipt(
        _constructed_publish_candidate(currentness_ref=None),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )

    assert missing_public_safe.decision == RdlcPublicationSelectorDecision.REFUSED
    assert "missing_publication:disposition:blocked" not in missing_public_safe.blocked_reasons
    assert "missing_publication:public_safe_evidence_refs" in missing_public_safe.blocked_reasons
    assert missing_currentness.decision == RdlcPublicationSelectorDecision.REFUSED
    assert "missing_publication:disposition:blocked" not in missing_currentness.blocked_reasons
    assert "missing_publication:currentness_ref" in missing_currentness.blocked_reasons


def test_public_safe_refs_do_not_satisfy_frozen_evidence_gate() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _constructed_publish_candidate(frozen_ruler_ref=None),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.REFUSED
    assert selector.selector_input.public_safe_evidence_refs == ("public:pr-4460-merge-summary",)
    assert selector.selector_input.frozen_evidence_refs == ()
    assert "missing_publication:disposition:blocked" not in selector.blocked_reasons
    assert "missing_publication:frozen_evidence_refs" in selector.blocked_reasons


def test_unversioned_frozen_ruler_ref_does_not_satisfy_frozen_evidence_gate() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _constructed_publish_candidate(frozen_ruler_version=None),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.REFUSED
    assert selector.selector_input.frozen_evidence_refs == ()
    assert "missing_publication:disposition:blocked" not in selector.blocked_reasons
    assert "missing_publication:frozen_evidence_refs" in selector.blocked_reasons


def test_blank_frozen_ruler_fields_do_not_satisfy_frozen_evidence_gate() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _constructed_publish_candidate(frozen_ruler_ref=" ", frozen_ruler_version=" "),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.REFUSED
    assert selector.selector_input.frozen_evidence_refs == ()
    assert "missing_publication:frozen_evidence_refs" in selector.blocked_reasons


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"claim_text": None}, "missing_publication:claim_text"),
        (
            {"observation": _observation(claim_ceiling=None), "claim_ceiling": None},
            "missing_publication:claim_ceiling",
        ),
        ({"freshness_ref": None}, "missing_publication:freshness_ref"),
    ],
)
def test_missing_claim_or_freshness_fields_emit_specific_selector_reasons(
    overrides,
    expected_reason: str,
) -> None:
    selector = build_publication_vehicle_selector_receipt(
        _constructed_publish_candidate(**overrides),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )

    assert selector.decision == RdlcPublicationSelectorDecision.REFUSED
    assert "missing_publication:disposition:blocked" not in selector.blocked_reasons
    assert expected_reason in selector.blocked_reasons


def test_selected_vehicle_builds_draft_only_preprint_artifact(monkeypatch) -> None:
    write_attempts: list[str] = []
    original_open = Path.open
    original_builtin_open = builtins.open

    def fail_on_write(path: Path, mode: str = "r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            write_attempts.append(f"Path.open:{path}:{mode}")
            raise AssertionError(f"unexpected artifact write to {path} with mode {mode}")
        return original_open(path, mode, *args, **kwargs)

    def fail_path_write(path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        write_attempts.append(f"Path.write:{path}")
        raise AssertionError(f"unexpected artifact write to {path}")

    def fail_builtin_write(file, mode: str = "r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            write_attempts.append(f"builtins.open:{file}:{mode}")
            raise AssertionError(f"unexpected artifact write to {file} with mode {mode}")
        return original_builtin_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_on_write)
    monkeypatch.setattr(Path, "write_text", fail_path_write)
    monkeypatch.setattr(Path, "write_bytes", fail_path_write)
    monkeypatch.setattr(builtins, "open", fail_builtin_write)
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )

    artifact = build_preprint_draft_from_vehicle_selection(
        selector,
        slug="rdlc-sdlc-method-note",
        title="RDLC SDLC Method Note",
    )

    assert isinstance(artifact, PreprintArtifact)
    assert artifact.approval == ApprovalState.DRAFT
    assert "publish/inbox" not in str(artifact.draft_path(state_root=Path("/tmp/state")))
    assert "omg-weblog" in artifact.surfaces_targeted
    assert "osf-preprint" in artifact.surfaces_targeted
    assert "zenodo-doi" in artifact.surfaces_targeted
    assert artifact.publication_gate_context is not None
    assert artifact.publication_gate_context["egress_state"] == "draft_only_no_inbox_write"
    assert artifact.publication_gate_context["publication_authorized"] is False
    assert artifact.publication_gate_context["claim_ceiling"] == (
        "case-study candidate, not generalized causal proof"
    )
    assert artifact.publication_gate_context["rdlc_disposition_receipt_id"] == (
        "rdlc-disp:obs-pr-4460-merge:publish_candidate"
    )
    assert artifact.publication_gate_context["frozen_evidence_refs"] == [
        "sha256:rdlc-ruler@2026-07-08T04:12:33Z"
    ]
    assert artifact.publication_gate_context["currentness_evidence_refs"] == [
        "gh:merge:2026-07-08T04:12:33Z",
        "gh:pr-4460:3668787",
    ]
    assert any(
        item["role"] == "doi_citation"
        for item in artifact.publication_gate_context["surface_roles"]
    )
    assert write_attempts == []


def test_dataset_card_draft_deduplicates_repeated_surface_targets() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(),
        audience_family=RdlcPublicationAudienceFamily.DATASET_USERS,
    )
    raw_surfaces = tuple(surface.surface for surface in selector.selected_surfaces)

    artifact = build_preprint_draft_from_vehicle_selection(
        selector,
        slug="rdlc-sdlc-dataset-card",
    )

    assert raw_surfaces.count("zenodo-doi") == 2
    assert artifact.surfaces_targeted.count("zenodo-doi") == 1
    assert artifact.surfaces_targeted == ["omg-weblog", "zenodo-doi"]


def test_malformed_selected_receipt_cannot_build_draft() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )
    malformed = selector.model_copy(update={"recommended_vehicle": None})

    with pytest.raises(RdlcPublicationVehicleError, match="next action: rebuild"):
        build_preprint_draft_from_vehicle_selection(malformed, slug="malformed")


def test_reconstructed_selected_receipt_must_still_satisfy_publication_gates() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )
    unsafe_input = selector.selector_input.model_copy(update={"currentness_ref": None})
    reconstructed = selector.model_copy(update={"selector_input": unsafe_input})

    with pytest.raises(RdlcPublicationVehicleError, match="currentness_ref"):
        build_preprint_draft_from_vehicle_selection(reconstructed, slug="unsafe")


def test_reconstructed_selected_receipt_must_match_vehicle_surface_policy() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )
    product_spec = VEHICLE_SPECS[RdlcPublicationVehicle.PRODUCT_RESEARCH_UPDATE]
    reconstructed = selector.model_copy(
        update={
            "recommended_vehicle": product_spec.vehicle,
            "surface_budget_profile": product_spec.budget_profile,
            "selected_surfaces": product_spec.surfaces,
        }
    )

    with pytest.raises(RdlcPublicationVehicleError, match="vehicle/surface policy mismatch"):
        build_preprint_draft_from_vehicle_selection(reconstructed, slug="surface-injection")


def test_reconstructed_selected_receipt_must_match_audience_vehicle_policy() -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(observation=_observation(privacy_risk=RdlcRiskLevel.HIGH)),
        audience_family=RdlcPublicationAudienceFamily.GOVERNANCE_SAFETY,
    )
    mismatched_input = selector.selector_input.model_copy(
        update={"audience_family": RdlcPublicationAudienceFamily.RESEARCH_METHODS}
    )
    reconstructed = selector.model_copy(update={"selector_input": mismatched_input})

    with pytest.raises(RdlcPublicationVehicleError, match="audience does not match"):
        build_preprint_draft_from_vehicle_selection(reconstructed, slug="audience-mismatch")


@pytest.mark.parametrize(
    "updates",
    [
        {"hardening_context": {}},
        {"public_abstract": "tampered abstract"},
        {"public_body_md": "# Tampered body"},
        {"vehicle_rationale": "tampered rationale"},
        {"blocked_reasons": ("should_not_be_selected",)},
    ],
)
def test_reconstructed_selected_receipt_must_match_selector_content(updates) -> None:
    selector = build_publication_vehicle_selector_receipt(
        _publish_candidate(),
        audience_family=RdlcPublicationAudienceFamily.RESEARCH_METHODS,
    )
    reconstructed = selector.model_copy(update=updates)

    with pytest.raises(RdlcPublicationVehicleError, match="content/hardening policy mismatch"):
        build_preprint_draft_from_vehicle_selection(reconstructed, slug="tampered")
