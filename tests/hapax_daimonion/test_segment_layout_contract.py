from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agents.hapax_daimonion.segment_layout_contract import (
    DOCTRINE_NAME,
    LAYOUT_RESPONSIBILITY_VERSION,
    PARENT_PREPARED_ARTIFACT_AUTHORITY,
    PREPARED_ARTIFACT_AUTHORITY,
    RUNTIME_LAYOUT_AUTHORITY,
    ActionIntentKind,
    ExpectedVisibleEffect,
    HostingContext,
    HostingMode,
    LayoutDecisionContract,
    LayoutPosture,
    LayoutReceiptStatus,
    PreparedSegmentLayoutContract,
    PublicPrivateMode,
    RuntimeLayoutDecision,
    RuntimeLayoutReceipt,
    RuntimeReadbackKind,
    RuntimeReadbackRef,
    SegmentActionIntent,
    beat_layout_intents_from_action_intents,
    current_beat_layout_proposals,
    prepared_artifact_layout_metadata,
    project_parent_prepared_artifact_layout_contract,
    validate_prepared_artifact_layout_metadata,
    validate_prepared_segment_artifact,
    validate_runtime_layout_decision,
    validate_runtime_layout_receipt,
)

HASH_BEFORE = "sha256:" + "0" * 64
HASH_AFTER = "sha256:" + "1" * 64


def test_responsible_contract_metadata_is_proposal_only() -> None:
    contract = _responsible_contract()

    metadata = prepared_artifact_layout_metadata(contract)
    parsed = validate_prepared_artifact_layout_metadata(metadata)

    assert parsed == contract
    assert metadata["layout_responsibility_version"] == LAYOUT_RESPONSIBILITY_VERSION
    assert metadata["doctrine"] == DOCTRINE_NAME
    assert metadata["authority"] == PREPARED_ARTIFACT_AUTHORITY
    assert metadata["parent_artifact_authority"] == "prior_only"
    assert metadata["layout_decision_contract"]["receipt_required"] is True
    assert metadata["layout_decision_contract"]["may_command_layout"] is False
    assert metadata["beat_layout_intents"][0]["proposed_postures"] == ["asset_front"]
    assert metadata["beat_layout_intents"][0]["needs"] == ["evidence_visible"]
    assert "canonical_broadcast_runtime" not in json.dumps(metadata)
    assert "layout_name" not in json.dumps(metadata)


def test_prepared_metadata_rejects_runtime_policy_overrides() -> None:
    metadata = prepared_artifact_layout_metadata(_responsible_contract())
    metadata["layout_decision_contract"]["ttl_s"] = 1

    with pytest.raises(ValueError, match="code-owned runtime policy"):
        validate_prepared_artifact_layout_metadata(metadata)

    metadata = prepared_artifact_layout_metadata(_responsible_contract())
    metadata["runtime_layout_validation"]["readback_kinds_required"] = []

    with pytest.raises(ValueError, match="code-owned runtime policy"):
        validate_prepared_artifact_layout_metadata(metadata)


