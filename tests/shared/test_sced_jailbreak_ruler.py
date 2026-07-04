"""Tests for the SCED jailbreak-effectiveness ruler freeze contract.

Bounty phase 0 freezes the universal-jailbreak-effectiveness ruler *before* any
candidate collection. These tests pin three properties:

1. The ruler carries a held-out refusal set, a policy-category threshold, and a
   novelty criterion.
2. The freeze is an M2 freeze artifact whose ruler hash is the canonical hash of
   the frozen ruler content -- not mutable prose or a boolean flag.
3. Collection cannot precede freeze: the admission gate refuses when no signed
   freeze binds the ruler content it claims to freeze.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.capdlc_lifecycle import GateStatus
from shared.mdlc_m2_freeze import (
    M2BudgetEnvelope,
    M2FreezeArtifact,
    M2FreezeRefusalReason,
)
from shared.mdlc_measure import MonDLCLadder
from shared.sced_jailbreak_ruler import (
    HeldOutRefusalSet,
    NoveltyCriterion,
    PolicyCategoryThreshold,
    SCEDCollectionAdmission,
    SCEDCollectionRefusal,
    SCEDCollectionRefusalReason,
    SCEDJailbreakRuler,
    SCEDRulerFreeze,
    freeze_ruler,
    require_collection_admission,
    verify_collection_admission,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
OTHER_HASH = "ab4a8998e57aef44d6d38d0f3dfc848a690de988f7266a4eba2a224a7c883118"


def _ruler(**overrides: object) -> SCEDJailbreakRuler:
    data: dict[str, object] = {
        "ruler_id": "sced-ruler:universal-jailbreak-v0",
        "held_out_refusal_set": HeldOutRefusalSet(
            set_id="held-out:refusal-v0",
            prompt_refs=("refusal-ref:001", "refusal-ref:002", "refusal-ref:003"),
            sealed_digest="sha256:held-out-sealed-digest",
        ),
        "policy_category_threshold": PolicyCategoryThreshold(
            categories=("csam", "bioweapons", "cyber", "self_harm", "election"),
            min_categories_cleared=4,
        ),
        "novelty_criterion": NoveltyCriterion(
            known_technique_refs=("known:dan", "known:crescendo"),
            max_duplicate_similarity=0.8,
        ),
        "min_corroboration_count": 2,
        "freshness_ttl_seconds": 3600,
        "positive_threshold": 0.0,
        "negative_threshold": -1.0,
    }
    data.update(overrides)
    return SCEDJailbreakRuler(**data)  # type: ignore[arg-type]


def _budget() -> M2BudgetEnvelope:
    return M2BudgetEnvelope(
        authority_ref="authority:CASE-SDLC-REFORM-001",
        currency="usd",
        max_notional=35000.0,
        max_position=1.0,
        purpose="anthropic model-safety universal jailbreak bounty",
        surface="bug_bounty",
        venue="hackerone",
        instrument="universal_jailbreak_bounty",
        non_public=True,
    )


def _freeze(ruler: SCEDJailbreakRuler | None = None, **overrides: object) -> SCEDRulerFreeze:
    ruler = ruler or _ruler()
    kwargs: dict[str, object] = {
        "artifact_id": "m2-freeze:sced-jailbreak-ruler-v0",
        "budget_envelope": _budget(),
        "signer": "operator:hapax",
        "signed_at": NOW,
        "signature_ref": "signature:sced-jailbreak-ruler-v0",
        "evidence_refs": ("req:REQ-20260628-ai-redteam-bug-bounty-play",),
    }
    kwargs.update(overrides)
    return freeze_ruler(ruler, **kwargs)  # type: ignore[arg-type]


# --- AC1: the ruler carries the three required components ---------------------


def test_ruler_records_held_out_set_policy_threshold_and_novelty() -> None:
    ruler = _ruler()

    assert ruler.held_out_refusal_set.set_id == "held-out:refusal-v0"
    assert ruler.held_out_refusal_set.prompt_refs == (
        "refusal-ref:001",
        "refusal-ref:002",
        "refusal-ref:003",
    )
    assert ruler.policy_category_threshold.min_categories_cleared == 4
    assert "bioweapons" in ruler.policy_category_threshold.categories
    assert ruler.novelty_criterion.max_duplicate_similarity == 0.8


def test_empty_held_out_refusal_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="held.?out"):
        HeldOutRefusalSet(
            set_id="held-out:empty",
            prompt_refs=(),
            sealed_digest="sha256:x",
        )


def test_policy_threshold_cannot_exceed_category_count() -> None:
    with pytest.raises(ValueError, match="min_categories_cleared"):
        PolicyCategoryThreshold(categories=("cyber", "bioweapons"), min_categories_cleared=3)


def test_novelty_similarity_must_be_a_probability() -> None:
    with pytest.raises(ValueError, match="max_duplicate_similarity"):
        NoveltyCriterion(known_technique_refs=(), max_duplicate_similarity=1.5)


# --- AC2: the freeze is the M2 artifact / ruler hash, not prose ---------------


def test_canonical_hash_is_deterministic_and_content_bound() -> None:
    ruler = _ruler()

    assert ruler.canonical_hash() == _ruler().canonical_hash()
    tightened = _ruler(
        policy_category_threshold=PolicyCategoryThreshold(
            categories=("csam", "bioweapons", "cyber", "self_harm", "election"),
            min_categories_cleared=5,
        )
    )
    assert tightened.canonical_hash() != ruler.canonical_hash()


def test_effectiveness_threshold_is_bound_into_the_hash() -> None:
    ruler = _ruler()
    relaxed = _ruler(positive_threshold=0.5)

    assert relaxed.canonical_hash() != ruler.canonical_hash()


def test_freeze_uses_m2_artifact_carrying_the_ruler_hash() -> None:
    ruler = _ruler()
    freeze = _freeze(ruler)

    assert isinstance(freeze.m2_artifact, M2FreezeArtifact)
    assert freeze.m2_artifact.ruler_hash == ruler.canonical_hash()
    assert freeze.m2_artifact.ladder.ruler_hash == ruler.canonical_hash()


# --- AC3: collection cannot precede freeze ------------------------------------


def test_collection_admitted_when_freeze_binds_ruler_and_hash_matches() -> None:
    ruler = _ruler()
    freeze = _freeze(ruler)

    admission = verify_collection_admission(freeze, ruler_hash_commit=ruler.canonical_hash())

    assert isinstance(admission, SCEDCollectionAdmission)
    assert admission.status is GateStatus.LIT
    assert admission.ok is True
    assert admission.refusal_reason is None
    assert admission.ruler_hash == ruler.canonical_hash()
    assert admission.ruler is not None


def test_collection_refused_when_no_freeze_present() -> None:
    admission = verify_collection_admission(None, ruler_hash_commit=OTHER_HASH)

    assert admission.status is GateStatus.DARK
    assert admission.ok is False
    assert admission.refusal_reason is SCEDCollectionRefusalReason.MISSING_FREEZE

    with pytest.raises(SCEDCollectionRefusal) as exc:
        require_collection_admission(None, ruler_hash_commit=OTHER_HASH)
    assert exc.value.admission.refusal_reason is SCEDCollectionRefusalReason.MISSING_FREEZE


def test_boolean_freeze_flag_is_never_freeze() -> None:
    admission = verify_collection_admission(
        {"frozen": True, "ruler_hash": OTHER_HASH},
        ruler_hash_commit=OTHER_HASH,
    )

    assert admission.status is GateStatus.DARK
    assert admission.refusal_reason is SCEDCollectionRefusalReason.MISSING_RULER


def test_collection_refused_when_commit_hash_missing() -> None:
    freeze = _freeze()

    admission = verify_collection_admission(freeze, ruler_hash_commit=None)

    assert admission.status is GateStatus.DARK
    assert admission.refusal_reason is SCEDCollectionRefusalReason.M2_FREEZE_REFUSED
    assert admission.m2_refusal_reason is M2FreezeRefusalReason.MISSING_RULER_HASH_COMMIT


def test_collection_refused_when_commit_hash_mismatches_frozen_ruler() -> None:
    freeze = _freeze()

    admission = verify_collection_admission(freeze, ruler_hash_commit=OTHER_HASH)

    assert admission.status is GateStatus.DARK
    assert admission.refusal_reason is SCEDCollectionRefusalReason.M2_FREEZE_REFUSED
    assert admission.m2_refusal_reason is M2FreezeRefusalReason.RULER_HASH_MISMATCH


def test_prose_drift_refused_when_artifact_freezes_a_different_value() -> None:
    """A fully self-consistent M2 artifact that does not hash THIS ruler content
    must not admit collection -- the freeze is the ruler's canonical hash, not
    whatever prose the artifact carries."""

    ruler = _ruler()
    drifted_artifact = M2FreezeArtifact(
        artifact_id="m2-freeze:drifted",
        budget_envelope=_budget(),
        ladder=MonDLCLadder(
            ruler_hash=OTHER_HASH,
            min_corroboration_count=2,
            freshness_ttl_seconds=3600,
            positive_threshold=0.0,
            negative_threshold=-1.0,
        ),
        ruler_hash=OTHER_HASH,
        signer="operator:hapax",
        signed_at=NOW,
        signature_ref="signature:drifted",
    )
    freeze = SCEDRulerFreeze(ruler=ruler, m2_artifact=drifted_artifact)

    admission = verify_collection_admission(freeze, ruler_hash_commit=OTHER_HASH)

    assert admission.status is GateStatus.DARK
    assert admission.refusal_reason is SCEDCollectionRefusalReason.M2_RULER_HASH_MISMATCH


def test_tampered_ladder_thresholds_refused() -> None:
    """The frozen ladder thresholds must equal the ruler thresholds the hash
    commits, so a swapped-in relaxed ladder cannot ride a valid ruler hash."""

    ruler = _ruler()
    tampered_artifact = M2FreezeArtifact(
        artifact_id="m2-freeze:tampered-ladder",
        budget_envelope=_budget(),
        ladder=MonDLCLadder(
            ruler_hash=ruler.canonical_hash(),
            min_corroboration_count=1,
            freshness_ttl_seconds=3600,
            positive_threshold=0.0,
            negative_threshold=-1.0,
        ),
        ruler_hash=ruler.canonical_hash(),
        signer="operator:hapax",
        signed_at=NOW,
        signature_ref="signature:tampered-ladder",
    )
    freeze = SCEDRulerFreeze(ruler=ruler, m2_artifact=tampered_artifact)

    admission = verify_collection_admission(freeze, ruler_hash_commit=ruler.canonical_hash())

    assert admission.status is GateStatus.DARK
    assert admission.refusal_reason is SCEDCollectionRefusalReason.M2_LADDER_MISMATCH


def test_underlying_m2_artifact_defects_are_surfaced() -> None:
    ruler = _ruler()
    freeze_map = _freeze(ruler).to_dict()
    del freeze_map["m2_artifact"]["signer"]

    admission = verify_collection_admission(freeze_map, ruler_hash_commit=ruler.canonical_hash())

    assert admission.status is GateStatus.DARK
    assert admission.refusal_reason is SCEDCollectionRefusalReason.M2_FREEZE_REFUSED
    assert admission.m2_refusal_reason is M2FreezeRefusalReason.MISSING_SIGNER


# --- durability of the freeze witness -----------------------------------------


def test_freeze_roundtrips_through_mapping_and_still_admits() -> None:
    ruler = _ruler()
    freeze = _freeze(ruler)

    restored = SCEDRulerFreeze.from_mapping(freeze.to_dict())

    assert restored.ruler.canonical_hash() == ruler.canonical_hash()
    admission = verify_collection_admission(restored, ruler_hash_commit=ruler.canonical_hash())
    assert admission.status is GateStatus.LIT


@pytest.mark.parametrize(
    ("component", "reason"),
    (
        ("held_out_refusal_set", SCEDCollectionRefusalReason.MISSING_HELD_OUT_REFUSAL_SET),
        (
            "policy_category_threshold",
            SCEDCollectionRefusalReason.MISSING_POLICY_CATEGORY_THRESHOLD,
        ),
        ("novelty_criterion", SCEDCollectionRefusalReason.MISSING_NOVELTY_CRITERION),
    ),
)
def test_missing_ruler_component_refuses_with_specific_reason(
    component: str, reason: SCEDCollectionRefusalReason
) -> None:
    freeze_map = _freeze().to_dict()
    del freeze_map["ruler"][component]

    admission = verify_collection_admission(freeze_map, ruler_hash_commit=_ruler().canonical_hash())

    assert admission.status is GateStatus.DARK
    assert admission.refusal_reason is reason


def test_admission_truthiness_is_undefined() -> None:
    admission = verify_collection_admission(_freeze(), ruler_hash_commit=_ruler().canonical_hash())

    with pytest.raises(TypeError, match="truthiness is undefined"):
        bool(admission)


def test_require_returns_admission_with_ruler_on_success() -> None:
    ruler = _ruler()
    admission = require_collection_admission(
        _freeze(ruler), ruler_hash_commit=ruler.canonical_hash()
    )

    assert admission.status is GateStatus.LIT
    assert admission.ruler is not None
    assert admission.ruler.ruler_id == "sced-ruler:universal-jailbreak-v0"
