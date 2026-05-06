from __future__ import annotations

import json

import pytest

from agents.hapax_daimonion.segment_layout_contract import (
    DOCTRINE_NAME,
    LAYOUT_RESPONSIBILITY_VERSION,
    PREPARED_ARTIFACT_AUTHORITY,
    RUNTIME_LAYOUT_AUTHORITY,
    ActionIntentKind,
    ExpectedVisibleEffect,
    HostingContext,
    HostingMode,
    LayoutPosture,
    LayoutReceiptStatus,
    PreparedSegmentLayoutContract,
    PublicPrivateMode,
    RuntimeLayoutDecision,
    RuntimeLayoutReceipt,
    SegmentActionIntent,
    beat_layout_intents_from_action_intents,
    prepared_artifact_layout_metadata,
    validate_prepared_artifact_layout_metadata,
    validate_runtime_layout_decision,
    validate_runtime_layout_receipt,
)


def test_responsible_contract_metadata_is_proposal_only() -> None:
    contract = _responsible_contract()

    metadata = prepared_artifact_layout_metadata(contract)
    parsed = validate_prepared_artifact_layout_metadata(metadata)

    assert parsed == contract
    assert metadata["layout_responsibility_version"] == LAYOUT_RESPONSIBILITY_VERSION
    assert metadata["doctrine"] == DOCTRINE_NAME
    assert metadata["artifact_authority"] == PREPARED_ARTIFACT_AUTHORITY
    assert metadata["layout_decision_contract"]["receipt_required"] is True
    assert metadata["beat_layout_intents"][0]["proposed_postures"] == [
        "asset_front",
        "camera_subject",
    ]
    assert "canonical_broadcast_runtime" not in json.dumps(metadata)
    assert "layout_name" not in json.dumps(metadata)


def test_spoken_only_action_intent_does_not_create_responsible_layout_success() -> None:
    intents = beat_layout_intents_from_action_intents(
        (
            SegmentActionIntent(
                beat_id="beat-1",
                intent_id="narrate-only",
                kind=ActionIntentKind.NARRATE,
            ),
        )
    )

    assert intents == ()


def test_responsible_hosting_requires_explicit_visible_layout_intents() -> None:
    with pytest.raises(ValueError, match="requires beat_layout_intents"):
        PreparedSegmentLayoutContract(
            segment_id="seg-1",
            hosting_context=_responsible_context(),
        )


def test_responsible_hosting_rejects_static_success_allowance() -> None:
    with pytest.raises(ValueError, match="static_layout_success_allowed"):
        HostingContext(
            mode=HostingMode.RESPONSIBLE_HOSTING,
            public_private_mode=PublicPrivateMode.PUBLIC,
            hapax_controls_layout=True,
            responsible_for_content_quality=True,
            static_layout_success_allowed=True,
        )


def test_responsible_hosting_rejects_non_responsible_static_posture() -> None:
    beat = (
        _responsible_contract()
        .beat_layout_intents[0]
        .model_copy(update={"proposed_postures": (LayoutPosture.NON_RESPONSIBLE_STATIC,)})
    )

    with pytest.raises(ValueError, match="non_responsible_static posture"):
        PreparedSegmentLayoutContract(
            segment_id="seg-1",
            hosting_context=_responsible_context(),
            beat_layout_intents=(beat,),
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("layout_name",), "garage-door"),
        (("beat_layout_intents", 0, "surface_id"), "main"),
        (("beat_layout_intents", 0, "x"), 20),
        (("beat_layout_intents", 0, "z_order"), 900),
        (("beat_layout_intents", 0, "segment_cues"), ["write layout-mode.txt"]),
        (("runtime", "shm_path"), "/dev/shm/hapax-compositor/layout-mode.txt"),
        (("runtime", "command_string"), "compositor.surface.set_geometry"),
    ],
)
def test_prepared_metadata_rejects_direct_layout_commands(
    path: tuple[str | int, ...],
    value: object,
) -> None:
    metadata = prepared_artifact_layout_metadata(_responsible_contract())
    _assign_path(metadata, path, value)

    with pytest.raises(ValueError, match="prepared artifact layout metadata cannot"):
        validate_prepared_artifact_layout_metadata(metadata)


