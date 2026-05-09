"""Private resource-capability dispatch metric contracts.

This module is intentionally inert. It validates private recommendation
artifacts over resource-capability and dashboard fixtures, but it does not write
tasks, dispatch sessions, call providers, read credentials, send mail, write
calendars, publish claims, start services, or move money.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.resource_capability import (
    ActionClass,
    DecisionState,
    MeasurementActionContract,
    load_resource_capability_fixtures,
)
from shared.resource_capability_dashboard import load_resource_capability_dashboard_fixtures

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CAPABILITY_DISPATCH_FIXTURES = (
    REPO_ROOT / "config" / "resource-capability-dispatch-fixtures.json"
)

ACTION_BEARING_CLASSES = frozenset(
    {
        ActionClass.DISPATCH,
        ActionClass.GATE,
        ActionClass.HOLD,
        ActionClass.KILL,
        ActionClass.ESCALATE,
    }
)


class ResourceCapabilityDispatchError(ValueError):
    """Raised when dispatch fixtures cannot be loaded safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DispatchRecommendationKind(StrEnum):
    INTERNAL_FOLLOWUP_TASK_DRAFT = "internal_followup_task_draft"
    HOLD_RECOMMENDATION = "hold_recommendation"
    BLOCK_RECOMMENDATION = "block_recommendation"


class MetricContractEvaluationState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    MISSING_CONTRACT = "missing_contract"
    UNSUPPORTED_ACTION = "unsupported_action"
    BLOCKED_STALE_CONFLICT = "blocked_stale_conflict"


class DispatchAuthorityBlock(StrictModel):
    """External and live internal effects stay forbidden in this slice."""

    task_file_write_authorized: Literal[False] = False
    coordinator_send_authorized: Literal[False] = False
    provider_api_execution_authorized: Literal[False] = False
    credential_lookup_authorized: Literal[False] = False
    outbound_email_authorized: Literal[False] = False
    live_calendar_write_authorized: Literal[False] = False
    payment_movement_authorized: Literal[False] = False
    public_offer_authorized: Literal[False] = False
    public_claim_upgrade_authorized: Literal[False] = False
    public_projection_allowed: Literal[False] = False
    runtime_feeder_execution_authorized: Literal[False] = False
    service_execution_authorized: Literal[False] = False
    external_action_authorized: Literal[False] = False
    stale_surface_activation_authorized: Literal[False] = False


class MetricActionEvaluation(DispatchAuthorityBlock):
    """Evaluation of one metric contract against one dashboard row."""

    evaluation_id: str
    measurement_contract_ref: str
    dashboard_row_ref: str
    source_snapshot_ref: str
    action_class: ActionClass
    evidence_refs: list[str] = Field(min_length=1)
    threshold_basis: str
    state: MetricContractEvaluationState
    eligible_for_internal_followup: bool
    hold_or_block_required: bool
    fail_closed_reason: str | None = None

    @model_validator(mode="after")
    def _evaluation_state_is_coherent(self) -> Self:
        refs = [
            self.measurement_contract_ref,
            self.dashboard_row_ref,
            self.source_snapshot_ref,
            *self.evidence_refs,
        ]
        _reject_private_or_identity_refs(refs, "dispatch evaluation")

        if self.state is MetricContractEvaluationState.PASSED:
            if self.action_class not in ACTION_BEARING_CLASSES:
                raise ValueError("passed dispatch evaluations require action-bearing class")
            if not self.eligible_for_internal_followup:
                raise ValueError("passed dispatch evaluations must be eligible for followup")
            if self.hold_or_block_required:
                raise ValueError("passed dispatch evaluations cannot require hold/block")
            if self.fail_closed_reason is not None:
                raise ValueError("passed dispatch evaluations cannot carry fail reason")
        else:
            if self.eligible_for_internal_followup:
                raise ValueError("failed dispatch evaluations cannot be followup eligible")
            if not self.hold_or_block_required:
                raise ValueError("failed dispatch evaluations require hold/block")
            if not self.fail_closed_reason:
                raise ValueError("failed dispatch evaluations require fail-closed reason")
        return self


