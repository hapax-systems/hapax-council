"""Application obligation refusal gate for grants and fellowships.

The gate keeps opportunity work from becoming hidden recurring operator labor
or false affiliation. It is intentionally deterministic: callers provide the
declared obligations and the gate returns allowed, guarded, or refused with
operator-visible reasons.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_PATH = REPO_ROOT / "config" / "application-obligation-refusal-fixtures.json"

type ObligationClass = Literal[
    "legal_attestation",
    "bootstrap_setup",
    "reporting",
    "public_demo",
    "custom_deliverable",
    "private_data_exposure",
    "institution_requirement",
    "community_client_service",
    "recurring_manual_labor",
]
type Disposition = Literal["allowed", "guarded", "refused"]
type Recurrence = Literal["one_time", "recurring", "unknown"]
type AutomationFit = Literal["automated", "operator_attestation", "manual", "unknown"]
type RefusalReason = Literal[
    "fake_affiliation",
    "manual_opportunity_chasing",
    "recurring_reports",
    "private_data_exposure",
    "custom_performance",
    "customer_service_obligation",
    "recurring_manual_labor",
    "unknown_obligation",
]
type OperatorAction = Literal[
    "none",
    "one_time_bootstrap",
    "explicit_legal_attestation",
    "guarded_public_demo_review",
    "institution_requirement_review",
]


class ObligationModel(BaseModel):
    """Shared frozen base for the obligation policy models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ObligationPolicy(ObligationModel):
    """Canonical disposition for one obligation class."""

    class_id: ObligationClass
    disposition: Disposition
    operator_action: OperatorAction
    operator_visible_reason: str = Field(min_length=1)


class ApplicationObligation(ObligationModel):
    """One declared application obligation."""

    class_id: ObligationClass
    recurrence: Recurrence
    automation_fit: AutomationFit
    summary: str = Field(min_length=1)


class ApplicationOpportunity(ObligationModel):
    """Application opportunity input to the refusal gate."""

    opportunity_id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    title: str = Field(min_length=1)
    obligations: tuple[ApplicationObligation, ...] = Field(min_length=1)
    requires_fake_affiliation: bool = False
    requires_manual_opportunity_chasing: bool = False


class ObligationDecision(ObligationModel):
    """Decision for one declared obligation."""

    class_id: ObligationClass
    disposition: Disposition
    operator_action: OperatorAction
    refusal_reasons: tuple[RefusalReason, ...]
    operator_visible_reason: str


class ApplicationDecision(ObligationModel):
    """Aggregate decision for an application opportunity."""

    opportunity_id: str
    decision: Disposition
    obligation_decisions: tuple[ObligationDecision, ...]
    refusal_reasons: tuple[RefusalReason, ...]
    operator_actions: tuple[OperatorAction, ...]
    operator_visible_reason: str


class ApplicationFixture(ObligationModel):
    """Fixture row proving an expected application decision."""

    fixture_id: str = Field(pattern=r"^[a-z0-9_]+$")
    opportunity: ApplicationOpportunity
    expected_decision: Disposition
    expected_refusal_reasons: tuple[RefusalReason, ...] = ()
    expected_operator_actions: tuple[OperatorAction, ...] = ()