def test_parent_emitted_field_names_project_to_blue_contract_without_mutating_parent() -> None:
    parent = _parent_artifact(
        programme_id="prog-1",
        parent_show_id="show-1",
        parent_condition_id="condition-1",
        hosting_context="hapax_responsible_live",
        authority=PARENT_PREPARED_ARTIFACT_AUTHORITY,
        beat_layout_intents=[
            {
                "beat_id": "beat-1",
                "action_intent_kinds": ["show_evidence"],
                "needs": ["evidence_visible"],
                "proposed_postures": ["asset_front"],
                "expected_effects": ["evidence_on_screen"],
                "evidence_refs": ["artifact:source-card"],
                "source_affordances": ["asset:source-card"],
            }
        ],
        layout_decision_contract={
            "may_command_layout": False,
            "bounded_vocabulary": ["asset_front"],
            "min_dwell_s": 8,
            "ttl_s": 30,
            "conflict_order": ["safety", "action_visibility", "readability"],
            "receipt_required": True,
        },
        runtime_layout_validation={
            "receipt_required": True,
            "layout_state_hash_required": True,
            "layout_state_signature_required": True,
            "ward_visibility_required": True,
            "readback_kinds_required": ["wcs", "layout_state", "ward_visibility"],
        },
    )

    parsed = project_parent_prepared_artifact_layout_contract(
        parent,
        artifact_sha256="2" * 64,
        parent_programme_id="prog-1",
        parent_show_id="show-1",
        parent_condition_id="condition-1",
    )

    assert parsed.hosting_context.mode is HostingMode.RESPONSIBLE_HOSTING
    assert parsed.hosting_context.public_private_mode is PublicPrivateMode.PUBLIC
    assert parsed.artifact_authority == PREPARED_ARTIFACT_AUTHORITY
    assert parsed.parent_artifact_authority == PARENT_PREPARED_ARTIFACT_AUTHORITY
    assert parsed.prepared_artifact_ref == f"prepared_artifact:{'2' * 64}"
    assert parsed.beat_layout_intents[0].needs[0].value == "evidence_visible"
    assert parsed.beat_layout_intents[0].evidence_refs[0] == f"prepared_artifact:{'2' * 64}"
    assert parsed.beat_layout_intents[0].evidence_refs[1] == "artifact:source-card"
    assert parsed.layout_decision_contract.may_command_layout is False
    assert parent["authority"] == "prior_only"


def test_parent_only_spoken_artifact_is_rejected_for_responsible_hosting() -> None:
    parent = _parent_artifact(
        beat_layout_intents=[
            {
                "beat_id": "hook",
                "beat_index": 0,
                "needs": ["host_presence", "spoken_argument"],
                "evidence_refs": ["vault:spoken-note"],
            }
        ],
    )

    with pytest.raises(ValueError, match="requires beat_layout_intents"):
        project_parent_prepared_artifact_layout_contract(
            parent,
            artifact_sha256="3" * 64,
        )


def test_parent_spoken_needs_are_dropped_when_visual_need_remains() -> None:
    parent = _parent_artifact(
        beat_layout_intents=[
            {
                "beat_id": "hook",
                "beat_index": 0,
                "needs": ["host_presence", "evidence_visible", "spoken_argument"],
                "evidence_refs": ["vault:source-note"],
                "source_affordances": ["asset:source-card"],
            }
        ],
    )

    parsed = project_parent_prepared_artifact_layout_contract(
        parent,
        artifact_sha256="3" * 64,
    )

    assert [need.value for need in parsed.beat_layout_intents[0].needs] == ["evidence_visible"]


def test_parent_camera_subject_need_is_rejected_for_responsible_hosting() -> None:
    parent = _parent_artifact(
        beat_layout_intents=[
            {
                "beat_id": "hook",
                "beat_index": 0,
                "needs": ["camera_subject"],
                "evidence_refs": ["vault:source-note"],
                "source_affordances": ["asset:source-card"],
            }
        ],
    )

    with pytest.raises(ValueError, match="camera_subject"):
        project_parent_prepared_artifact_layout_contract(
            parent,
            artifact_sha256="3" * 64,
        )


def test_parent_tier_chat_comparison_needs_project_with_artifact_evidence() -> None:
    parent = _parent_artifact(
        beat_layout_intents=[
            {
                "beat_id": "rank",
                "beat_index": 4,
                "needs": ["tier_visual", "chat_prompt", "comparison"],
                "evidence_refs": ["vault:tier-source"],
                "source_affordances": ["asset:tier-board", "chat:prompt"],
            }
        ]
    )

    parsed = project_parent_prepared_artifact_layout_contract(
        parent,
        artifact_sha256="4" * 64,
    )

    beat = parsed.beat_layout_intents[0]
    assert beat.parent_beat_index == 4
    assert {posture.value for posture in beat.proposed_postures} == {
        "ranked_visual",
        "chat_prompt",
        "comparison",
    }
    assert {need.value for need in beat.needs} == {
        "comparison_visible",
        "referent_visible",
    }
    assert {effect.value for effect in beat.expected_effects} == {
        "comparison_legible",
        "referent_available",
    }
    assert beat.evidence_refs == (f"prepared_artifact:{'4' * 64}", "vault:tier-source")


