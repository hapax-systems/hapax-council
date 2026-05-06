"""Responsible segment layout control loop.

This module is the narrow contract layer between prepared segment/action
intents and compositor layout switching. It is deliberately pure: callers
provide runtime readbacks, available layouts, and prior state, then receive a
bounded posture decision plus a receipt. The receipt never grants playback,
audio, narration, or public action authority.

Cc-task: ``segment-layout-control-loop-chaos-guards``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

ResponsibleLayoutMode = Literal["responsible_hosting", "legacy_default"]


class LayoutNeedKind(StrEnum):
    """Bounded vocabulary of layout needs a segment beat may request."""

    RANKED_LIST = "show_ranked_list"
    SOURCE_COMPARISON = "show_source_comparison"
    ARTIFACT_DETAIL = "show_artifact_detail"
    AUDIENCE_POLL = "show_audience_poll"
    WORLD_SURFACE_RECEIPT = "show_world_surface_receipt"
    PROGRAMME_CONTEXT = "show_programme_context"
    TIER_STATUS = "show_tier_status"
    CHAT_RESPONSE = "show_chat_response"
    NON_RESPONSIBLE_FALLBACK = "use_non_responsible_fallback"


class LayoutPosture(StrEnum):
    """Bounded responsibility posture emitted by the controller."""

    RANKED_LIST = "ranked_list"
    SOURCE_COMPARISON = "source_comparison"
    ARTIFACT_DETAIL = "artifact_detail"
    AUDIENCE_POLL = "audience_poll"
    WORLD_SURFACE_RECEIPT = "world_surface_receipt"
    PROGRAMME_CONTEXT = "programme_context"
    TIER_STATUS = "tier_status"
    CHAT_RESPONSE = "chat_response"
    NON_RESPONSIBLE_FALLBACK = "non_responsible_fallback"
    SAFETY_FALLBACK = "safety_fallback"


class LayoutDecisionStatus(StrEnum):
    ACCEPTED = "accepted"
    HELD = "held"
    REFUSED = "refused"
    FALLBACK = "fallback"


class LayoutDecisionReason(StrEnum):
    ACCEPTED = "accepted"
    RESPONSIBLE_HOSTING_DISABLED = "responsible_hosting_disabled"
    NO_LAYOUT_NEEDS = "no_layout_needs"
    EXPIRED_NEED = "expired_need"
    UNKNOWN_NEED_KIND = "unknown_need_kind"
    MISSING_EVIDENCE = "missing_evidence"
    STALE_READBACK = "stale_readback"
    UNSUPPORTED_LAYOUT = "unsupported_layout"
    ARBITRARY_LAYOUT_REJECTED = "arbitrary_layout_rejected"
    CONFLICTING_NEEDS = "conflicting_needs"
    HYSTERESIS_HOLD = "hysteresis_hold"
    RENDERED_READBACK_MISMATCH = "rendered_readback_mismatch"
    RENDERED_READBACK_REQUIRED = "rendered_readback_required"
    DEFAULT_STATIC_LAYOUT_IN_RESPONSIBLE_HOSTING = "default_static_layout_in_responsible_hosting"
    EXPLICIT_FALLBACK = "explicit_fallback"
    SAFETY_FALLBACK = "safety_fallback"
    SAFETY_FALLBACK_UNAVAILABLE = "safety_fallback_unavailable"


NEED_TO_POSTURE: Mapping[LayoutNeedKind, LayoutPosture] = {
    LayoutNeedKind.RANKED_LIST: LayoutPosture.RANKED_LIST,
    LayoutNeedKind.SOURCE_COMPARISON: LayoutPosture.SOURCE_COMPARISON,
    LayoutNeedKind.ARTIFACT_DETAIL: LayoutPosture.ARTIFACT_DETAIL,
    LayoutNeedKind.AUDIENCE_POLL: LayoutPosture.AUDIENCE_POLL,
    LayoutNeedKind.WORLD_SURFACE_RECEIPT: LayoutPosture.WORLD_SURFACE_RECEIPT,
    LayoutNeedKind.PROGRAMME_CONTEXT: LayoutPosture.PROGRAMME_CONTEXT,
    LayoutNeedKind.TIER_STATUS: LayoutPosture.TIER_STATUS,
    LayoutNeedKind.CHAT_RESPONSE: LayoutPosture.CHAT_RESPONSE,
    LayoutNeedKind.NON_RESPONSIBLE_FALLBACK: LayoutPosture.NON_RESPONSIBLE_FALLBACK,
}

POSTURE_TO_LAYOUT: Mapping[LayoutPosture, str] = {
    LayoutPosture.RANKED_LIST: "segment-list",
    LayoutPosture.SOURCE_COMPARISON: "segment-compare",
    LayoutPosture.ARTIFACT_DETAIL: "segment-detail",
    LayoutPosture.AUDIENCE_POLL: "segment-poll",
    LayoutPosture.WORLD_SURFACE_RECEIPT: "segment-receipt",
    LayoutPosture.PROGRAMME_CONTEXT: "segment-programme-context",
    LayoutPosture.TIER_STATUS: "segment-tier",
    LayoutPosture.CHAT_RESPONSE: "segment-chat",
    LayoutPosture.NON_RESPONSIBLE_FALLBACK: "default",
    LayoutPosture.SAFETY_FALLBACK: "consent-safe",
}

POSTURE_TO_REQUIRED_WARD: Mapping[LayoutPosture, str] = {
    LayoutPosture.RANKED_LIST: "ranked-list-panel",
    LayoutPosture.SOURCE_COMPARISON: "compare-panel",
    LayoutPosture.ARTIFACT_DETAIL: "artifact-detail-panel",
    LayoutPosture.AUDIENCE_POLL: "audience-poll-panel",
    LayoutPosture.WORLD_SURFACE_RECEIPT: "world-receipt-panel",
    LayoutPosture.PROGRAMME_CONTEXT: "programme-context",
    LayoutPosture.TIER_STATUS: "tier-panel",
    LayoutPosture.CHAT_RESPONSE: "chat-panel",
}

BOUNDED_LAYOUTS: frozenset[str] = frozenset(POSTURE_TO_LAYOUT.values())
DEFAULT_STATIC_LAYOUTS: frozenset[str] = frozenset({"default", "default-legacy", "garage-door"})
SAFETY_STATES: frozenset[str] = frozenset(
    {"consent_safe_active", "consent-safe", "consent_safe", "safety_fallback"}
)

DEFAULT_HYSTERESIS_S: float = 12.0
DEFAULT_NEED_TTL_S: float = 20.0
DEFAULT_READBACK_TTL_S: float = 5.0
MAX_PRIORITY: int = 100
MIN_PRIORITY: int = 0


@dataclass(frozen=True)
class SegmentActionIntent:
    """One responsibility-bearing action/layout intent from a segment beat."""

    intent_id: str
    kind: str
    requested_at: float
    priority: int
    evidence_refs: tuple[str, ...]
    ttl_s: float = DEFAULT_NEED_TTL_S
    programme_id: str | None = None
    beat_index: int | None = None
    target_ref: str | None = None
    authority_ref: str | None = None
    requested_layout: str | None = None
    expected_effects: tuple[str, ...] = ()
    spoken_text_ref: str | None = None


SegmentLayoutNeed = SegmentActionIntent


@dataclass(frozen=True)
class RuntimeLayoutReadback:
    """Runtime readback surface consumed by the responsibility controller."""

    readback_ref: str
    observed_at: float
    active_layout: str | None
    active_wards: tuple[str, ...] = ()
    ward_properties: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    camera_available: bool | None = None
    safety_state: str | None = None
    chat_available: bool | None = None
    media_available: bool | None = None
    segment_playback_ref: str | None = None
    segment_action_intents_ref: str | None = None


@dataclass(frozen=True)
class SegmentLayoutState:
    """Prior layout-control state supplied by the caller."""

    current_layout: str | None = None
    current_posture: LayoutPosture | str | None = None
    active_need_id: str | None = None
    active_priority: int = 0
    switched_at: float | None = None


@dataclass(frozen=True)
class LayoutDecisionReceipt:
    """Responsibility receipt for a segment layout decision."""

    status: LayoutDecisionStatus
    reason: LayoutDecisionReason
    selected_posture: LayoutPosture | None
    selected_layout: str | None
    previous_layout: str | None
    need_id: str | None
    need_kind: str | None
    observed_at: float
    expires_at: float | None
    evidence_refs: tuple[str, ...]
    input_refs: tuple[str, ...]
    readback_refs: tuple[str, ...]
    satisfied_effects: tuple[str, ...]
    unsatisfied_effects: tuple[str, ...]
    denied_intents: tuple[str, ...] = ()
    applied_layout_changes: tuple[str, ...] = ()
    applied_ward_changes: tuple[str, ...] = ()
    applied_action_changes: tuple[str, ...] = ()
    safety_arbitration: Mapping[str, object] = field(default_factory=dict)
    fallback_reason: str | None = None
    spoken_text_altered: bool = False
    refusal_metadata: Mapping[str, object] = field(default_factory=dict)
    receipt_metadata: Mapping[str, object] = field(default_factory=dict)
    grants_playback_authority: Literal[False] = False
    grants_audio_authority: Literal[False] = False

    @property
    def layout_applied(self) -> bool:
        return self.status is LayoutDecisionStatus.ACCEPTED

    @property
    def visible_metadata(self) -> dict[str, object]:
        """Metadata safe for a status/debug overlay."""

        base: dict[str, object] = {
            "status": self.status.value,
            "reason": self.reason.value,
            "selected_posture": self.selected_posture.value if self.selected_posture else None,
            "selected_layout": self.selected_layout,
            "previous_layout": self.previous_layout,
            "need_id": self.need_id,
            "need_kind": self.need_kind,
            "evidence_refs": list(self.evidence_refs),
            "input_refs": list(self.input_refs),
            "readback_refs": list(self.readback_refs),
            "satisfied_effects": list(self.satisfied_effects),
            "unsatisfied_effects": list(self.unsatisfied_effects),
            "denied_intents": list(self.denied_intents),
            "applied_layout_changes": list(self.applied_layout_changes),
            "applied_ward_changes": list(self.applied_ward_changes),
            "applied_action_changes": list(self.applied_action_changes),
            "fallback_reason": self.fallback_reason,
            "spoken_text_altered": self.spoken_text_altered,
            "grants_playback_authority": False,
            "grants_audio_authority": False,
        }
        if self.safety_arbitration:
            base["safety_arbitration"] = dict(self.safety_arbitration)
        if self.refusal_metadata:
            base["refusal"] = dict(self.refusal_metadata)
        if self.receipt_metadata:
            base["receipt"] = dict(self.receipt_metadata)
        return base


@dataclass(frozen=True)
class _ValidIntent:
    intent: SegmentActionIntent
    kind: LayoutNeedKind
    posture: LayoutPosture
    layout: str


class LayoutResponsibilityController:
    """Pure controller for hosted-segment layout responsibility."""

    def __init__(
        self,
        *,
        available_layouts: Iterable[str],
        hysteresis_s: float = DEFAULT_HYSTERESIS_S,
        readback_ttl_s: float = DEFAULT_READBACK_TTL_S,
    ) -> None:
        self.available_layouts = frozenset(available_layouts)
        self.hysteresis_s = hysteresis_s
        self.readback_ttl_s = readback_ttl_s

    def decide(
        self,
        intents: Iterable[SegmentActionIntent],
        *,
        readback: RuntimeLayoutReadback,
        state: SegmentLayoutState,
        now: float,
        mode: ResponsibleLayoutMode = "responsible_hosting",
    ) -> LayoutDecisionReceipt:
        return decide_layout_responsibility(
            intents,
            available_layouts=self.available_layouts,
            readback=readback,
            state=state,
            now=now,
            mode=mode,
            hysteresis_s=self.hysteresis_s,
            readback_ttl_s=self.readback_ttl_s,
        )


def decide_layout_responsibility(
    intents: Iterable[SegmentActionIntent],
    *,
    available_layouts: Iterable[str],
    readback: RuntimeLayoutReadback,
    state: SegmentLayoutState,
    now: float,
    mode: ResponsibleLayoutMode = "responsible_hosting",
    hysteresis_s: float = DEFAULT_HYSTERESIS_S,
    readback_ttl_s: float = DEFAULT_READBACK_TTL_S,
) -> LayoutDecisionReceipt:
    """Choose a bounded posture or return a refusal/hold/fallback receipt."""

    intent_list = list(intents)
    readback_refs = _readback_refs(readback)
    input_refs = _input_refs(intent_list, readback)
    available = frozenset(available_layouts)

    if _safety_active(readback):
        return _safety_fallback_receipt(
            intents=intent_list,
            available_layouts=available,
            readback=readback,
            state=state,
            now=now,
            input_refs=input_refs,
            readback_refs=readback_refs,
        )

    if mode != "responsible_hosting":
        return _receipt(
            status=LayoutDecisionStatus.HELD,
            reason=LayoutDecisionReason.RESPONSIBLE_HOSTING_DISABLED,
            selected_posture=LayoutPosture.NON_RESPONSIBLE_FALLBACK,
            selected_layout=readback.active_layout or state.current_layout,
            previous_layout=state.current_layout,
            intent=None,
            now=now,
            evidence_refs=(),
            input_refs=input_refs,
            readback_refs=readback_refs,
            satisfied_effects=("non_responsible_context",),
            unsatisfied_effects=(),
            fallback_reason="legacy_default_mode",
            refusal_metadata={
                "mode": mode,
                "message": "responsible layout control disabled; legacy layout owner remains active",
            },
        )

    fallback_intent = _select_explicit_fallback(intent_list, now)
    if fallback_intent is not None:
        return _explicit_fallback_receipt(
            intent=fallback_intent,
            all_intents=intent_list,
            readback=readback,
            state=state,
            now=now,
            input_refs=input_refs,
            readback_refs=readback_refs,
        )

    if _stale_readback(readback, now=now, readback_ttl_s=readback_ttl_s):
        return _receipt(
            status=LayoutDecisionStatus.REFUSED,
            reason=LayoutDecisionReason.STALE_READBACK,
            selected_posture=None,
            selected_layout=None,
            previous_layout=state.current_layout,
            intent=intent_list[0] if intent_list else None,
            now=now,
            evidence_refs=_flatten_evidence(intent_list),
            input_refs=input_refs,
            readback_refs=readback_refs,
            satisfied_effects=(),
            unsatisfied_effects=("readback:fresh",),
            denied_intents=_intent_ids(intent_list),
            refusal_metadata={
                "readback_observed_at": readback.observed_at,
                "readback_ttl_s": readback_ttl_s,
                "message": "responsible hosting requires a fresh runtime readback",
            },
        )

    validation = _validate_intents(intent_list, now=now, available_layouts=available)

    if not intent_list:
        return _receipt(
            status=LayoutDecisionStatus.REFUSED,
            reason=LayoutDecisionReason.NO_LAYOUT_NEEDS,
            selected_posture=None,
            selected_layout=None,
            previous_layout=state.current_layout,
            intent=None,
            now=now,
            evidence_refs=(),
            input_refs=input_refs,
            readback_refs=readback_refs,
            satisfied_effects=(),
            unsatisfied_effects=("intent:layout_need",),
            refusal_metadata={"message": "responsible hosting requires an explicit layout need"},
        )

    if not validation.valid:
        first = intent_list[0]
        reason = _dominant_rejection_reason(validation.rejections)
        return _receipt(
            status=LayoutDecisionStatus.REFUSED,
            reason=reason,
            selected_posture=None,
            selected_layout=None,
            previous_layout=state.current_layout,
            intent=first,
            now=now,
            evidence_refs=first.evidence_refs,
            input_refs=input_refs,
            readback_refs=readback_refs,
            satisfied_effects=(),
            unsatisfied_effects=("layout:bounded_supported_posture",),
            denied_intents=_intent_ids(intent_list),
            refusal_metadata={
                "rejections": validation.rejections,
                "message": "no supported fresh layout need; default/static layout is not success",
            },
        )

    max_priority = max(_clamp_priority(item.intent.priority) for item in validation.valid)
    winners = [
        item for item in validation.valid if _clamp_priority(item.intent.priority) == max_priority
    ]
    winner_postures = {item.posture for item in winners}
    if len(winner_postures) > 1:
        first = winners[0].intent
        return _receipt(
            status=LayoutDecisionStatus.REFUSED,
            reason=LayoutDecisionReason.CONFLICTING_NEEDS,
            selected_posture=None,
            selected_layout=None,
            previous_layout=state.current_layout,
            intent=first,
            now=now,
            evidence_refs=_flatten_evidence(item.intent for item in winners),
            input_refs=input_refs,
            readback_refs=readback_refs,
            satisfied_effects=(),
            unsatisfied_effects=("intent:single_highest_priority_posture",),
            denied_intents=tuple(item.intent.intent_id for item in winners),
            refusal_metadata={
                "conflicts": [
                    {
                        "intent_id": item.intent.intent_id,
                        "kind": item.kind.value,
                        "posture": item.posture.value,
                        "layout": item.layout,
                        "priority": _clamp_priority(item.intent.priority),
                    }
                    for item in winners
                ],
                "message": "equal-priority segment intents requested incompatible postures",
            },
        )

    selected = max(winners, key=lambda item: (item.intent.requested_at, item.intent.intent_id))
    expected_effects = tuple(_expected_effects(selected.intent, selected.layout, selected.posture))
    satisfied_effects, unsatisfied_effects = _split_effects(expected_effects, readback)

    if _should_hold_for_hysteresis(
        state=state,
        selected_intent=selected.intent,
        selected_posture=selected.posture,
        now=now,
        hysteresis_s=hysteresis_s,
    ):
        return _receipt(
            status=LayoutDecisionStatus.HELD,
            reason=LayoutDecisionReason.HYSTERESIS_HOLD,
            selected_posture=_state_posture(state),
            selected_layout=readback.active_layout or state.current_layout,
            previous_layout=state.current_layout,
            intent=selected.intent,
            now=now,
            evidence_refs=selected.intent.evidence_refs,
            input_refs=input_refs,
            readback_refs=readback_refs,
            satisfied_effects=satisfied_effects,
            unsatisfied_effects=unsatisfied_effects
            + (f"candidate_posture:{selected.posture.value}",),
            denied_intents=(selected.intent.intent_id,),
            receipt_metadata={
                "candidate_posture": selected.posture.value,
                "candidate_layout": selected.layout,
                "active_need_id": state.active_need_id,
                "active_priority": state.active_priority,
                "hysteresis_s": hysteresis_s,
            },
        )

    critical_unsatisfied = _critical_unsatisfied_effects(unsatisfied_effects)
    if (
        readback.active_layout in DEFAULT_STATIC_LAYOUTS
        or readback.active_layout != selected.layout
        or not readback.active_wards
        or critical_unsatisfied
    ):
        reason = (
            LayoutDecisionReason.DEFAULT_STATIC_LAYOUT_IN_RESPONSIBLE_HOSTING
            if readback.active_layout in DEFAULT_STATIC_LAYOUTS
            else LayoutDecisionReason.RENDERED_READBACK_MISMATCH
        )
        unsatisfied = tuple(
            dict.fromkeys(
                (
                    *unsatisfied_effects,
                    *(
                        ()
                        if readback.active_layout == selected.layout
                        else ("readback:rendered_layout",)
                    ),
                    *(() if readback.active_wards else ("readback:active_wards",)),
                )
            )
        )
        return _receipt(
            status=LayoutDecisionStatus.HELD,
            reason=reason,
            selected_posture=selected.posture,
            selected_layout=selected.layout,
            previous_layout=readback.active_layout or state.current_layout,
            intent=selected.intent,
            now=now,
            evidence_refs=selected.intent.evidence_refs,
            input_refs=input_refs,
            readback_refs=readback_refs,
            satisfied_effects=satisfied_effects,
            unsatisfied_effects=unsatisfied,
            denied_intents=(selected.intent.intent_id,),
            receipt_metadata={
                "active_layout_readback": readback.active_layout,
                "required_layout_readback": selected.layout,
                "active_wards": list(readback.active_wards),
                "critical_unsatisfied_effects": list(critical_unsatisfied),
                "message": (
                    "default/static layout is not responsible-hosting success; "
                    "LayoutStore active layout alone is advisory and rendered readback "
                    "must satisfy posture"
                ),
            },
        )

    return _receipt(
        status=LayoutDecisionStatus.ACCEPTED,
        reason=LayoutDecisionReason.ACCEPTED,
        selected_posture=selected.posture,
        selected_layout=selected.layout,
        previous_layout=state.current_layout,
        intent=selected.intent,
        now=now,
        evidence_refs=selected.intent.evidence_refs,
        input_refs=input_refs,
        readback_refs=readback_refs,
        satisfied_effects=satisfied_effects,
        unsatisfied_effects=unsatisfied_effects,
        applied_layout_changes=(selected.layout,),
        receipt_metadata={
            "kind": selected.kind.value,
            "priority": _clamp_priority(selected.intent.priority),
            "programme_id": selected.intent.programme_id,
            "beat_index": selected.intent.beat_index,
            "target_ref": selected.intent.target_ref,
            "authority_ref": selected.intent.authority_ref,
            "active_layout_readback": readback.active_layout,
            "active_wards": list(readback.active_wards),
            "ward_properties": {
                ward_id: dict(values) for ward_id, values in readback.ward_properties.items()
            },
            "camera_available": readback.camera_available,
            "chat_available": readback.chat_available,
            "media_available": readback.media_available,
        },
    )


def decide_segment_layout(
    needs: Iterable[SegmentLayoutNeed],
    *,
    available_layouts: Iterable[str],
    state: SegmentLayoutState,
    now: float,
    mode: ResponsibleLayoutMode = "responsible_hosting",
    hysteresis_s: float = DEFAULT_HYSTERESIS_S,
) -> LayoutDecisionReceipt:
    """Compatibility wrapper for legacy callers.

    In responsible-hosting mode this wrapper is refusal-only: it has no
    rendered ``LayoutState``/ward readback and must not launder advisory
    state into success. Legacy/non-responsible callers can still use the
    explicit mode boundary.
    """

    if mode == "responsible_hosting":
        need_list = list(needs)
        return _receipt(
            status=LayoutDecisionStatus.REFUSED,
            reason=LayoutDecisionReason.RENDERED_READBACK_REQUIRED,
            selected_posture=None,
            selected_layout=None,
            previous_layout=state.current_layout,
            intent=need_list[0] if need_list else None,
            now=now,
            evidence_refs=_flatten_evidence(need_list),
            input_refs=tuple(
                ref for need in need_list for ref in (need.intent_id, *need.evidence_refs)
            ),
            readback_refs=(),
            satisfied_effects=(),
            unsatisfied_effects=("readback:rendered_layout_state", "readback:active_wards"),
            denied_intents=_intent_ids(need_list),
            refusal_metadata={
                "message": "responsible hosting requires rendered LayoutState/ward readback",
            },
        )

    readback = RuntimeLayoutReadback(
        readback_ref="legacy-state-readback",
        observed_at=now,
        active_layout=state.current_layout,
    )
    return decide_layout_responsibility(
        needs,
        available_layouts=available_layouts,
        readback=readback,
        state=state,
        now=now,
        mode=mode,
        hysteresis_s=hysteresis_s,
    )


@dataclass(frozen=True)
class _Validation:
    valid: tuple[_ValidIntent, ...]
    rejections: tuple[dict[str, object], ...]


def _validate_intents(
    intents: Iterable[SegmentActionIntent],
    *,
    now: float,
    available_layouts: Iterable[str],
) -> _Validation:
    available = frozenset(available_layouts)
    valid: list[_ValidIntent] = []
    rejections: list[dict[str, object]] = []
    for intent in intents:
        parsed_kind = _parse_kind(intent.kind)
        if parsed_kind is None:
            rejections.append(_rejection(intent, LayoutDecisionReason.UNKNOWN_NEED_KIND))
            continue
        if parsed_kind is LayoutNeedKind.NON_RESPONSIBLE_FALLBACK:
            if _is_expired(intent, now):
                rejections.append(_rejection(intent, LayoutDecisionReason.EXPIRED_NEED))
            elif not intent.evidence_refs:
                rejections.append(_rejection(intent, LayoutDecisionReason.MISSING_EVIDENCE))
            continue
        if _is_expired(intent, now):
            rejections.append(_rejection(intent, LayoutDecisionReason.EXPIRED_NEED))
            continue
        if not intent.evidence_refs:
            rejections.append(_rejection(intent, LayoutDecisionReason.MISSING_EVIDENCE))
            continue

        posture = NEED_TO_POSTURE[parsed_kind]
        layout_name = POSTURE_TO_LAYOUT[posture]
        if intent.requested_layout is not None:
            if intent.requested_layout not in BOUNDED_LAYOUTS:
                rejections.append(
                    _rejection(
                        intent,
                        LayoutDecisionReason.ARBITRARY_LAYOUT_REJECTED,
                        extra={
                            "requested_layout": intent.requested_layout,
                            "bounded_layouts": sorted(BOUNDED_LAYOUTS),
                        },
                    )
                )
                continue
            if intent.requested_layout != layout_name:
                rejections.append(
                    _rejection(
                        intent,
                        LayoutDecisionReason.ARBITRARY_LAYOUT_REJECTED,
                        extra={
                            "requested_layout": intent.requested_layout,
                            "expected_layout": layout_name,
                            "message": "layout names must be derived from bounded posture, not role rules",
                        },
                    )
                )
                continue
        if layout_name not in available:
            rejections.append(
                _rejection(
                    intent,
                    LayoutDecisionReason.UNSUPPORTED_LAYOUT,
                    extra={"layout": layout_name},
                )
            )
            continue
        valid.append(
            _ValidIntent(
                intent=intent,
                kind=parsed_kind,
                posture=posture,
                layout=layout_name,
            )
        )
    return _Validation(valid=tuple(valid), rejections=tuple(rejections))


def _parse_kind(kind: str) -> LayoutNeedKind | None:
    try:
        return LayoutNeedKind(kind)
    except ValueError:
        return None


def _is_expired(intent: SegmentActionIntent, now: float) -> bool:
    return now > intent.requested_at + max(0.0, intent.ttl_s)


def _clamp_priority(priority: int) -> int:
    return max(MIN_PRIORITY, min(MAX_PRIORITY, int(priority)))


def _safety_active(readback: RuntimeLayoutReadback) -> bool:
    if readback.safety_state is None:
        return False
    return readback.safety_state in SAFETY_STATES


def _stale_readback(
    readback: RuntimeLayoutReadback,
    *,
    now: float,
    readback_ttl_s: float,
) -> bool:
    return now > readback.observed_at + max(0.0, readback_ttl_s)


def _select_explicit_fallback(
    intents: Iterable[SegmentActionIntent],
    now: float,
) -> SegmentActionIntent | None:
    candidates: list[SegmentActionIntent] = []
    for intent in intents:
        if _parse_kind(intent.kind) is not LayoutNeedKind.NON_RESPONSIBLE_FALLBACK:
            continue
        if _is_expired(intent, now) or not intent.evidence_refs:
            continue
        candidates.append(intent)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (_clamp_priority(item.priority), item.requested_at))


def _state_posture(state: SegmentLayoutState) -> LayoutPosture | None:
    if state.current_posture is None:
        return None
    if isinstance(state.current_posture, LayoutPosture):
        return state.current_posture
    try:
        return LayoutPosture(state.current_posture)
    except ValueError:
        return None


def _should_hold_for_hysteresis(
    *,
    state: SegmentLayoutState,
    selected_intent: SegmentActionIntent,
    selected_posture: LayoutPosture,
    now: float,
    hysteresis_s: float,
) -> bool:
    current_posture = _state_posture(state)
    if current_posture is None or current_posture is selected_posture:
        return False
    if state.switched_at is None:
        return False
    return now - state.switched_at < hysteresis_s


def _readback_refs(readback: RuntimeLayoutReadback) -> tuple[str, ...]:
    refs = [
        readback.readback_ref,
        readback.segment_playback_ref,
        readback.segment_action_intents_ref,
    ]
    return tuple(ref for ref in refs if ref)


def _input_refs(
    intents: Iterable[SegmentActionIntent],
    readback: RuntimeLayoutReadback,
) -> tuple[str, ...]:
    refs: dict[str, None] = {}
    for intent in intents:
        refs.setdefault(intent.intent_id, None)
        for evidence_ref in intent.evidence_refs:
            refs.setdefault(evidence_ref, None)
        if intent.authority_ref:
            refs.setdefault(intent.authority_ref, None)
        if intent.spoken_text_ref:
            refs.setdefault(intent.spoken_text_ref, None)
    for ref in _readback_refs(readback):
        refs.setdefault(ref, None)
    return tuple(refs)


def _intent_ids(intents: Iterable[SegmentActionIntent]) -> tuple[str, ...]:
    return tuple(intent.intent_id for intent in intents)


def _expected_effects(
    intent: SegmentActionIntent,
    layout: str,
    posture: LayoutPosture,
) -> tuple[str, ...]:
    base = [f"posture:{posture.value}", f"layout:{layout}"]
    required_ward = POSTURE_TO_REQUIRED_WARD.get(posture)
    if required_ward:
        base.append(f"ward:{required_ward}")
    base.extend(intent.expected_effects)
    return tuple(dict.fromkeys(base))


def _split_effects(
    expected_effects: tuple[str, ...],
    readback: RuntimeLayoutReadback,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    satisfied: list[str] = []
    unsatisfied: list[str] = []
    active_wards = set(readback.active_wards)
    for effect in expected_effects:
        if effect.startswith("layout:"):
            layout = effect.split(":", 1)[1]
            target = satisfied if readback.active_layout == layout else unsatisfied
            target.append(effect)
            continue
        if effect.startswith("ward:"):
            ward_id = effect.split(":", 1)[1]
            target = (
                satisfied
                if ward_id in active_wards and _ward_is_visible(ward_id, readback.ward_properties)
                else unsatisfied
            )
            target.append(effect)
            continue
        unsatisfied.append(effect)
    return tuple(satisfied), tuple(unsatisfied)


def _critical_unsatisfied_effects(effects: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        effect
        for effect in effects
        if not effect.startswith("posture:") and not effect.startswith("candidate_posture:")
    )


def _ward_is_visible(
    ward_id: str,
    ward_properties: Mapping[str, Mapping[str, object]],
) -> bool:
    props = ward_properties.get(ward_id)
    if props is None:
        return False
    if props.get("rendered_blit") is not True:
        return False
    visible = props.get("visible")
    if visible is not True:
        return False
    alpha = props.get("alpha")
    return not (isinstance(alpha, int | float) and float(alpha) <= 0.0)


def _safety_fallback_receipt(
    *,
    intents: tuple[SegmentActionIntent, ...],
    available_layouts: frozenset[str],
    readback: RuntimeLayoutReadback,
    state: SegmentLayoutState,
    now: float,
    input_refs: tuple[str, ...],
    readback_refs: tuple[str, ...],
) -> LayoutDecisionReceipt:
    selected_layout = POSTURE_TO_LAYOUT[LayoutPosture.SAFETY_FALLBACK]
    if selected_layout not in available_layouts:
        return _receipt(
            status=LayoutDecisionStatus.HELD,
            reason=LayoutDecisionReason.SAFETY_FALLBACK_UNAVAILABLE,
            selected_posture=LayoutPosture.SAFETY_FALLBACK,
            selected_layout=selected_layout,
            previous_layout=state.current_layout,
            intent=intents[0] if intents else None,
            now=now,
            evidence_refs=_flatten_evidence(intents),
            input_refs=input_refs,
            readback_refs=readback_refs,
            satisfied_effects=(),
            unsatisfied_effects=(f"layout:{selected_layout}", "safety:consent"),
            denied_intents=_intent_ids(intents),
            safety_arbitration={
                "safety_state": readback.safety_state,
                "bypasses_hysteresis": True,
                "message": "safety fallback layout unavailable; fail closed instead of faking success",
            },
            fallback_reason="safety_unavailable",
            refusal_metadata={"missing_layout": selected_layout},
        )
    satisfied_effects, unsatisfied_effects = _split_effects(
        (f"layout:{selected_layout}", "safety:consent"),
        readback,
    )
    return _receipt(
        status=LayoutDecisionStatus.FALLBACK,
        reason=LayoutDecisionReason.SAFETY_FALLBACK,
        selected_posture=LayoutPosture.SAFETY_FALLBACK,
        selected_layout=selected_layout,
        previous_layout=state.current_layout,
        intent=intents[0] if intents else None,
        now=now,
        evidence_refs=_flatten_evidence(intents),
        input_refs=input_refs,
        readback_refs=readback_refs,
        satisfied_effects=satisfied_effects,
        unsatisfied_effects=unsatisfied_effects,
        denied_intents=_intent_ids(intents),
        safety_arbitration={
            "safety_state": readback.safety_state,
            "bypasses_hysteresis": True,
            "message": "safety/consent fallback outranks hosted-segment layout posture",
        },
        fallback_reason="safety",
        receipt_metadata={
            "active_layout_readback": readback.active_layout,
            "active_wards": list(readback.active_wards),
        },
    )


def _explicit_fallback_receipt(
    *,
    intent: SegmentActionIntent,
    all_intents: tuple[SegmentActionIntent, ...],
    readback: RuntimeLayoutReadback,
    state: SegmentLayoutState,
    now: float,
    input_refs: tuple[str, ...],
    readback_refs: tuple[str, ...],
) -> LayoutDecisionReceipt:
    selected_layout = POSTURE_TO_LAYOUT[LayoutPosture.NON_RESPONSIBLE_FALLBACK]
    satisfied_effects, unsatisfied_effects = _split_effects(
        (f"layout:{selected_layout}", "fallback:explicit_non_responsible"),
        readback,
    )
    return _receipt(
        status=LayoutDecisionStatus.FALLBACK,
        reason=LayoutDecisionReason.EXPLICIT_FALLBACK,
        selected_posture=LayoutPosture.NON_RESPONSIBLE_FALLBACK,
        selected_layout=selected_layout,
        previous_layout=state.current_layout,
        intent=intent,
        now=now,
        evidence_refs=intent.evidence_refs,
        input_refs=input_refs,
        readback_refs=readback_refs,
        satisfied_effects=satisfied_effects,
        unsatisfied_effects=unsatisfied_effects,
        denied_intents=tuple(
            candidate.intent_id
            for candidate in all_intents
            if candidate.intent_id != intent.intent_id
        ),
        fallback_reason="explicit_non_responsible",
        receipt_metadata={
            "message": "default/static fallback is explicit and not success",
            "active_layout_readback": readback.active_layout,
        },
    )


def _receipt(
    *,
    status: LayoutDecisionStatus,
    reason: LayoutDecisionReason,
    selected_posture: LayoutPosture | None,
    selected_layout: str | None,
    previous_layout: str | None,
    intent: SegmentActionIntent | None,
    now: float,
    evidence_refs: tuple[str, ...],
    input_refs: tuple[str, ...],
    readback_refs: tuple[str, ...],
    satisfied_effects: tuple[str, ...],
    unsatisfied_effects: tuple[str, ...],
    denied_intents: tuple[str, ...] = (),
    applied_layout_changes: tuple[str, ...] = (),
    applied_ward_changes: tuple[str, ...] = (),
    applied_action_changes: tuple[str, ...] = (),
    safety_arbitration: Mapping[str, object] | None = None,
    fallback_reason: str | None = None,
    spoken_text_altered: bool = False,
    refusal_metadata: Mapping[str, object] | None = None,
    receipt_metadata: Mapping[str, object] | None = None,
) -> LayoutDecisionReceipt:
    return LayoutDecisionReceipt(
        status=status,
        reason=reason,
        selected_posture=selected_posture,
        selected_layout=selected_layout,
        previous_layout=previous_layout,
        need_id=intent.intent_id if intent else None,
        need_kind=intent.kind if intent else None,
        observed_at=now,
        expires_at=(intent.requested_at + intent.ttl_s) if intent else None,
        evidence_refs=evidence_refs,
        input_refs=input_refs,
        readback_refs=readback_refs,
        satisfied_effects=satisfied_effects,
        unsatisfied_effects=unsatisfied_effects,
        denied_intents=denied_intents,
        applied_layout_changes=applied_layout_changes,
        applied_ward_changes=applied_ward_changes,
        applied_action_changes=applied_action_changes,
        safety_arbitration=safety_arbitration or {},
        fallback_reason=fallback_reason,
        spoken_text_altered=spoken_text_altered,
        refusal_metadata=refusal_metadata or {},
        receipt_metadata=receipt_metadata or {},
    )


def _rejection(
    intent: SegmentActionIntent,
    reason: LayoutDecisionReason,
    *,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "intent_id": intent.intent_id,
        "kind": intent.kind,
        "reason": reason.value,
        "evidence_refs": list(intent.evidence_refs),
    }
    if extra:
        payload.update(extra)
    return payload


def _dominant_rejection_reason(
    rejections: Iterable[dict[str, object]],
) -> LayoutDecisionReason:
    for rejection in rejections:
        first_reason = str(rejection.get("reason"))
        try:
            return LayoutDecisionReason(first_reason)
        except ValueError:
            continue
    return LayoutDecisionReason.NO_LAYOUT_NEEDS


def _flatten_evidence(intents: Iterable[SegmentActionIntent]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for intent in intents:
        for ref in intent.evidence_refs:
            seen.setdefault(ref, None)
    return tuple(seen)


__all__ = [
    "BOUNDED_LAYOUTS",
    "DEFAULT_HYSTERESIS_S",
    "DEFAULT_NEED_TTL_S",
    "DEFAULT_READBACK_TTL_S",
    "DEFAULT_STATIC_LAYOUTS",
    "LayoutDecisionReason",
    "LayoutDecisionReceipt",
    "LayoutDecisionStatus",
    "LayoutNeedKind",
    "LayoutPosture",
    "LayoutResponsibilityController",
    "NEED_TO_POSTURE",
    "POSTURE_TO_LAYOUT",
    "ResponsibleLayoutMode",
    "RuntimeLayoutReadback",
    "SegmentActionIntent",
    "SegmentLayoutNeed",
    "SegmentLayoutState",
    "decide_layout_responsibility",
    "decide_segment_layout",
]