class ApplicationObligationFixtureSet(ObligationModel):
    """Fixture packet for the application obligation refusal gate."""

    schema_version: Literal[1]
    policy_id: Literal["application_obligation_refusal_gate"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    obligation_policies: tuple[ObligationPolicy, ...] = Field(min_length=9)
    fixtures: tuple[ApplicationFixture, ...] = Field(min_length=7)


OBLIGATION_POLICIES: dict[ObligationClass, ObligationPolicy] = {
    policy.class_id: policy
    for policy in (
        ObligationPolicy(
            class_id="legal_attestation",
            disposition="allowed",
            operator_action="explicit_legal_attestation",
            operator_visible_reason=(
                "Legal attestation is allowed only as an explicit operator act, "
                "not recurring application labor."
            ),
        ),
        ObligationPolicy(
            class_id="bootstrap_setup",
            disposition="allowed",
            operator_action="one_time_bootstrap",
            operator_visible_reason=(
                "One-time account, credential, identity, or setup work is allowed "
                "when it unlocks an automated path."
            ),
        ),
        ObligationPolicy(
            class_id="reporting",
            disposition="guarded",
            operator_action="none",
            operator_visible_reason=(
                "Reporting is guarded and must be automated or one-time; recurring "
                "manual reports are refused."
            ),
        ),
        ObligationPolicy(
            class_id="public_demo",
            disposition="guarded",
            operator_action="guarded_public_demo_review",
            operator_visible_reason=(
                "Public demos require rights, privacy, egress, and readiness gates; "
                "they do not authorize custom performance labor."
            ),
        ),
        ObligationPolicy(
            class_id="custom_deliverable",
            disposition="refused",
            operator_action="none",
            operator_visible_reason=(
                "Custom deliverables or performances create bespoke service labor."
            ),
        ),
        ObligationPolicy(
            class_id="private_data_exposure",
            disposition="refused",
            operator_action="none",
            operator_visible_reason="Private data exposure is refused.",
        ),
        ObligationPolicy(
            class_id="institution_requirement",
            disposition="guarded",
            operator_action="institution_requirement_review",
            operator_visible_reason=(
                "Institutional requirements are guarded; fake affiliation is refused."
            ),
        ),
        ObligationPolicy(
            class_id="community_client_service",
            disposition="refused",
            operator_action="none",
            operator_visible_reason=(
                "Community, client, or customer service obligations are refused."
            ),
        ),
        ObligationPolicy(
            class_id="recurring_manual_labor",
            disposition="refused",
            operator_action="none",
            operator_visible_reason="Recurring manual operator labor is refused.",
        ),
    )
}

_REFUSAL_BY_CLASS: dict[ObligationClass, RefusalReason] = {
    "custom_deliverable": "custom_performance",
    "private_data_exposure": "private_data_exposure",
    "community_client_service": "customer_service_obligation",
    "recurring_manual_labor": "recurring_manual_labor",
}


def _dedupe_sorted[T: str](values: Iterable[T]) -> tuple[T, ...]:
    return tuple(sorted(set(values)))


def _decision_for_obligation(obligation: ApplicationObligation) -> ObligationDecision:
    policy = OBLIGATION_POLICIES[obligation.class_id]
    refusal_reasons: list[RefusalReason] = []
    disposition = policy.disposition

    if obligation.class_id == "reporting" and (
        obligation.recurrence == "recurring" or obligation.automation_fit in {"manual", "unknown"}
    ):
        disposition = "refused"
        refusal_reasons.append("recurring_reports")
    elif obligation.class_id in _REFUSAL_BY_CLASS:
        refusal_reasons.append(_REFUSAL_BY_CLASS[obligation.class_id])

    return ObligationDecision(
        class_id=obligation.class_id,
        disposition=disposition,
        operator_action=policy.operator_action,
        refusal_reasons=tuple(refusal_reasons),
        operator_visible_reason=policy.operator_visible_reason,
    )


def evaluate_application_obligation(opportunity: ApplicationOpportunity) -> ApplicationDecision:
    """Evaluate an application opportunity against the refusal gate."""

    obligation_decisions = tuple(
        _decision_for_obligation(obligation) for obligation in opportunity.obligations
    )
    refusal_reasons: list[RefusalReason] = []
    if opportunity.requires_fake_affiliation:
        refusal_reasons.append("fake_affiliation")
    if opportunity.requires_manual_opportunity_chasing:
        refusal_reasons.append("manual_opportunity_chasing")

    for decision in obligation_decisions:
        refusal_reasons.extend(decision.refusal_reasons)

    refused = bool(refusal_reasons) or any(
        decision.disposition == "refused" for decision in obligation_decisions
    )
    guarded = any(decision.disposition == "guarded" for decision in obligation_decisions)
    if refused:
        aggregate: Disposition = "refused"
        reason = "application carries refused obligations"
    elif guarded:
        aggregate = "guarded"
        reason = "application requires guarded evidence or readiness review"
    else:
        aggregate = "allowed"
        reason = "application obligations are limited to bootstrap or legal attestation"

    operator_actions = _dedupe_sorted(
        decision.operator_action
        for decision in obligation_decisions
        if decision.operator_action != "none"
    )

    return ApplicationDecision(
        opportunity_id=opportunity.opportunity_id,
        decision=aggregate,
        obligation_decisions=obligation_decisions,
        refusal_reasons=tuple(_dedupe_sorted(refusal_reasons)),
        operator_actions=operator_actions,
        operator_visible_reason=reason,
    )


def load_application_obligation_fixtures(
    path: Path = DEFAULT_FIXTURE_PATH,
) -> ApplicationObligationFixtureSet:
    """Load and validate the canonical application-obligation fixture packet."""

    return ApplicationObligationFixtureSet.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )
