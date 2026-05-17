"""Visual variance state vector and novelty ledger.

The ledger is a director/recruitment read surface. It records what visual move
was selected, what actually rendered, and whether any success/public claim is
allowed. Runtime intent never becomes rendered evidence by itself.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER_PATH = Path(
    os.environ.get(
        "HAPAX_VISUAL_VARIANCE_LEDGER_PATH",
        "/dev/shm/hapax-compositor/visual-variance-ledger.json",
    )
)
DEFAULT_DURABLE_DIR = Path(
    os.environ.get(
        "HAPAX_VISUAL_VARIANCE_LEDGER_DIR",
        str(Path.home() / "hapax-state" / "visual" / "variance-ledger"),
    )
)
DEFAULT_SCHEMA_REF = "schemas/visual-variance-ledger.schema.json"
DEFAULT_RUNTIME_TTL_S = 10.0
DEFAULT_FRAME_TTL_S = 5.0
DEFAULT_HISTORY_LIMIT = 24
AUTHORITY_CASE = "CASE-SLOTD-RIFT-VARIETY-20260517"
PARENT_SPEC = (
    "~/Documents/Personal/20-projects/hapax-requests/active/"
    "REQ-20260517090700-slotdrift-combinatorial-variety-coverage.md"
)


class VisualVarianceLedgerError(ValueError):
    """Raised when a visual variance ledger cannot be parsed or emitted."""


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"


class RenderedWitnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    BLOCKED = "blocked"


class ClaimStatus(StrEnum):
    WITNESSED_RENDERED = "witnessed_rendered"
    SELECTED_NOT_WITNESSED = "selected_not_witnessed"
    STALE_WITNESS_BLOCKED = "stale_witness_blocked"
    MISSING_WITNESS_BLOCKED = "missing_witness_blocked"
    PUBLIC_CLAIM_BLOCKED = "public_claim_blocked"


class NoveltyBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    STARVED = "starved"
    UNKNOWN = "unknown"


class VisualVarianceAxis(StrEnum):
    PROGRAMME_ROLE = "programme_role"
    PROGRAMME_FORMAT = "programme_format"
    ACTIVE_SOURCE_SET = "active_source_set"
    SOURCE_PROVENANCE_POSTURE = "source_provenance_posture"
    CAMERA_HERO = "camera_hero"
    CAMERA_LAYOUT = "camera_layout"
    CAMERA_ROLES = "camera_roles"
    GRAPH_FAMILY = "graph_family"
    GRAPH_TOPOLOGY_VARIANT = "graph_topology_variant"
    ACTIVE_NODE_SET = "active_node_set"
    UNUSED_NODE_EXPLORATION = "unused_node_exploration"
    PARAMETER_REGIONS = "parameter_regions"
    HOMAGE_PACKAGE = "homage_package"
    HOMAGE_ARTEFACT = "homage_artefact"
    VIDEO_EMISSIVE_PAIR_ROLE = "video_emissive_pair_role"
    SCRIM_PROFILE = "scrim_profile"
    SCRIM_PERMEABILITY = "scrim_permeability"
    DEPTH_PARALLAX_PROFILE = "depth_parallax_profile"
    WARD_SET = "ward_set"
    WARD_MOTION_STATE = "ward_motion_state"
    AUDIO_ROLE = "audio_role"
    AUDIO_SOURCE_ATTRIBUTION = "audio_source_attribution"
    TRANSITION_TYPE = "transition_type"
    COLOR_PALETTE_ROLE = "color_palette_role"
    ARCHIVE_REPLAY_PUBLIC_EVENT_STATUS = "archive_replay_public_event_status"


AXIS_WEIGHTS: dict[VisualVarianceAxis, float] = {
    VisualVarianceAxis.PROGRAMME_ROLE: 0.55,
    VisualVarianceAxis.PROGRAMME_FORMAT: 0.55,
    VisualVarianceAxis.ACTIVE_SOURCE_SET: 1.25,
    VisualVarianceAxis.SOURCE_PROVENANCE_POSTURE: 0.8,
    VisualVarianceAxis.CAMERA_HERO: 1.15,
    VisualVarianceAxis.CAMERA_LAYOUT: 1.1,
    VisualVarianceAxis.CAMERA_ROLES: 0.9,
    VisualVarianceAxis.GRAPH_FAMILY: 1.2,
    VisualVarianceAxis.GRAPH_TOPOLOGY_VARIANT: 1.4,
    VisualVarianceAxis.ACTIVE_NODE_SET: 1.3,
    VisualVarianceAxis.UNUSED_NODE_EXPLORATION: 0.85,
    VisualVarianceAxis.PARAMETER_REGIONS: 1.0,
    VisualVarianceAxis.HOMAGE_PACKAGE: 0.85,
    VisualVarianceAxis.HOMAGE_ARTEFACT: 0.85,
    VisualVarianceAxis.VIDEO_EMISSIVE_PAIR_ROLE: 0.9,
    VisualVarianceAxis.SCRIM_PROFILE: 0.95,
    VisualVarianceAxis.SCRIM_PERMEABILITY: 0.95,
    VisualVarianceAxis.DEPTH_PARALLAX_PROFILE: 0.95,
    VisualVarianceAxis.WARD_SET: 1.05,
    VisualVarianceAxis.WARD_MOTION_STATE: 1.1,
    VisualVarianceAxis.AUDIO_ROLE: 0.8,
    VisualVarianceAxis.AUDIO_SOURCE_ATTRIBUTION: 0.75,
    VisualVarianceAxis.TRANSITION_TYPE: 0.75,
    VisualVarianceAxis.COLOR_PALETTE_ROLE: 0.75,
    VisualVarianceAxis.ARCHIVE_REPLAY_PUBLIC_EVENT_STATUS: 0.6,
}

NOVELTY_CRITICAL_AXES = frozenset(
    {
        VisualVarianceAxis.ACTIVE_SOURCE_SET,
        VisualVarianceAxis.CAMERA_HERO,
        VisualVarianceAxis.CAMERA_LAYOUT,
        VisualVarianceAxis.GRAPH_FAMILY,
        VisualVarianceAxis.GRAPH_TOPOLOGY_VARIANT,
        VisualVarianceAxis.ACTIVE_NODE_SET,
        VisualVarianceAxis.WARD_SET,
        VisualVarianceAxis.PARAMETER_REGIONS,
    }
)

_UNKNOWN_MARKERS = frozenset({"", "unknown", "none", "null", "missing"})


class LedgerModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VisualFreshness(LedgerModel):
    state: FreshnessState
    checked_at: str
    ttl_s: float = Field(ge=0.0)
    observed_age_s: float | None = Field(default=None, ge=0.0)
    source_ref: str | None = None

    @model_validator(mode="after")
    def _fresh_requires_source_and_age(self) -> Self:
        if self.state is FreshnessState.FRESH:
            if self.observed_age_s is None or self.source_ref is None:
                raise ValueError("fresh visual evidence requires observed_age_s and source_ref")
            if self.observed_age_s > self.ttl_s:
                raise ValueError("fresh visual evidence cannot exceed ttl_s")
        if self.state is FreshnessState.STALE and not self.source_ref:
            raise ValueError("stale visual evidence requires source_ref")
        return self


class RenderedWitness(LedgerModel):
    witness_id: str
    status: RenderedWitnessStatus
    path: str
    source_ref: str
    checked_at: str
    ttl_s: float = Field(ge=0.0)
    observed_age_s: float | None = Field(default=None, ge=0.0)
    byte_size: int = Field(default=0, ge=0)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _fresh_requires_real_file_evidence(self) -> Self:
        if self.status is RenderedWitnessStatus.FRESH:
            if self.observed_age_s is None or self.byte_size <= 0:
                raise ValueError("fresh rendered witness requires age and non-empty bytes")
            if self.observed_age_s > self.ttl_s:
                raise ValueError("fresh rendered witness cannot exceed ttl_s")
            if not self.evidence_refs:
                raise ValueError("fresh rendered witness requires evidence_refs")
        if self.status in {RenderedWitnessStatus.STALE, RenderedWitnessStatus.MISSING}:
            if self.status is RenderedWitnessStatus.STALE and self.observed_age_s is None:
                raise ValueError("stale rendered witness requires observed_age_s")
        return self


class VisualStateVector(LedgerModel):
    """Canonical visual variance axes from the 2026-04-29 research audit."""

    schema_version: Literal[1] = 1
    programme_role: str = "unknown"
    programme_format: str = "unknown"
    active_source_set: tuple[str, ...] = Field(default_factory=tuple)
    source_provenance_posture: tuple[str, ...] = Field(default_factory=tuple)
    camera_hero: str = "unknown"
    camera_layout: str = "unknown"
    camera_roles: tuple[str, ...] = Field(default_factory=tuple)
    graph_family: str = "unknown"
    graph_topology_variant: str = "unknown"
    active_node_set: tuple[str, ...] = Field(default_factory=tuple)
    unused_node_exploration: tuple[str, ...] = Field(default_factory=tuple)
    parameter_regions: tuple[str, ...] = Field(default_factory=tuple)
    homage_package: str = "unknown"
    homage_artefact: str = "unknown"
    video_emissive_pair_role: str = "unknown"
    scrim_profile: str = "unknown"
    scrim_permeability: str = "unknown"
    depth_parallax_profile: str = "unknown"
    ward_set: tuple[str, ...] = Field(default_factory=tuple)
    ward_motion_state: tuple[str, ...] = Field(default_factory=tuple)
    audio_role: tuple[str, ...] = Field(default_factory=tuple)
    audio_source_attribution: tuple[str, ...] = Field(default_factory=tuple)
    transition_type: str = "unknown"
    color_palette_role: str = "unknown"
    archive_replay_public_event_status: str = "unknown"
    camera_salience_refs: tuple[str, ...] = Field(default_factory=tuple)
    cross_camera_time_evidence: tuple[str, ...] = Field(default_factory=tuple)
    ir_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    livestream_self_classification_refs: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator(
        "active_source_set",
        "source_provenance_posture",
        "camera_roles",
        "active_node_set",
        "unused_node_exploration",
        "parameter_regions",
        "ward_set",
        "ward_motion_state",
        "audio_role",
        "audio_source_attribution",
        "camera_salience_refs",
        "cross_camera_time_evidence",
        "ir_evidence_refs",
        "livestream_self_classification_refs",
        mode="before",
    )
    @classmethod
    def _normalise_tuple(cls, value: object) -> tuple[str, ...]:
        return _stable_tuple(value)

    def value_for_axis(self, axis: VisualVarianceAxis) -> str | tuple[str, ...]:
        return getattr(self, axis.value)


class VisualSelectedMove(LedgerModel):
    selected_at: str
    move_id: str
    selected_by: str
    selected_effect_nodes: tuple[str, ...] = Field(default_factory=tuple)
    selected_graph_family: str = "unknown"
    selected_source_refs: tuple[str, ...] = Field(default_factory=tuple)
    selected_camera_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    selection_allowed: bool = True

    @field_validator(
        "selected_effect_nodes",
        "selected_source_refs",
        "selected_camera_refs",
        "evidence_refs",
        mode="before",
    )
    @classmethod
    def _normalise_tuple(cls, value: object) -> tuple[str, ...]:
        return _stable_tuple(value)


class VisualNoveltyAxisScore(LedgerModel):
    axis: VisualVarianceAxis
    distance: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    immediate_repeat: bool
    recent_repeat: bool
    missing_or_unknown: bool
    basis: str


class VisualNoveltyAssessment(LedgerModel):
    score: float = Field(ge=0.0, le=1.0)
    band: NoveltyBand
    history_window_count: int = Field(ge=0)
    axis_scores: tuple[VisualNoveltyAxisScore, ...] = Field(min_length=1)
    repeated_axes: tuple[str, ...] = Field(default_factory=tuple)
    novelty_pressure_axes: tuple[str, ...] = Field(default_factory=tuple)
    missing_axes: tuple[str, ...] = Field(default_factory=tuple)


class VisualClaimGate(LedgerModel):
    selected_move_recorded: bool
    rendered_witness_status: RenderedWitnessStatus
    success_claim_allowed: bool
    public_claim_requested: bool = False
    public_claim_allowed: bool = False
    public_safe: bool = False
    claim_status: ClaimStatus
    blockers: tuple[str, ...] = Field(default_factory=tuple)
    public_aperture_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _claimability_is_fail_closed(self) -> Self:
        if self.success_claim_allowed:
            success_blockers = tuple(
                blocker for blocker in self.blockers if not blocker.startswith("public_")
            )
            if self.rendered_witness_status is not RenderedWitnessStatus.FRESH:
                raise ValueError("success_claim_allowed requires a fresh rendered witness")
            if success_blockers:
                raise ValueError("success_claim_allowed cannot carry rendered-success blockers")
        if self.public_claim_allowed:
            if not self.success_claim_allowed:
                raise ValueError("public_claim_allowed requires success_claim_allowed")
            if not self.public_safe or not self.public_aperture_refs:
                raise ValueError("public_claim_allowed requires explicit public-safe aperture refs")
        return self


class VisualVarianceLedger(LedgerModel):
    schema_version: Literal[1] = 1
    ledger_id: str
    schema_ref: Literal["schemas/visual-variance-ledger.schema.json"] = DEFAULT_SCHEMA_REF
    generated_at: str
    authority_case: str = AUTHORITY_CASE
    parent_spec: str = PARENT_SPEC
    state_vector: VisualStateVector
    selected_move: VisualSelectedMove
    rendered_witnesses: tuple[RenderedWitness, ...] = Field(default_factory=tuple)
    novelty: VisualNoveltyAssessment
    claim_gate: VisualClaimGate
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    camera_salience_projection: dict[str, Any] | None = None
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    prior_ledger_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _ledger_claim_gate_matches_witnesses(self) -> Self:
        statuses = {witness.status for witness in self.rendered_witnesses}
        if self.claim_gate.rendered_witness_status is RenderedWitnessStatus.FRESH:
            if RenderedWitnessStatus.FRESH not in statuses:
                raise ValueError("claim gate says fresh but no fresh rendered witness exists")
        if self.claim_gate.selected_move_recorded != bool(self.selected_move.move_id):
            raise ValueError("claim gate selected_move_recorded does not match selected_move")
        return self

    def prompt_projection_payload(self) -> dict[str, Any]:
        """Compact director-facing payload without compositor implementation details."""

        return {
            "ledger_id": self.ledger_id,
            "generated_at": self.generated_at,
            "novelty_score": self.novelty.score,
            "novelty_band": self.novelty.band.value,
            "novelty_pressure_axes": list(self.novelty.novelty_pressure_axes),
            "repeated_axes": list(self.novelty.repeated_axes),
            "selected_effect_nodes": list(self.selected_move.selected_effect_nodes),
            "active_sources": list(self.state_vector.active_source_set),
            "camera_hero": self.state_vector.camera_hero,
            "camera_layout": self.state_vector.camera_layout,
            "graph_topology_variant": self.state_vector.graph_topology_variant,
            "success_claim_allowed": self.claim_gate.success_claim_allowed,
            "public_claim_allowed": self.claim_gate.public_claim_allowed,
            "claim_blockers": list(self.claim_gate.blockers),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class VisualVarianceRuntimePaths:
    effect_drift_state: Path = Path("/dev/shm/hapax-visual/effect-drift-state.json")
    effect_plan: Path = Path("/dev/shm/hapax-imagination/pipeline/plan.json")
    visual_frame: Path = Path("/dev/shm/hapax-visual/frame.jpg")
    compositor_snapshot: Path = Path("/dev/shm/hapax-compositor/snapshot.jpg")
    compositor_fx_snapshot: Path = Path("/dev/shm/hapax-compositor/fx-snapshot.jpg")
    current_layout_state: Path = Path("/dev/shm/hapax-compositor/current-layout-state.json")
    active_wards: Path = Path("/dev/shm/hapax-compositor/active_wards.json")
    ward_properties: Path = Path("/dev/shm/hapax-compositor/ward-properties.json")
    camera_classifications: Path = Path("/dev/shm/hapax-compositor/camera-classifications.json")
    hero_camera_override: Path = Path("/dev/shm/hapax-compositor/hero-camera-override.json")
    follow_mode_recommendation: Path = Path(
        "/dev/shm/hapax-compositor/follow-mode-recommendation.json"
    )
    person_detection: Path = Path("/dev/shm/hapax-compositor/person-detection.json")
    scene_classification: Path = Path("/dev/shm/hapax-compositor/scene-classification.json")
    segment_layout_receipt: Path = Path("/dev/shm/hapax-compositor/segment-layout-receipt.json")
    composition_state: Path = Path("/dev/shm/hapax-compositor/composition-state.json")
    homage_substrate_package: Path = Path("/dev/shm/hapax-compositor/homage-substrate-package.json")
    homage_active_artefact: Path = Path("/dev/shm/hapax-compositor/homage-active-artefact.json")
    color_resonance: Path = Path("/dev/shm/hapax-compositor/color-resonance.json")
    audio_source_ledger: Path = Path("/dev/shm/hapax-compositor/audio-source-ledger.json")
    unified_reactivity: Path = Path("/dev/shm/hapax-compositor/unified-reactivity.json")
    stream_mode_intent: Path = Path("/dev/shm/hapax-compositor/stream-mode-intent.json")
    dmn_visual_salience: Path = Path("/dev/shm/hapax-dmn/visual-salience.json")
    conversation_visual_signal: Path = Path("/dev/shm/hapax-conversation/visual-signal.json")


def build_visual_variance_ledger(
    *,
    state_vector: VisualStateVector,
    selected_move: VisualSelectedMove | None = None,
    rendered_witnesses: Sequence[RenderedWitness] = (),
    prior_vectors: Sequence[VisualStateVector] = (),
    public_claim_requested: bool = False,
    public_aperture_refs: Sequence[str] = (),
    camera_salience_projection: Mapping[str, Any] | None = None,
    evidence_refs: Sequence[str] = (),
    warnings: Sequence[str] = (),
    prior_ledger_refs: Sequence[str] = (),
    now: float | None = None,
) -> VisualVarianceLedger:
    current = time.time() if now is None else now
    generated_at = _iso_from_epoch(current)
    move = selected_move or VisualSelectedMove(
        selected_at=generated_at,
        move_id=f"visual-move:{int(current)}",
        selected_by="shared.visual_variance_ledger",
        selected_effect_nodes=state_vector.active_node_set,
        selected_graph_family=state_vector.graph_family,
        selected_source_refs=state_vector.active_source_set,
        selected_camera_refs=(state_vector.camera_hero,)
        if state_vector.camera_hero != "unknown"
        else (),
        evidence_refs=evidence_refs,
    )
    witnesses = tuple(rendered_witnesses)
    novelty = score_visual_novelty(state_vector, prior_vectors)
    claim_gate = _claim_gate_for(
        selected_move=move,
        witnesses=witnesses,
        public_claim_requested=public_claim_requested,
        public_aperture_refs=tuple(public_aperture_refs),
    )
    refs = tuple(dict.fromkeys((*evidence_refs, *move.evidence_refs, *claim_gate.evidence_refs)))
    return VisualVarianceLedger(
        ledger_id=f"visual-variance-ledger:{generated_at}",
        generated_at=generated_at,
        state_vector=state_vector,
        selected_move=move,
        rendered_witnesses=witnesses,
        novelty=novelty,
        claim_gate=claim_gate,
        evidence_refs=refs or ("shared.visual_variance_ledger",),
        camera_salience_projection=dict(camera_salience_projection)
        if camera_salience_projection is not None
        else None,
        warnings=tuple(dict.fromkeys(warnings)),
        prior_ledger_refs=tuple(dict.fromkeys(prior_ledger_refs)),
    )


def build_visual_variance_ledger_from_runtime(
    *,
    paths: VisualVarianceRuntimePaths | None = None,
    prior_vectors: Sequence[VisualStateVector] = (),
    public_claim_requested: bool = False,
    public_aperture_refs: Sequence[str] = (),
    include_camera_salience: bool = True,
    now: float | None = None,
) -> VisualVarianceLedger:
    current = time.time() if now is None else now
    paths = paths or VisualVarianceRuntimePaths()
    evidence_refs: list[str] = []
    warnings: list[str] = []
    state_vector = build_visual_state_vector_from_runtime(paths=paths, now=current)
    witnesses = (
        rendered_witness_from_path(
            "visual-final-frame",
            paths.visual_frame,
            now=current,
            ttl_s=DEFAULT_FRAME_TTL_S,
        ),
        rendered_witness_from_path(
            "compositor-snapshot",
            paths.compositor_snapshot,
            now=current,
            ttl_s=DEFAULT_FRAME_TTL_S,
        ),
        rendered_witness_from_path(
            "compositor-fx-snapshot",
            paths.compositor_fx_snapshot,
            now=current,
            ttl_s=DEFAULT_FRAME_TTL_S,
        ),
    )
    for witness in witnesses:
        evidence_refs.extend(witness.evidence_refs)

    camera_projection = None
    if include_camera_salience:
        camera_projection = _query_camera_salience_projection()
        if camera_projection is None:
            warnings.append("camera_salience_projection_unavailable")

    return build_visual_variance_ledger(
        state_vector=state_vector,
        rendered_witnesses=witnesses,
        prior_vectors=prior_vectors,
        public_claim_requested=public_claim_requested,
        public_aperture_refs=public_aperture_refs,
        camera_salience_projection=camera_projection,
        evidence_refs=evidence_refs,
        warnings=warnings,
        now=current,
    )


def build_visual_state_vector_from_runtime(
    *,
    paths: VisualVarianceRuntimePaths | None = None,
    now: float | None = None,
) -> VisualStateVector:
    current = time.time() if now is None else now
    paths = paths or VisualVarianceRuntimePaths()
    effect_state = _read_json(paths.effect_drift_state)
    effect_plan = _read_json(paths.effect_plan)
    layout = _read_json(paths.current_layout_state)
    active_wards = _read_json(paths.active_wards)
    ward_props = _read_json(paths.ward_properties)
    cameras = _read_json(paths.camera_classifications)
    hero = _read_json(paths.hero_camera_override)
    follow = _read_json(paths.follow_mode_recommendation)
    person_detection = _read_json(paths.person_detection)
    scene = _read_json(paths.scene_classification)
    receipt = _read_json(paths.segment_layout_receipt)
    composition = _read_json(paths.composition_state)
    homage_package = _read_json(paths.homage_substrate_package)
    homage_artefact = _read_json(paths.homage_active_artefact)
    color_resonance = _read_json(paths.color_resonance)
    audio_ledger = _read_json(paths.audio_source_ledger)
    reactivity = _read_json(paths.unified_reactivity)
    stream_mode = _read_json(paths.stream_mode_intent)
    dmn_salience = _read_json(paths.dmn_visual_salience)
    visual_signal = _read_json(paths.conversation_visual_signal)

    passes = tuple(_effect_passes(effect_state))
    nodes = tuple(str(row.get("node_id")) for row in passes if row.get("node_id"))
    families = tuple(str(row.get("effect_family")) for row in passes if row.get("effect_family"))
    effect_inputs = tuple(str(ref) for row in passes for ref in _as_tuple(row.get("inputs")))
    parameter_regions = tuple(
        f"{row.get('node_id')}:{region.get('param')}:{region.get('region')}"
        for row in passes
        for region in _as_dict_sequence(row.get("parameter_regions"))
        if row.get("node_id") and region.get("param") and region.get("region")
    )
    source_bound_count = sum(1 for row in passes if row.get("source_bound") is True)
    full_surface_count = sum(1 for row in passes if row.get("full_surface") is True)
    topology_variant = _graph_topology_variant(nodes, source_bound_count, full_surface_count)

    coverage = _coverage(effect_state, effect_plan)
    unused = tuple(
        str(row.get("name"))
        for row in _as_dict_sequence(coverage.get("effect_counts"))
        if row.get("name") and int(row.get("coverage_window_count") or 0) == 0
    )

    layout_assignments = tuple(_as_dict_sequence(layout.get("assignments")))
    layout_sources = tuple(
        str(row.get("source")) for row in layout_assignments if row.get("source")
    )
    active_source_set = _stable_tuple(
        (
            *layout_sources,
            *effect_inputs,
            *_as_tuple(homage_package.get("substrate_source_ids")),
            *_active_audio_sources(audio_ledger, reactivity),
        )
    )
    ward_ids = _runtime_ward_ids(active_wards, layout)
    ward_motion = _ward_motion_state(ward_props)
    active_audio_roles, active_audio_sources = _audio_roles_and_sources(audio_ledger, reactivity)
    camera_hero = _camera_hero(hero, follow, current)
    camera_roles = _camera_roles(cameras)
    ir_refs = tuple(key for key in _as_mapping(cameras) if key.startswith("pi-noir"))

    scene_ref = "shm:hapax-compositor/scene-classification.json" if scene else ""
    person_ref = "shm:hapax-compositor/person-detection.json" if person_detection else ""
    dmn_ref = "shm:hapax-dmn/visual-salience.json" if dmn_salience else ""
    visual_signal_ref = "shm:hapax-conversation/visual-signal.json" if visual_signal else ""

    return VisualStateVector(
        programme_role=str(receipt.get("need_kind") or receipt.get("reason") or "unknown"),
        programme_format=str(receipt.get("selected_posture") or "unknown"),
        active_source_set=active_source_set,
        source_provenance_posture=_source_provenance_posture(homage_package, stream_mode),
        camera_hero=camera_hero,
        camera_layout=f"{layout.get('layout_mode', 'unknown')}:{layout.get('layout_name', 'unknown')}",
        camera_roles=camera_roles,
        graph_family=_graph_family(families),
        graph_topology_variant=topology_variant,
        active_node_set=nodes,
        unused_node_exploration=unused[:12],
        parameter_regions=parameter_regions,
        homage_package=str(homage_package.get("package") or "unknown"),
        homage_artefact=_homage_artefact(homage_artefact),
        video_emissive_pair_role=_video_emissive_pair_role(homage_package),
        scrim_profile=_scrim_profile(layout, stream_mode),
        scrim_permeability=_scrim_permeability(ward_props),
        depth_parallax_profile=_depth_parallax_profile(ward_props, layout),
        ward_set=ward_ids,
        ward_motion_state=ward_motion,
        audio_role=active_audio_roles,
        audio_source_attribution=active_audio_sources,
        transition_type=str(composition.get("reframe") or "steady"),
        color_palette_role=_color_palette_role(homage_package, color_resonance),
        archive_replay_public_event_status=str(stream_mode.get("target_mode") or "unknown"),
        camera_salience_refs=("shared.camera_salience_singleton:visual_variance",),
        cross_camera_time_evidence=tuple(ref for ref in (person_ref, scene_ref) if ref),
        ir_evidence_refs=ir_refs,
        livestream_self_classification_refs=tuple(
            ref for ref in (scene_ref, dmn_ref, visual_signal_ref) if ref
        ),
    )


def score_visual_novelty(
    state_vector: VisualStateVector,
    prior_vectors: Sequence[VisualStateVector] = (),
) -> VisualNoveltyAssessment:
    history = tuple(prior_vectors[:DEFAULT_HISTORY_LIMIT])
    axis_scores: list[VisualNoveltyAxisScore] = []
    weighted = 0.0
    total_weight = 0.0
    repeated: list[str] = []
    pressure: list[str] = []
    missing: list[str] = []

    for axis, weight in AXIS_WEIGHTS.items():
        current = state_vector.value_for_axis(axis)
        missing_or_unknown = _is_unknown_axis_value(current)
        if not history:
            distance = 0.35 if missing_or_unknown else 0.75
            immediate_repeat = False
            recent_repeat = False
            basis = "no_prior_window"
        else:
            immediate = _axis_distance(current, history[0].value_for_axis(axis))
            distances = [
                immediate,
                *(_axis_distance(current, row.value_for_axis(axis)) for row in history[1:]),
            ]
            distance = min(distances)
            immediate_repeat = immediate <= 0.02 and not missing_or_unknown
            recent_repeat = distance <= 0.02 and not missing_or_unknown
            basis = "min_distance_to_recent_state_vector"
        if missing_or_unknown:
            distance = min(distance, 0.2)
            missing.append(axis.value)
        if immediate_repeat or recent_repeat:
            repeated.append(axis.value)
            if axis in NOVELTY_CRITICAL_AXES:
                pressure.append(axis.value)
        weighted += distance * weight
        total_weight += weight
        axis_scores.append(
            VisualNoveltyAxisScore(
                axis=axis,
                distance=round(distance, 4),
                weight=weight,
                immediate_repeat=immediate_repeat,
                recent_repeat=recent_repeat,
                missing_or_unknown=missing_or_unknown,
                basis=basis,
            )
        )

    score = round(weighted / total_weight, 4) if total_weight else 0.0
    if not history:
        band = NoveltyBand.UNKNOWN
    elif score >= 0.72:
        band = NoveltyBand.HIGH
    elif score >= 0.45:
        band = NoveltyBand.MEDIUM
    elif score >= 0.2:
        band = NoveltyBand.LOW
    else:
        band = NoveltyBand.STARVED

    return VisualNoveltyAssessment(
        score=score,
        band=band,
        history_window_count=len(history),
        axis_scores=tuple(axis_scores),
        repeated_axes=tuple(dict.fromkeys(repeated)),
        novelty_pressure_axes=tuple(dict.fromkeys(pressure)),
        missing_axes=tuple(dict.fromkeys(missing)),
    )


def rendered_witness_from_path(
    witness_id: str,
    path: Path,
    *,
    now: float | None = None,
    ttl_s: float = DEFAULT_FRAME_TTL_S,
) -> RenderedWitness:
    current = time.time() if now is None else now
    checked_at = _iso_from_epoch(current)
    source_ref = f"file:{path}"
    try:
        stat = path.stat()
    except FileNotFoundError:
        return RenderedWitness(
            witness_id=witness_id,
            status=RenderedWitnessStatus.MISSING,
            path=str(path),
            source_ref=source_ref,
            checked_at=checked_at,
            ttl_s=ttl_s,
            evidence_refs=(),
        )
    except OSError:
        return RenderedWitness(
            witness_id=witness_id,
            status=RenderedWitnessStatus.BLOCKED,
            path=str(path),
            source_ref=source_ref,
            checked_at=checked_at,
            ttl_s=ttl_s,
            evidence_refs=(),
        )

    age = max(0.0, current - stat.st_mtime)
    status = (
        RenderedWitnessStatus.FRESH
        if age <= ttl_s and stat.st_size > 0
        else RenderedWitnessStatus.STALE
    )
    return RenderedWitness(
        witness_id=witness_id,
        status=status,
        path=str(path),
        source_ref=source_ref,
        checked_at=checked_at,
        ttl_s=ttl_s,
        observed_age_s=round(age, 3),
        byte_size=int(stat.st_size),
        evidence_refs=(source_ref,) if status is RenderedWitnessStatus.FRESH else (),
    )


def write_visual_variance_ledger(
    ledger: VisualVarianceLedger,
    *,
    path: Path = DEFAULT_LEDGER_PATH,
    durable_dir: Path = DEFAULT_DURABLE_DIR,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(ledger.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    durable_dir.mkdir(parents=True, exist_ok=True)
    summary_path = durable_dir / f"{ledger.generated_at[:10]}.jsonl"
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_ledger_summary(ledger), sort_keys=True) + "\n")


def read_visual_variance_ledger(path: Path = DEFAULT_LEDGER_PATH) -> VisualVarianceLedger | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualVarianceLedgerError(f"invalid visual variance ledger at {path}: {exc}") from exc
    try:
        return VisualVarianceLedger.model_validate(payload)
    except ValidationError as exc:
        raise VisualVarianceLedgerError(f"invalid visual variance ledger at {path}: {exc}") from exc


def read_visual_variance_history(
    *,
    path: Path = DEFAULT_LEDGER_PATH,
    durable_dir: Path = DEFAULT_DURABLE_DIR,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> tuple[VisualStateVector, ...]:
    rows: list[VisualStateVector] = []
    current = read_visual_variance_ledger(path)
    if current is not None:
        rows.append(current.state_vector)

    for jsonl_path in sorted(durable_dir.glob("*.jsonl"), reverse=True):
        if len(rows) >= limit:
            break
        try:
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if len(rows) >= limit:
                break
            try:
                payload = json.loads(line)
                vector = VisualStateVector.model_validate(payload["state_vector"])
            except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
                continue
            rows.append(vector)

    return tuple(rows[:limit])


def _claim_gate_for(
    *,
    selected_move: VisualSelectedMove,
    witnesses: tuple[RenderedWitness, ...],
    public_claim_requested: bool,
    public_aperture_refs: tuple[str, ...],
) -> VisualClaimGate:
    fresh = tuple(w for w in witnesses if w.status is RenderedWitnessStatus.FRESH)
    stale = tuple(w for w in witnesses if w.status is RenderedWitnessStatus.STALE)
    blockers: list[str] = []
    evidence_refs = tuple(ref for witness in fresh for ref in witness.evidence_refs)
    if fresh:
        status = RenderedWitnessStatus.FRESH
        success_allowed = True
        claim_status = ClaimStatus.WITNESSED_RENDERED
    elif stale:
        status = RenderedWitnessStatus.STALE
        success_allowed = False
        claim_status = ClaimStatus.STALE_WITNESS_BLOCKED
        blockers.append("rendered_witness_stale")
    else:
        status = RenderedWitnessStatus.MISSING
        success_allowed = False
        claim_status = (
            ClaimStatus.SELECTED_NOT_WITNESSED
            if selected_move.move_id
            else ClaimStatus.MISSING_WITNESS_BLOCKED
        )
        blockers.append("rendered_witness_missing")

    public_safe = bool(public_aperture_refs)
    public_allowed = success_allowed and public_safe
    if public_claim_requested and not public_allowed:
        claim_status = ClaimStatus.PUBLIC_CLAIM_BLOCKED
        if not public_aperture_refs:
            blockers.append("public_aperture_refs_missing")
        if not success_allowed:
            blockers.append("fresh_rendered_witness_missing")

    return VisualClaimGate(
        selected_move_recorded=bool(selected_move.move_id),
        rendered_witness_status=status,
        success_claim_allowed=success_allowed,
        public_claim_requested=public_claim_requested,
        public_claim_allowed=public_allowed,
        public_safe=public_safe,
        claim_status=claim_status,
        blockers=tuple(dict.fromkeys(blockers)),
        public_aperture_refs=tuple(dict.fromkeys(public_aperture_refs)),
        evidence_refs=evidence_refs,
    )


def _axis_distance(current: str | tuple[str, ...], prior: str | tuple[str, ...]) -> float:
    if isinstance(current, tuple) or isinstance(prior, tuple):
        current_set = set(_as_tuple(current))
        prior_set = set(_as_tuple(prior))
        if not current_set and not prior_set:
            return 0.0
        if not current_set or not prior_set:
            return 0.65
        return 1.0 - (len(current_set & prior_set) / len(current_set | prior_set))
    if _unknownish(current) or _unknownish(prior):
        return 0.25
    return 0.0 if current == prior else 1.0


def _is_unknown_axis_value(value: str | tuple[str, ...]) -> bool:
    if isinstance(value, tuple):
        return not value or all(_unknownish(item) for item in value)
    return _unknownish(value)


def _unknownish(value: object) -> bool:
    return str(value).strip().lower() in _UNKNOWN_MARKERS


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _effect_passes(effect_state: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        row
        for row in _as_dict_sequence(effect_state.get("passes"))
        if row.get("non_neutral") is not False
    )


def _coverage(effect_state: Mapping[str, Any], effect_plan: Mapping[str, Any]) -> dict[str, Any]:
    coverage = effect_state.get("slotdrift_coverage")
    if isinstance(coverage, dict):
        return coverage
    plan_coverage = effect_plan.get("slotdrift_coverage")
    return plan_coverage if isinstance(plan_coverage, dict) else {}


def _graph_family(families: Sequence[str]) -> str:
    counts: dict[str, int] = {}
    for family in families:
        if _unknownish(family):
            continue
        counts[family] = counts.get(family, 0) + 1
    if not counts:
        return "unknown"
    return "+".join(f"{family}:{counts[family]}" for family in sorted(counts))


def _graph_topology_variant(
    nodes: Sequence[str],
    source_bound_count: int,
    full_surface_count: int,
) -> str:
    if not nodes:
        return "unknown"
    return (
        "slotdrift:"
        + ">".join(nodes)
        + f":source_bound={source_bound_count}:full_surface={full_surface_count}"
    )


def _runtime_ward_ids(
    active_wards: Mapping[str, Any], layout: Mapping[str, Any]
) -> tuple[str, ...]:
    ids = active_wards.get("ward_ids") or layout.get("active_ward_ids") or ()
    return _stable_tuple(ids)


def _ward_motion_state(ward_props: Mapping[str, Any]) -> tuple[str, ...]:
    rows: list[str] = []
    wards = _as_mapping(ward_props.get("wards"))
    for ward_id, raw in sorted(wards.items()):
        props = _as_mapping(raw)
        if not props.get("visible", False):
            continue
        z_plane = str(props.get("z_plane") or "unknown")
        front = str(props.get("front_state") or "unknown")
        drift_hz = _bucket_float(props.get("drift_hz"), (0.05, 0.3, 1.0))
        drift_amp = _bucket_float(props.get("drift_amplitude_px"), (1.0, 4.0, 10.0))
        rows.append(f"{ward_id}:z={z_plane}:front={front}:hz={drift_hz}:amp={drift_amp}")
    return tuple(rows)


def _camera_hero(hero: Mapping[str, Any], follow: Mapping[str, Any], now: float) -> str:
    camera = _fresh_ttl_value(hero, "camera_role", now=now, ts_key="set_at", ttl_key="ttl_s")
    if camera:
        return camera
    follow_camera = _fresh_ttl_value(follow, "camera_role", now=now, ts_key="ts", ttl_key="ttl_s")
    return follow_camera or "unknown"


def _camera_roles(cameras: Mapping[str, Any]) -> tuple[str, ...]:
    rows: list[str] = []
    for camera_id, raw in sorted(_as_mapping(cameras).items()):
        row = _as_mapping(raw)
        role = str(row.get("semantic_role") or "unknown")
        angle = str(row.get("angle") or "unknown")
        visible = "operator-visible" if row.get("operator_visible") else "operator-hidden"
        rows.append(f"{camera_id}:{role}:{angle}:{visible}")
    return tuple(rows)


def _active_audio_sources(
    audio_ledger: Mapping[str, Any], reactivity: Mapping[str, Any]
) -> tuple[str, ...]:
    _, sources = _audio_roles_and_sources(audio_ledger, reactivity)
    return sources


def _audio_roles_and_sources(
    audio_ledger: Mapping[str, Any],
    reactivity: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    roles: list[str] = []
    sources: list[str] = []
    for row in _as_dict_sequence(audio_ledger.get("source_rows")):
        if row.get("active") is True:
            role = str(row.get("role") or "unknown")
            source = str(row.get("source_id") or "unknown")
            roles.append(role)
            sources.append(source)
    if not sources:
        for source in _as_tuple(reactivity.get("active_sources")):
            sources.append(source)
            roles.append(f"reactivity:{source}")
    return _stable_tuple(roles), _stable_tuple(sources)


def _source_provenance_posture(
    homage_package: Mapping[str, Any],
    stream_mode: Mapping[str, Any],
) -> tuple[str, ...]:
    rows = [
        f"homage_package:{homage_package.get('package', 'unknown')}",
        f"stream_mode:{stream_mode.get('target_mode', 'unknown')}",
    ]
    for source_id in _as_tuple(homage_package.get("substrate_source_ids")):
        rows.append(f"substrate:{source_id}:private_runtime_ref")
    return _stable_tuple(rows)


def _homage_artefact(payload: Mapping[str, Any]) -> str:
    if not payload:
        return "unknown"
    return ":".join(str(payload.get(key) or "unknown") for key in ("package", "form", "author_tag"))


def _video_emissive_pair_role(homage_package: Mapping[str, Any]) -> str:
    sources = set(_as_tuple(homage_package.get("substrate_source_ids")))
    if {"reverie", "reverie_external_rgba"} & sources and len(sources) >= 2:
        return "homage_video_emissive_pair"
    if sources:
        return "single_substrate"
    return "unknown"


def _scrim_profile(layout: Mapping[str, Any], stream_mode: Mapping[str, Any]) -> str:
    return (
        f"layout={layout.get('layout_name', 'unknown')}:"
        f"mode={layout.get('layout_mode', 'unknown')}:"
        f"stream={stream_mode.get('target_mode', 'unknown')}"
    )


def _scrim_permeability(ward_props: Mapping[str, Any]) -> str:
    wards = _as_mapping(ward_props.get("wards"))
    visible = [_as_mapping(row) for row in wards.values() if _as_mapping(row).get("visible")]
    if not visible:
        return "unknown"
    alpha_values = [_safe_float(row.get("alpha"), 1.0) for row in visible]
    avg_alpha = sum(alpha_values) / len(alpha_values)
    alpha_bucket = _bucket_float(avg_alpha, (0.35, 0.7, 0.95))
    return f"visible={len(visible)}:avg_alpha={alpha_bucket}"


def _depth_parallax_profile(ward_props: Mapping[str, Any], layout: Mapping[str, Any]) -> str:
    wards = _as_mapping(ward_props.get("wards"))
    z_counts: dict[str, int] = {}
    parallax_rows: list[str] = []
    for raw in wards.values():
        row = _as_mapping(raw)
        if not row.get("visible"):
            continue
        z_plane = str(row.get("z_plane") or "unknown")
        z_counts[z_plane] = z_counts.get(z_plane, 0) + 1
        video = _bucket_float(row.get("parallax_scalar_video"), (0.75, 1.25, 1.75))
        emissive = _bucket_float(row.get("parallax_scalar_emissive"), (0.75, 1.25, 1.75))
        parallax_rows.append(f"{video}/{emissive}")
    z_part = ",".join(f"{key}:{z_counts[key]}" for key in sorted(z_counts)) or "z=unknown"
    parallax_part = ",".join(sorted(set(parallax_rows))) or "parallax=unknown"
    return f"{layout.get('layout_mode', 'unknown')}:{z_part}:{parallax_part}"


def _color_palette_role(
    homage_package: Mapping[str, Any],
    color_resonance: Mapping[str, Any],
) -> str:
    package = str(homage_package.get("package") or "unknown")
    hue = homage_package.get("palette_accent_hue_deg")
    if hue is not None:
        return f"homage:{package}:hue={_bucket_float(hue, (90.0, 180.0, 270.0))}"
    if color_resonance:
        return f"color_resonance:{sorted(color_resonance)[:3]}"
    return f"homage:{package}"


def _fresh_ttl_value(
    payload: Mapping[str, Any],
    value_key: str,
    *,
    now: float,
    ts_key: str,
    ttl_key: str,
) -> str | None:
    if not payload:
        return None
    value = payload.get(value_key)
    ts = _safe_float(payload.get(ts_key), -1.0)
    ttl = _safe_float(payload.get(ttl_key), 0.0)
    if value and ts >= 0.0 and ttl > 0.0 and now - ts <= ttl:
        return str(value)
    return None


def _query_camera_salience_projection() -> dict[str, Any] | None:
    try:
        from shared.bayesian_camera_salience_world_surface import EvidenceClass, PrivacyMode
        from shared.camera_salience_singleton import broker

        bundle = broker().query(
            consumer="visual_variance",
            decision_context="visual_variance_ledger_projection",
            candidate_action="score_visual_state_vector_novelty",
            evidence_classes=(
                EvidenceClass.FRAME,
                EvidenceClass.IR_PRESENCE,
                EvidenceClass.COMPOSED_LIVESTREAM,
            ),
            privacy_mode=PrivacyMode.PRIVATE,
            max_images=0,
            max_tokens=160,
        )
        return None if bundle is None else bundle.model_dump(mode="json")
    except Exception:
        log.debug("visual variance camera salience projection failed", exc_info=True)
        return None


def _ledger_summary(ledger: VisualVarianceLedger) -> dict[str, Any]:
    return {
        "ledger_id": ledger.ledger_id,
        "generated_at": ledger.generated_at,
        "state_vector": ledger.state_vector.model_dump(mode="json"),
        "novelty_score": ledger.novelty.score,
        "novelty_band": ledger.novelty.band.value,
        "novelty_pressure_axes": list(ledger.novelty.novelty_pressure_axes),
        "claim_status": ledger.claim_gate.claim_status.value,
        "success_claim_allowed": ledger.claim_gate.success_claim_allowed,
        "public_claim_allowed": ledger.claim_gate.public_claim_allowed,
        "blockers": list(ledger.claim_gate.blockers),
    }


def _stable_tuple(value: object) -> tuple[str, ...]:
    rows = tuple(str(item).strip() for item in _as_tuple(value) if str(item).strip())
    return tuple(dict.fromkeys(sorted(rows)))


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list | set | frozenset):
        return tuple(str(item) for item in value)
    return (str(value),)


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_dict_sequence(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(row for row in value if isinstance(row, dict))


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bucket_float(value: object, thresholds: tuple[float, ...]) -> str:
    numeric = _safe_float(value, float("nan"))
    if numeric != numeric:
        return "unknown"
    labels = ("low", "mid", "high", "very_high")
    for index, threshold in enumerate(thresholds):
        if numeric <= threshold:
            return labels[index]
    return labels[min(len(thresholds), len(labels) - 1)]


def _iso_from_epoch(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


__all__ = [
    "AUTHORITY_CASE",
    "PARENT_SPEC",
    "RenderedWitness",
    "RenderedWitnessStatus",
    "VisualClaimGate",
    "VisualNoveltyAssessment",
    "VisualSelectedMove",
    "VisualStateVector",
    "VisualVarianceLedger",
    "VisualVarianceLedgerError",
    "VisualVarianceRuntimePaths",
    "build_visual_state_vector_from_runtime",
    "build_visual_variance_ledger",
    "build_visual_variance_ledger_from_runtime",
    "read_visual_variance_history",
    "read_visual_variance_ledger",
    "rendered_witness_from_path",
    "score_visual_novelty",
    "write_visual_variance_ledger",
]