def test_parent_countdown_need_projects_to_ranked_list_contract() -> None:
    parent = _parent_artifact(
        beat_layout_intents=[
            {
                "beat_id": "countdown",
                "beat_index": 2,
                "needs": ["countdown_visual"],
                "evidence_refs": ["vault:countdown-source"],
                "source_affordances": ["countdown"],
            }
        ]
    )

    parsed = project_parent_prepared_artifact_layout_contract(
        parent,
        artifact_sha256="5" * 64,
    )

    beat = parsed.beat_layout_intents[0]
    assert [need.value for need in beat.needs] == ["ranked_list_visible"]
    assert [posture.value for posture in beat.proposed_postures] == ["countdown_visual"]
    assert [effect.value for effect in beat.expected_effects] == ["ranked_list_legible"]


@pytest.mark.parametrize(
    ("patch", "match"),
    [
        (
            {"beat_layout_intents": [{"beat_id": "hook", "needs": ["teleport_layout"]}]},
            "unsupported",
        ),
        (
            {
                "beat_layout_intents": [
                    {"beat_id": "hook", "needs": ["evidence_visible"], "layout": "asset_front"}
                ]
            },
            "cannot set",
        ),
        (
            {
                "beat_layout_intents": [
                    {"beat_id": "hook", "needs": ["evidence_visible"], "LayoutName": "garage-door"}
                ]
            },
            "cannot set",
        ),
        (
            {
                "beat_layout_intents": [
                    {"beat_id": "hook", "needs": ["evidence_visible"], "surfaceId": "main"}
                ]
            },
            "cannot set",
        ),
        (
            {
                "beat_layout_intents": [
                    {
                        "beat_id": "hook",
                        "needs": ["evidence_visible"],
                        "source_affordances": ["config/compositor-layouts/default.json"],
                    }
                ]
            },
            "cannot name concrete layout",
        ),
        ({"segment_cues": ["camera.hero tight"]}, "cannot set"),
    ],
)
def test_parent_projection_refuses_unsupported_static_and_command_fields(
    patch: dict[str, object],
    match: str,
) -> None:
    parent = _parent_artifact(**patch)

    with pytest.raises(ValueError, match=match):
        project_parent_prepared_artifact_layout_contract(parent, artifact_sha256="5" * 64)


def test_parent_projection_maps_explicit_fallback_without_responsible_success() -> None:
    parent = _parent_artifact(hosting_context="explicit_fallback", beat_layout_intents=[])

    parsed = project_parent_prepared_artifact_layout_contract(
        parent,
        artifact_sha256="6" * 64,
    )

    assert parsed.hosting_context.mode is HostingMode.EXPLICIT_FALLBACK
    assert parsed.hosting_context.public_private_mode is PublicPrivateMode.PUBLIC
    assert parsed.hosting_context.static_layout_success_allowed is True
    assert parsed.hosting_context.responsible_for_content_quality is False
    assert parsed.beat_layout_intents == ()


def test_parent_projection_maps_non_responsible_static_to_internal_rehearsal() -> None:
    parent = _parent_artifact(hosting_context="non_responsible_static", beat_layout_intents=[])

    parsed = project_parent_prepared_artifact_layout_contract(
        parent,
        artifact_sha256="7" * 64,
    )

    assert parsed.hosting_context.mode is HostingMode.NON_RESPONSIBLE_STATIC
    assert parsed.hosting_context.public_private_mode is PublicPrivateMode.INTERNAL_REHEARSAL
    assert parsed.hosting_context.static_layout_success_allowed is True


def test_parent_projection_rejects_missing_non_command_authority_gate() -> None:
    parent = _parent_artifact(layout_decision_contract={"receipt_required": True})

    with pytest.raises(ValueError, match="may_command_layout"):
        project_parent_prepared_artifact_layout_contract(parent, artifact_sha256="8" * 64)

    parent = _parent_artifact(authority=PREPARED_ARTIFACT_AUTHORITY)
    with pytest.raises(ValueError, match="prior_only"):
        project_parent_prepared_artifact_layout_contract(parent, artifact_sha256="8" * 64)


