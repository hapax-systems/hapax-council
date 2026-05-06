"""Segment layout-responsibility contract.

Doctrine: responsible layout is a witnessed runtime control loop, not a
template choice.

When Hapax hosts a responsible livestream segment, the default/static
composition is not a successful outcome. A prepared artifact may declare typed
layout needs and expected visible effects derived from action intents; it must
not name arbitrary concrete layouts as commands. The canonical broadcast
runtime remains responsible for decisions, receipts, and readbacks.

Motivation: LayoutStore's active name and gauge are advisory until a runtime
resolver mutates LayoutState and proves the visible result. Responsibility
therefore requires a decision plus readback, not only a template selection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LAYOUT_RESPONSIBILITY_VERSION = 1
DOCTRINE_NAME = "responsible layout is a witnessed runtime control loop, not a template choice"
DOCTRINE_SUMMARY = (
    "Default/static layout is invalid as success for Hapax-hosted responsible "
    "livestream segments; it is allowed only as explicit fallback or "
    "non-responsible-static posture. LayoutStore active-name/gauge state is "
    "advisory; LayoutState mutation plus receipt/readback is the responsible "
    "runtime control loop."
)
PREPARED_ARTIFACT_AUTHORITY = "declares_layout_needs_only"
RUNTIME_LAYOUT_AUTHORITY = "canonical_broadcast_runtime"
STATIC_DEFAULT_LAYOUTS = frozenset(
    {
        "balanced",
        "default",
        "default.json",
        "garage-door",
        "garage_door",
        "static",
    }
)
SAFETY_FALLBACK_LAYOUTS = frozenset({"consent-safe", "consent_safe", "consent-safe.json"})
_FORBIDDEN_PREPARED_LAYOUT_KEYS = frozenset(
    {
        "bounds",
        "command",
        "command_string",
        "compositor_command",
        "coordinate",
        "coordinates",
        "cue",
        "cue_string",
        "cues",
        "geometry",
        "h",
        "layout",
        "layout_mode",
        "layout_name",
        "scene_command",
        "selected_layout",
        "segment_cues",
        "segment_cues_as_command",
        "shm_path",
        "shm_paths",
        "surface_id",
        "surface_ids",
        "target_layout",
        "target_surface_id",
        "preset",
        "w",
        "x",
        "y",
        "z",
        "z-order",
        "z_order",
    }
)
_FORBIDDEN_PREPARED_LAYOUT_VALUES = (
    STATIC_DEFAULT_LAYOUTS
    | SAFETY_FALLBACK_LAYOUTS
    | frozenset(
        {
            "default-legacy",
            "default_legacy",
            "vinyl-focus",
            "vinyl_focus",
        }
    )
)


class HostingMode(StrEnum):
    RESPONSIBLE_HOSTING = "responsible_hosting"
    NON_RESPONSIBLE_STATIC = "non_responsible_static"
    EXPLICIT_FALLBACK = "explicit_fallback"


class PublicPrivateMode(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL_REHEARSAL = "internal_rehearsal"


class ActionIntentKind(StrEnum):
    NARRATE = "narrate"
    SHOW_EVIDENCE = "show_evidence"
    DEMONSTRATE_ACTION = "demonstrate_action"
    COMPARE_REFERENTS = "compare_referents"
    CITE_SOURCE = "cite_source"
    READ_DETAIL = "read_detail"


class LayoutNeedKind(StrEnum):
    EVIDENCE_VISIBLE = "evidence_visible"
    ACTION_VISIBLE = "action_visible"
    COMPARISON_VISIBLE = "comparison_visible"
    SOURCE_VISIBLE = "source_visible"
    READABILITY_HELD = "readability_held"
    REFERENT_VISIBLE = "referent_visible"


class ExpectedVisibleEffect(StrEnum):
    EVIDENCE_ON_SCREEN = "evidence_on_screen"
    ACTION_ON_SCREEN = "action_on_screen"
    COMPARISON_LEGIBLE = "comparison_legible"
    SOURCE_CONTEXT_LEGIBLE = "source_context_legible"
    DETAIL_READABLE = "detail_readable"
    REFERENT_AVAILABLE = "referent_available"


class LayoutPosture(StrEnum):
    SEGMENT_PRIMARY = "segment_primary"
    RANKED_VISUAL = "ranked_visual"
    COUNTDOWN_VISUAL = "countdown_visual"
    DEPTH_VISUAL = "depth_visual"
    CAMERA_SUBJECT = "camera_subject"
    CHAT_PROMPT = "chat_prompt"
    ASSET_FRONT = "asset_front"
    COMPARISON = "comparison"
    SPOKEN_ONLY_FALLBACK = "spoken_only_fallback"
    NON_RESPONSIBLE_STATIC = "non_responsible_static"


class LayoutConflictPriority(StrEnum):
    SAFETY = "safety"
    OPERATOR_OVERRIDE = "operator_override"
    SOURCE_AVAILABILITY = "source_availability"
    ACTION_VISIBILITY = "action_visibility"
    READABILITY = "readability"
    CONTINUITY = "continuity"


class LayoutReceiptStatus(StrEnum):
    PENDING = "pending"
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    FALLBACK_ACTIVE = "fallback_active"


DEFAULT_POSTURE_VOCABULARY: tuple[LayoutPosture, ...] = (
    LayoutPosture.SEGMENT_PRIMARY,
    LayoutPosture.RANKED_VISUAL,
    LayoutPosture.COUNTDOWN_VISUAL,
    LayoutPosture.DEPTH_VISUAL,
    LayoutPosture.CAMERA_SUBJECT,
    LayoutPosture.CHAT_PROMPT,
    LayoutPosture.ASSET_FRONT,
    LayoutPosture.COMPARISON,
    LayoutPosture.SPOKEN_ONLY_FALLBACK,
    LayoutPosture.NON_RESPONSIBLE_STATIC,
)
DEFAULT_DECISION_VOCABULARY = DEFAULT_POSTURE_VOCABULARY
DEFAULT_CONFLICT_ORDER: tuple[LayoutConflictPriority, ...] = (
    LayoutConflictPriority.SAFETY,
    LayoutConflictPriority.OPERATOR_OVERRIDE,
    LayoutConflictPriority.SOURCE_AVAILABILITY,
    LayoutConflictPriority.ACTION_VISIBILITY,
    LayoutConflictPriority.READABILITY,
    LayoutConflictPriority.CONTINUITY,
)


class HostingContext(BaseModel):
    """Explicit responsibility posture for a segment."""

    model_config = ConfigDict(extra="forbid")

    mode: HostingMode
    public_private_mode: PublicPrivateMode
    hapax_controls_layout: bool
    responsible_for_content_quality: bool
    static_layout_success_allowed: bool = False

    @model_validator(mode="after")
    def _static_success_requires_explicit_non_responsibility(self) -> HostingContext:
        if self.mode is HostingMode.RESPONSIBLE_HOSTING:
            if not self.hapax_controls_layout:
                raise ValueError("responsible_hosting requires hapax_controls_layout=true")
            if not self.responsible_for_content_quality:
                raise ValueError(
                    "responsible_hosting requires responsible_for_content_quality=true"
                )
            if self.static_layout_success_allowed:
                raise ValueError(
                    "static_layout_success_allowed cannot be true for responsible_hosting"
                )
        if self.static_layout_success_allowed and self.mode not in {
            HostingMode.NON_RESPONSIBLE_STATIC,
            HostingMode.EXPLICIT_FALLBACK,
        }:
            raise ValueError(
                "static_layout_success_allowed is only valid for "
                "non_responsible_static or explicit_fallback"
            )
        if self.mode is HostingMode.NON_RESPONSIBLE_STATIC and self.responsible_for_content_quality:
            raise ValueError(
                "non_responsible_static cannot also claim responsible_for_content_quality"
            )
        return self


class SegmentActionIntent(BaseModel):
    """Typed segment action intent before layout needs are derived."""

    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    kind: ActionIntentKind
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_affordances: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _visible_action_intents_need_sources(self) -> SegmentActionIntent:
        if self.kind is ActionIntentKind.NARRATE:
            return self
        if not self.evidence_refs:
            raise ValueError(f"{self.intent_id}: visible/action intent requires evidence_refs")
        if not self.source_affordances:
            raise ValueError(f"{self.intent_id}: visible/action intent requires source_affordances")
        return self


class BeatLayoutIntent(BaseModel):
    """Prepared-artifact declaration for one beat's layout responsibility."""

    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(min_length=1)
    action_intent_kinds: tuple[ActionIntentKind, ...] = Field(min_length=1)
    layout_needs: tuple[LayoutNeedKind, ...] = Field(min_length=1)
    proposed_postures: tuple[LayoutPosture, ...] = Field(min_length=1)
    expected_effects: tuple[ExpectedVisibleEffect, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    source_affordances: tuple[str, ...] = Field(min_length=1)
    default_static_success_allowed: bool = False


class LayoutDecisionContract(BaseModel):
    """Bounded runtime layout-decision contract."""

    model_config = ConfigDict(extra="forbid")

    bounded_vocabulary: tuple[LayoutPosture, ...] = DEFAULT_POSTURE_VOCABULARY
    min_dwell_s: int = Field(default=8, ge=1, le=300)
    ttl_s: int = Field(default=30, ge=1, le=600)
    conflict_order: tuple[LayoutConflictPriority, ...] = DEFAULT_CONFLICT_ORDER
    receipt_required: bool = True

    @model_validator(mode="after")
    def _bounded_contract_is_complete(self) -> LayoutDecisionContract:
        if not self.receipt_required:
            raise ValueError("layout decisions require receipts/readbacks")
        if not self.bounded_vocabulary:
            raise ValueError("bounded_vocabulary must not be empty")
        if len(set(self.bounded_vocabulary)) != len(self.bounded_vocabulary):
            raise ValueError("bounded_vocabulary must not contain duplicates")
        if len(set(self.conflict_order)) != len(self.conflict_order):
            raise ValueError("conflict_order must not contain duplicates")
        if self.ttl_s < self.min_dwell_s:
            raise ValueError("ttl_s must be >= min_dwell_s")
        return self


class PreparedSegmentLayoutContract(BaseModel):
    """Proposal-only layout contract emitted with prepared segment artifacts."""

    model_config = ConfigDict(extra="forbid")

    layout_responsibility_version: Literal[1] = LAYOUT_RESPONSIBILITY_VERSION
    doctrine: Literal[
        "responsible layout is a witnessed runtime control loop, not a template choice"
    ] = DOCTRINE_NAME
    artifact_authority: Literal["declares_layout_needs_only"] = PREPARED_ARTIFACT_AUTHORITY
    segment_id: str = Field(min_length=1)
    hosting_context: HostingContext
    beat_layout_intents: tuple[BeatLayoutIntent, ...] = Field(default_factory=tuple)
    layout_decision_contract: LayoutDecisionContract = Field(default_factory=LayoutDecisionContract)

    @model_validator(mode="after")
    def _responsible_hosting_needs_visible_work(self) -> PreparedSegmentLayoutContract:
        if self.hosting_context.mode is HostingMode.RESPONSIBLE_HOSTING:
            if not self.beat_layout_intents:
                raise ValueError(
                    "responsible_hosting requires beat_layout_intents; "
                    "default/static layout is not a success path"
                )
            for beat in self.beat_layout_intents:
                if beat.default_static_success_allowed:
                    raise ValueError(
                        f"{beat.beat_id}: default_static_success_allowed cannot be true "
                        "for responsible_hosting"
                    )
                if LayoutPosture.NON_RESPONSIBLE_STATIC in beat.proposed_postures:
                    raise ValueError(
                        f"{beat.beat_id}: non_responsible_static posture cannot be "
                        "proposed for responsible_hosting"
                    )
        else:
            for beat in self.beat_layout_intents:
                if (
                    beat.default_static_success_allowed
                    and not self.hosting_context.static_layout_success_allowed
                ):
                    raise ValueError(
                        f"{beat.beat_id}: beat default_static_success_allowed requires "
                        "hosting_context.static_layout_success_allowed"
                    )
        return self


class RuntimeLayoutDecision(BaseModel):
    """Decision emitted by the canonical runtime layout resolver.

    Runtime decisions can reference LayoutStore/LayoutState, WCS/readback
    requirements, and safety constraints. Prepared artifacts cannot emit this
    model because it carries runtime authority.
    """

    model_config = ConfigDict(extra="forbid")

    layout_responsibility_version: Literal[1] = LAYOUT_RESPONSIBILITY_VERSION
    authority: Literal["canonical_broadcast_runtime"] = RUNTIME_LAYOUT_AUTHORITY
    decision_id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    beat_id: str | None = None
    posture: LayoutPosture
    reason: str = Field(min_length=1)
    expected_effects: tuple[ExpectedVisibleEffect, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    layout_state_hash_before: str | None = None
    layout_store_active_name: str | None = None
    layout_store_gauge_active: str | None = None
    wcs_readback_requirements: tuple[str, ...] = Field(default_factory=tuple)
    consent_constraints: tuple[str, ...] = Field(default_factory=tuple)
    broadcast_constraints: tuple[str, ...] = Field(default_factory=tuple)
    min_dwell_s: int = Field(ge=1, le=300)
    ttl_s: int = Field(ge=1, le=600)
    issued_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _decision_ttl_covers_dwell(self) -> RuntimeLayoutDecision:
        if self.ttl_s < self.min_dwell_s:
            raise ValueError("runtime layout decision ttl_s must be >= min_dwell_s")
        return self


class RuntimeLayoutReceipt(BaseModel):
    """Receipt/readback emitted by canonical runtime layout authority."""

    model_config = ConfigDict(extra="forbid")

    layout_responsibility_version: Literal[1] = LAYOUT_RESPONSIBILITY_VERSION
    authority: Literal["canonical_broadcast_runtime"] = RUNTIME_LAYOUT_AUTHORITY
    receipt_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    beat_id: str | None = None
    posture: LayoutPosture
    status: LayoutReceiptStatus
    observed_layout: str | None = None
    layout_state_hash_after: str | None = None
    ward_visibility: Mapping[str, bool] = Field(default_factory=dict)
    observed_effects: tuple[ExpectedVisibleEffect, ...] = Field(default_factory=tuple)
    wcs_readback_refs: tuple[str, ...] = Field(default_factory=tuple)
    consent_constraints: tuple[str, ...] = Field(default_factory=tuple)
    broadcast_constraints: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    issued_at: str = Field(min_length=1)


def beat_layout_intents_from_action_intents(
    action_intents: Sequence[SegmentActionIntent],
) -> tuple[BeatLayoutIntent, ...]:
    """Derive prepared-artifact layout intents from typed action intents."""

    by_beat: dict[str, list[SegmentActionIntent]] = {}
    for intent in action_intents:
        by_beat.setdefault(intent.beat_id, []).append(intent)

    beat_intents: list[BeatLayoutIntent] = []
    for beat_id, intents in by_beat.items():
        layout_needs: list[LayoutNeedKind] = []
        expected_effects: list[ExpectedVisibleEffect] = []
        evidence_refs: list[str] = []
        source_affordances: list[str] = []
        action_kinds: list[ActionIntentKind] = []
        for intent in intents:
            action_kinds.append(intent.kind)
            if intent.kind is ActionIntentKind.NARRATE:
                continue
            need, effect, posture = _layout_need_for_action_intent(intent.kind)
            if need not in layout_needs:
                layout_needs.append(need)
            if effect not in expected_effects:
                expected_effects.append(effect)
            evidence_refs.extend(intent.evidence_refs)
            source_affordances.extend(intent.source_affordances)

        if not layout_needs:
            continue
        proposed_postures = _dedupe(
            tuple(
                _layout_need_for_action_intent(intent.kind)[2]
                for intent in intents
                if intent.kind is not ActionIntentKind.NARRATE
            )
            + tuple(
                posture
                for intent in intents
                for posture in _postures_for_source_affordances(intent.source_affordances)
            )
        )
        beat_intents.append(
            BeatLayoutIntent(
                beat_id=beat_id,
                action_intent_kinds=tuple(_dedupe(action_kinds)),
                layout_needs=tuple(layout_needs),
                proposed_postures=proposed_postures,
                expected_effects=tuple(expected_effects),
                evidence_refs=tuple(_dedupe(evidence_refs)),
                source_affordances=tuple(_dedupe(source_affordances)),
            )
        )
    return tuple(beat_intents)


def prepared_artifact_layout_metadata(contract: PreparedSegmentLayoutContract) -> dict[str, Any]:
    """Render proposal-only layout metadata for a prepared artifact."""

    payload = contract.model_dump(mode="json")
    validate_prepared_artifact_layout_metadata(payload)
    return payload


def validate_prepared_artifact_layout_metadata(
    metadata: Mapping[str, Any],
) -> PreparedSegmentLayoutContract:
    """Validate prepared-artifact metadata and reject layout commands."""

    _reject_prepared_layout_commands(metadata)
    return PreparedSegmentLayoutContract.model_validate(metadata)


def validate_runtime_layout_decision(
    contract: PreparedSegmentLayoutContract,
    decision: RuntimeLayoutDecision,
) -> None:
    """Validate runtime decision authority against the prepared contract."""

    if decision.segment_id != contract.segment_id:
        raise ValueError("layout decision segment_id does not match prepared contract")
    if decision.posture not in contract.layout_decision_contract.bounded_vocabulary:
        raise ValueError(f"layout decision posture {decision.posture.value!r} is outside contract")
    if decision.ttl_s > contract.layout_decision_contract.ttl_s:
        raise ValueError("layout decision ttl_s exceeds prepared contract")
    if decision.min_dwell_s < contract.layout_decision_contract.min_dwell_s:
        raise ValueError("layout decision min_dwell_s is below prepared contract")
    if contract.hosting_context.mode is HostingMode.RESPONSIBLE_HOSTING:
        if decision.posture is LayoutPosture.NON_RESPONSIBLE_STATIC:
            raise ValueError(
                "responsible_hosting decision cannot use non_responsible_static posture"
            )
        if not decision.layout_state_hash_before:
            raise ValueError("responsible_hosting decision requires layout_state_hash_before")


def validate_runtime_layout_receipt(
    contract: PreparedSegmentLayoutContract,
    receipt: RuntimeLayoutReceipt,
) -> None:
    """Validate that runtime authority satisfied the prepared contract."""

    if receipt.segment_id != contract.segment_id:
        raise ValueError("layout receipt segment_id does not match prepared contract")
    if receipt.posture not in contract.layout_decision_contract.bounded_vocabulary:
        raise ValueError(f"layout receipt posture {receipt.posture.value!r} is outside contract")
    if receipt.status in {LayoutReceiptStatus.PENDING, LayoutReceiptStatus.MISMATCHED}:
        raise ValueError(
            f"layout receipt status {receipt.status.value!r} is not successful readback"
        )

    observed = _layout_token(receipt.observed_layout or "")
    mode = contract.hosting_context.mode
    if mode is HostingMode.RESPONSIBLE_HOSTING:
        if receipt.status is LayoutReceiptStatus.FALLBACK_ACTIVE:
            raise ValueError("responsible_hosting cannot count fallback-active layout as success")
        if receipt.posture is LayoutPosture.NON_RESPONSIBLE_STATIC:
            raise ValueError("responsible_hosting cannot count non_responsible_static as success")
        if observed in STATIC_DEFAULT_LAYOUTS:
            raise ValueError(
                "static/default layout cannot be responsible_hosting success even with receipt"
            )
        if not receipt.observed_effects:
            raise ValueError("responsible_hosting receipt requires observed_effects")
        if not receipt.layout_state_hash_after:
            raise ValueError("responsible_hosting receipt requires layout_state_hash_after")
        if not receipt.ward_visibility and not receipt.wcs_readback_refs:
            raise ValueError(
                "responsible_hosting receipt requires ward_visibility or WCS/readback refs"
            )
    elif mode is HostingMode.EXPLICIT_FALLBACK:
        if receipt.status is not LayoutReceiptStatus.FALLBACK_ACTIVE:
            raise ValueError("explicit_fallback success requires fallback_active receipt")
    elif (
        mode is HostingMode.NON_RESPONSIBLE_STATIC
        and not contract.hosting_context.static_layout_success_allowed
    ):
        raise ValueError("non_responsible_static success requires explicit static allowance")


def _layout_need_for_action_intent(
    kind: ActionIntentKind,
) -> tuple[LayoutNeedKind, ExpectedVisibleEffect, LayoutPosture]:
    if kind is ActionIntentKind.SHOW_EVIDENCE:
        return (
            LayoutNeedKind.EVIDENCE_VISIBLE,
            ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,
            LayoutPosture.ASSET_FRONT,
        )
    if kind is ActionIntentKind.DEMONSTRATE_ACTION:
        return (
            LayoutNeedKind.ACTION_VISIBLE,
            ExpectedVisibleEffect.ACTION_ON_SCREEN,
            LayoutPosture.SEGMENT_PRIMARY,
        )
    if kind is ActionIntentKind.COMPARE_REFERENTS:
        return (
            LayoutNeedKind.COMPARISON_VISIBLE,
            ExpectedVisibleEffect.COMPARISON_LEGIBLE,
            LayoutPosture.COMPARISON,
        )
    if kind is ActionIntentKind.CITE_SOURCE:
        return (
            LayoutNeedKind.SOURCE_VISIBLE,
            ExpectedVisibleEffect.SOURCE_CONTEXT_LEGIBLE,
            LayoutPosture.ASSET_FRONT,
        )
    if kind is ActionIntentKind.READ_DETAIL:
        return (
            LayoutNeedKind.READABILITY_HELD,
            ExpectedVisibleEffect.DETAIL_READABLE,
            LayoutPosture.DEPTH_VISUAL,
        )
    return (
        LayoutNeedKind.REFERENT_VISIBLE,
        ExpectedVisibleEffect.REFERENT_AVAILABLE,
        LayoutPosture.SPOKEN_ONLY_FALLBACK,
    )


def _postures_for_source_affordances(
    source_affordances: Sequence[str],
) -> tuple[LayoutPosture, ...]:
    out: list[LayoutPosture] = []
    for affordance in source_affordances:
        lowered = affordance.lower()
        if "camera" in lowered or "cam." in lowered:
            out.append(LayoutPosture.CAMERA_SUBJECT)
        if "chat" in lowered:
            out.append(LayoutPosture.CHAT_PROMPT)
        if "countdown" in lowered:
            out.append(LayoutPosture.COUNTDOWN_VISUAL)
        if "rank" in lowered or "tier" in lowered:
            out.append(LayoutPosture.RANKED_VISUAL)
    return _dedupe(out)


def _dedupe[T](items: Sequence[T]) -> tuple[T, ...]:
    seen: set[T] = set()
    out: list[T] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def _reject_prepared_layout_commands(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            if key_text in _FORBIDDEN_PREPARED_LAYOUT_KEYS:
                raise ValueError(f"prepared artifact layout metadata cannot set {path}.{key_text}")
            _reject_prepared_layout_commands(nested, path=f"{path}.{key_text}")
        return
    if isinstance(value, str):
        if _layout_token(value) in _FORBIDDEN_PREPARED_LAYOUT_VALUES:
            raise ValueError(
                f"prepared artifact layout metadata cannot name concrete layout {value!r}"
            )
        return
    if isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _reject_prepared_layout_commands(nested, path=f"{path}[{index}]")


def _layout_token(value: str) -> str:
    return value.strip().lower()


__all__ = [
    "DEFAULT_CONFLICT_ORDER",
    "DEFAULT_DECISION_VOCABULARY",
    "DEFAULT_POSTURE_VOCABULARY",
    "DOCTRINE_NAME",
    "DOCTRINE_SUMMARY",
    "LAYOUT_RESPONSIBILITY_VERSION",
    "PREPARED_ARTIFACT_AUTHORITY",
    "RUNTIME_LAYOUT_AUTHORITY",
    "SAFETY_FALLBACK_LAYOUTS",
    "STATIC_DEFAULT_LAYOUTS",
    "ActionIntentKind",
    "BeatLayoutIntent",
    "ExpectedVisibleEffect",
    "HostingContext",
    "HostingMode",
    "LayoutConflictPriority",
    "LayoutDecisionContract",
    "LayoutNeedKind",
    "LayoutPosture",
    "LayoutReceiptStatus",
    "PreparedSegmentLayoutContract",
    "PublicPrivateMode",
    "RuntimeLayoutDecision",
    "RuntimeLayoutReceipt",
    "SegmentActionIntent",
    "beat_layout_intents_from_action_intents",
    "prepared_artifact_layout_metadata",
    "validate_prepared_artifact_layout_metadata",
    "validate_runtime_layout_decision",
    "validate_runtime_layout_receipt",
]
