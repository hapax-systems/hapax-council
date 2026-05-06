"""Deterministic evaluator for segment quality/action/layout fixtures.

The evaluator is intentionally local and side-effect free. It validates
fixture objects that say, "this segment claims an action, these layout
needs follow, and these receipts prove what was visible." Prepared
artifacts may declare needs and intents; they never command layout or
claim public/broadcast authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class BeatRole(StrEnum):
    HOOK = "hook"
    CONTEXT = "context"
    EVIDENCE = "evidence"
    TURN = "turn"
    ACTION = "action"
    CLOSE = "close"


class HostingMode(StrEnum):
    RESPONSIBLE_HOSTING = "responsible_hosting"
    NON_RESPONSIBLE = "non_responsible"
    BOOT_SAFETY_FALLBACK = "boot_safety_fallback"


class LayoutMode(StrEnum):
    DEFAULT_STATIC = "default_static"
    DYNAMIC_RESPONSIBLE = "dynamic_responsible"
    EXPLICIT_FALLBACK = "explicit_fallback"


class LayoutAuthority(StrEnum):
    CANONICAL_BROADCAST_RUNTIME = "canonical_broadcast_runtime"
    PREPARED_ARTIFACT = "prepared_artifact"
    TEST_FIXTURE = "test_fixture"


class ArtifactAuthority(StrEnum):
    PREP_METADATA_ONLY = "prep_metadata_only"
    PUBLIC_BROADCAST = "public_broadcast"
    LAYOUT_COMMAND = "layout_command"


class LayoutNeedKind(StrEnum):
    SEGMENT_FOCUS = "segment_focus"
    RANKING_FOCUS = "ranking_focus"
    COMPARISON_SPLIT = "comparison_split"
    CHAT_PROMPT = "chat_prompt"
    CAMERA_TARGET = "camera_target"
    CONSENT_SAFE = "consent_safe"
    SPEECH_ONLY_FALLBACK = "speech_only_fallback"
    NON_RESPONSIBLE_STATIC = "non_responsible_static"


class LayoutReceiptSource(StrEnum):
    LAYOUT_STATE = "layout_state"
    WARD_READBACK = "ward_readback"
    RENDERED_FRAME = "rendered_frame"
    LAYOUT_STORE = "layout_store"
    GAUGE = "gauge"
    ADVISORY_STORE = "advisory_store"
    FALLBACK_RECEIPT = "fallback_receipt"


_RENDERED_RECEIPT_SOURCES = {
    LayoutReceiptSource.LAYOUT_STATE,
    LayoutReceiptSource.WARD_READBACK,
    LayoutReceiptSource.RENDERED_FRAME,
}


_BOUNDED_LAYOUT_VOCABULARY = frozenset(LayoutNeedKind)


class EvidenceRef(BaseModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class HostingContext(BaseModel):
    mode: HostingMode = HostingMode.RESPONSIBLE_HOSTING
    hapax_controls_layout: bool = True
    responsible_for_content_quality: bool = True
    static_layout_success_allowed: bool = False
    explicit_static_reason: str | None = None


class ScriptBeat(BaseModel):
    beat_id: str = Field(min_length=1)
    role: BeatRole
    text: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    callback_refs: list[str] = Field(default_factory=list)
    action_intent_refs: list[str] = Field(default_factory=list)


class SegmentScript(BaseModel):
    premise: str = Field(min_length=1)
    tension: str = Field(min_length=1)
    beats: list[ScriptBeat] = Field(min_length=1)


class SegmentActionIntent(BaseModel):
    id: str = Field(min_length=1)
    spoken_claim: str = Field(min_length=1)
    operator_visible_effect: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    required_layout_needs: list[str] = Field(default_factory=list)


class SegmentLayoutNeed(BaseModel):
    id: str = Field(min_length=1)
    kind: LayoutNeedKind
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    action_intent_refs: list[str] = Field(default_factory=list)


class BeatLayoutIntent(BaseModel):
    beat_id: str = Field(min_length=1)
    layout_needs: list[str] = Field(default_factory=list)
    expected_effects: list[str] = Field(default_factory=list)
    default_static_success_allowed: bool = False


class LayoutDecisionContract(BaseModel):
    bounded_vocabulary: list[LayoutNeedKind] = Field(
        default_factory=lambda: list(_BOUNDED_LAYOUT_VOCABULARY)
    )


class LayoutReceipt(BaseModel):
    id: str = Field(min_length=1)
    source: LayoutReceiptSource
    need_ids: list[str] = Field(default_factory=list)
    visible_effects: list[str] = Field(default_factory=list)
    rendered: bool = False
    ttl_s: float | None = None
    reason: str = ""


class LayoutDecision(BaseModel):
    mode: LayoutMode
    need_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    receipt_refs: list[str] = Field(default_factory=list)
    authority: LayoutAuthority = LayoutAuthority.CANONICAL_BROADCAST_RUNTIME
    ttl_s: float | None = None
    min_dwell_s: float | None = None


class PreparedArtifactPolicy(BaseModel):
    model_id: str = "command-r-08-2024-exl3-5.0bpw"
    prior_only: bool = True
    authority: ArtifactAuthority = ArtifactAuthority.PREP_METADATA_ONLY
    provenance_refs: list[str] = Field(default_factory=list)
    direct_layout_commands: list[str] = Field(default_factory=list)
    public_broadcast_bypass: bool = False


class SegmentQualityLayoutFixture(BaseModel):
    fixture_id: str = Field(min_length=1)
    format: str = Field(min_length=1)
    expected_pass: bool
    layout_responsibility_version: int = Field(default=1)
    hosting_context: HostingContext = Field(default_factory=HostingContext)
    topic_anchors: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    script: SegmentScript
    action_intents: list[SegmentActionIntent] = Field(default_factory=list)
    layout_needs: list[SegmentLayoutNeed] = Field(default_factory=list)
    beat_layout_intents: list[BeatLayoutIntent] = Field(default_factory=list)
    layout_decision_contract: LayoutDecisionContract = Field(default_factory=LayoutDecisionContract)
    layout_decision: LayoutDecision
    layout_receipts: list[LayoutReceipt] = Field(default_factory=list)
    prepared_artifact: PreparedArtifactPolicy = Field(default_factory=PreparedArtifactPolicy)


class SegmentQualityLayoutFailure(BaseModel):
    code: str
    message: str


class SegmentQualityLayoutReport(BaseModel):
    fixture_id: str
    passed: bool
    failures: list[SegmentQualityLayoutFailure]


_REQUIRED_ARC_ROLES = {
    BeatRole.HOOK,
    BeatRole.EVIDENCE,
    BeatRole.TURN,
    BeatRole.ACTION,
    BeatRole.CLOSE,
}


def evaluate_segment_quality_layout_fixture(
    fixture: SegmentQualityLayoutFixture | Mapping[str, Any],
) -> SegmentQualityLayoutReport:
    """Evaluate one fixture without model calls or runtime side effects."""

    f = (
        fixture
        if isinstance(fixture, SegmentQualityLayoutFixture)
        else SegmentQualityLayoutFixture.model_validate(fixture)
    )
    failures: list[SegmentQualityLayoutFailure] = []

    def add(code: str, message: str) -> None:
        failures.append(SegmentQualityLayoutFailure(code=code, message=message))

    _check_responsibility_header(f, add)
    _check_script_quality(f, add)
    _check_evidence_references(f, add)
    _check_action_alignment(f, add)
    _check_layout_alignment(f, add)
    _check_layout_receipts(f, add)
    _check_prepared_artifact_policy(f, add)

    return SegmentQualityLayoutReport(
        fixture_id=f.fixture_id,
        passed=not failures,
        failures=failures,
    )


def _check_responsibility_header(f: SegmentQualityLayoutFixture, add: Any) -> None:
    if f.layout_responsibility_version != 1:
        add("responsibility.version", "layout_responsibility_version must be 1")

    ctx = f.hosting_context
    if ctx.mode is HostingMode.RESPONSIBLE_HOSTING:
        if not ctx.hapax_controls_layout:
            add("responsibility.no_layout_control", "responsible hosting requires layout control")
        if not ctx.responsible_for_content_quality:
            add(
                "responsibility.not_content_responsible",
                "responsible hosting requires content-quality responsibility",
            )
        if ctx.static_layout_success_allowed:
            add(
                "responsibility.static_success_allowed",
                "responsible hosting must not allow static layout as success",
            )

    if (
        ctx.mode is HostingMode.NON_RESPONSIBLE
        and f.layout_decision.mode is LayoutMode.DEFAULT_STATIC
    ):
        if not ctx.static_layout_success_allowed or not (ctx.explicit_static_reason or "").strip():
            add(
                "layout.non_responsible_static_without_reason",
                "non-responsible static layout requires an explicit reason",
            )


def _check_script_quality(f: SegmentQualityLayoutFixture, add: Any) -> None:
    roles = {beat.role for beat in f.script.beats}
    missing_roles = sorted(role.value for role in _REQUIRED_ARC_ROLES - roles)
    if missing_roles:
        add("script.missing_arc_roles", f"missing required arc roles: {missing_roles}")

    all_text = " ".join(
        [f.script.premise, f.script.tension, *(beat.text for beat in f.script.beats)]
    )
    anchor_hits = [anchor for anchor in f.topic_anchors if anchor.lower() in all_text.lower()]
    if len(f.topic_anchors) < 3 or len(anchor_hits) < 3:
        add(
            "script.generic_prose",
            "script lacks enough topic anchors to distinguish it from generic prose",
        )

    callback_count = sum(len(beat.callback_refs) for beat in f.script.beats)
    if callback_count < 2:
        add("script.missing_callbacks", "excellent segment fixtures need at least two callbacks")

    if len(f.script.beats) < 5:
        add("script.pacing_thin", "excellent segment fixtures need at least five beats")

    short_roles = [
        beat.role.value
        for beat in f.script.beats
        if beat.role is not BeatRole.CLOSE and len(beat.text.strip()) < 80
    ]
    if short_roles:
        add("script.pacing_thin", f"thin beat prose in roles: {short_roles}")

    if not f.evidence_refs:
        add("source.missing_evidence_refs", "fixture declares no evidence refs")


def _check_evidence_references(f: SegmentQualityLayoutFixture, add: Any) -> None:
    known = {ref.id for ref in f.evidence_refs}
    used: set[str] = set()
    used.update(ref for beat in f.script.beats for ref in beat.evidence_refs)
    used.update(ref for action in f.action_intents for ref in action.evidence_refs)
    used.update(ref for need in f.layout_needs for ref in need.evidence_refs)
    used.update(f.prepared_artifact.provenance_refs)

    unknown = sorted(used - known)
    if unknown:
        add("source.unknown_evidence_ref", f"unknown evidence refs: {unknown}")

    for beat in f.script.beats:
        if beat.role in {BeatRole.EVIDENCE, BeatRole.ACTION} and not beat.evidence_refs:
            add(
                "source.beat_without_evidence",
                f"{beat.role.value} beat has no evidence refs",
            )


def _check_action_alignment(f: SegmentQualityLayoutFixture, add: Any) -> None:
    action_ids = {action.id for action in f.action_intents}
    scripted_action_ids = {
        action_id for beat in f.script.beats for action_id in beat.action_intent_refs
    }

    if not f.action_intents:
        add("action.missing_intent", "fixture declares no action intents")

    for unknown in sorted(scripted_action_ids - action_ids):
        add("action.unknown_intent_ref", f"script references unknown action intent {unknown!r}")

    for action in f.action_intents:
        if action.id not in scripted_action_ids:
            add("action.intent_not_scripted", f"action intent {action.id!r} is not scripted")
        if not action.evidence_refs:
            add(
                "action.unsupported_claim",
                f"action intent {action.id!r} has no evidence refs",
            )
        if not action.required_layout_needs:
            add(
                "action.missing_layout_need",
                f"action intent {action.id!r} declares no required layout needs",
            )


def _check_layout_alignment(f: SegmentQualityLayoutFixture, add: Any) -> None:
    need_ids = {need.id for need in f.layout_needs}
    decision_need_ids = set(f.layout_decision.need_ids)
    contract_vocab = set(f.layout_decision_contract.bounded_vocabulary)
    beat_ids = {beat.beat_id for beat in f.script.beats}
    beat_intent_need_ids = {
        need_id for intent in f.beat_layout_intents for need_id in intent.layout_needs
    }

    for need in f.layout_needs:
        if need.kind not in _BOUNDED_LAYOUT_VOCABULARY or need.kind not in contract_vocab:
            add("layout.unbounded_vocabulary", f"layout need {need.id!r} uses {need.kind!r}")

    for intent in f.beat_layout_intents:
        if intent.beat_id not in beat_ids:
            add("layout.unknown_beat_intent", f"unknown beat id {intent.beat_id!r}")
        if f.hosting_context.mode is HostingMode.RESPONSIBLE_HOSTING:
            if intent.default_static_success_allowed:
                add(
                    "layout.beat_static_success_allowed",
                    f"beat {intent.beat_id!r} allows default/static success",
                )
        if not intent.layout_needs:
            add("layout.beat_without_need", f"beat {intent.beat_id!r} declares no layout needs")
        if not intent.expected_effects:
            add(
                "layout.beat_without_expected_effect",
                f"beat {intent.beat_id!r} declares no expected effects",
            )

    for unknown in sorted(beat_intent_need_ids - need_ids):
        add("layout.unknown_need_ref", f"beat intent references unknown need {unknown!r}")

    for unknown in sorted(decision_need_ids - need_ids):
        add("layout.unknown_decision_need", f"decision references unknown need {unknown!r}")

    for action in f.action_intents:
        for need_id in action.required_layout_needs:
            if need_id not in need_ids:
                add(
                    "action.unknown_layout_need",
                    f"action {action.id!r} requires unknown layout need {need_id!r}",
                )
            elif need_id not in beat_intent_need_ids:
                add(
                    "layout.action_need_without_beat_intent",
                    f"action {action.id!r} need {need_id!r} is not built by beat intents",
                )
            elif need_id not in decision_need_ids:
                add(
                    "layout.action_need_not_decided",
                    f"action {action.id!r} requires layout need {need_id!r} not in decision",
                )

    if f.hosting_context.mode is HostingMode.RESPONSIBLE_HOSTING:
        if f.layout_decision.mode is LayoutMode.DEFAULT_STATIC:
            add(
                "layout.default_static_responsible",
                "responsible hosting cannot pass with default/static layout",
            )
        if f.layout_decision.authority is not LayoutAuthority.CANONICAL_BROADCAST_RUNTIME:
            add(
                "layout.noncanonical_authority",
                "responsible layout decisions must use canonical runtime authority",
            )

    if f.layout_decision.mode is LayoutMode.EXPLICIT_FALLBACK:
        add("layout.explicit_fallback_not_success", "explicit fallback is not success")
        if not f.layout_decision.reason.strip():
            add("layout.fallback_missing_reason", "explicit fallback requires a reason")
        if not f.layout_decision.receipt_refs:
            add("layout.fallback_missing_receipt", "explicit fallback requires a receipt")
        if f.layout_decision.ttl_s is None or f.layout_decision.ttl_s <= 0:
            add("layout.fallback_missing_ttl", "explicit fallback requires a positive TTL")

    if f.layout_decision.mode is LayoutMode.DYNAMIC_RESPONSIBLE:
        if not f.layout_decision.reason.strip():
            add("layout.missing_reason", "responsible layout decision needs a reason")
        if f.layout_decision.ttl_s is None or f.layout_decision.ttl_s <= 0:
            add("layout.missing_ttl", "responsible layout decision needs a positive TTL")
        if f.layout_decision.min_dwell_s is None or f.layout_decision.min_dwell_s <= 0:
            add("layout.missing_dwell", "responsible layout decision needs positive dwell")
        if (
            f.layout_decision.ttl_s is not None
            and f.layout_decision.min_dwell_s is not None
            and f.layout_decision.ttl_s < f.layout_decision.min_dwell_s
        ):
            add("layout.ttl_dwell_thrash", "layout TTL must not be shorter than min dwell")


def _check_layout_receipts(f: SegmentQualityLayoutFixture, add: Any) -> None:
    receipts = {receipt.id: receipt for receipt in f.layout_receipts}
    selected = [receipts[ref] for ref in f.layout_decision.receipt_refs if ref in receipts]
    missing = sorted(set(f.layout_decision.receipt_refs) - receipts.keys())
    if missing:
        add("layout.missing_receipt", f"missing layout receipts: {missing}")

    if f.layout_decision.mode is LayoutMode.DEFAULT_STATIC:
        if f.hosting_context.mode is HostingMode.NON_RESPONSIBLE:
            return
        if not f.layout_decision.receipt_refs:
            add("layout.default_static_missing_receipt", "default/static needs an explicit receipt")
        return

    if f.layout_decision.mode is LayoutMode.EXPLICIT_FALLBACK:
        fallback_receipts = [
            r for r in selected if r.source is LayoutReceiptSource.FALLBACK_RECEIPT
        ]
        if not fallback_receipts:
            add("layout.fallback_missing_receipt", "fallback needs a fallback receipt")
        for receipt in fallback_receipts:
            if receipt.ttl_s is None or receipt.ttl_s <= 0:
                add("layout.fallback_missing_ttl", "fallback receipt needs a positive TTL")
            if not receipt.reason.strip():
                add("layout.fallback_missing_reason", "fallback receipt needs a reason")
        return

    rendered_receipts = [
        receipt
        for receipt in selected
        if receipt.source in _RENDERED_RECEIPT_SOURCES and receipt.rendered
    ]
    if not rendered_receipts:
        add(
            "layout.rendered_state_missing",
            "store/gauge/advisory success is not enough without rendered LayoutState/ward readback",
        )

    expected_effects = _expected_effects_for_decision(f)
    rendered_effects = {
        effect for receipt in rendered_receipts for effect in receipt.visible_effects
    }
    missing_effects = sorted(expected_effects - rendered_effects)
    if missing_effects:
        add(
            "layout.visible_effect_missing", f"rendered receipts missing effects: {missing_effects}"
        )

    rendered_need_ids = {need_id for receipt in rendered_receipts for need_id in receipt.need_ids}
    missing_need_receipts = sorted(set(f.layout_decision.need_ids) - rendered_need_ids)
    if missing_need_receipts:
        add(
            "layout.rendered_need_missing",
            f"rendered receipts do not confirm needs: {missing_need_receipts}",
        )


def _expected_effects_for_decision(f: SegmentQualityLayoutFixture) -> set[str]:
    decision_need_ids = set(f.layout_decision.need_ids)
    effects: set[str] = set()
    for intent in f.beat_layout_intents:
        if decision_need_ids.intersection(intent.layout_needs):
            effects.update(intent.expected_effects)
    return effects


def _check_prepared_artifact_policy(f: SegmentQualityLayoutFixture, add: Any) -> None:
    artifact = f.prepared_artifact
    if not artifact.model_id.lower().startswith("command-r"):
        add("artifact.non_command_r_model", "prepared fixture must use Command-R-only prep")
    if not artifact.prior_only:
        add("artifact.not_prior_only", "prepared fixture must be prior-only")
    if artifact.authority is not ArtifactAuthority.PREP_METADATA_ONLY:
        add("artifact.authority_bypass", "prepared artifacts may only carry metadata")
    if artifact.direct_layout_commands:
        add("artifact.direct_layout_command", "prepared artifact contains direct layout commands")
    if artifact.public_broadcast_bypass:
        add("artifact.public_broadcast_bypass", "prepared artifact claims public/broadcast bypass")