class InternalFollowUpTaskDraft(DispatchAuthorityBlock):
    """Private draft of possible work; it does not write a task file."""

    draft_id: str
    recommendation_kind: Literal[DispatchRecommendationKind.INTERNAL_FOLLOWUP_TASK_DRAFT] = (
        DispatchRecommendationKind.INTERNAL_FOLLOWUP_TASK_DRAFT
    )
    from_evaluation_id: str
    measurement_contract_ref: str
    dashboard_row_ref: str
    title: str
    objective: str
    rationale: str
    proposed_task_kind: Literal["internal_followup_only"] = "internal_followup_only"
    source_refs: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    consumer_permission_after: Literal["private_internal_recommendation_tests_only"]
    internal_followup_task_draft_authorized: Literal[True] = True
    creates_vault_task: Literal[False] = False
    sends_to_coordinator: Literal[False] = False

    @model_validator(mode="after")
    def _draft_is_private_and_symbolic(self) -> Self:
        _reject_private_or_identity_refs(
            [
                self.from_evaluation_id,
                self.measurement_contract_ref,
                self.dashboard_row_ref,
                *self.source_refs,
            ],
            "internal followup draft",
        )
        if "public" in self.title.lower():
            raise ValueError("internal followup draft title cannot imply public action")
        return self


class HoldBlockRecommendation(DispatchAuthorityBlock):
    """Private hold/block artifact for gaps, stale conflicts, or authority boundaries."""

    recommendation_id: str
    recommendation_kind: DispatchRecommendationKind
    from_evaluation_id: str
    measurement_contract_ref: str
    dashboard_row_ref: str
    decision_state: DecisionState
    stale_conflict_refs: list[str] = Field(default_factory=list)
    reason: str
    required_later_authority: str | None = None
    hold_block_recommendation_authorized: Literal[True] = True
    creates_vault_task: Literal[False] = False
    sends_to_coordinator: Literal[False] = False

    @model_validator(mode="after")
    def _hold_or_block_stays_closed(self) -> Self:
        _reject_private_or_identity_refs(
            [
                self.from_evaluation_id,
                self.measurement_contract_ref,
                self.dashboard_row_ref,
                *self.stale_conflict_refs,
            ],
            "hold/block recommendation",
        )
        if self.recommendation_kind not in {
            DispatchRecommendationKind.HOLD_RECOMMENDATION,
            DispatchRecommendationKind.BLOCK_RECOMMENDATION,
        }:
            raise ValueError("hold/block rows cannot be followup drafts")
        if (
            self.stale_conflict_refs
            and self.decision_state is not DecisionState.BLOCKED_STALE_CONFLICT
        ):
            raise ValueError("stale conflicts must stay blocked_stale_conflict")
        if (
            self.decision_state is DecisionState.BLOCKED_STALE_CONFLICT
            and not self.stale_conflict_refs
        ):
            raise ValueError("blocked stale conflicts require stale_conflict_refs")
        return self