def test_parent_projection_ignores_parent_runtime_policy_fields() -> None:
    parent = _parent_artifact(
        layout_decision_contract={
            "may_command_layout": False,
            "bounded_vocabulary": ["spoken_only_fallback"],
            "min_dwell_s": 1,
            "ttl_s": 1,
            "receipt_required": True,
        },
        runtime_layout_validation={
            "receipt_required": False,
            "layout_state_hash_required": False,
            "readback_kinds_required": [],
        },
    )

    parsed = project_parent_prepared_artifact_layout_contract(
        parent,
        artifact_sha256="9" * 64,
    )

    assert LayoutPosture.SPOKEN_ONLY_FALLBACK not in (
        parsed.layout_decision_contract.bounded_vocabulary
    )
    assert parsed.layout_decision_contract.ttl_s == 30
    assert parsed.layout_decision_contract.min_dwell_s == 8
    assert parsed.runtime_layout_validation.receipt_required is True
    assert parsed.runtime_layout_validation.layout_state_hash_required is True
    assert parsed.runtime_layout_validation.readback_kinds_required


def test_parent_projection_requires_non_positional_beat_key() -> None:
    parent = _parent_artifact(
        beat_layout_intents=[
            {
                "needs": ["evidence_visible"],
                "evidence_refs": ["vault:source-note"],
                "source_affordances": ["asset:source-card"],
            }
        ]
    )

    with pytest.raises(ValueError, match="requires beat_id or beat_index"):
        project_parent_prepared_artifact_layout_contract(parent, artifact_sha256="8" * 64)


def test_parent_projection_rejects_parent_id_mismatch() -> None:
    parent = _parent_artifact(
        programme_id="prog-1",
        parent_show_id="show-1",
        parent_condition_id="condition-1",
    )

    with pytest.raises(ValueError, match="programme_id"):
        project_parent_prepared_artifact_layout_contract(
            parent,
            artifact_sha256="9" * 64,
            parent_programme_id="prog-2",
        )
    with pytest.raises(ValueError, match="parent_show_id"):
        project_parent_prepared_artifact_layout_contract(
            parent,
            artifact_sha256="9" * 64,
            parent_show_id="show-2",
        )
    with pytest.raises(ValueError, match="parent_condition_id"):
        project_parent_prepared_artifact_layout_contract(
            parent,
            artifact_sha256="9" * 64,
            parent_condition_id="condition-2",
        )


def test_current_beat_layout_proposals_select_by_beat_key_not_position() -> None:
    content = SimpleNamespace(
        segment_beats=["hook: open", "body: show source", "close: land"],
        beat_layout_intents=[
            {
                "beat_id": "close",
                "parent_beat_index": 2,
                "needs": ["referent_visible"],
            },
            {
                "beat_id": "body",
                "parent_beat_index": 1,
                "needs": ["evidence_visible"],
                "expected_effects": ["evidence_on_screen"],
            },
        ],
    )

    proposals = current_beat_layout_proposals(content, 1)

    assert len(proposals) == 1
    assert proposals[0]["beat_id"] == "body"
    assert proposals[0]["needs"] == ["evidence_visible"]
    assert current_beat_layout_proposals(content, 0) == ()


def test_current_beat_layout_proposals_explicit_index_prevents_adjacent_beat_id_bleed() -> None:
    content = SimpleNamespace(
        segment_beats=["open: cite", "compare: contrast"],
        beat_layout_intents=[
            {
                "beat_id": "beat-1",
                "parent_beat_index": 0,
                "needs": ["source_visible"],
            },
            {
                "beat_id": "beat-2",
                "parent_beat_index": 1,
                "needs": ["comparison_visible"],
            },
        ],
    )

    proposals = current_beat_layout_proposals(content, 1)

    assert len(proposals) == 1
    assert proposals[0]["beat_id"] == "beat-2"
    assert proposals[0]["needs"] == ["comparison_visible"]


def test_current_beat_layout_proposals_fail_closed_for_unkeyed_ambiguous_rows() -> None:
    content = SimpleNamespace(
        segment_beats=["hook: open"],
        beat_layout_intents=[
            {"needs": ["evidence_visible"]},
        ],
    )

    assert current_beat_layout_proposals(content, 0) == ()

    content = SimpleNamespace(
        segment_beats=["hook: open"],
        beat_layout_intents=[
            {"beat_id": "hook", "parent_beat_index": 1, "beat_index": 0},
        ],
    )
    assert current_beat_layout_proposals(content, 0) == ()


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


