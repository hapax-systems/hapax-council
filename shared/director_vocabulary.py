"""Director runtime vocabulary builder.

The director should speak and act from mounted evidence, not from a
prompt-side list of imagined capabilities. This module builds a compact
vocabulary envelope from typed substrate rows, spectacle lanes, live wards,
cameras, private controls, programme state, and claim bindings. It does not
execute moves; it exposes the terms, low-level verbs, format-level grounding
actions, and unavailable reasons that later director/control-move layers can
consume.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.cameras import CAMERAS, CameraSpec
from shared.programme import Programme

DirectorVerb = Literal[
    "foreground",
    "background",
    "hold",
    "suppress",
    "transition",
    "crossfade",
    "intensify",
    "stabilize",
    "route_attention",
    "mark_boundary",
]

EvidenceStatus = Literal["fresh", "stale", "missing", "unknown", "not_applicable"]
FallbackMode = Literal[
    "no_op",
    "dry_run",
    "fallback",
    "operator_reason",
    "hold_last_safe",
    "suppress",
    "private_only",
    "degraded_status",
    "kill_switch",
]
TargetType = Literal[
    "substrate",
    "spectacle_lane",
    "ward",
    "camera",
    "re_splay_device",
    "private_control",
    "cuepoint",
    "claim_binding",
    "programme",
    "egress_status",
]
GeneratedFrom = Literal[
    "content_substrate",
    "spectacle_lane",
    "ward_registry",
    "camera_status",
    "re_splay_probe",
    "private_control",
    "cuepoint_event",
    "claim_binding",
    "programme_store",
    "egress_state",
]
FormatGroundingAction = Literal[
    "classify",
    "rank",
    "compare",
    "review",
    "explain",
    "refuse",
    "audit_claim",
    "mark_failure",
    "evaluate_format",
]

STABLE_DIRECTOR_VERBS: tuple[DirectorVerb, ...] = (
    "foreground",
    "background",
    "hold",
    "suppress",
    "transition",
    "crossfade",
    "intensify",
    "stabilize",
    "route_attention",
    "mark_boundary",
)
_STABLE_VERB_SET = set(STABLE_DIRECTOR_VERBS)
_COMMANDABLE_LANE_STATES = {"dry-run", "private", "mounted", "degraded", "public-live"}
_COMMANDABLE_SUBSTRATE_STATUSES = {"dry-run", "private", "public-live", "archive-only", "degraded"}
_PUBLIC_SAFE_RIGHTS = {"operator_original", "operator_controlled", "third_party_attributed"}
_PUBLIC_SAFE_PRIVACY = {"public_safe", "aggregate_only"}


class Endpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str
    state: str
    evidence: str


class ContentSubstrateFallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal[
        "hide",
        "hold_last_safe",
        "dry_run_badge",
        "private_only",
        "archive_only",
        "operator_prompt",
        "kill",
    ]
    reason: str


class KillSwitchBehavior(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: str
    action: str
    operator_recovery: str


class PublicClaimPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_live: bool
    claim_archive: bool
    claim_monetizable: bool
    requires_egress_public_claim: bool
    requires_audio_safe: bool
    requires_provenance: bool
    requires_operator_action: bool


class HealthSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str
    status_ref: str
    freshness_ref: str | None = None


class ContentSubstrate(BaseModel):
    """Typed row matching ``livestream-content-substrate.schema.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    substrate_id: str
    display_name: str
    substrate_type: str
    producer: Endpoint
    consumer: Endpoint
    freshness_ttl_s: int | None
    rights_class: str
    provenance_token: str | None
    privacy_class: str
    public_private_modes: list[str]
    render_target: str
    director_vocabulary: list[str] = Field(default_factory=list)
    director_affordances: list[str] = Field(default_factory=list)
    programme_bias_hooks: list[str] = Field(default_factory=list)
    objective_links: list[str] = Field(default_factory=list)
    public_claim_permissions: PublicClaimPermissions
    health_signal: HealthSignal
    fallback: ContentSubstrateFallback
    kill_switch_behavior: KillSwitchBehavior
    integration_status: str
    existing_task_anchors: list[str] = Field(default_factory=list)
    notes: str = ""


class RenderabilityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str
    status_ref: str
    freshness_ref: str | None = None
    evidence_kind: str


class SpectacleLaneFallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal[
        "no_op_explain",
        "dry_run_badge",
        "hold_last_safe",
        "suppress",
        "private_only",
        "degraded_status",
        "operator_prompt",
        "kill_switch",
    ]
    reason: str


