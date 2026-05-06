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

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

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
PARENT_PREPARED_ARTIFACT_AUTHORITY = "prior_only"
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
_FORBIDDEN_PREPARED_LAYOUT_KEY_TOKENS = frozenset(
    {
        "bounds",
        "command",
        "commandstring",
        "compositorcommand",
        "coordinate",
        "coordinates",
        "cue",
        "cuestring",
        "cues",
        "defaultlayout",
        "geometry",
        "h",
        "layout",
        "layoutmode",
        "layoutname",
        "scenecommand",
        "selectedlayout",
        "segmentcues",
        "segmentcuesascommand",
        "shmpath",
        "shmpaths",
        "surfaceid",
        "surfaceids",
        "targetlayout",
        "targetsurfaceid",
        "preset",
        "w",
        "x",
        "y",
        "z",
        "zindex",
        "zorder",
    }
)
_FORBIDDEN_PREPARED_COMMAND_RE = re.compile(
    r"(?<![a-z0-9_])(?:camera|front|composition|transition|media|scrim|mood|gem)\.",
    re.IGNORECASE,
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
_RESPONSIBLE_HOSTING_CONTEXT_STRINGS = frozenset(
    {
        "hapax_responsible_live",
        "responsible_hosting",
        "responsible-live",
    }
)
_EXPLICIT_FALLBACK_CONTEXT_STRINGS = frozenset({"explicit_fallback", "fallback_active"})
_NON_RESPONSIBLE_STATIC_CONTEXT_STRINGS = frozenset(
    {"non_responsible_static", "non-responsible-static"}
)
_PARENT_LAYOUT_NON_COMMAND_VALUE = False
_PARENT_IGNORED_RESPONSIBLE_NEEDS = frozenset({"hostpresence", "spokenargument"})
_PARENT_OVERRIDE_KEYS = frozenset(
    {
        "artifactauthority",
        "authority",
        "contractid",
        "hostingcontext",
        "layoutresponsibilityversion",
        "parentconditionid",
        "parentshowid",
        "programmeid",
        "segmentid",
    }
)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


class RuntimeReadbackKind(StrEnum):
    WCS = "wcs"
    LAYOUT_STATE = "layout_state"
    WARD_VISIBILITY = "ward_visibility"
    BROADCAST_CONSTRAINT = "broadcast_constraint"


class RuntimeReadbackRef(BaseModel):
    """Typed runtime readback reference.

    Arbitrary prepared strings are not receipts. The runtime authority must
    provide a bounded readback kind and a stable reference id.
    """

    model_config = ConfigDict(extra="forbid")

    kind: RuntimeReadbackKind
    ref_id: str = Field(min_length=1)
    verified: bool = True
    digest: str | None = None

    @field_validator("digest")
    @classmethod
    def _digest_is_sha256(cls, value: str | None) -> str | None:
        if value is not None and not _is_sha256(value):
            raise ValueError("runtime readback digest must be sha256:<64 lowercase hex>")
        return value


class PreparedRuntimeLayoutValidation(BaseModel):
    """Prepared requirements for runtime validation, not runtime authority."""

    model_config = ConfigDict(extra="forbid")

    receipt_required: bool = True
    layout_state_hash_required: bool = True
    layout_state_signature_required: bool = True
    ward_visibility_required: bool = True
    readback_kinds_required: tuple[RuntimeReadbackKind, ...] = (
        RuntimeReadbackKind.WCS,
        RuntimeReadbackKind.LAYOUT_STATE,
        RuntimeReadbackKind.WARD_VISIBILITY,
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
    needs: tuple[LayoutNeedKind, ...] = Field(
        min_length=1,
        validation_alias=AliasChoices("needs", "layout_needs"),
    )
    proposed_postures: tuple[LayoutPosture, ...] = Field(min_length=1)
    expected_effects: tuple[ExpectedVisibleEffect, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    source_affordances: tuple[str, ...] = Field(min_length=1)
    default_static_success_allowed: bool = False
    parent_beat_index: int | None = Field(default=None, ge=0)


class LayoutDecisionContract(BaseModel):
    """Bounded runtime layout-decision contract."""

    model_config = ConfigDict(extra="forbid")

    bounded_vocabulary: tuple[LayoutPosture, ...] = DEFAULT_POSTURE_VOCABULARY
    min_dwell_s: int = Field(default=8, ge=1, le=300)
    ttl_s: int = Field(default=30, ge=1, le=600)
    conflict_order: tuple[LayoutConflictPriority, ...] = DEFAULT_CONFLICT_ORDER
    receipt_required: bool = True
    may_command_layout: Literal[False] = False

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

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    layout_responsibility_version: Literal[1] = LAYOUT_RESPONSIBILITY_VERSION
    doctrine: Literal[
        "responsible layout is a witnessed runtime control loop, not a template choice"
    ] = DOCTRINE_NAME
    artifact_authority: Literal["declares_layout_needs_only"] = Field(
        default=PREPARED_ARTIFACT_AUTHORITY,
        validation_alias=AliasChoices("artifact_authority", "authority"),
        serialization_alias="authority",
    )
    parent_artifact_authority: Literal["prior_only"] = PARENT_PREPARED_ARTIFACT_AUTHORITY
    contract_id: str | None = None
    artifact_id: str | None = None
    prepared_artifact_ref: str | None = None
    prepared_artifact_sha256: str | None = None
    segment_id: str = Field(min_length=1)
    programme_id: str | None = None
    parent_show_id: str | None = None
    parent_condition_id: str | None = None
    hosting_context: HostingContext
    beat_layout_intents: tuple[BeatLayoutIntent, ...] = Field(default_factory=tuple)
    layout_decision_contract: LayoutDecisionContract = Field(default_factory=LayoutDecisionContract)
    runtime_layout_validation: PreparedRuntimeLayoutValidation = Field(
        default_factory=PreparedRuntimeLayoutValidation
    )

    @field_validator("hosting_context", mode="before")
    @classmethod
    def _adapt_parent_hosting_context(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        token = _hosting_context_token(value)
        if token in {_hosting_context_token(v) for v in _RESPONSIBLE_HOSTING_CONTEXT_STRINGS}:
            return {
                "mode": HostingMode.RESPONSIBLE_HOSTING.value,
                "public_private_mode": PublicPrivateMode.PUBLIC.value,
                "hapax_controls_layout": True,
                "responsible_for_content_quality": True,
                "static_layout_success_allowed": False,
            }
        if token in {_hosting_context_token(v) for v in _EXPLICIT_FALLBACK_CONTEXT_STRINGS}:
            return {
                "mode": HostingMode.EXPLICIT_FALLBACK.value,
                "public_private_mode": PublicPrivateMode.PUBLIC.value,
                "hapax_controls_layout": True,
                "responsible_for_content_quality": False,
                "static_layout_success_allowed": True,
            }
        if token in {_hosting_context_token(v) for v in _NON_RESPONSIBLE_STATIC_CONTEXT_STRINGS}:
            return {
                "mode": HostingMode.NON_RESPONSIBLE_STATIC.value,
                "public_private_mode": PublicPrivateMode.INTERNAL_REHEARSAL.value,
                "hapax_controls_layout": False,
                "responsible_for_content_quality": False,
                "static_layout_success_allowed": True,
            }
        return value

    @field_validator("prepared_artifact_sha256")
    @classmethod
    def _prepared_artifact_sha_is_hex(cls, value: str | None) -> str | None:
        if value is not None and not _is_bare_sha256(value):
            raise ValueError("prepared_artifact_sha256 must be 64 lowercase hex characters")
        return value

    @model_validator(mode="after")
    def _responsible_hosting_needs_visible_work(self) -> PreparedSegmentLayoutContract:
        if self.prepared_artifact_sha256 and self.prepared_artifact_ref not in {
            f"prepared_artifact:{self.prepared_artifact_sha256}"
        }:
            raise ValueError("prepared_artifact_ref must be prepared_artifact:<sha256>")
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
            if LayoutPosture.NON_RESPONSIBLE_STATIC in (
                self.layout_decision_contract.bounded_vocabulary
            ):
                raise ValueError(
                    "responsible_hosting layout_decision_contract cannot advertise "
                    "non_responsible_static"
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
    required_ward_ids: tuple[str, ...] = Field(default_factory=tuple)
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
        if self.layout_state_hash_before and not _is_sha256(self.layout_state_hash_before):
            raise ValueError("layout_state_hash_before must be sha256:<64 lowercase hex>")
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
    layout_state_signature: str | None = None
    ward_visibility: Mapping[str, bool] = Field(default_factory=dict)
    observed_effects: tuple[ExpectedVisibleEffect, ...] = Field(default_factory=tuple)
    wcs_readback_refs: tuple[RuntimeReadbackRef, ...] = Field(default_factory=tuple)
    consent_constraints: tuple[str, ...] = Field(default_factory=tuple)
    broadcast_constraints: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    issued_at: str = Field(min_length=1)

    @field_validator("layout_state_hash_after")
    @classmethod
    def _layout_state_hash_is_sha256(cls, value: str | None) -> str | None:
        if value is not None and not _is_sha256(value):
            raise ValueError("layout_state_hash_after must be sha256:<64 lowercase hex>")
        return value


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
                needs=tuple(layout_needs),
                proposed_postures=proposed_postures,
                expected_effects=tuple(expected_effects),
                evidence_refs=tuple(_dedupe(evidence_refs)),
                source_affordances=tuple(_dedupe(source_affordances)),
            )
        )
    return tuple(beat_intents)


def prepared_artifact_layout_metadata(contract: PreparedSegmentLayoutContract) -> dict[str, Any]:
    """Render proposal-only layout metadata for a prepared artifact."""

    payload = contract.model_dump(mode="json", by_alias=True)
    validate_prepared_artifact_layout_metadata(payload)
    return payload


def validate_prepared_artifact_layout_metadata(
    metadata: Mapping[str, Any],
    *,
    parent_programme_id: str | None = None,
    parent_show_id: str | None = None,
    parent_condition_id: str | None = None,
    embedding_metadata: Mapping[str, Any] | None = None,
) -> PreparedSegmentLayoutContract:
    """Validate prepared-artifact metadata and reject layout commands."""

    _reject_prepared_layout_commands(metadata)
    if embedding_metadata is not None:
        _reject_parent_metadata_overrides(embedding_metadata)
    contract = PreparedSegmentLayoutContract.model_validate(metadata)
    if parent_programme_id and contract.programme_id not in {None, parent_programme_id}:
        raise ValueError("prepared layout contract programme_id does not match parent")
    if parent_show_id and contract.parent_show_id not in {None, parent_show_id}:
        raise ValueError("prepared layout contract parent_show_id does not match parent")
    if parent_condition_id and contract.parent_condition_id not in {None, parent_condition_id}:
        raise ValueError("prepared layout contract parent_condition_id does not match parent")
    return contract


def project_parent_prepared_artifact_layout_contract(
    artifact: Mapping[str, Any],
    *,
    artifact_sha256: str,
    parent_programme_id: str | None = None,
    parent_show_id: str | None = None,
    parent_condition_id: str | None = None,
) -> PreparedSegmentLayoutContract:
    """Project parent prepared metadata into the blue proposal-only contract.

    The parent artifact keeps ``authority=prior_only`` and its original bytes.
    Blue derives ``authority=declares_layout_needs_only`` only when the parent
    also declares ``layout_decision_contract.may_command_layout=false``.
    """

    _reject_prepared_layout_commands(artifact)
    sha = _normalize_bare_sha256(artifact_sha256)
    parent_authority = _optional_str(
        artifact.get("authority") or artifact.get("artifact_authority")
    )
    if parent_authority != PARENT_PREPARED_ARTIFACT_AUTHORITY:
        raise ValueError("parent prepared artifact authority must be prior_only")

    layout_decision_contract = _mapping_or_none(artifact.get("layout_decision_contract")) or {}
    if layout_decision_contract.get("may_command_layout") is not _PARENT_LAYOUT_NON_COMMAND_VALUE:
        raise ValueError(
            "parent layout_decision_contract.may_command_layout must be false for projection"
        )

    programme_id = _optional_str(artifact.get("programme_id") or artifact.get("segment_id"))
    show_id = _optional_str(artifact.get("parent_show_id") or artifact.get("show_id"))
    condition_id = _optional_str(
        artifact.get("parent_condition_id") or artifact.get("condition_id")
    )
    if parent_programme_id and programme_id not in {None, parent_programme_id}:
        raise ValueError("prepared layout contract programme_id does not match parent")
    if parent_show_id and show_id not in {None, parent_show_id}:
        raise ValueError("prepared layout contract parent_show_id does not match parent")
    if parent_condition_id and condition_id not in {None, parent_condition_id}:
        raise ValueError("prepared layout contract parent_condition_id does not match parent")

    hosting_context = _project_parent_hosting_context(artifact.get("hosting_context"))
    beat_layout_intents = _project_parent_beat_layout_intents(
        artifact.get("beat_layout_intents") or (),
        artifact_sha256=sha,
        responsible=hosting_context.mode is HostingMode.RESPONSIBLE_HOSTING,
    )

    contract_payload = {
        "layout_responsibility_version": LAYOUT_RESPONSIBILITY_VERSION,
        "doctrine": DOCTRINE_NAME,
        "authority": PREPARED_ARTIFACT_AUTHORITY,
        "parent_artifact_authority": PARENT_PREPARED_ARTIFACT_AUTHORITY,
        "artifact_id": _optional_str(artifact.get("artifact_id")),
        "prepared_artifact_sha256": sha,
        "prepared_artifact_ref": f"prepared_artifact:{sha}",
        "segment_id": _optional_str(artifact.get("segment_id")) or programme_id or "unknown",
        "programme_id": programme_id,
        "parent_show_id": show_id,
        "parent_condition_id": condition_id,
        "hosting_context": hosting_context.model_dump(mode="json"),
        "beat_layout_intents": [intent.model_dump(mode="json") for intent in beat_layout_intents],
        "layout_decision_contract": _project_parent_layout_decision_contract(
            layout_decision_contract
        ).model_dump(mode="json"),
        "runtime_layout_validation": _project_parent_runtime_validation(
            _mapping_or_none(artifact.get("runtime_layout_validation")) or {}
        ).model_dump(mode="json"),
    }
    return validate_prepared_artifact_layout_metadata(
        contract_payload,
        parent_programme_id=parent_programme_id,
        parent_show_id=parent_show_id,
        parent_condition_id=parent_condition_id,
        embedding_metadata=_mapping_or_none(artifact.get("embedding_metadata")),
    )


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
    beat = _contract_beat(contract, decision.beat_id)
    if beat is None:
        raise ValueError("layout decision beat_id does not match prepared contract")
    missing_effects = set(decision.expected_effects) - set(beat.expected_effects)
    if missing_effects:
        missing = ", ".join(sorted(effect.value for effect in missing_effects))
        raise ValueError(f"layout decision expected_effects outside prepared beat: {missing}")
    if contract.hosting_context.mode is HostingMode.RESPONSIBLE_HOSTING:
        if decision.posture is LayoutPosture.NON_RESPONSIBLE_STATIC:
            raise ValueError(
                "responsible_hosting decision cannot use non_responsible_static posture"
            )
        if not decision.layout_state_hash_before:
            raise ValueError("responsible_hosting decision requires layout_state_hash_before")
        if not decision.required_ward_ids:
            raise ValueError("responsible_hosting decision requires required_ward_ids")


def validate_runtime_layout_receipt(
    contract: PreparedSegmentLayoutContract,
    receipt: RuntimeLayoutReceipt,
    *,
    decision: RuntimeLayoutDecision | None = None,
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

    mode = contract.hosting_context.mode
    if mode is HostingMode.RESPONSIBLE_HOSTING:
        if decision is None:
            raise ValueError("responsible_hosting receipt validation requires matching decision")
        validate_runtime_layout_decision(contract, decision)
        _validate_receipt_matches_decision(decision, receipt)
        if receipt.status is LayoutReceiptStatus.FALLBACK_ACTIVE:
            raise ValueError("responsible_hosting cannot count fallback-active layout as success")
        if receipt.posture is LayoutPosture.NON_RESPONSIBLE_STATIC:
            raise ValueError("responsible_hosting cannot count non_responsible_static as success")
        if _is_static_default_layout(receipt.observed_layout or ""):
            raise ValueError(
                "static/default layout cannot be responsible_hosting success even with receipt"
            )
        missing_effects = set(decision.expected_effects) - set(receipt.observed_effects)
        if missing_effects:
            missing = ", ".join(sorted(effect.value for effect in missing_effects))
            raise ValueError(f"responsible_hosting receipt missing expected effect: {missing}")
        if not receipt.layout_state_hash_after:
            raise ValueError("responsible_hosting receipt requires layout_state_hash_after")
        if receipt.layout_state_hash_after == decision.layout_state_hash_before:
            raise ValueError("responsible_hosting receipt did not change LayoutState hash")
        if not receipt.layout_state_signature:
            raise ValueError("responsible_hosting receipt requires signed LayoutState hash")
        if not any(
            receipt.ward_visibility.get(ward_id) is True for ward_id in decision.required_ward_ids
        ):
            raise ValueError("responsible_hosting receipt requires a required ward visible=true")
        _validate_typed_readbacks(contract, receipt)
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


def _project_parent_hosting_context(value: Any) -> HostingContext:
    token = _hosting_context_token(str(value or ""))
    if token in {_hosting_context_token(v) for v in _RESPONSIBLE_HOSTING_CONTEXT_STRINGS}:
        return HostingContext(
            mode=HostingMode.RESPONSIBLE_HOSTING,
            public_private_mode=PublicPrivateMode.PUBLIC,
            hapax_controls_layout=True,
            responsible_for_content_quality=True,
            static_layout_success_allowed=False,
        )
    if token in {_hosting_context_token(v) for v in _EXPLICIT_FALLBACK_CONTEXT_STRINGS}:
        return HostingContext(
            mode=HostingMode.EXPLICIT_FALLBACK,
            public_private_mode=PublicPrivateMode.PUBLIC,
            hapax_controls_layout=True,
            responsible_for_content_quality=False,
            static_layout_success_allowed=True,
        )
    if token in {_hosting_context_token(v) for v in _NON_RESPONSIBLE_STATIC_CONTEXT_STRINGS}:
        return HostingContext(
            mode=HostingMode.NON_RESPONSIBLE_STATIC,
            public_private_mode=PublicPrivateMode.INTERNAL_REHEARSAL,
            hapax_controls_layout=False,
            responsible_for_content_quality=False,
            static_layout_success_allowed=True,
        )
    raise ValueError(f"unsupported parent hosting_context {value!r}")


def _project_parent_layout_decision_contract(parent: Mapping[str, Any]) -> LayoutDecisionContract:
    allowed: dict[str, Any] = {"may_command_layout": False}
    for key in ("bounded_vocabulary", "min_dwell_s", "ttl_s", "conflict_order", "receipt_required"):
        if key in parent:
            allowed[key] = parent[key]
    return LayoutDecisionContract.model_validate(allowed)


def _project_parent_runtime_validation(
    parent: Mapping[str, Any],
) -> PreparedRuntimeLayoutValidation:
    allowed = {
        key: parent[key]
        for key in (
            "receipt_required",
            "layout_state_hash_required",
            "layout_state_signature_required",
            "ward_visibility_required",
            "readback_kinds_required",
        )
        if key in parent
    }
    return PreparedRuntimeLayoutValidation.model_validate(allowed)


def _project_parent_beat_layout_intents(
    parent_intents: Any,
    *,
    artifact_sha256: str,
    responsible: bool,
) -> tuple[BeatLayoutIntent, ...]:
    if not isinstance(parent_intents, Sequence) or isinstance(parent_intents, str):
        raise ValueError("parent beat_layout_intents must be a list")

    out: list[BeatLayoutIntent] = []
    for raw in parent_intents:
        if not isinstance(raw, Mapping):
            raise ValueError("parent beat_layout_intents entries must be objects")
        _reject_prepared_layout_commands(raw)
        parent_needs = tuple(str(need) for need in raw.get("needs") or ())
        if not parent_needs:
            raise ValueError("parent beat layout intent missing needs")
        projected = [
            _project_parent_need(need)
            for need in parent_needs
            if not (responsible and _need_token(need) in _PARENT_IGNORED_RESPONSIBLE_NEEDS)
        ]
        if not projected:
            continue

        action_kinds: list[ActionIntentKind] = []
        layout_needs: list[LayoutNeedKind] = []
        postures: list[LayoutPosture] = []
        expected_effects: list[ExpectedVisibleEffect] = []
        for action_kind, layout_need, posture, expected_effect in projected:
            action_kinds.append(action_kind)
            layout_needs.append(layout_need)
            postures.append(posture)
            expected_effects.append(expected_effect)

        parent_evidence_refs = _string_tuple(raw.get("evidence_refs") or raw.get("evidence_ref"))
        evidence_refs = _dedupe((f"prepared_artifact:{artifact_sha256}", *parent_evidence_refs))
        source_affordances = _dedupe(
            _string_tuple(raw.get("source_affordances") or raw.get("source_affordance"))
            or (f"prepared_artifact:{artifact_sha256}",)
        )
        beat_index = raw.get("beat_index")
        if beat_index is None:
            parent_beat_index = None
        elif isinstance(beat_index, int) and not isinstance(beat_index, bool) and beat_index >= 0:
            parent_beat_index = beat_index
        else:
            raise ValueError("parent beat layout intent beat_index must be a non-negative integer")
        beat_id = _optional_str(raw.get("beat_id"))
        if beat_id is None and parent_beat_index is None:
            raise ValueError("parent beat layout intent requires beat_id or beat_index")
        if beat_id is None:
            beat_id = f"beat-{parent_beat_index + 1}"

        out.append(
            BeatLayoutIntent(
                beat_id=beat_id,
                parent_beat_index=parent_beat_index,
                action_intent_kinds=tuple(_dedupe(action_kinds)),
                needs=tuple(_dedupe(layout_needs)),
                proposed_postures=tuple(_dedupe(postures)),
                expected_effects=tuple(_dedupe(expected_effects)),
                evidence_refs=evidence_refs,
                source_affordances=source_affordances,
                default_static_success_allowed=bool(
                    raw.get("default_static_success_allowed", False)
                ),
            )
        )
    return tuple(out)


def _project_parent_need(
    need: str,
) -> tuple[ActionIntentKind, LayoutNeedKind, LayoutPosture, ExpectedVisibleEffect]:
    token = _need_token(need)
    if token in {"evidencevisible", "evidence", "assetfront", "visualevidence"}:
        return (
            ActionIntentKind.SHOW_EVIDENCE,
            LayoutNeedKind.EVIDENCE_VISIBLE,
            LayoutPosture.ASSET_FRONT,
            ExpectedVisibleEffect.EVIDENCE_ON_SCREEN,
        )
    if token in {"sourcevisible", "citesource", "sourcecontext"}:
        return (
            ActionIntentKind.CITE_SOURCE,
            LayoutNeedKind.SOURCE_VISIBLE,
            LayoutPosture.ASSET_FRONT,
            ExpectedVisibleEffect.SOURCE_CONTEXT_LEGIBLE,
        )
    if token in {"actionvisible", "action", "demonstrateaction"}:
        return (
            ActionIntentKind.DEMONSTRATE_ACTION,
            LayoutNeedKind.ACTION_VISIBLE,
            LayoutPosture.SEGMENT_PRIMARY,
            ExpectedVisibleEffect.ACTION_ON_SCREEN,
        )
    if token in {"comparison", "comparisonvisible", "compare", "tiervisual", "rankedvisual"}:
        return (
            ActionIntentKind.COMPARE_REFERENTS,
            LayoutNeedKind.COMPARISON_VISIBLE,
            LayoutPosture.RANKED_VISUAL
            if token in {"tiervisual", "rankedvisual"}
            else LayoutPosture.COMPARISON,
            ExpectedVisibleEffect.COMPARISON_LEGIBLE,
        )
    if token in {"chatprompt", "chat"}:
        return (
            ActionIntentKind.SHOW_EVIDENCE,
            LayoutNeedKind.REFERENT_VISIBLE,
            LayoutPosture.CHAT_PROMPT,
            ExpectedVisibleEffect.REFERENT_AVAILABLE,
        )
    if token in {"countdownvisual", "countdown"}:
        return (
            ActionIntentKind.COMPARE_REFERENTS,
            LayoutNeedKind.COMPARISON_VISIBLE,
            LayoutPosture.COUNTDOWN_VISUAL,
            ExpectedVisibleEffect.COMPARISON_LEGIBLE,
        )
    if token in {"depthvisual", "readabilityheld", "readdetail"}:
        return (
            ActionIntentKind.READ_DETAIL,
            LayoutNeedKind.READABILITY_HELD,
            LayoutPosture.DEPTH_VISUAL,
            ExpectedVisibleEffect.DETAIL_READABLE,
        )
    if token in {"referentvisible", "camerasubject"}:
        return (
            ActionIntentKind.SHOW_EVIDENCE,
            LayoutNeedKind.REFERENT_VISIBLE,
            LayoutPosture.CAMERA_SUBJECT,
            ExpectedVisibleEffect.REFERENT_AVAILABLE,
        )
    if token in _PARENT_IGNORED_RESPONSIBLE_NEEDS:
        return (
            ActionIntentKind.NARRATE,
            LayoutNeedKind.REFERENT_VISIBLE,
            LayoutPosture.SPOKEN_ONLY_FALLBACK,
            ExpectedVisibleEffect.REFERENT_AVAILABLE,
        )
    raise ValueError(f"unsupported parent layout need {need!r}")


def validate_prepared_segment_artifact(
    artifact: Mapping[str, Any],
    *,
    artifact_path: str | None = None,
    artifact_sha256: str | None = None,
    parent_programme_id: str | None = None,
    parent_show_id: str | None = None,
    parent_condition_id: str | None = None,
) -> PreparedSegmentLayoutContract:
    """Validate a saved prepared segment artifact before load/index/playback.

    The prepared script is prior content. It is not unchecked runtime authority,
    and any executable layout cue is rejected for responsible hosting.
    """

    if not artifact.get("prepared_script"):
        raise ValueError("prepared segment artifact missing prepared_script")
    _reject_prepared_layout_commands(artifact)
    programme_id = parent_programme_id or _optional_str(artifact.get("programme_id"))
    if programme_id and _optional_str(artifact.get("segment_id")) not in {None, programme_id}:
        raise ValueError("prepared segment artifact segment_id does not match programme_id")
    sha = _normalize_bare_sha256(
        artifact_sha256
        or _optional_str(artifact.get("artifact_sha256"))
        or _optional_str(artifact.get("prepared_artifact_sha256"))
    )
    contract = project_parent_prepared_artifact_layout_contract(
        artifact,
        artifact_sha256=sha,
        parent_programme_id=programme_id,
        parent_show_id=parent_show_id,
        parent_condition_id=parent_condition_id,
    )
    if contract.hosting_context.mode is HostingMode.RESPONSIBLE_HOSTING and artifact.get(
        "segment_cues"
    ):
        raise ValueError(
            "responsible_hosting prepared artifact cannot carry executable segment_cues"
        )
    return contract


def programme_content_has_responsible_layout_contract(content: Any) -> bool:
    """Return whether a ProgrammeContent-like object declares responsible hosting."""

    hosting_context = getattr(content, "hosting_context", None)
    if isinstance(hosting_context, Mapping):
        mode = hosting_context.get("mode") or hosting_context.get("hosting_context")
        return _hosting_context_token(str(mode or "")) in {
            _hosting_context_token(HostingMode.RESPONSIBLE_HOSTING.value),
            *(_hosting_context_token(v) for v in _RESPONSIBLE_HOSTING_CONTEXT_STRINGS),
        }
    if isinstance(hosting_context, str):
        return _hosting_context_token(hosting_context) in {
            _hosting_context_token(HostingMode.RESPONSIBLE_HOSTING.value),
            *(_hosting_context_token(v) for v in _RESPONSIBLE_HOSTING_CONTEXT_STRINGS),
        }
    return bool(getattr(content, "beat_layout_intents", None))


def current_beat_layout_proposal(
    content: Any,
    beat_index: int,
) -> dict[str, Any] | None:
    """Return one proposal-only current beat layout metadata entry."""

    proposals = current_beat_layout_proposals(content, beat_index)
    if len(proposals) != 1:
        return None
    return proposals[0]


def current_beat_layout_proposals(
    content: Any,
    beat_index: int,
) -> tuple[dict[str, Any], ...]:
    """Return proposal-only current beat layout metadata for active-segment state.

    Parent declarations are keyed by beat id/index, not trusted by list
    position. Ambiguous or unkeyed rows fail closed by returning no proposal.
    """

    intents = list(getattr(content, "beat_layout_intents", []) or [])
    if beat_index < 0 or not intents:
        return ()
    beat_ids = _current_beat_id_candidates(content, beat_index)
    matches: list[dict[str, Any]] = []
    for intent in intents:
        projected = _layout_intent_to_dict(intent)
        if projected is None:
            return ()
        parent_index = projected.get("parent_beat_index")
        beat_index_value = projected.get("beat_index")
        index_values = {
            value
            for value in (parent_index, beat_index_value)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        }
        if (parent_index is not None or beat_index_value is not None) and not index_values:
            return ()
        if len(index_values) > 1:
            return ()
        parent_beat_index = next(iter(index_values), None)
        beat_id = _optional_str(projected.get("beat_id"))
        if parent_beat_index is None and beat_id is None:
            return ()
        if parent_beat_index == beat_index or (beat_id is not None and beat_id in beat_ids):
            matches.append(projected)
    if not matches:
        return ()
    return tuple(matches)


def _current_beat_id_candidates(content: Any, beat_index: int) -> set[str]:
    candidates = {
        str(beat_index),
        str(beat_index + 1),
        f"beat-{beat_index}",
        f"beat-{beat_index + 1}",
    }
    beats = list(getattr(content, "segment_beats", []) or [])
    if 0 <= beat_index < len(beats):
        beat_text = str(beats[beat_index]).strip()
        if beat_text:
            candidates.add(beat_text)
            prefix = beat_text.split(":", 1)[0].strip()
            if prefix:
                candidates.add(prefix)
    return candidates


def _layout_intent_to_dict(intent: Any) -> dict[str, Any] | None:
    if isinstance(intent, BaseModel):
        return intent.model_dump(mode="json")
    if isinstance(intent, Mapping):
        _reject_prepared_layout_commands(intent)
        return dict(intent)
    return None


def _reject_prepared_layout_commands(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            if _key_token(key_text) in _FORBIDDEN_PREPARED_LAYOUT_KEY_TOKENS:
                raise ValueError(f"prepared artifact layout metadata cannot set {path}.{key_text}")
            _reject_prepared_layout_commands(nested, path=f"{path}.{key_text}")
        return
    if isinstance(value, str):
        if _contains_forbidden_command_text(value):
            raise ValueError(
                f"prepared artifact layout metadata cannot carry executable cue {value!r}"
            )
        if _is_forbidden_prepared_layout_value(value):
            raise ValueError(
                f"prepared artifact layout metadata cannot name concrete layout {value!r}"
            )
        return
    if isinstance(value, list | tuple):
        for index, nested in enumerate(value):
            _reject_prepared_layout_commands(nested, path=f"{path}[{index}]")


def _layout_token(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"^[a-z]+:", "", text)
    text = re.split(r"[?#]", text, maxsplit=1)[0]
    text = text.replace("\\", "/").rstrip("/")
    basename = text.rsplit("/", 1)[-1]
    if basename.endswith(".json"):
        basename = basename[:-5]
    token = re.sub(r"[^a-z0-9]+", "-", basename).strip("-")
    for prefix in ("default", "balanced", "static", "garage-door", "consent-safe"):
        if token == prefix or token.startswith(f"{prefix}-"):
            return prefix
    return token


def _is_static_default_layout(value: str) -> bool:
    return _layout_token(value) in {_layout_token(item) for item in STATIC_DEFAULT_LAYOUTS}


def _is_forbidden_prepared_layout_value(value: str) -> bool:
    token = _layout_token(value)
    forbidden = {_layout_token(item) for item in _FORBIDDEN_PREPARED_LAYOUT_VALUES}
    return token in forbidden or _is_static_default_layout(value)


def _contains_forbidden_command_text(value: str) -> bool:
    return bool(
        _FORBIDDEN_PREPARED_COMMAND_RE.search(value)
        or "/dev/shm" in value
        or "compositor.surface." in value.lower()
    )


def _key_token(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", key.lower())


def _hosting_context_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _need_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _is_sha256(value: str) -> bool:
    return bool(_SHA256_RE.match(value))


def _is_bare_sha256(value: str) -> bool:
    return bool(_HEX_SHA256_RE.match(value))


def _normalize_bare_sha256(value: str | None) -> str:
    if value is None:
        raise ValueError("prepared artifact projection requires artifact_sha256")
    stripped = value.strip().lower()
    if stripped.startswith("sha256:"):
        stripped = stripped.removeprefix("sha256:")
    if not _is_bare_sha256(stripped):
        raise ValueError("prepared artifact projection requires 64 lowercase hex artifact_sha256")
    return stripped


def _contract_beat(
    contract: PreparedSegmentLayoutContract,
    beat_id: str | None,
) -> BeatLayoutIntent | None:
    if beat_id is None:
        return None
    for beat in contract.beat_layout_intents:
        if beat.beat_id == beat_id:
            return beat
    return None


def _validate_receipt_matches_decision(
    decision: RuntimeLayoutDecision,
    receipt: RuntimeLayoutReceipt,
) -> None:
    if receipt.decision_id != decision.decision_id:
        raise ValueError("layout receipt decision_id does not match decision")
    if receipt.segment_id != decision.segment_id:
        raise ValueError("layout receipt segment_id does not match decision")
    if receipt.beat_id != decision.beat_id:
        raise ValueError("layout receipt beat_id does not match decision")
    if receipt.posture is not decision.posture:
        raise ValueError("layout receipt posture does not match decision")


def _validate_typed_readbacks(
    contract: PreparedSegmentLayoutContract,
    receipt: RuntimeLayoutReceipt,
) -> None:
    if not receipt.wcs_readback_refs:
        raise ValueError("responsible_hosting receipt requires typed readback refs")
    observed_kinds = {ref.kind for ref in receipt.wcs_readback_refs if ref.verified}
    required = set(contract.runtime_layout_validation.readback_kinds_required)
    missing = required - observed_kinds
    if missing:
        names = ", ".join(sorted(kind.value for kind in missing))
        raise ValueError(f"responsible_hosting receipt missing typed readback refs: {names}")


def _reject_parent_metadata_overrides(metadata: Mapping[str, Any], *, path: str = "$") -> None:
    for key, value in metadata.items():
        key_text = str(key)
        if _key_token(key_text) in _PARENT_OVERRIDE_KEYS:
            raise ValueError(
                f"embedding metadata cannot override layout contract field {path}.{key_text}"
            )
        if isinstance(value, Mapping):
            _reject_parent_metadata_overrides(value, path=f"{path}.{key_text}")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, Sequence):
        out = tuple(str(item).strip() for item in value if str(item).strip())
        return out
    text = str(value).strip()
    return (text,) if text else ()


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


__all__ = [
    "DEFAULT_CONFLICT_ORDER",
    "DEFAULT_DECISION_VOCABULARY",
    "DEFAULT_POSTURE_VOCABULARY",
    "DOCTRINE_NAME",
    "DOCTRINE_SUMMARY",
    "LAYOUT_RESPONSIBILITY_VERSION",
    "PARENT_PREPARED_ARTIFACT_AUTHORITY",
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
    "PreparedRuntimeLayoutValidation",
    "PreparedSegmentLayoutContract",
    "PublicPrivateMode",
    "RuntimeReadbackKind",
    "RuntimeReadbackRef",
    "RuntimeLayoutDecision",
    "RuntimeLayoutReceipt",
    "SegmentActionIntent",
    "beat_layout_intents_from_action_intents",
    "current_beat_layout_proposal",
    "current_beat_layout_proposals",
    "prepared_artifact_layout_metadata",
    "programme_content_has_responsible_layout_contract",
    "project_parent_prepared_artifact_layout_contract",
    "validate_prepared_artifact_layout_metadata",
    "validate_prepared_segment_artifact",
    "validate_runtime_layout_decision",
    "validate_runtime_layout_receipt",
]