def test_responsible_contract_rejects_spoken_only_fallback_posture() -> None:
    payload = _responsible_contract().model_dump(mode="json")
    payload["beat_layout_intents"][0]["proposed_postures"] = ["spoken_only_fallback"]
    with pytest.raises(ValueError, match="spoken_only_fallback"):
        PreparedSegmentLayoutContract.model_validate(payload)

    payload = _responsible_contract().model_dump(mode="json")
    payload["layout_decision_contract"]["bounded_vocabulary"] = ["spoken_only_fallback"]
    with pytest.raises(ValueError, match="spoken_only_fallback"):
        PreparedSegmentLayoutContract.model_validate(payload)


def test_responsible_contract_rejects_camera_posture_and_affordance() -> None:
    payload = _responsible_contract().model_dump(mode="json")
    payload["beat_layout_intents"][0]["proposed_postures"] = ["camera_subject"]
    with pytest.raises(ValueError, match="camera_subject"):
        PreparedSegmentLayoutContract.model_validate(payload)

    payload = _responsible_contract().model_dump(mode="json")
    payload["layout_decision_contract"]["bounded_vocabulary"] = ["camera_subject"]
    with pytest.raises(ValueError, match="camera_subject"):
        PreparedSegmentLayoutContract.model_validate(payload)

    payload = _responsible_contract().model_dump(mode="json")
    payload["beat_layout_intents"][0]["source_affordances"] = ["camera:overhead"]
    with pytest.raises(ValueError, match="camera source affordances"):
        PreparedSegmentLayoutContract.model_validate(payload)


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


def test_responsible_hosting_rejects_non_responsible_static_posture_and_vocabulary() -> None:
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

    with pytest.raises(ValueError, match="cannot advertise non_responsible_static"):
        PreparedSegmentLayoutContract(
            segment_id="seg-1",
            hosting_context=_responsible_context(),
            beat_layout_intents=_responsible_contract().beat_layout_intents,
            layout_decision_contract=LayoutDecisionContract(
                bounded_vocabulary=(
                    LayoutPosture.ASSET_FRONT,
                    LayoutPosture.NON_RESPONSIBLE_STATIC,
                )
            ),
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("LayoutName",), "garage-door"),
        (("layout-name",), "default"),
        (("layout.name",), "default"),
        (("beat_layout_intents", 0, "surfaceId"), "main"),
        (("beat_layout_intents", 0, "targetLayout"), "balanced"),
        (("beat_layout_intents", 0, "shmPath"), "/dev/shm/hapax-compositor/x"),
        (("beat_layout_intents", 0, "zIndex"), 900),
        (("beat_layout_intents", 0, "segment_cues"), ["write layout-mode.txt"]),
        (("runtime", "command_string"), "compositor.surface.set_geometry"),
    ],
)
def test_prepared_metadata_rejects_canonicalized_direct_layout_command_keys(
    path: tuple[str | int, ...],
    value: object,
) -> None:
    metadata = prepared_artifact_layout_metadata(_responsible_contract())
    _assign_path(metadata, path, value)

    with pytest.raises(ValueError, match="prepared artifact layout metadata cannot"):
        validate_prepared_artifact_layout_metadata(metadata)


@pytest.mark.parametrize(
    "forbidden_value",
    [
        "garage-door",
        "garage_door",
        "consent-safe",
        "config/compositor-layouts/default.json",
        "layout:default",
        "default-live",
        "balanced-v2",
        "camera.hero tight",
        "Switch to the overhead camera now.",
        "Cut to the director view while I explain the tradeoff.",
        "Show the desk camera feed for proof.",
        "Take overhead while I explain the tradeoff.",
        "Bring overhead up while chat votes.",
        "Take desk cam while I explain the tradeoff.",
        "front.youtube https://example.invalid/video",
        "/dev/shm/hapax-compositor/layout-mode.txt",
    ],
)
def test_prepared_metadata_rejects_concrete_layouts_and_cue_strings(
    forbidden_value: str,
) -> None:
    metadata = prepared_artifact_layout_metadata(_responsible_contract())
    metadata["beat_layout_intents"][0]["source_affordances"] = [forbidden_value]

    with pytest.raises(ValueError, match="prepared artifact layout metadata cannot"):
        validate_prepared_artifact_layout_metadata(metadata)


