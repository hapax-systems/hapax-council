"""WCS/evidence projection for content programme boundary events."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.content_programme_feedback_ledger import programme_state_from_run_envelope
from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    FixtureCaseId,
    ProgrammeBoundaryEventRef,
    PublicPrivateMode,
    public_conversion_is_allowed,
)
from shared.format_public_event_adapter import ProgrammeBoundaryEvent

REPO_ROOT = Path(__file__).resolve().parents[1]
PROGRAMME_BOUNDARY_WCS_EVIDENCE_FIXTURES = (
    REPO_ROOT / "config" / "programme-boundary-wcs-evidence-adapter.json"
)

PRODUCER = "shared.programme_boundary_wcs_evidence_adapter"
TASK_ANCHOR = "programme-boundary-wcs-evidence-adapter"
FORMAT_PUBLIC_EVENT_ADAPTER = "format_public_event_adapter"
CONTENT_PROGRAMME_FEEDBACK_LEDGER = "content_programme_feedback_ledger"
DOWNSTREAM_CONSUMERS = (FORMAT_PUBLIC_EVENT_ADAPTER, CONTENT_PROGRAMME_FEEDBACK_LEDGER)
PUBLIC_MODES: frozenset[PublicPrivateMode] = frozenset(
    {"public_live", "public_archive", "public_monetizable"}
)

type BoundaryProjectionState = Literal[
    "rvpe_linked",
    "held_for_rvpe",
    "internal_only",
    "blocked",
    "refusal_supported",
    "correction_supported",
]
type PublicHandoffState = Literal["rvpe_linked", "held_for_rvpe", "internal_only", "blocked"]
type DownstreamConsumer = Literal[
    "format_public_event_adapter", "content_programme_feedback_ledger"
]


class ProgrammeBoundaryWcsEvidenceError(ValueError):
    """Raised when boundary WCS/evidence fixtures cannot be projected safely."""


class BoundaryWcsEvidenceModel(BaseModel):
    """Strict immutable base for adapter records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class BoundaryEvidenceRefs(BoundaryWcsEvidenceModel):
    """Evidence and WCS refs attached to one programme boundary."""

    wcs_snapshot_refs: tuple[str, ...] = Field(default_factory=tuple)
    wcs_surface_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    grounding_gate_refs: tuple[str, ...] = Field(default_factory=tuple)
    outcome_refs: tuple[str, ...] = Field(default_factory=tuple)
    witnessed_outcome_refs: tuple[str, ...] = Field(default_factory=tuple)
    refusal_or_correction_refs: tuple[str, ...] = Field(default_factory=tuple)


class BoundaryGroundingGateProjection(BoundaryWcsEvidenceModel):
    """Boundary-local grounding gate plus run-level gate refs."""

    boundary_gate_ref: str | None
    run_grounding_gate_refs: tuple[str, ...] = Field(default_factory=tuple)
    gate_state: str
    claim_allowed: bool
    public_claim_allowed: bool
    infractions: tuple[str, ...] = Field(default_factory=tuple)
    adapter_grants_public_claim: Literal[False] = False


class PublicConversionHandoff(BoundaryWcsEvidenceModel):
    """Bounded handoff posture for the later public-event adapter."""

    handoff_state: PublicHandoffState
    research_vehicle_public_event_ref: str | None = None
    conversion_candidate_refs: tuple[str, ...] = Field(default_factory=tuple)
    format_public_event_adapter_ready: bool
    format_public_event_input_ref: str
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)
    boundary_alone_grants_public_conversion: Literal[False] = False
    adapter_grants_public_authority: Literal[False] = False
    adapter_grants_monetization_authority: Literal[False] = False


class ProgrammeBoundaryWcsEvidenceProjection(BoundaryWcsEvidenceModel):
    """Projected contract consumed by public-event and feedback adapters."""

    schema_version: Literal[1] = 1
    projection_id: str
    producer: Literal["shared.programme_boundary_wcs_evidence_adapter"] = PRODUCER
    task_anchor: Literal["programme-boundary-wcs-evidence-adapter"] = TASK_ANCHOR
    generated_at: datetime
    run_ref: str
    boundary_ref: str
    run_id: str
    programme_id: str
    format_id: str
    boundary_id: str
    boundary_type: str
    public_private_mode: PublicPrivateMode
    projection_state: BoundaryProjectionState
    refs: BoundaryEvidenceRefs
    grounding_gate_result: BoundaryGroundingGateProjection
    blocker_reasons: tuple[str, ...] = Field(default_factory=tuple)
    public_conversion: PublicConversionHandoff
    downstream_consumers: tuple[DownstreamConsumer, ...] = DOWNSTREAM_CONSUMERS
    feedback_ledger_input_ref: str
    internal_until_research_vehicle_public_event_accepts: Literal[True] = True


class ProgrammeBoundaryWcsEvidenceExpected(BoundaryWcsEvidenceModel):
    """Expected projection pins carried by the fixture file."""

    projection_state: BoundaryProjectionState
    format_public_event_adapter_ready: bool
    blocker_reasons: tuple[str, ...] = Field(default_factory=tuple)
    refusal_or_correction_refs_present: bool


class ProgrammeBoundaryWcsEvidenceFixture(BoundaryWcsEvidenceModel):
    """One canonical adapter fixture."""

    fixture_id: str = Field(pattern=r"^[a-z0-9_]+$")
    run_fixture_case: FixtureCaseId
    generated_at: datetime
    boundary: ProgrammeBoundaryEvent
    expected: ProgrammeBoundaryWcsEvidenceExpected


class ProgrammeBoundaryWcsEvidenceFixtureSet(BoundaryWcsEvidenceModel):
    """Canonical fixtures for boundary WCS/evidence projection."""

    schema_version: Literal[1] = 1
    fixture_set_id: Literal["programme_boundary_wcs_evidence_adapter"]
    schema_ref: Literal["schemas/programme-boundary-wcs-evidence-adapter.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: datetime
    producer: Literal["shared.programme_boundary_wcs_evidence_adapter"] = PRODUCER
    required_fixture_cases: tuple[str, ...] = Field(min_length=5)
    fail_closed_policy: dict[str, bool]
    fixtures: tuple[ProgrammeBoundaryWcsEvidenceFixture, ...] = Field(min_length=5)


def project_boundary_wcs_evidence(
    run: ContentProgrammeRunEnvelope,
    boundary_event: ProgrammeBoundaryEvent | Mapping[str, Any],
    *,
    generated_at: datetime | str,
) -> ProgrammeBoundaryWcsEvidenceProjection:
    """Attach WCS/evidence/gate/outcome refs to one boundary without publishing it."""

    boundary = _coerce_boundary(boundary_event)
    generated = _normalise_timestamp(generated_at)
    boundary_ref = _matching_boundary_ref(run, boundary)
    refs = _boundary_evidence_refs(run, boundary)
    gate = BoundaryGroundingGateProjection(
        boundary_gate_ref=boundary.no_expert_system_gate.gate_ref,
        run_grounding_gate_refs=run.gate_refs.grounding_gate_refs,
        gate_state=boundary.no_expert_system_gate.gate_state,
        claim_allowed=boundary.no_expert_system_gate.claim_allowed,
        public_claim_allowed=boundary.no_expert_system_gate.public_claim_allowed,
        infractions=boundary.no_expert_system_gate.infractions,
    )
    blockers = _blocker_reasons(run, boundary, boundary_ref, refs)
    public_conversion = _public_conversion_handoff(run, boundary, boundary_ref, refs, blockers)
    return ProgrammeBoundaryWcsEvidenceProjection(
        projection_id=f"pbwe:{run.run_id}:{boundary.boundary_id}",
        generated_at=generated,
        run_ref=f"ContentProgrammeRunEnvelope:{run.run_id}",
        boundary_ref=f"ProgrammeBoundaryEvent:{boundary.boundary_id}",
        run_id=run.run_id,
        programme_id=run.programme_id,
        format_id=run.format_id,
        boundary_id=boundary.boundary_id,
        boundary_type=boundary.boundary_type,
        public_private_mode=boundary.public_private_mode,
        projection_state=_projection_state(boundary, public_conversion, blockers),
        refs=refs,
        grounding_gate_result=gate,
        blocker_reasons=blockers,
        public_conversion=public_conversion,
        feedback_ledger_input_ref=(
            f"ContentProgrammeFeedbackEvent:feedback:{run.run_id}:"
            f"{programme_state_from_run_envelope(run)}"
        ),
    )


def load_programme_boundary_wcs_evidence_fixtures(
    path: Path = PROGRAMME_BOUNDARY_WCS_EVIDENCE_FIXTURES,
) -> ProgrammeBoundaryWcsEvidenceFixtureSet:
    """Load canonical boundary WCS/evidence adapter fixtures."""

    try:
        fixture_set = ProgrammeBoundaryWcsEvidenceFixtureSet.model_validate(_load_json_object(path))
        _validate_fixture_set(fixture_set)
        return fixture_set
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ProgrammeBoundaryWcsEvidenceError(
            f"invalid programme boundary WCS evidence fixtures at {path}: {exc}"
        ) from exc


def project_fixture(
    fixture: ProgrammeBoundaryWcsEvidenceFixture,
) -> ProgrammeBoundaryWcsEvidenceProjection:
    """Project one fixture row using the canonical run-store fixture envelope."""

    from shared.content_programme_run_store import build_fixture_envelope

    run = build_fixture_envelope(fixture.run_fixture_case, generated_at=fixture.generated_at)
    return project_boundary_wcs_evidence(
        run,
        fixture.boundary,
        generated_at=fixture.generated_at,
    )


def project_programme_boundary_wcs_evidence_fixture_set(
    path: Path = PROGRAMME_BOUNDARY_WCS_EVIDENCE_FIXTURES,
) -> tuple[ProgrammeBoundaryWcsEvidenceProjection, ...]:
    """Load and project the canonical fixture set."""

    fixture_set = load_programme_boundary_wcs_evidence_fixtures(path)
    return tuple(project_fixture(fixture) for fixture in fixture_set.fixtures)


def _coerce_boundary(
    boundary_event: ProgrammeBoundaryEvent | Mapping[str, Any],
) -> ProgrammeBoundaryEvent:
    if isinstance(boundary_event, ProgrammeBoundaryEvent):
        return boundary_event
    return ProgrammeBoundaryEvent.model_validate(boundary_event)


def _boundary_evidence_refs(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> BoundaryEvidenceRefs:
    evidence_refs = _dedupe(
        (
            *boundary.evidence_refs,
            *run.selected_input_refs,
            *(ref for claim in run.claims for ref in claim.evidence_refs),
        )
    )
    evidence_envelope_refs = _dedupe(
        (
            *run.wcs.evidence_envelope_refs,
            *(ref for claim in run.claims for ref in claim.evidence_envelope_refs),
            *(ref for outcome in run.witnessed_outcomes for ref in outcome.evidence_envelope_refs),
        )
    )
    return BoundaryEvidenceRefs(
        wcs_snapshot_refs=_dedupe(
            (
                f"ContentProgrammeRunEnvelope:{run.run_id}#wcs",
                run.director_plan.director_snapshot_ref,
                run.director_plan.director_plan_ref,
                *run.director_plan.director_move_refs,
            )
        ),
        wcs_surface_refs=_dedupe(
            (
                *run.substrate_refs,
                *run.wcs.semantic_substrate_refs,
                *run.wcs.grounding_contract_refs,
            )
        ),
        evidence_refs=evidence_refs,
        evidence_envelope_refs=evidence_envelope_refs,
        grounding_gate_refs=_dedupe(
            (
                boundary.no_expert_system_gate.gate_ref,
                *run.gate_refs.grounding_gate_refs,
                *run.gate_refs.rights_gate_refs,
                *run.gate_refs.privacy_gate_refs,
                *run.gate_refs.public_event_gate_refs,
            )
        ),
        outcome_refs=_dedupe(
            (
                *run.wcs.capability_outcome_refs,
                *(outcome.capability_outcome_ref for outcome in run.witnessed_outcomes),
            )
        ),
        witnessed_outcome_refs=tuple(outcome.outcome_id for outcome in run.witnessed_outcomes),
        refusal_or_correction_refs=_refusal_or_correction_refs(run, boundary),
    )


def _blocker_reasons(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
    boundary_ref: ProgrammeBoundaryEventRef | None,
    refs: BoundaryEvidenceRefs,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if (
        boundary.run_id != run.run_id
        or boundary.programme_id != run.programme_id
        or boundary.format_id != run.format_id
    ):
        reasons.append("run_identity_mismatch")
    if boundary_ref is None:
        reasons.append("run_boundary_ref_missing")
    reasons.extend(_mode_reasons(run.public_private_mode, boundary.public_private_mode))
    reasons.extend(_wcs_reasons(run))
    reasons.extend(_rights_privacy_reasons(run))
    reasons.extend(run.wcs.unavailable_reasons)
    reasons.extend(run.rights_privacy_public_mode.unavailable_reasons)
    reasons.extend(boundary.public_event_mapping.unavailable_reasons)
    reasons.extend(boundary.dry_run_unavailable_reasons)
    if not boundary.evidence_refs:
        reasons.append("missing_evidence_ref")
    reasons.extend(_ref_completeness_reasons(refs))
    reasons.extend(_gate_reasons(run, boundary))
    reasons.extend(_public_mapping_reasons(boundary))
    reasons.extend(_refusal_or_correction_reasons(boundary, refs))
    if (
        boundary.public_private_mode in PUBLIC_MODES
        and _research_vehicle_public_event_ref(boundary_ref) is None
    ):
        reasons.append("research_vehicle_public_event_missing")
    return _dedupe(reasons)


def _public_conversion_handoff(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
    boundary_ref: ProgrammeBoundaryEventRef | None,
    refs: BoundaryEvidenceRefs,
    blockers: tuple[str, ...],
) -> PublicConversionHandoff:
    rvpe_ref = _research_vehicle_public_event_ref(boundary_ref)
    conversion_candidates = tuple(candidate.candidate_id for candidate in run.conversion_candidates)
    candidate_allows_public = any(
        public_conversion_is_allowed(candidate)
        and candidate.research_vehicle_public_event_ref == rvpe_ref
        for candidate in run.conversion_candidates
    )
    adapter_ready = (
        rvpe_ref is not None
        and candidate_allows_public
        and not blockers
        and boundary.public_private_mode in PUBLIC_MODES
        and bool(refs.wcs_snapshot_refs)
        and bool(refs.wcs_surface_refs)
        and bool(refs.evidence_envelope_refs)
        and bool(refs.grounding_gate_refs)
        and bool(refs.outcome_refs)
    )
    return PublicConversionHandoff(
        handoff_state=_handoff_state(boundary, rvpe_ref, blockers),
        research_vehicle_public_event_ref=rvpe_ref,
        conversion_candidate_refs=conversion_candidates,
        format_public_event_adapter_ready=adapter_ready,
        format_public_event_input_ref=(
            f"FormatPublicEventAdapterInput:{run.run_id}:{boundary.boundary_id}"
        ),
        unavailable_reasons=blockers,
    )


def _projection_state(
    boundary: ProgrammeBoundaryEvent,
    public_conversion: PublicConversionHandoff,
    blockers: tuple[str, ...],
) -> BoundaryProjectionState:
    if boundary.boundary_type == "refusal.issued":
        return "refusal_supported"
    if boundary.boundary_type == "correction.made":
        return "correction_supported"
    if public_conversion.handoff_state == "rvpe_linked":
        return "rvpe_linked"
    if _has_hard_blocker(blockers):
        return "blocked"
    if public_conversion.handoff_state == "held_for_rvpe":
        return "held_for_rvpe"
    if public_conversion.handoff_state == "internal_only":
        return "internal_only"
    if blockers:
        return "blocked"
    return "held_for_rvpe"


def _has_hard_blocker(blockers: tuple[str, ...]) -> bool:
    soft_hold_reasons = {
        "dry_run_mode",
        "grounding_gate_failed",
        "research_vehicle_public_event_missing",
        "unsupported_claim",
    }
    return any(reason not in soft_hold_reasons for reason in blockers)


def _handoff_state(
    boundary: ProgrammeBoundaryEvent,
    rvpe_ref: str | None,
    blockers: tuple[str, ...],
) -> PublicHandoffState:
    if boundary.public_event_mapping.internal_only:
        return "internal_only"
    if rvpe_ref is None:
        return "held_for_rvpe"
    if blockers:
        return "blocked"
    return "rvpe_linked"


def _matching_boundary_ref(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> ProgrammeBoundaryEventRef | None:
    for boundary_ref in run.boundary_event_refs:
        if boundary_ref.boundary_id == boundary.boundary_id:
            return boundary_ref
    return None


def _research_vehicle_public_event_ref(
    boundary_ref: ProgrammeBoundaryEventRef | None,
) -> str | None:
    if boundary_ref is None:
        return None
    return boundary_ref.public_event_mapping_ref


def _refusal_or_correction_refs(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> tuple[str, ...]:
    if boundary.boundary_type == "refusal.issued" or boundary.claim_shape.claim_kind == "refusal":
        return tuple(refusal.state_id for refusal in run.refusals)
    if (
        boundary.boundary_type == "correction.made"
        or boundary.claim_shape.claim_kind == "correction"
    ):
        return tuple(correction.state_id for correction in run.corrections)
    return ()


def _mode_reasons(
    run_mode: PublicPrivateMode,
    boundary_mode: PublicPrivateMode,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for mode in (run_mode, boundary_mode):
        if mode == "private":
            reasons.append("private_mode")
        elif mode == "dry_run":
            reasons.append("dry_run_mode")
    return tuple(reasons)


def _wcs_reasons(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    if run.wcs.health_state in {"blocked", "unsafe"}:
        return ("world_surface_blocked",)
    if run.wcs.health_state == "stale":
        return ("source_stale",)
    if run.wcs.health_state == "missing":
        return ("missing_evidence_ref",)
    if run.wcs.health_state == "private_only":
        return ("private_mode",)
    if run.wcs.health_state in {"dry_run", "candidate"}:
        return ("dry_run_mode",)
    return ()


def _rights_privacy_reasons(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    reasons: list[str] = []
    if run.rights_privacy_public_mode.rights_state in {"blocked", "unknown"}:
        reasons.append("rights_blocked")
    if run.rights_privacy_public_mode.privacy_state in {
        "operator_private",
        "blocked",
        "unknown",
    }:
        reasons.append("privacy_blocked")
    return tuple(reasons)


def _ref_completeness_reasons(refs: BoundaryEvidenceRefs) -> tuple[str, ...]:
    reasons: list[str] = []
    if not refs.wcs_snapshot_refs:
        reasons.append("wcs_snapshot_ref_missing")
    if not refs.wcs_surface_refs:
        reasons.append("wcs_surface_ref_missing")
    if not refs.evidence_refs:
        reasons.append("missing_evidence_ref")
    if not refs.evidence_envelope_refs:
        reasons.append("evidence_envelope_ref_missing")
    if not refs.grounding_gate_refs:
        reasons.append("missing_grounding_gate")
    if not refs.outcome_refs:
        reasons.append("capability_outcome_ref_missing")
    return tuple(reasons)


def _gate_reasons(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> tuple[str, ...]:
    if _is_public_safe_refusal_or_correction(run, boundary):
        return ()
    gate = boundary.no_expert_system_gate
    reasons: list[str] = []
    if gate.gate_ref is None:
        reasons.append("missing_grounding_gate")
    if gate.gate_state in {"fail", "dry_run", "private_only"} or gate.infractions:
        reasons.append("grounding_gate_failed")
    if not gate.claim_allowed or not gate.public_claim_allowed:
        reasons.append("unsupported_claim")
    if boundary.claim_shape.authority_ceiling == "internal_only":
        reasons.append("unsupported_claim")
    return tuple(reasons)


def _public_mapping_reasons(boundary: ProgrammeBoundaryEvent) -> tuple[str, ...]:
    mapping = boundary.public_event_mapping
    if mapping.internal_only:
        return ("public_event_mapping_internal_only",)
    if (
        mapping.research_vehicle_event_type is None
        or mapping.state_kind is None
        or mapping.source_substrate_id is None
        or not mapping.allowed_surfaces
    ):
        return ("format_public_event_mapping_missing",)
    return ()


def _refusal_or_correction_reasons(
    boundary: ProgrammeBoundaryEvent,
    refs: BoundaryEvidenceRefs,
) -> tuple[str, ...]:
    if (
        boundary.boundary_type == "refusal.issued" or boundary.claim_shape.claim_kind == "refusal"
    ) and not refs.refusal_or_correction_refs:
        return ("refusal_ref_missing",)
    if (
        boundary.boundary_type == "correction.made"
        or boundary.claim_shape.claim_kind == "correction"
    ) and not refs.refusal_or_correction_refs:
        return ("correction_ref_missing",)
    return ()


def _is_public_safe_refusal_or_correction(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
) -> bool:
    claim_kind = boundary.claim_shape.claim_kind
    if claim_kind not in {"refusal", "correction"}:
        return False
    if boundary.boundary_type not in {"refusal.issued", "correction.made"}:
        return False
    return (
        run.public_private_mode in PUBLIC_MODES
        and run.rights_privacy_public_mode.rights_state
        in {
            "operator_original",
            "cleared",
            "platform_embed_only",
        }
        and run.rights_privacy_public_mode.privacy_state in {"public_safe", "aggregate_only"}
        and not boundary.public_event_mapping.internal_only
        and boundary.public_event_mapping.research_vehicle_event_type
        in {"publication.artifact", "metadata.update", "programme.boundary"}
    )


def _normalise_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dedupe(items: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProgrammeBoundaryWcsEvidenceError(f"{path} did not contain a JSON object")
    return payload


def _validate_fixture_set(fixture_set: ProgrammeBoundaryWcsEvidenceFixtureSet) -> None:
    expected_policy = {
        "boundary_alone_grants_public_conversion": False,
        "adapter_grants_public_authority": False,
        "adapter_grants_monetization_authority": False,
        "public_conversion_without_rvpe_allowed": False,
        "missing_wcs_evidence_or_outcome_refs_can_publish": False,
    }
    if fixture_set.fail_closed_policy != expected_policy:
        raise ValueError("programme boundary adapter fail_closed_policy must pin gates false")
    fixture_cases = {fixture.run_fixture_case for fixture in fixture_set.fixtures}
    missing_cases = set(fixture_set.required_fixture_cases) - fixture_cases
    if missing_cases:
        raise ValueError("fixture set missing required cases: " + ", ".join(sorted(missing_cases)))


__all__ = [
    "CONTENT_PROGRAMME_FEEDBACK_LEDGER",
    "DOWNSTREAM_CONSUMERS",
    "FORMAT_PUBLIC_EVENT_ADAPTER",
    "PROGRAMME_BOUNDARY_WCS_EVIDENCE_FIXTURES",
    "ProgrammeBoundaryWcsEvidenceError",
    "ProgrammeBoundaryWcsEvidenceFixture",
    "ProgrammeBoundaryWcsEvidenceFixtureSet",
    "ProgrammeBoundaryWcsEvidenceProjection",
    "load_programme_boundary_wcs_evidence_fixtures",
    "project_boundary_wcs_evidence",
    "project_fixture",
    "project_programme_boundary_wcs_evidence_fixture_set",
]