@pytest.mark.parametrize("forbidden_layout", ["garage-door", "garage_door", "consent-safe"])
def test_prepared_metadata_rejects_concrete_layout_names_even_as_values(
    forbidden_layout: str,
) -> None:
    metadata = prepared_artifact_layout_metadata(_responsible_contract())
    metadata["beat_layout_intents"][0]["source_affordances"] = [forbidden_layout]

    with pytest.raises(ValueError, match="cannot name concrete layout"):
        validate_prepared_artifact_layout_metadata(metadata)


def test_runtime_decision_carries_authority_and_layoutstate_context() -> None:
    contract = _responsible_contract()
    decision = RuntimeLayoutDecision(
        decision_id="decision-1",
        segment_id="seg-1",
        beat_id="beat-1",
        posture=LayoutPosture.ASSET_FRONT,
        reason="source card must be visible while Hapax cites it",
        expected_effects=(ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,),
        evidence_refs=("artifact:source-card",),
        layout_state_hash_before="sha256:before",
        layout_store_active_name="garage-door",
        layout_store_gauge_active="garage-door",
        wcs_readback_requirements=("wcs:composed-frame",),
        consent_constraints=("no_guest_present",),
        broadcast_constraints=("public_safe",),
        min_dwell_s=8,
        ttl_s=20,
        issued_at="2026-05-06T00:20:00Z",
    )

    validate_runtime_layout_decision(contract, decision)
    assert decision.authority == RUNTIME_LAYOUT_AUTHORITY


def test_responsible_runtime_decision_requires_layoutstate_hash() -> None:
    decision = RuntimeLayoutDecision(
        decision_id="decision-1",
        segment_id="seg-1",
        posture=LayoutPosture.ASSET_FRONT,
        reason="source card must be visible while Hapax cites it",
        expected_effects=(ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,),
        evidence_refs=("artifact:source-card",),
        min_dwell_s=8,
        ttl_s=20,
        issued_at="2026-05-06T00:20:00Z",
    )

    with pytest.raises(ValueError, match="layout_state_hash_before"):
        validate_runtime_layout_decision(_responsible_contract(), decision)


def test_responsible_runtime_receipt_accepts_witnessed_non_static_layout() -> None:
    receipt = RuntimeLayoutReceipt(
        receipt_id="receipt-1",
        decision_id="decision-1",
        segment_id="seg-1",
        beat_id="beat-1",
        posture=LayoutPosture.ASSET_FRONT,
        status=LayoutReceiptStatus.MATCHED,
        observed_layout="runtime-source-card-focus",
        layout_state_hash_after="sha256:after",
        ward_visibility={"source-card": True},
        observed_effects=(ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,),
        wcs_readback_refs=("readback:composed-frame:source-card-visible",),
        issued_at="2026-05-06T00:20:01Z",
    )

    validate_runtime_layout_receipt(_responsible_contract(), receipt)


@pytest.mark.parametrize("observed_layout", ["default", "balanced", "garage-door", "garage_door"])
def test_responsible_runtime_receipt_rejects_static_default_success(
    observed_layout: str,
) -> None:
    receipt = RuntimeLayoutReceipt(
        receipt_id="receipt-1",
        decision_id="decision-1",
        segment_id="seg-1",
        posture=LayoutPosture.ASSET_FRONT,
        status=LayoutReceiptStatus.MATCHED,
        observed_layout=observed_layout,
        layout_state_hash_after="sha256:after",
        ward_visibility={"source-card": True},
        observed_effects=(ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,),
        issued_at="2026-05-06T00:20:01Z",
    )

    with pytest.raises(ValueError, match="static/default layout"):
        validate_runtime_layout_receipt(_responsible_contract(), receipt)