@pytest.mark.parametrize(
    "beat_id",
    ["surface", "surface-level", "deep", "default-analysis", "static-overview", "balanced-take"],
)
def test_prepared_metadata_allows_content_bearing_beat_ids(beat_id: str) -> None:
    artifact = _parent_artifact(
        beat_layout_intents=[
            {
                "beat_id": beat_id,
                "beat_index": 0,
                "needs": ["evidence_visible"],
                "evidence_refs": ["vault:source-note"],
                "source_affordances": ["asset:source-card"],
            }
        ],
    )

    parsed = validate_prepared_segment_artifact(artifact, artifact_sha256="6" * 64)

    assert parsed.segment_id == "seg-1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("topic", "A balanced overview of static default patterns"),
        ("rationale", "Surface the default balanced approach"),
        ("hook_text", "The static surface of a balanced system"),
    ],
)
def test_prepared_artifact_allows_layout_words_in_content_fields(field: str, value: str) -> None:
    artifact = _parent_artifact(**{field: value})

    parsed = validate_prepared_segment_artifact(artifact, artifact_sha256="6" * 64)

    assert parsed.segment_id == "seg-1"


def test_prepared_segment_artifact_allows_neutral_camera_descriptions() -> None:
    artifact = _parent_artifact(
        prepared_script=[
            "The overhead camera feed has a color cast in the source record; "
            "that sentence is descriptive context, not a layout instruction. "
            "Take the long view on the tradeoff, move the argument into view, "
            "and push the comparison angle harder."
        ]
    )

    parsed = validate_prepared_segment_artifact(artifact, artifact_sha256="6" * 64)

    assert parsed.segment_id == "seg-1"


def test_prepared_segment_artifact_rejects_segment_cues_in_responsible_hosting() -> None:
    artifact = {
        **prepared_artifact_layout_metadata(_responsible_contract()),
        "programme_id": "seg-1",
        "prepared_script": ["prepared words"],
        "segment_cues": ["camera.hero tight"],
    }

    with pytest.raises(ValueError, match="segment_cues"):
        validate_prepared_segment_artifact(artifact)


def test_prepared_segment_artifact_rejects_unprojected_responsible_beat() -> None:
    artifact = _parent_artifact(
        beat_layout_intents=[
            {
                "beat_id": "hook",
                "beat_index": 0,
                "needs": ["evidence_visible"],
                "evidence_refs": ["vault:source-note"],
                "source_affordances": ["asset:source-card"],
            },
            {
                "beat_id": "spoken",
                "beat_index": 1,
                "needs": ["host_presence"],
                "evidence_refs": ["voice:host"],
                "source_affordances": ["host_camera_or_voice_presence"],
            },
        ],
        prepared_script=["visible words", "spoken-only words"],
    )

    with pytest.raises(ValueError, match="every prepared_script beat"):
        validate_prepared_segment_artifact(artifact, artifact_sha256="6" * 64)


def test_parent_id_mismatch_and_embedding_override_are_rejected() -> None:
    metadata = prepared_artifact_layout_metadata(
        _responsible_contract().model_copy(update={"programme_id": "prog-1"})
    )

    with pytest.raises(ValueError, match="programme_id"):
        validate_prepared_artifact_layout_metadata(metadata, parent_programme_id="prog-2")

    with pytest.raises(ValueError, match="embedding metadata cannot override"):
        validate_prepared_artifact_layout_metadata(
            metadata,
            embedding_metadata={"hosting_context": "non_responsible_static"},
        )


def test_runtime_decision_carries_authority_and_layoutstate_context() -> None:
    decision = _decision()

    validate_runtime_layout_decision(_responsible_contract(), decision)
    assert decision.authority == RUNTIME_LAYOUT_AUTHORITY


def test_responsible_runtime_decision_requires_layoutstate_hash_and_required_wards() -> None:
    decision = _decision().model_copy(update={"layout_state_hash_before": None})

    with pytest.raises(ValueError, match="layout_state_hash_before"):
        validate_runtime_layout_decision(_responsible_contract(), decision)

    decision = _decision().model_copy(update={"required_ward_ids": ()})
    with pytest.raises(ValueError, match="required_ward_ids"):
        validate_runtime_layout_decision(_responsible_contract(), decision)


def test_responsible_runtime_receipt_accepts_witnessed_non_static_layout() -> None:
    receipt = _receipt()

    validate_runtime_layout_receipt(_responsible_contract(), receipt, decision=_decision())


@pytest.mark.parametrize(
    "observed_layout",
    [
        "default",
        "balanced",
        "garage-door",
        "garage_door",
        "config/compositor-layouts/default.json",
        "layout:default",
        "default-live",
        "balanced-v2",
    ],
)
def test_responsible_runtime_receipt_rejects_static_default_success(
    observed_layout: str,
) -> None:
    receipt = _receipt().model_copy(update={"observed_layout": observed_layout})

    with pytest.raises(ValueError, match="static/default layout"):
        validate_runtime_layout_receipt(_responsible_contract(), receipt, decision=_decision())


def test_runtime_receipt_requires_matching_decision_identity_and_beat() -> None:
    with pytest.raises(ValueError, match="decision_id"):
        validate_runtime_layout_receipt(
            _responsible_contract(),
            _receipt().model_copy(update={"decision_id": "other"}),
            decision=_decision(),
        )

    with pytest.raises(ValueError, match="beat_id"):
        validate_runtime_layout_receipt(
            _responsible_contract(),
            _receipt().model_copy(update={"beat_id": "other-beat"}),
            decision=_decision(),
        )


def test_runtime_receipt_rejects_laundered_readbacks_and_unchanged_state() -> None:
    with pytest.raises(ValueError, match="missing required ward visibility"):
        validate_runtime_layout_receipt(
            _responsible_contract(),
            _receipt().model_copy(update={"ward_visibility": {"source-card": False}}),
            decision=_decision(),
        )

    with pytest.raises(ValidationError):
        RuntimeLayoutReceipt(
            receipt_id="receipt-1",
            decision_id="decision-1",
            segment_id="seg-1",
            beat_id="beat-1",
            posture=LayoutPosture.ASSET_FRONT,
            status=LayoutReceiptStatus.MATCHED,
            observed_layout="runtime-source-card-focus",
            layout_state_hash_after=HASH_AFTER,
            layout_state_signature="sig:layout-state",
            ward_visibility={"source-card": True},
            observed_effects=(ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,),
            wcs_readback_refs=("readback:composed-frame:source-card-visible",),
            issued_at="2026-05-06T00:20:01Z",
        )

    with pytest.raises(ValueError, match="did not change LayoutState hash"):
        validate_runtime_layout_receipt(
            _responsible_contract(),
            _receipt().model_copy(update={"layout_state_hash_after": HASH_BEFORE}),
            decision=_decision(),
        )

    with pytest.raises(ValueError, match="signed LayoutState hash"):
        validate_runtime_layout_receipt(
            _responsible_contract(),
            _receipt().model_copy(update={"layout_state_signature": None}),
            decision=_decision(),
        )

    with pytest.raises(ValueError, match="missing expected effect"):
        validate_runtime_layout_receipt(
            _responsible_contract(),
            _receipt().model_copy(update={"observed_effects": ()}),
            decision=_decision(),
        )


def test_runtime_receipt_requires_all_required_wards_visible() -> None:
    decision = _decision().model_copy(update={"required_ward_ids": ("source-card", "chart")})

    with pytest.raises(ValueError, match="chart"):
        validate_runtime_layout_receipt(
            _responsible_contract(),
            _receipt().model_copy(update={"ward_visibility": {"source-card": True}}),
            decision=decision,
        )


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
    with pytest.raises(ValueError, match="requires matching decision"):
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


def _parent_artifact(**overrides: object) -> dict[str, object]:
    artifact: dict[str, object] = {
        "programme_id": "seg-1",
        "segment_id": "seg-1",
        "parent_show_id": "show-1",
        "parent_condition_id": "condition-1",
        "hosting_context": "hapax_responsible_live",
        "authority": PARENT_PREPARED_ARTIFACT_AUTHORITY,
        "beat_layout_intents": [
            {
                "beat_id": "hook",
                "beat_index": 0,
                "needs": ["evidence_visible"],
                "evidence_refs": ["vault:source-note"],
                "source_affordances": ["asset:source-card"],
            }
        ],
        "layout_decision_contract": {
            "may_command_layout": False,
            "bounded_vocabulary": [
                "segment_primary",
                "ranked_visual",
                "countdown_visual",
                "depth_visual",
                "chat_prompt",
                "asset_front",
                "comparison",
                "spoken_only_fallback",
            ],
            "min_dwell_s": 8,
            "ttl_s": 30,
            "conflict_order": [
                "safety",
                "operator_override",
                "source_availability",
                "action_visibility",
                "readability",
                "continuity",
            ],
            "receipt_required": True,
        },
        "runtime_layout_validation": {
            "receipt_required": True,
            "layout_state_hash_required": True,
            "layout_state_signature_required": True,
            "ward_visibility_required": True,
            "readback_kinds_required": ["wcs", "layout_state", "ward_visibility"],
        },
        "prepared_script": ["prepared words"],
    }
    artifact.update(overrides)
    return artifact


def _responsible_contract() -> PreparedSegmentLayoutContract:
    beat_layout_intents = beat_layout_intents_from_action_intents(
        (
            SegmentActionIntent(
                beat_id="beat-1",
                intent_id="cite-source",
                kind=ActionIntentKind.SHOW_EVIDENCE,
                evidence_refs=("artifact:source-card",),
                source_affordances=("asset:source-card",),
            ),
        )
    )
    return PreparedSegmentLayoutContract(
        segment_id="seg-1",
        hosting_context=_responsible_context(),
        beat_layout_intents=beat_layout_intents,
    )


def _decision() -> RuntimeLayoutDecision:
    return RuntimeLayoutDecision(
        decision_id="decision-1",
        segment_id="seg-1",
        beat_id="beat-1",
        posture=LayoutPosture.ASSET_FRONT,
        reason="source card must be visible while Hapax cites it",
        expected_effects=(ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,),
        evidence_refs=("artifact:source-card",),
        required_ward_ids=("source-card",),
        layout_state_hash_before=HASH_BEFORE,
        layout_store_active_name="garage-door",
        layout_store_gauge_active="garage-door",
        wcs_readback_requirements=("wcs:composed-frame",),
        consent_constraints=("no_guest_present",),
        broadcast_constraints=("public_safe",),
        min_dwell_s=8,
        ttl_s=20,
        issued_at="2026-05-06T00:20:00Z",
    )


def _receipt() -> RuntimeLayoutReceipt:
    return RuntimeLayoutReceipt(
        receipt_id="receipt-1",
        decision_id="decision-1",
        segment_id="seg-1",
        beat_id="beat-1",
        posture=LayoutPosture.ASSET_FRONT,
        status=LayoutReceiptStatus.MATCHED,
        observed_layout="runtime-source-card-focus",
        layout_state_hash_after=HASH_AFTER,
        layout_state_signature="sig:layout-state",
        ward_visibility={"source-card": True},
        observed_effects=(ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,),
        wcs_readback_refs=(
            RuntimeReadbackRef(
                kind=RuntimeReadbackKind.WCS,
                ref_id="readback:composed-frame:source-card-visible",
                digest=HASH_AFTER,
            ),
            RuntimeReadbackRef(
                kind=RuntimeReadbackKind.LAYOUT_STATE,
                ref_id="layout-state:after",
                digest=HASH_AFTER,
            ),
            RuntimeReadbackRef(
                kind=RuntimeReadbackKind.WARD_VISIBILITY,
                ref_id="ward:source-card:visible",
            ),
        ),
        issued_at="2026-05-06T00:20:01Z",
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
        layout_decision_contract=LayoutDecisionContract(
            bounded_vocabulary=(LayoutPosture.NON_RESPONSIBLE_STATIC,),
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
