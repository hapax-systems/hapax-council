"""Responsible segment-layout control-loop contract tests.

cc-task: segment-layout-control-loop-chaos-guards
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.studio_compositor.segment_layout_control import (
    POSTURE_TO_LAYOUT,
    POSTURE_TO_REQUIRED_WARD,
    LayoutDecisionReason,
    LayoutDecisionStatus,
    LayoutNeedKind,
    LayoutPosture,
    RuntimeLayoutReadback,
    SegmentActionIntent,
    SegmentLayoutState,
    decide_layout_responsibility,
    decide_segment_layout,
)
from shared.compositor_model import Layout

NOW = 1_000.0
LAYOUTS_DIR = Path(__file__).resolve().parents[2] / "config" / "compositor-layouts"


def _intent(
    kind: LayoutNeedKind = LayoutNeedKind.RANKED_LIST,
    *,
    intent_id: str = "intent-ranked",
    priority: int = 50,
    requested_at: float = NOW - 1.0,
    evidence_refs: tuple[str, ...] = ("prior:ranked-list",),
    requested_layout: str | None = None,
    expected_effects: tuple[str, ...] = ("ward:ranked-list-panel", "action:visible-claim"),
) -> SegmentActionIntent:
    return SegmentActionIntent(
        intent_id=intent_id,
        kind=kind.value,
        requested_at=requested_at,
        priority=priority,
        evidence_refs=evidence_refs,
        programme_id="programme:segment-7",
        beat_index=3,
        target_ref="artifact:segment-card",
        authority_ref="provenance:command-r-prior",
        requested_layout=requested_layout,
        expected_effects=expected_effects,
        spoken_text_ref="spoken:beat-3",
    )


def _readback(
    *,
    active_layout: str = "segment-list",
    active_wards: tuple[str, ...] = ("ranked-list-panel",),
    ward_properties: dict[str, dict[str, object]] | None = None,
    observed_at: float = NOW,
    safety_state: str | None = None,
) -> RuntimeLayoutReadback:
    return RuntimeLayoutReadback(
        readback_ref="rendered:frame-42",
        observed_at=observed_at,
        active_layout=active_layout,
        active_wards=active_wards,
        ward_properties=ward_properties or {"ranked-list-panel": {"visible": True}},
        camera_available=True,
        safety_state=safety_state,
        chat_available=True,
        media_available=True,
        segment_playback_ref="segment-playback:beat-3",
        segment_action_intents_ref="segment-action-intents:sha256",
    )


def _available() -> set[str]:
    names: set[str] = set()
    for path in sorted(LAYOUTS_DIR.rglob("*.json")):
        if "examples" in path.parts:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            layout = Layout.model_validate_json(raw)
        except Exception:
            continue
        if layout.sources or layout.surfaces or layout.assignments:
            names.add(layout.name)
    return names


def test_responsible_acceptance_requires_rendered_readback_receipt_refs() -> None:
    intent = _intent()
    receipt = decide_layout_responsibility(
        [intent],
        available_layouts=_available(),
        readback=_readback(),
        state=SegmentLayoutState(current_layout="segment-list"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.ACCEPTED
    assert receipt.reason is LayoutDecisionReason.ACCEPTED
    assert receipt.selected_posture is LayoutPosture.RANKED_LIST
    assert receipt.selected_layout == "segment-list"
    assert "intent-ranked" in receipt.input_refs
    assert "prior:ranked-list" in receipt.input_refs
    assert "provenance:command-r-prior" in receipt.input_refs
    assert "rendered:frame-42" in receipt.readback_refs
    assert "segment-action-intents:sha256" in receipt.readback_refs
    assert "layout:segment-list" in receipt.satisfied_effects
    assert "ward:ranked-list-panel" in receipt.satisfied_effects
    assert "action:visible-claim" in receipt.unsatisfied_effects
    assert receipt.grants_playback_authority is False
    assert receipt.grants_audio_authority is False
    assert receipt.spoken_text_altered is False


@pytest.mark.parametrize("static_layout", ["default", "default-legacy", "garage-door"])
def test_static_default_readback_fails_responsible_hosting(static_layout: str) -> None:
    receipt = decide_layout_responsibility(
        [_intent()],
        available_layouts=_available(),
        readback=_readback(active_layout=static_layout, active_wards=("ranked-list-panel",)),
        state=SegmentLayoutState(current_layout=static_layout),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.HELD
    assert receipt.reason is LayoutDecisionReason.DEFAULT_STATIC_LAYOUT_IN_RESPONSIBLE_HOSTING
    assert receipt.selected_layout == "segment-list"
    assert receipt.previous_layout == static_layout
    assert receipt.layout_applied is False
    assert receipt.applied_layout_changes == ()
    assert receipt.grants_playback_authority is False
    assert "layout:segment-list" in receipt.unsatisfied_effects
    assert "default" in receipt.receipt_metadata["message"]


def test_programme_context_never_launders_default_as_responsible_success() -> None:
    receipt = decide_layout_responsibility(
        [
            _intent(
                LayoutNeedKind.PROGRAMME_CONTEXT,
                intent_id="intent-programme",
                expected_effects=("ward:programme-context",),
            )
        ],
        available_layouts={"default"},
        readback=_readback(active_layout="default", active_wards=("programme-context",)),
        state=SegmentLayoutState(current_layout="default"),
        now=NOW,
    )

    assert POSTURE_TO_LAYOUT[LayoutPosture.PROGRAMME_CONTEXT] == "segment-programme-context"
    assert receipt.status is LayoutDecisionStatus.REFUSED
    assert receipt.reason is LayoutDecisionReason.UNSUPPORTED_LAYOUT
    assert receipt.selected_layout is None
    assert receipt.layout_applied is False
    assert receipt.grants_playback_authority is False


def test_fallback_requires_explicit_receipt_and_is_not_success() -> None:
    fallback = _intent(
        LayoutNeedKind.NON_RESPONSIBLE_FALLBACK,
        intent_id="intent-explicit-fallback",
        priority=90,
        expected_effects=(),
    )
    active_need = _intent(LayoutNeedKind.CHAT_RESPONSE, intent_id="intent-chat", priority=40)
    receipt = decide_layout_responsibility(
        [active_need, fallback],
        available_layouts=_available(),
        readback=_readback(active_layout="default", active_wards=("chrome",)),
        state=SegmentLayoutState(current_layout="default"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.FALLBACK
    assert receipt.reason is LayoutDecisionReason.EXPLICIT_FALLBACK
    assert receipt.selected_posture is LayoutPosture.NON_RESPONSIBLE_FALLBACK
    assert receipt.selected_layout == "default"
    assert receipt.fallback_reason == "explicit_non_responsible"
    assert receipt.layout_applied is False
    assert receipt.denied_intents == ("intent-chat",)
    assert "intent-explicit-fallback" in receipt.input_refs


def test_expired_fallback_is_refused_not_used_as_default_success() -> None:
    expired_fallback = _intent(
        LayoutNeedKind.NON_RESPONSIBLE_FALLBACK,
        intent_id="intent-expired-fallback",
        requested_at=NOW - 100.0,
        expected_effects=(),
    )
    receipt = decide_layout_responsibility(
        [expired_fallback],
        available_layouts=_available(),
        readback=_readback(active_layout="default", active_wards=("chrome",)),
        state=SegmentLayoutState(current_layout="default"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.REFUSED
    assert receipt.reason is LayoutDecisionReason.EXPIRED_NEED
    assert receipt.selected_layout is None
    assert receipt.layout_applied is False


def test_arbitrary_layout_name_outside_bounded_vocabulary_is_rejected() -> None:
    receipt = decide_layout_responsibility(
        [_intent(requested_layout="role-tier-dashboard")],
        available_layouts=_available() | {"role-tier-dashboard"},
        readback=_readback(),
        state=SegmentLayoutState(current_layout="segment-list"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.REFUSED
    assert receipt.reason is LayoutDecisionReason.ARBITRARY_LAYOUT_REJECTED
    assert receipt.selected_layout is None
    assert receipt.layout_applied is False
    rejection = receipt.refusal_metadata["rejections"][0]
    assert rejection["requested_layout"] == "role-tier-dashboard"


def test_rendered_readback_mismatch_holds_instead_of_claiming_success() -> None:
    receipt = decide_layout_responsibility(
        [_intent(LayoutNeedKind.SOURCE_COMPARISON, expected_effects=("ward:compare-panel",))],
        available_layouts=_available(),
        readback=_readback(active_layout="segment-list", active_wards=("ranked-list-panel",)),
        state=SegmentLayoutState(current_layout="segment-list"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.HELD
    assert receipt.reason is LayoutDecisionReason.RENDERED_READBACK_MISMATCH
    assert receipt.selected_layout == "segment-compare"
    assert "layout:segment-compare" in receipt.unsatisfied_effects
    assert "readback:rendered_layout" in receipt.unsatisfied_effects
    assert receipt.layout_applied is False
    assert receipt.applied_layout_changes == ()


def test_matching_layout_without_required_ward_is_held() -> None:
    receipt = decide_layout_responsibility(
        [_intent()],
        available_layouts=_available(),
        readback=_readback(active_layout="segment-list", active_wards=()),
        state=SegmentLayoutState(current_layout="segment-list"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.HELD
    assert receipt.reason is LayoutDecisionReason.RENDERED_READBACK_MISMATCH
    assert "ward:ranked-list-panel" in receipt.unsatisfied_effects
    assert "readback:active_wards" in receipt.unsatisfied_effects


@pytest.mark.parametrize(
    "ward_properties",
    [
        {"ranked-list-panel": {}},
        {"ranked-list-panel": {"visible": False}},
        {"ranked-list-panel": {"visible": True, "alpha": 0.0}},
    ],
)
def test_matching_layout_with_invisible_required_ward_is_held(
    ward_properties: dict[str, dict[str, object]],
) -> None:
    receipt = decide_layout_responsibility(
        [_intent()],
        available_layouts=_available(),
        readback=_readback(
            active_layout="segment-list",
            active_wards=("ranked-list-panel",),
            ward_properties=ward_properties,
        ),
        state=SegmentLayoutState(current_layout="segment-list"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.HELD
    assert receipt.reason is LayoutDecisionReason.RENDERED_READBACK_MISMATCH
    assert "ward:ranked-list-panel" in receipt.unsatisfied_effects


def test_hysteresis_prevents_tier_chat_tier_thrash() -> None:
    state = SegmentLayoutState(
        current_layout="segment-tier",
        current_posture=LayoutPosture.TIER_STATUS,
        active_need_id="intent-tier",
        active_priority=20,
        switched_at=NOW - 2.0,
    )
    receipt = decide_layout_responsibility(
        [
            _intent(
                LayoutNeedKind.CHAT_RESPONSE,
                intent_id="intent-chat",
                priority=100,
                expected_effects=("ward:chat-panel",),
            )
        ],
        available_layouts=_available(),
        readback=_readback(active_layout="segment-tier", active_wards=("tier-panel",)),
        state=state,
        now=NOW,
        hysteresis_s=12.0,
    )

    assert receipt.status is LayoutDecisionStatus.HELD
    assert receipt.reason is LayoutDecisionReason.HYSTERESIS_HOLD
    assert receipt.selected_posture is LayoutPosture.TIER_STATUS
    assert receipt.selected_layout == "segment-tier"
    assert "candidate_posture:chat_response" in receipt.unsatisfied_effects
    assert receipt.layout_applied is False


def test_consent_safe_bypasses_dwell_and_records_safety_fallback() -> None:
    state = SegmentLayoutState(
        current_layout="segment-tier",
        current_posture=LayoutPosture.TIER_STATUS,
        active_need_id="intent-tier",
        active_priority=100,
        switched_at=NOW - 1.0,
    )
    receipt = decide_layout_responsibility(
        [_intent(LayoutNeedKind.CHAT_RESPONSE, intent_id="intent-chat", priority=100)],
        available_layouts=_available(),
        readback=_readback(
            active_layout="segment-tier",
            active_wards=("tier-panel",),
            safety_state="consent_safe_active",
        ),
        state=state,
        now=NOW,
        hysteresis_s=12.0,
    )

    assert receipt.status is LayoutDecisionStatus.FALLBACK
    assert receipt.reason is LayoutDecisionReason.SAFETY_FALLBACK
    assert receipt.selected_posture is LayoutPosture.SAFETY_FALLBACK
    assert receipt.selected_layout == "consent-safe"
    assert receipt.fallback_reason == "safety"
    assert receipt.safety_arbitration["bypasses_hysteresis"] is True
    assert receipt.denied_intents == ("intent-chat",)
    assert receipt.layout_applied is False


def test_missing_consent_safe_layout_fails_closed() -> None:
    receipt = decide_layout_responsibility(
        [_intent(LayoutNeedKind.CHAT_RESPONSE, intent_id="intent-chat", priority=100)],
        available_layouts=_available() - {"consent-safe"},
        readback=_readback(
            active_layout="segment-tier",
            active_wards=("tier-panel",),
            safety_state="consent_safe_active",
        ),
        state=SegmentLayoutState(current_layout="segment-tier"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.HELD
    assert receipt.reason is LayoutDecisionReason.SAFETY_FALLBACK_UNAVAILABLE
    assert receipt.selected_layout == "consent-safe"
    assert receipt.applied_layout_changes == ()
    assert receipt.fallback_reason == "safety_unavailable"
    assert receipt.refusal_metadata["missing_layout"] == "consent-safe"


def test_missing_evidence_refuses_and_never_grants_public_authority() -> None:
    receipt = decide_layout_responsibility(
        [_intent(evidence_refs=())],
        available_layouts=_available(),
        readback=_readback(),
        state=SegmentLayoutState(current_layout="segment-list"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.REFUSED
    assert receipt.reason is LayoutDecisionReason.MISSING_EVIDENCE
    assert receipt.grants_playback_authority is False
    assert receipt.grants_audio_authority is False
    assert receipt.spoken_text_altered is False


def test_stale_readback_refuses_before_layout_success() -> None:
    receipt = decide_layout_responsibility(
        [_intent()],
        available_layouts=_available(),
        readback=_readback(observed_at=NOW - 30.0),
        state=SegmentLayoutState(current_layout="segment-list"),
        now=NOW,
        readback_ttl_s=5.0,
    )

    assert receipt.status is LayoutDecisionStatus.REFUSED
    assert receipt.reason is LayoutDecisionReason.STALE_READBACK
    assert receipt.selected_layout is None
    assert "readback:fresh" in receipt.unsatisfied_effects


def test_legacy_wrapper_cannot_launder_advisory_state_as_readback() -> None:
    receipt = decide_segment_layout(
        [_intent()],
        available_layouts=_available(),
        state=SegmentLayoutState(current_layout="segment-list"),
        now=NOW,
    )

    assert receipt.status is LayoutDecisionStatus.REFUSED
    assert receipt.reason is LayoutDecisionReason.RENDERED_READBACK_REQUIRED
    assert "readback:rendered_layout_state" in receipt.unsatisfied_effects
    assert receipt.readback_refs == ()


def test_responsible_posture_layouts_exist_in_real_config_corpus() -> None:
    available = _available()
    for posture, layout_name in POSTURE_TO_LAYOUT.items():
        if posture is LayoutPosture.NON_RESPONSIBLE_FALLBACK:
            continue
        assert layout_name in available
        required_ward = POSTURE_TO_REQUIRED_WARD.get(posture)
        if required_ward is not None:
            layout_path = LAYOUTS_DIR / f"{layout_name}.json"
            layout = Layout.model_validate_json(layout_path.read_text(encoding="utf-8"))
            assert required_ward in {source.id for source in layout.sources}