def test_runtime_receipt_allows_consent_safe_as_explicit_safety_fallback() -> None:
    receipt = RuntimeLayoutReceipt(
        receipt_id="receipt-1",
        decision_id="decision-1",
        segment_id="seg-1",
        posture=LayoutPosture.SPOKEN_ONLY_FALLBACK,
        status=LayoutReceiptStatus.FALLBACK_ACTIVE,
        observed_layout="consent-safe",
        consent_constraints=("guest_present",),
        broadcast_constraints=("consent_safe_required",),
        issued_at="2026-05-06T00:20:01Z",
    )

    validate_runtime_layout_receipt(_explicit_fallback_contract(), receipt)
    with pytest.raises(ValueError, match="fallback-active"):
        validate_runtime_layout_receipt(_responsible_contract(), receipt)


def test_non_responsible_static_can_count_static_layout_only_when_explicit() -> None:
    receipt = RuntimeLayoutReceipt(
        receipt_id="receipt-1",
        decision_id="decision-1",
        segment_id="seg-1",
        posture=LayoutPosture.NON_RESPONSIBLE_STATIC,
        status=LayoutReceiptStatus.MATCHED,
        observed_layout="garage-door",
        issued_at="2026-05-06T00:20:01Z",
    )

    validate_runtime_layout_receipt(_non_responsible_static_contract(), receipt)


def _responsible_context() -> HostingContext:
    return HostingContext(
        mode=HostingMode.RESPONSIBLE_HOSTING,
        public_private_mode=PublicPrivateMode.PUBLIC,
        hapax_controls_layout=True,
        responsible_for_content_quality=True,
        static_layout_success_allowed=False,
    )


def _responsible_contract() -> PreparedSegmentLayoutContract:
    beat_layout_intents = beat_layout_intents_from_action_intents(
        (
            SegmentActionIntent(
                beat_id="beat-1",
                intent_id="cite-source",
                kind=ActionIntentKind.SHOW_EVIDENCE,
                evidence_refs=("artifact:source-card",),
                source_affordances=("asset:source-card", "camera:overhead"),
            ),
        )
    )
    return PreparedSegmentLayoutContract(
        segment_id="seg-1",
        hosting_context=_responsible_context(),
        beat_layout_intents=beat_layout_intents,
    )


def _explicit_fallback_contract() -> PreparedSegmentLayoutContract:
    return PreparedSegmentLayoutContract(
        segment_id="seg-1",
        hosting_context=HostingContext(
            mode=HostingMode.EXPLICIT_FALLBACK,
            public_private_mode=PublicPrivateMode.PUBLIC,
            hapax_controls_layout=True,
            responsible_for_content_quality=False,
            static_layout_success_allowed=True,
        ),
    )


def _non_responsible_static_contract() -> PreparedSegmentLayoutContract:
    return PreparedSegmentLayoutContract(
        segment_id="seg-1",
        hosting_context=HostingContext(
            mode=HostingMode.NON_RESPONSIBLE_STATIC,
            public_private_mode=PublicPrivateMode.INTERNAL_REHEARSAL,
            hapax_controls_layout=False,
            responsible_for_content_quality=False,
            static_layout_success_allowed=True,
        ),
    )


def _assign_path(root: dict[str, object], path: tuple[str | int, ...], value: object) -> None:
    cursor: object = root
    for part in path[:-1]:
        if isinstance(part, int):
            cursor = cursor[part]  # type: ignore[index]
        else:
            if not isinstance(cursor, dict):
                raise AssertionError(f"cannot assign through non-dict at {part}")
            cursor = cursor.setdefault(part, {})
    leaf = path[-1]
    if (
        isinstance(cursor, list)
        and isinstance(leaf, int)
        or isinstance(cursor, dict)
        and isinstance(leaf, str)
    ):
        cursor[leaf] = value
    else:
        raise AssertionError(f"cannot assign {leaf!r} on {type(cursor).__name__}")