class ResourceCapabilityDispatchPacket(DispatchAuthorityBlock):
    """Complete private dispatch metric packet."""

    schema_version: Literal[1] = 1
    packet_id: str
    evaluated_at: str
    authority_source: Literal["isap:resource-capability-dispatch-active-metrics-20260509"]
    generated_from: list[str] = Field(min_length=1)
    source_fixture_refs: list[str] = Field(min_length=3)
    privacy_scope: Literal["private"] = "private"
    consumer_permission_after: Literal["private_internal_recommendation_tests_only"]
    metric_evaluations: list[MetricActionEvaluation] = Field(min_length=1)
    internal_followup_task_drafts: list[InternalFollowUpTaskDraft] = Field(default_factory=list)
    hold_block_recommendations: list[HoldBlockRecommendation] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _packet_contract(self) -> Self:
        generated = set(self.generated_from)
        required_generated = {
            "shared/resource_capability.py",
            "shared/resource_capability_dashboard.py",
            "config/resource-capability-fixtures.json",
            "config/resource-capability-dashboard-fixtures.json",
        }
        if not required_generated.issubset(generated):
            missing = required_generated - generated
            raise ValueError(f"dispatch packet missing generated_from refs: {sorted(missing)}")

        _reject_private_or_identity_refs(
            [*self.generated_from, *self.source_fixture_refs, *self.evidence_refs],
            "dispatch packet",
        )

        evaluation_ids = [evaluation.evaluation_id for evaluation in self.metric_evaluations]
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("metric evaluation_id values must be unique")

        evaluations_by_id = {
            evaluation.evaluation_id: evaluation for evaluation in self.metric_evaluations
        }
        passed_ids = {
            evaluation.evaluation_id
            for evaluation in self.metric_evaluations
            if evaluation.state is MetricContractEvaluationState.PASSED
        }
        failed_ids = set(evaluations_by_id) - passed_ids

        draft_eval_ids = {draft.from_evaluation_id for draft in self.internal_followup_task_drafts}
        if not draft_eval_ids.issubset(passed_ids):
            raise ValueError("internal followup drafts require passed evaluations")

        hold_eval_ids = {
            recommendation.from_evaluation_id for recommendation in self.hold_block_recommendations
        }
        missing_holds = failed_ids - hold_eval_ids
        if missing_holds:
            raise ValueError(f"failed evaluations require hold/block rows: {sorted(missing_holds)}")

        if any(evaluations_by_id[eval_id].hold_or_block_required for eval_id in draft_eval_ids):
            raise ValueError("hold/block evaluations cannot produce followup drafts")
        return self


class ResourceCapabilityDispatchFixtureSet(StrictModel):
    """Private fixture set for RC-004 dispatch-active metric contracts."""

    schema_version: Literal[1] = 1
    fixture_set_id: str
    consumer_permission_after: Literal["private_internal_recommendation_tests_only"]
    dispatch_packets: list[ResourceCapabilityDispatchPacket] = Field(min_length=1)

    @model_validator(mode="after")
    def _fixture_set_stays_private(self) -> Self:
        if any(packet.public_projection_allowed for packet in self.dispatch_packets):
            raise ValueError("dispatch packets cannot allow public projection")
        if any(packet.task_file_write_authorized for packet in self.dispatch_packets):
            raise ValueError("dispatch packets cannot write task files")
        if any(packet.coordinator_send_authorized for packet in self.dispatch_packets):
            raise ValueError("dispatch packets cannot send coordinator messages")
        return self


def _reject_private_or_identity_refs(refs: list[str], label: str) -> None:
    if any(ref.startswith(("/", "~")) for ref in refs):
        raise ValueError(f"{label} refs must stay repo-relative or symbolic")
    if any("@" in ref for ref in refs):
        raise ValueError(f"{label} refs must not contain raw email addresses")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResourceCapabilityDispatchError(f"{path} did not contain a JSON object")
    return payload