class SpectacleLaneState(BaseModel):
    """Typed row matching ``spectacle-control-plane.schema.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    lane_id: str
    display_name: str
    lane_kind: str
    content_substrate_refs: list[str] = Field(default_factory=list)
    state: str
    mounted: bool
    renderable: bool
    renderability_evidence: RenderabilityEvidence
    claim_bearing: str
    rights_risk: str
    consent_risk: str
    monetization_risk: str
    director_verbs: list[str] = Field(default_factory=list)
    programme_hooks: list[str] = Field(default_factory=list)
    fallback: SpectacleLaneFallback
    public_claim_allowed: bool
    control_inputs: list[str] = Field(default_factory=list)
    child_task_anchors: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("director_verbs")
    @classmethod
    def _known_director_verbs(cls, value: list[str]) -> list[str]:
        unknown = sorted(
            _normalise_verb(v) for v in value if _normalise_verb(v) not in _STABLE_VERB_SET
        )
        if unknown:
            raise ValueError(f"unknown director verbs: {unknown}")
        return value


class DirectorRightsState(BaseModel):
    """Public-claim floor shared by substrate/lane/camera vocabulary."""

    model_config = ConfigDict(frozen=True)

    egress_public_claim_allowed: bool = False
    audio_safe: bool = False
    privacy_safe: bool = False
    rights_safe: bool = True
    monetization_safe: bool = False
    source_refs: list[str] = Field(default_factory=lambda: ["egress:livestream"])
    detail: str = "no live egress evidence supplied"

    @property
    def allows_public_claim(self) -> bool:
        return (
            self.egress_public_claim_allowed
            and self.audio_safe
            and self.privacy_safe
            and self.rights_safe
        )

    @classmethod
    def from_livestream_egress(cls, state: Any) -> DirectorRightsState:
        """Build a rights floor from ``shared.livestream_egress_state`` output."""

        privacy_floor = getattr(getattr(state, "privacy_floor", None), "value", None)
        audio_floor = getattr(getattr(state, "audio_floor", None), "value", None)
        return cls(
            egress_public_claim_allowed=bool(getattr(state, "public_claim_allowed", False)),
            audio_safe=audio_floor == "satisfied",
            privacy_safe=privacy_floor == "satisfied",
            rights_safe=True,
            monetization_safe=str(getattr(state, "monetization_risk", "")) in {"low", "none", ""},
            source_refs=["egress:livestream"],
            detail=str(getattr(state, "operator_action", "livestream egress evidence")),
        )


class PrivateControlBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_id: str
    display_name: str
    source_ref: str
    command: str | None = None
    available: bool = True
    reason: str = "private control is locally available"
    terms: list[str] = Field(default_factory=list)


class ProgrammeBoundarySignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    boundary_id: str
    display_name: str = "Programme boundary"
    programme_id: str | None = None
    condition_id: str | None = None
    observed_at: float | None = None
    fresh: bool = True
    source_ref: str = "cuepoint:programme_boundary"
    reason: str = "programme boundary evidence is available"


class DirectorVocabularyEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: str
    ref: str
    status: EvidenceStatus
    observed_at: str | None
    age_s: float | None
    ttl_s: float | None
    detail: str


class DirectorVocabularyEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_type: TargetType
    target_id: str
    display_name: str
    terms: list[str]
    verbs: list[DirectorVerb] = Field(default_factory=list)
    source_refs: list[str]
    generated_from: list[GeneratedFrom]
    evidence: list[DirectorVocabularyEvidence]
    public_claim_allowed: bool = False
    unavailable_reason: str | None = None
    fallback_mode: FallbackMode = "no_op"


class DirectorVocabulary(BaseModel):
    """Runtime envelope consumed by programme scheduling and content runners."""

    model_config = ConfigDict(frozen=True)

    generated_at: str
    stable_verbs: tuple[DirectorVerb, ...] = STABLE_DIRECTOR_VERBS
    programme_id: str | None = None
    condition_id: str = "none"
    format_actions: list[FormatGroundingAction] = Field(default_factory=list)
    entries: list[DirectorVocabularyEntry] = Field(default_factory=list)

    @property
    def unavailable_reasons(self) -> dict[str, str]:
        return {
            f"{entry.target_type}:{entry.target_id}": entry.unavailable_reason
            for entry in self.entries
            if entry.unavailable_reason
        }

    def all_terms(self) -> list[str]:
        terms: set[str] = set()
        for entry in self.entries:
            terms.update(entry.terms)
        return sorted(terms)

    def for_programme_scheduler(self) -> dict[str, Any]:
        """Compact view for programme scheduling/envelope construction."""

        return {
            "programme_id": self.programme_id,
            "condition_id": self.condition_id,
            "stable_verbs": list(self.stable_verbs),
            "format_actions": list(self.format_actions),
            "targets": [
                {
                    "target_type": entry.target_type,
                    "target_id": entry.target_id,
                    "terms": list(entry.terms),
                    "verbs": list(entry.verbs),
                    "public_claim_allowed": entry.public_claim_allowed,
                    "unavailable_reason": entry.unavailable_reason,
                }
                for entry in self.entries
            ],
        }

    def for_content_runner(self) -> dict[str, Any]:
        """Execution-facing view that keeps low-level verbs and format actions apart."""

        return {
            "terms": self.all_terms(),
            "verbs_by_target": {
                f"{entry.target_type}:{entry.target_id}": list(entry.verbs)
                for entry in self.entries
            },
            "format_actions": list(self.format_actions),
            "public_claim_allowed_targets": [
                f"{entry.target_type}:{entry.target_id}"
                for entry in self.entries
                if entry.public_claim_allowed
            ],
            "unavailable_reasons": self.unavailable_reasons,
        }


def build_director_vocabulary(
    *,
    substrates: Iterable[ContentSubstrate | Mapping[str, Any]] = (),
    lanes: Iterable[SpectacleLaneState | Mapping[str, Any]] = (),
    active_wards: Iterable[str] = (),
    ward_claims: Mapping[str, Any] | None = None,
    camera_status: Mapping[str, str] | None = None,
    camera_status_observed_at: float | None = None,
    camera_status_ttl_s: float = 20.0,
    camera_specs: Iterable[CameraSpec] = CAMERAS,
    private_controls: Iterable[PrivateControlBinding | Mapping[str, Any]] = (),
    programme: Programme | None = None,
    cuepoints: Iterable[ProgrammeBoundarySignal | Mapping[str, Any]] = (),
    rights_state: DirectorRightsState | None = None,
    format_actions: Iterable[FormatGroundingAction] = (),
    now: float | None = None,
) -> DirectorVocabulary:
    """Build a fail-closed director vocabulary envelope from typed truth."""

    current = now if now is not None else time.time()
    checked_at = _iso(current)
    rights = rights_state or DirectorRightsState()
    substrate_rows = [ContentSubstrate.model_validate(row) for row in substrates]
    lane_rows = [SpectacleLaneState.model_validate(row) for row in lanes]
    substrate_by_id = {row.substrate_id: row for row in substrate_rows}
    lane_by_id = {row.lane_id: row for row in lane_rows}
    entries: list[DirectorVocabularyEntry] = []

    for row in sorted(substrate_rows, key=lambda item: item.substrate_id):
        entries.append(_entry_from_substrate(row, rights, checked_at))

    for lane in sorted(lane_rows, key=lambda item: item.lane_id):
        entries.append(_entry_from_lane(lane, substrate_by_id, rights, checked_at))

    entries.extend(_re_splay_entries(substrate_rows, lane_by_id, rights, checked_at))
    entries.extend(
        _ward_entries(
            active_wards=active_wards,
            ward_claims=ward_claims or {},
            checked_at=checked_at,
            current=current,
        )
    )
    entries.extend(
        _camera_entries(
            camera_specs=camera_specs,
            camera_status=camera_status or {},
            observed_at=camera_status_observed_at,
            ttl_s=camera_status_ttl_s,
            current=current,
            rights=rights,
        )
    )
    entries.extend(
        _private_control_entries(
            private_controls=[
                PrivateControlBinding.model_validate(control) for control in private_controls
            ],
            checked_at=checked_at,
        )
    )
    entries.extend(
        _cuepoint_entries(
            cuepoints=[ProgrammeBoundarySignal.model_validate(cuepoint) for cuepoint in cuepoints],
            current=current,
            checked_at=checked_at,
        )
    )

    if programme is not None:
        entries.append(_entry_from_programme(programme, checked_at))

    entries.append(_entry_from_rights_state(rights, checked_at))

    return DirectorVocabulary(
        generated_at=checked_at,
        programme_id=programme.programme_id if programme is not None else None,
        condition_id=programme.parent_condition_id or "none" if programme is not None else "none",
        format_actions=list(dict.fromkeys(format_actions)),
        entries=_dedupe_entries(entries),
    )


def read_runtime_director_vocabulary(
    *,
    substrates: Iterable[ContentSubstrate | Mapping[str, Any]] = (),
    lanes: Iterable[SpectacleLaneState | Mapping[str, Any]] = (),
    streamdeck_path: Path | None = None,
    now: float | None = None,
) -> DirectorVocabulary:
    """Best-effort live adapter over current local status files.

    Missing files become unavailable/private entries. Network probes are
    deliberately disabled here; public liveness must be supplied by the
    egress resolver's local evidence.
    """

    current = now if now is not None else time.time()
    camera_status, camera_observed_at = _read_compositor_camera_status(current)
    rights = _read_rights_state()
    active_wards = sorted(_read_active_ward_ids(current))
    private_controls = [
        *read_streamdeck_private_controls(
            streamdeck_path or _repo_root() / "config" / "streamdeck.yaml"
        ),
        *kdeconnect_private_controls(),
        sidechat_private_control(),
    ]
    return build_director_vocabulary(
        substrates=substrates,
        lanes=lanes,
        active_wards=active_wards,
        ward_claims=_read_ward_claims(active_wards),
        camera_status=camera_status,
        camera_status_observed_at=camera_observed_at,
        private_controls=private_controls,
        programme=_read_active_programme(),
        rights_state=rights,
        now=current,
    )


def read_streamdeck_private_controls(path: Path) -> list[PrivateControlBinding]:
    try:
        from agents.streamdeck_adapter.key_map import load_key_map

        key_map = load_key_map(path)
    except Exception as exc:
        return [
            PrivateControlBinding(
                control_id="stream_deck",
                display_name="Stream Deck",
                source_ref="control:stream_deck",
                available=False,
                reason=f"Stream Deck key map unavailable: {type(exc).__name__}",
                terms=["Stream Deck"],
            )
        ]

    controls: list[PrivateControlBinding] = []
    for binding in key_map.bindings:
        label = binding.label or binding.command
        controls.append(
            PrivateControlBinding(
                control_id=f"stream_deck.key.{binding.key}",
                display_name=f"Stream Deck key {binding.key}: {label}",
                source_ref=f"control:stream_deck.key.{binding.key}",
                command=binding.command,
                available=True,
                terms=[label, binding.command, f"Stream Deck key {binding.key}"],
            )
        )
    return controls


def kdeconnect_private_controls() -> list[PrivateControlBinding]:
    controls = [
        ("kdeconnect.hero", "KDEConnect hero camera", "studio.hero.set"),
        ("kdeconnect.vinyl", "KDEConnect vinyl rate", "audio.vinyl.rate_preset"),
        ("kdeconnect.fx", "KDEConnect FX chain", "fx.chain.set"),
        ("kdeconnect.mode", "KDEConnect working mode", "mode.set"),
        ("kdeconnect.ward", "KDEConnect ward rotation", "studio.ward.*"),
        ("kdeconnect.safe", "KDEConnect safe mode", "degraded.activate"),
        ("kdeconnect.sidechat", "KDEConnect sidechat", None),
        ("kdeconnect.unknown", "KDEConnect unknown command reason", None),
    ]
    return [
        PrivateControlBinding(
            control_id=control_id,
            display_name=display,
            source_ref=f"control:{control_id}",
            command=command,
            available=control_id != "kdeconnect.unknown",
            reason="unknown KDEConnect commands return operator-facing reasons"
            if control_id == "kdeconnect.unknown"
            else "KDEConnect grammar command is private-only",
            terms=[display],
        )
        for control_id, display, command in controls
    ]


def sidechat_private_control(path: Path | None = None) -> PrivateControlBinding:
    target = path or Path("/dev/shm/hapax-compositor/operator-sidechat.jsonl")
    return PrivateControlBinding(
        control_id="sidechat",
        display_name="Operator sidechat",
        source_ref="control:sidechat",
        available=target.parent.exists(),
        reason="sidechat JSONL parent is local-only"
        if target.parent.exists()
        else "sidechat JSONL parent is unavailable",
        terms=["sidechat", "operator sidechat"],
    )


def visible_ward_ids_from_properties(
    path: Path = Path("/dev/shm/hapax-compositor/ward-properties.json"),
    *,
    now: float | None = None,
) -> set[str]:
    current = now if now is not None else time.time()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    wards = data.get("wards")
    if not isinstance(wards, dict):
        return set()
    visible: set[str] = set()
    for ward_id, raw in wards.items():
        if not isinstance(ward_id, str) or not isinstance(raw, dict):
            continue
        if raw.get("visible") is False:
            continue
        expires_at = raw.get("expires_at")
        if isinstance(expires_at, (int, float)) and expires_at < current:
            continue
        visible.add(ward_id)
    return visible


def _entry_from_substrate(
    row: ContentSubstrate,
    rights: DirectorRightsState,
    checked_at: str,
) -> DirectorVocabularyEntry:
    commandable = row.integration_status in _COMMANDABLE_SUBSTRATE_STATUSES
    verbs = _normalised_verbs(row.director_affordances) if commandable else []
    public_allowed = _substrate_public_allowed(row, rights)
    unavailable = None if verbs else row.fallback.reason
    status: EvidenceStatus = "fresh" if commandable else "missing"
    if row.integration_status == "degraded":
        status = "stale"
    return DirectorVocabularyEntry(
        target_type="substrate",
        target_id=row.substrate_id,
        display_name=row.display_name,
        terms=_terms([row.display_name, row.substrate_id, *row.director_vocabulary]),
        verbs=verbs,
        source_refs=[f"substrate:{row.substrate_id}"],
        generated_from=["content_substrate"],
        evidence=[
            DirectorVocabularyEvidence(
                source_type="content_substrate",
                ref=f"{row.substrate_id}.integration_status",
                status=status,
                observed_at=checked_at if commandable else None,
                age_s=0.0 if commandable else None,
                ttl_s=float(row.freshness_ttl_s) if row.freshness_ttl_s is not None else None,
                detail=f"substrate status is {row.integration_status}",
            )
        ],
        public_claim_allowed=public_allowed,
        unavailable_reason=unavailable,
        fallback_mode=_fallback_mode_from_substrate(row.fallback.mode),
    )


def _entry_from_lane(
    lane: SpectacleLaneState,
    substrate_by_id: Mapping[str, ContentSubstrate],
    rights: DirectorRightsState,
    checked_at: str,
) -> DirectorVocabularyEntry:
    commandable = _lane_commandable(lane)
    verbs = _normalised_verbs(lane.director_verbs) if commandable else []
    source_refs = [
        f"lane:{lane.lane_id}",
        *[f"substrate:{ref}" for ref in lane.content_substrate_refs],
    ]
    substrate_terms: list[str] = []
    for ref in lane.content_substrate_refs:
        row = substrate_by_id.get(ref)
        if row is not None:
            substrate_terms.extend([row.display_name, *row.director_vocabulary])
    status: EvidenceStatus = "fresh" if commandable else "missing"
    if lane.state == "degraded":
        status = "stale"
    elif lane.state == "candidate":
        status = "unknown"
    return DirectorVocabularyEntry(
        target_type="spectacle_lane",
        target_id=lane.lane_id,
        display_name=lane.display_name,
        terms=_terms([lane.display_name, lane.lane_id, *substrate_terms]),
        verbs=verbs,
        source_refs=_unique(source_refs),
        generated_from=["spectacle_lane", "content_substrate"]
        if lane.content_substrate_refs
        else ["spectacle_lane"],
        evidence=[
            DirectorVocabularyEvidence(
                source_type="spectacle_lane",
                ref=f"{lane.lane_id}.state",
                status=status,
                observed_at=checked_at if commandable else None,
                age_s=0.0 if commandable else None,
                ttl_s=None,
                detail=(
                    "lane is mounted/renderable"
                    if commandable
                    else f"lane is {lane.state}: {lane.fallback.reason}"
                ),
            )
        ],
        public_claim_allowed=lane.public_claim_allowed and rights.allows_public_claim,
        unavailable_reason=None if verbs else lane.fallback.reason,
        fallback_mode=_fallback_mode_from_lane(lane.fallback.mode),
    )


def _re_splay_entries(
    substrates: list[ContentSubstrate],
    lane_by_id: Mapping[str, SpectacleLaneState],
    rights: DirectorRightsState,
    checked_at: str,
) -> list[DirectorVocabularyEntry]:
    lane = lane_by_id.get("re_splay")
    entries: list[DirectorVocabularyEntry] = []
    for row in sorted(
        (item for item in substrates if item.substrate_id.startswith("re_splay_")),
        key=lambda item: item.substrate_id,
    ):
        lane_commandable = _lane_commandable(lane) if lane is not None else False
        substrate_commandable = row.integration_status in _COMMANDABLE_SUBSTRATE_STATUSES
        commandable = lane_commandable and substrate_commandable
        verbs = _normalised_verbs(
            lane.director_verbs if lane is not None else row.director_affordances
        )
        if not commandable:
            verbs = []
        reason = row.fallback.reason
        if lane is not None and not lane_commandable:
            reason = lane.fallback.reason
        entries.append(
            DirectorVocabularyEntry(
                target_type="re_splay_device",
                target_id=row.substrate_id,
                display_name=row.display_name,
                terms=_terms([row.display_name, row.substrate_id, *row.director_vocabulary]),
                verbs=verbs,
                source_refs=_unique(
                    [f"substrate:{row.substrate_id}"]
                    + ([f"lane:{lane.lane_id}"] if lane is not None else [])
                ),
                generated_from=["content_substrate", "spectacle_lane", "re_splay_probe"]
                if lane is not None
                else ["content_substrate", "re_splay_probe"],
                evidence=[
                    DirectorVocabularyEvidence(
                        source_type="re_splay_probe",
                        ref=f"{row.substrate_id}.integration_status",
                        status="fresh" if commandable else "missing",
                        observed_at=checked_at if commandable else None,
                        age_s=0.0 if commandable else None,
                        ttl_s=float(row.freshness_ttl_s)
                        if row.freshness_ttl_s is not None
                        else None,
                        detail=(
                            "Re-Splay device has mounted lane evidence" if commandable else reason
                        ),
                    )
                ],
                public_claim_allowed=commandable and _substrate_public_allowed(row, rights),
                unavailable_reason=None if verbs else reason,
                fallback_mode="no_op" if not commandable else "degraded_status",
            )
        )
    return entries


def _ward_entries(
    *,
    active_wards: Iterable[str],
    ward_claims: Mapping[str, Any],
    checked_at: str,
    current: float,
) -> list[DirectorVocabularyEntry]:
    entries: list[DirectorVocabularyEntry] = []
    active = set(active_wards)
    for ward_id in sorted(active | set(ward_claims)):
        claim = ward_claims.get(ward_id)
        terms = [ward_id.replace("_", " "), ward_id]
        source_refs = [f"ward:{ward_id}"]
        generated_from: list[GeneratedFrom] = ["ward_registry"]
        evidence = [
            DirectorVocabularyEvidence(
                source_type="ward_registry",
                ref=f"{ward_id}.active",
                status="fresh" if ward_id in active else "missing",
                observed_at=checked_at if ward_id in active else None,
                age_s=0.0 if ward_id in active else None,
                ttl_s=5.0,
                detail="ward is active" if ward_id in active else "ward is not active",
            )
        ]
        unavailable_reason = None if ward_id in active else "ward is not active"
        if claim is not None:
            claim_terms, claim_evidence, claim_reason, claim_ref = _claim_terms_and_evidence(
                claim,
                ward_id=ward_id,
                current=current,
            )
            terms.extend(claim_terms)
            evidence.append(claim_evidence)
            generated_from.append("claim_binding")
            if claim_ref:
                source_refs.append(claim_ref)
            if claim_reason:
                unavailable_reason = claim_reason

        entries.append(
            DirectorVocabularyEntry(
                target_type="ward",
                target_id=ward_id,
                display_name=ward_id.replace("_", " ").replace("-", " ").title(),
                terms=_terms(terms),
                verbs=[
                    "foreground",
                    "background",
                    "hold",
                    "suppress",
                    "transition",
                    "crossfade",
                    "intensify",
                    "stabilize",
                    "route_attention",
                ]
                if ward_id in active
                else [],
                source_refs=_unique(source_refs),
                generated_from=_unique(generated_from),
                evidence=evidence,
                public_claim_allowed=False,
                unavailable_reason=unavailable_reason,
                fallback_mode="degraded_status" if unavailable_reason else "private_only",
            )
        )
    return entries


def _camera_entries(
    *,
    camera_specs: Iterable[CameraSpec],
    camera_status: Mapping[str, str],
    observed_at: float | None,
    ttl_s: float,
    current: float,
    rights: DirectorRightsState,
) -> list[DirectorVocabularyEntry]:
    entries: list[DirectorVocabularyEntry] = []
    age_s = current - observed_at if observed_at is not None else None
    fresh_status_file = age_s is not None and age_s <= ttl_s
    for spec in sorted(camera_specs, key=lambda item: item.role):
        status = camera_status.get(spec.role)
        active = status == "active" and fresh_status_file
        detail = (
            f"camera status is active ({age_s:.1f}s old)"
            if active and age_s is not None
            else f"camera is unavailable ({status or 'missing'} status)"
        )
        entries.append(
            DirectorVocabularyEntry(
                target_type="camera",
                target_id=spec.role,
                display_name=spec.role,
                terms=_terms([spec.role, spec.short, f"{spec.camera_class} camera"]),
                verbs=[
                    "foreground",
                    "background",
                    "hold",
                    "suppress",
                    "transition",
                    "crossfade",
                    "stabilize",
                    "route_attention",
                ]
                if active
                else [],
                source_refs=[f"camera:{spec.role}"],
                generated_from=["camera_status"],
                evidence=[
                    DirectorVocabularyEvidence(
                        source_type="camera_status",
                        ref=f"{spec.role}.status",
                        status="fresh" if active else "stale" if status else "missing",
                        observed_at=_iso(observed_at) if observed_at is not None else None,
                        age_s=age_s,
                        ttl_s=ttl_s,
                        detail=detail,
                    )
                ],
                public_claim_allowed=active and rights.allows_public_claim,
                unavailable_reason=None if active else detail,
                fallback_mode="degraded_status" if status else "no_op",
            )
        )
    return entries


def _private_control_entries(
    *,
    private_controls: list[PrivateControlBinding],
    checked_at: str,
) -> list[DirectorVocabularyEntry]:
    entries: list[DirectorVocabularyEntry] = []
    for control in sorted(private_controls, key=lambda item: item.control_id):
        entries.append(
            DirectorVocabularyEntry(
                target_type="private_control",
                target_id=control.control_id,
                display_name=control.display_name,
                terms=_terms([control.display_name, control.control_id, *(control.terms or [])]),
                verbs=["route_attention", "hold", "suppress", "stabilize"]
                if control.available
                else [],
                source_refs=[control.source_ref],
                generated_from=["private_control"],
                evidence=[
                    DirectorVocabularyEvidence(
                        source_type="private_control",
                        ref=control.source_ref,
                        status="fresh" if control.available else "missing",
                        observed_at=checked_at if control.available else None,
                        age_s=0.0 if control.available else None,
                        ttl_s=None,
                        detail=control.reason,
                    )
                ],
                public_claim_allowed=False,
                unavailable_reason=None if control.available else control.reason,
                fallback_mode="private_only" if control.available else "operator_reason",
            )
        )
    return entries


def _cuepoint_entries(
    *,
    cuepoints: list[ProgrammeBoundarySignal],
    current: float,
    checked_at: str,
) -> list[DirectorVocabularyEntry]:
    entries: list[DirectorVocabularyEntry] = []
    for cuepoint in sorted(cuepoints, key=lambda item: item.boundary_id):
        age = current - cuepoint.observed_at if cuepoint.observed_at is not None else None
        available = cuepoint.fresh and cuepoint.observed_at is not None
        entries.append(
            DirectorVocabularyEntry(
                target_type="cuepoint",
                target_id=cuepoint.boundary_id,
                display_name=cuepoint.display_name,
                terms=_terms([cuepoint.display_name, cuepoint.boundary_id, "programme boundary"]),
                verbs=["mark_boundary"] if available else [],
                source_refs=[cuepoint.source_ref],
                generated_from=["cuepoint_event"],
                evidence=[
                    DirectorVocabularyEvidence(
                        source_type="cuepoint_event",
                        ref=cuepoint.source_ref,
                        status="fresh" if available else "missing",
                        observed_at=_iso(cuepoint.observed_at)
                        if cuepoint.observed_at is not None
                        else None,
                        age_s=age,
                        ttl_s=None,
                        detail=cuepoint.reason,
                    )
                ],
                public_claim_allowed=False,
                unavailable_reason=None if available else cuepoint.reason,
                fallback_mode="no_op",
            )
        )
    return entries


def _entry_from_programme(programme: Programme, checked_at: str) -> DirectorVocabularyEntry:
    return DirectorVocabularyEntry(
        target_type="programme",
        target_id=programme.programme_id,
        display_name=programme.programme_id,
        terms=_terms(
            [
                programme.programme_id,
                programme.role.value,
                programme.content.narrative_beat or "",
                *(programme.constraints.preset_family_priors or []),
            ]
        ),
        verbs=["hold", "transition", "stabilize", "route_attention", "mark_boundary"],
        source_refs=[f"programme:{programme.programme_id}"],
        generated_from=["programme_store"],
        evidence=[
            DirectorVocabularyEvidence(
                source_type="programme_store",
                ref=f"{programme.programme_id}.status",
                status="fresh",
                observed_at=checked_at,
                age_s=0.0,
                ttl_s=None,
                detail=f"active programme role is {programme.role.value}",
            )
        ],
        public_claim_allowed=False,
        fallback_mode="private_only",
    )


def _entry_from_rights_state(
    rights: DirectorRightsState,
    checked_at: str,
) -> DirectorVocabularyEntry:
    return DirectorVocabularyEntry(
        target_type="egress_status",
        target_id="livestream_egress",
        display_name="Livestream egress and rights floor",
        terms=_terms(
            [
                "livestream egress",
                "rights floor",
                "public claim floor",
                "audio safety floor",
                "privacy floor",
            ]
        ),
        verbs=["hold", "suppress", "stabilize", "route_attention"],
        source_refs=rights.source_refs,
        generated_from=["egress_state"],
        evidence=[
            DirectorVocabularyEvidence(
                source_type="egress_state",
                ref="livestream.public_claim_allowed",
                status="fresh" if rights.allows_public_claim else "missing",
                observed_at=checked_at if rights.allows_public_claim else None,
                age_s=0.0 if rights.allows_public_claim else None,
                ttl_s=None,
                detail=rights.detail,
            )
        ],
        public_claim_allowed=rights.allows_public_claim,
        unavailable_reason=None if rights.allows_public_claim else rights.detail,
        fallback_mode="degraded_status" if rights.allows_public_claim else "operator_reason",
    )


def _claim_terms_and_evidence(
    claim: Any,
    *,
    ward_id: str,
    current: float,
) -> tuple[list[str], DirectorVocabularyEvidence, str | None, str | None]:
    name = str(getattr(claim, "name", "") or f"{ward_id}.claim")
    posterior = getattr(claim, "posterior", None)
    floor = getattr(claim, "narration_floor", 1.0)
    last_update = getattr(claim, "last_update_t", None)
    cutoff = getattr(claim, "staleness_cutoff_s", None)
    proposition = str(getattr(claim, "proposition", "") or "")
    fresh = (
        isinstance(last_update, (int, float))
        and isinstance(cutoff, (int, float))
        and current - last_update <= cutoff
    )
    above_floor = isinstance(posterior, (int, float)) and posterior >= float(floor)
    status: EvidenceStatus = (
        "fresh" if fresh and above_floor else "stale" if last_update else "unknown"
    )
    age = current - last_update if isinstance(last_update, (int, float)) else None
    detail = (
        f"claim posterior {posterior:.3f} meets floor {floor:.3f}"
        if isinstance(posterior, (int, float)) and fresh and above_floor
        else f"claim binding for {ward_id} is stale, missing, or below narration floor"
    )
    terms = [name, proposition] if fresh and above_floor else [f"{name} degraded"]
    reason = None if fresh and above_floor else detail
    return (
        _terms(terms),
        DirectorVocabularyEvidence(
            source_type="claim_binding",
            ref=f"{ward_id}.{name}",
            status=status,
            observed_at=_iso(last_update) if isinstance(last_update, (int, float)) else None,
            age_s=age,
            ttl_s=float(cutoff) if isinstance(cutoff, (int, float)) else None,
            detail=detail,
        ),
        reason,
        f"claim:{name}" if name else None,
    )


def _substrate_public_allowed(row: ContentSubstrate, rights: DirectorRightsState) -> bool:
    permissions = row.public_claim_permissions
    if not permissions.claim_live:
        return False
    if permissions.requires_egress_public_claim and not rights.egress_public_claim_allowed:
        return False
    if permissions.requires_audio_safe and not rights.audio_safe:
        return False
    if permissions.requires_provenance and not row.provenance_token:
        return False
    if permissions.requires_operator_action:
        return False
    return (
        row.integration_status == "public-live"
        and row.rights_class in _PUBLIC_SAFE_RIGHTS
        and row.privacy_class in _PUBLIC_SAFE_PRIVACY
        and rights.allows_public_claim
    )


def _lane_commandable(lane: SpectacleLaneState | None) -> bool:
    if lane is None:
        return False
    return lane.state in _COMMANDABLE_LANE_STATES and (lane.mounted or lane.renderable)


def _normalised_verbs(raw_verbs: Iterable[str]) -> list[DirectorVerb]:
    verbs: list[DirectorVerb] = []
    for raw in raw_verbs:
        verb = _normalise_verb(raw)
        if verb in _STABLE_VERB_SET and verb not in verbs:
            verbs.append(verb)  # type: ignore[arg-type]
    return verbs


def _normalise_verb(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def _fallback_mode_from_substrate(mode: str) -> FallbackMode:
    return {
        "hide": "no_op",
        "hold_last_safe": "hold_last_safe",
        "dry_run_badge": "dry_run",
        "private_only": "private_only",
        "archive_only": "degraded_status",
        "operator_prompt": "operator_reason",
        "kill": "kill_switch",
    }.get(mode, "no_op")  # type: ignore[return-value]


def _fallback_mode_from_lane(mode: str) -> FallbackMode:
    return {
        "no_op_explain": "no_op",
        "dry_run_badge": "dry_run",
        "hold_last_safe": "hold_last_safe",
        "suppress": "suppress",
        "private_only": "private_only",
        "degraded_status": "degraded_status",
        "operator_prompt": "operator_reason",
        "kill_switch": "kill_switch",
    }.get(mode, "no_op")  # type: ignore[return-value]


def _terms(values: Iterable[str]) -> list[str]:
    return _unique(v.strip() for v in values if isinstance(v, str) and v.strip())


def _unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _dedupe_entries(entries: Iterable[DirectorVocabularyEntry]) -> list[DirectorVocabularyEntry]:
    by_key: dict[tuple[str, str], DirectorVocabularyEntry] = {}
    for entry in entries:
        by_key[(entry.target_type, entry.target_id)] = entry
    return [by_key[key] for key in sorted(by_key)]


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_compositor_camera_status(current: float) -> tuple[dict[str, str], float | None]:
    path = Path.home() / ".cache" / "hapax-compositor" / "status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    cameras = data.get("cameras")
    if not isinstance(cameras, dict):
        return {}, None
    timestamp = data.get("timestamp")
    observed = float(timestamp) if isinstance(timestamp, (int, float)) else path.stat().st_mtime
    return {str(k): str(v) for k, v in cameras.items()}, observed


def _read_rights_state() -> DirectorRightsState:
    try:
        from shared.livestream_egress_state import resolve_livestream_egress_state

        state = resolve_livestream_egress_state(probe_network=False)
        return DirectorRightsState.from_livestream_egress(state)
    except Exception as exc:
        return DirectorRightsState(
            detail=f"livestream egress resolver unavailable: {type(exc).__name__}"
        )


def _read_active_ward_ids(current: float) -> set[str]:
    wards = set(visible_ward_ids_from_properties(now=current))
    try:
        from agents.studio_compositor import active_wards

        wards.update(active_wards.read())
    except Exception:
        pass
    return wards


def _read_ward_claims(active_wards: Iterable[str]) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    try:
        from agents.studio_compositor import ward_claim_bindings

        for ward_id in set(active_wards) | ward_claim_bindings.bound_wards():
            provider = ward_claim_bindings.get(ward_id)
            if provider is None:
                continue
            try:
                claims[ward_id] = provider()
            except Exception:
                claims[ward_id] = None
    except Exception:
        pass
    return claims


def _read_active_programme() -> Programme | None:
    try:
        from shared.programme_store import default_store

        return default_store().active_programme()
    except Exception:
        return None


__all__ = [
    "ContentSubstrate",
    "DirectorRightsState",
    "DirectorVocabulary",
    "DirectorVocabularyEntry",
    "DirectorVocabularyEvidence",
    "FormatGroundingAction",
    "PrivateControlBinding",
    "ProgrammeBoundarySignal",
    "STABLE_DIRECTOR_VERBS",
    "SpectacleLaneState",
    "build_director_vocabulary",
    "kdeconnect_private_controls",
    "read_runtime_director_vocabulary",
    "read_streamdeck_private_controls",
    "sidechat_private_control",
    "visible_ward_ids_from_properties",
]