def _validate_against_local_sources(fixtures: ResourceCapabilityDispatchFixtureSet) -> None:
    resource_fixtures = load_resource_capability_fixtures()
    dashboard_fixtures = load_resource_capability_dashboard_fixtures()

    contracts: dict[str, MeasurementActionContract] = {
        contract.metric_id: contract for contract in resource_fixtures.measurement_action_contracts
    }
    dashboard_rows = {
        row.row_id: row
        for snapshot in dashboard_fixtures.dashboard_snapshots
        for row in snapshot.dashboard_rows
    }
    dashboard_contract_refs = {
        ref
        for snapshot in dashboard_fixtures.dashboard_snapshots
        for ref in snapshot.measurement_contract_refs
    }

    for packet in fixtures.dispatch_packets:
        evaluations_by_id = {
            evaluation.evaluation_id: evaluation for evaluation in packet.metric_evaluations
        }
        for evaluation in packet.metric_evaluations:
            contract = contracts.get(evaluation.measurement_contract_ref)
            dashboard_row = dashboard_rows.get(evaluation.dashboard_row_ref)
            if dashboard_row is None:
                raise ResourceCapabilityDispatchError(
                    f"{evaluation.evaluation_id} references unknown dashboard row"
                )

            if contract is None:
                if evaluation.state is not MetricContractEvaluationState.MISSING_CONTRACT:
                    raise ResourceCapabilityDispatchError(
                        f"{evaluation.evaluation_id} missing contract must fail closed"
                    )
                continue

            if evaluation.action_class is not contract.action_class:
                raise ResourceCapabilityDispatchError(
                    f"{evaluation.evaluation_id} action_class does not match measurement contract"
                )
            if contract.metric_id not in dashboard_contract_refs:
                raise ResourceCapabilityDispatchError(
                    f"{evaluation.evaluation_id} measurement contract not present in dashboard snapshot"
                )
            if contract.action_class not in ACTION_BEARING_CLASSES:
                if evaluation.state is MetricContractEvaluationState.PASSED:
                    raise ResourceCapabilityDispatchError(
                        f"{evaluation.evaluation_id} observe-only contract cannot pass dispatch"
                    )
            if not contract.authoritative or contract.no_go_threshold is None:
                if evaluation.state is MetricContractEvaluationState.PASSED:
                    raise ResourceCapabilityDispatchError(
                        f"{evaluation.evaluation_id} non-authoritative contract cannot pass dispatch"
                    )
            if dashboard_row.stale_conflict_refs:
                if evaluation.state is MetricContractEvaluationState.PASSED:
                    raise ResourceCapabilityDispatchError(
                        f"{evaluation.evaluation_id} stale conflict row cannot pass dispatch"
                    )
                if evaluation.state is not MetricContractEvaluationState.BLOCKED_STALE_CONFLICT:
                    raise ResourceCapabilityDispatchError(
                        f"{evaluation.evaluation_id} stale conflict row must be blocked"
                    )

        for draft in packet.internal_followup_task_drafts:
            evaluation = evaluations_by_id[draft.from_evaluation_id]
            if evaluation.measurement_contract_ref != draft.measurement_contract_ref:
                raise ResourceCapabilityDispatchError(
                    f"{draft.draft_id} measurement contract mismatch"
                )
            if evaluation.dashboard_row_ref != draft.dashboard_row_ref:
                raise ResourceCapabilityDispatchError(f"{draft.draft_id} dashboard row mismatch")
            if evaluation.state is not MetricContractEvaluationState.PASSED:
                raise ResourceCapabilityDispatchError(
                    f"{draft.draft_id} requires passed evaluation"
                )


def load_resource_capability_dispatch_fixtures(
    path: Path = RESOURCE_CAPABILITY_DISPATCH_FIXTURES,
) -> ResourceCapabilityDispatchFixtureSet:
    """Load RC-004 dispatch fixtures, failing closed on malformed data."""

    try:
        fixtures = ResourceCapabilityDispatchFixtureSet.model_validate(_load_json_object(path))
        _validate_against_local_sources(fixtures)
        return fixtures
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ResourceCapabilityDispatchError(
            f"invalid resource capability dispatch fixtures at {path}: {exc}"
        ) from exc


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    MetricActionEvaluation._evaluation_state_is_coherent,
    InternalFollowUpTaskDraft._draft_is_private_and_symbolic,
    HoldBlockRecommendation._hold_or_block_stays_closed,
    ResourceCapabilityDispatchPacket._packet_contract,
    ResourceCapabilityDispatchFixtureSet._fixture_set_stays_private,
)


__all__ = [
    "ACTION_BEARING_CLASSES",
    "RESOURCE_CAPABILITY_DISPATCH_FIXTURES",
    "DispatchRecommendationKind",
    "HoldBlockRecommendation",
    "InternalFollowUpTaskDraft",
    "MetricActionEvaluation",
    "MetricContractEvaluationState",
    "ResourceCapabilityDispatchError",
    "ResourceCapabilityDispatchFixtureSet",
    "ResourceCapabilityDispatchPacket",
    "load_resource_capability_dispatch_fixtures",
]
