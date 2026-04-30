"""Typed conversion target readiness matrix.

This module is intentionally small: it loads the canonical threshold matrix and
offers a deterministic fail-closed decision helper for downstream conversion,
grant, monetization, and N=1 packaging work.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX_PATH = REPO_ROOT / "config" / "conversion-target-readiness-threshold-matrix.json"

type ReadinessState = Literal[
    "blocked",
    "private-evidence",
    "dry-run",
    "public-archive",
    "public-live",
    "public-monetizable",
    "refused",
]
type GateDimension = Literal[
    "wcs",
    "programme",
    "public_event",
    "archive",
    "rights",
    "privacy",
    "provenance",
    "egress",
    "monetization",
    "operator_attestation",
    "no_hidden_operator_labor",
]
type TargetFamilyId = Literal[
    "grants_fellowships",
    "youtube_vod_packaging",
    "replay_demo",
    "dataset_card",
    "artifact_edition_release",
    "support_prompt",
    "residency",
    "licensing",
]
type AntiOverclaimSignal = Literal[
    "engagement",
    "revenue_potential",
    "trend",
    "operator_desire",
]

READINESS_STATES: tuple[ReadinessState, ...] = (
    "blocked",
    "private-evidence",
    "dry-run",
    "public-archive",
    "public-live",
    "public-monetizable",
    "refused",
)
PUBLIC_READINESS_STATES: frozenset[ReadinessState] = frozenset(
    {"public-archive", "public-live", "public-monetizable"}
)
REQUIRED_GATE_DIMENSIONS: frozenset[GateDimension] = frozenset(
    {
        "wcs",
        "programme",
        "public_event",
        "archive",
        "rights",
        "privacy",
        "provenance",
        "egress",
        "monetization",
        "operator_attestation",
        "no_hidden_operator_labor",
    }
)
REQUIRED_TARGET_FAMILIES: frozenset[TargetFamilyId] = frozenset(
    {
        "grants_fellowships",
        "youtube_vod_packaging",
        "replay_demo",
        "dataset_card",
        "artifact_edition_release",
        "support_prompt",
        "residency",
        "licensing",
    }
)


class MatrixModel(BaseModel):
    """Shared frozen model base for the readiness matrix."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class AntiOverclaimPolicy(MatrixModel):
    """Signals that may inform opportunity priority but never readiness."""

    engagement_can_upgrade: Literal[False]
    revenue_potential_can_upgrade: Literal[False]
    trend_can_upgrade: Literal[False]
    operator_desire_can_upgrade: Literal[False]
    selected_or_commanded_is_success: Literal[False]
    refusal_can_validate_refused_claim: Literal[False]
    notes: tuple[str, ...] = Field(min_length=4)


class GateRequirement(MatrixModel):
    """One required evidence gate for a target family."""

    gate_ref: str = Field(min_length=1)
    required_for_states: tuple[ReadinessState, ...]
    operator_visible_reason: str = Field(min_length=1)
    evidence_ref_examples: tuple[str, ...] = Field(min_length=1)


class ConversionTargetThreshold(MatrixModel):
    """Threshold row for a conversion target family."""

    target_family_id: TargetFamilyId
    display_name: str = Field(min_length=1)
    target_policy_ref: str = Field(min_length=1)
    default_state: Literal["blocked"]
    allowed_states: tuple[ReadinessState, ...] = Field(min_length=2)
    private_evidence_allowed: bool
    public_release_allowed: bool
    monetization_allowed: bool
    operator_attestation_required: bool
    gate_requirements: dict[GateDimension, GateRequirement]
    downstream_consumers: tuple[str, ...] = Field(min_length=1)
    anti_overclaim_notes: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_target_gate_contract(self) -> Self:
        missing_dimensions = REQUIRED_GATE_DIMENSIONS - set(self.gate_requirements)
        if missing_dimensions:
            msg = f"{self.target_family_id} missing gate dimensions: {sorted(missing_dimensions)!r}"
            raise ValueError(msg)

        allowed = set(self.allowed_states)
        if "blocked" not in allowed or "refused" not in allowed:
            msg = f"{self.target_family_id} must explicitly allow blocked/refused states"
            raise ValueError(msg)
        if "private-evidence" in allowed and not self.private_evidence_allowed:
            msg = f"{self.target_family_id} allows private evidence but marks it disallowed"
            raise ValueError(msg)
        if allowed & PUBLIC_READINESS_STATES and not self.public_release_allowed:
            msg = f"{self.target_family_id} allows public states but public_release_allowed=false"
            raise ValueError(msg)
        if "public-monetizable" in allowed and not self.monetization_allowed:
            msg = f"{self.target_family_id} allows monetizable state without monetization authority"
            raise ValueError(msg)

        terminal_states: set[ReadinessState] = {"blocked", "refused"}
        for state in allowed - terminal_states:
            missing_for_state = self.missing_required_dimensions_for_state(state)
            if missing_for_state:
                msg = (
                    f"{self.target_family_id} state {state} has no listed requirement for "
                    f"{sorted(missing_for_state)!r}"
                )
                raise ValueError(msg)

        if self.operator_attestation_required:
            attestation = self.gate_requirements["operator_attestation"]
            if not attestation.required_for_states:
                msg = f"{self.target_family_id} requires attestation but no state requires it"
                raise ValueError(msg)

        monetization_gate = self.gate_requirements["monetization"]
        if "public-monetizable" in allowed and "public-monetizable" not in (
            monetization_gate.required_for_states
        ):
            msg = f"{self.target_family_id} monetizable state must require monetization gate"
            raise ValueError(msg)

        labor_gate = self.gate_requirements["no_hidden_operator_labor"]
        public_or_money_states = allowed & (PUBLIC_READINESS_STATES | {"private-evidence"})
        if public_or_money_states and not (
            set(labor_gate.required_for_states) & public_or_money_states
        ):
            msg = (
                f"{self.target_family_id} lacks no-hidden-operator-labor gate for "
                "private/public conversion"
            )
            raise ValueError(msg)
        return self

    def required_dimensions_for_state(self, state: ReadinessState) -> frozenset[GateDimension]:
        """Return all gate dimensions required to enter ``state``."""

        return frozenset(
            dimension
            for dimension, requirement in self.gate_requirements.items()
            if state in requirement.required_for_states
        )

    def missing_required_dimensions_for_state(
        self,
        state: ReadinessState,
    ) -> frozenset[GateDimension]:
        """Return listed dimensions that should gate non-terminal states but do not."""

        if state in {"blocked", "refused"}:
            return frozenset()
        if state == "private-evidence":
            minimum = frozenset(
                {"wcs", "programme", "privacy", "provenance", "no_hidden_operator_labor"}
            )
            if self.operator_attestation_required:
                minimum = minimum | {"operator_attestation"}
            return minimum - self.required_dimensions_for_state(state)
        if state == "dry-run":
            return frozenset(
                {
                    "wcs",
                    "programme",
                    "privacy",
                    "provenance",
                    "no_hidden_operator_labor",
                }
            ) - self.required_dimensions_for_state(state)
        if state in PUBLIC_READINESS_STATES:
            minimum = frozenset(
                {
                    "wcs",
                    "programme",
                    "public_event",
                    "archive",
                    "rights",
                    "privacy",
                    "provenance",
                    "egress",
                    "no_hidden_operator_labor",
                }
            )
            if state == "public-monetizable":
                minimum = minimum | {"monetization"}
            return minimum - self.required_dimensions_for_state(state)
        return frozenset()


class FailureFixture(MatrixModel):
    """Negative fixture proving value signals cannot upgrade readiness."""

    fixture_id: str = Field(pattern=r"^[a-z0-9_]+$")
    target_family_id: TargetFamilyId
    requested_state: ReadinessState
    expected_state: Literal["blocked", "refused"]
    missing_gate_dimensions: tuple[GateDimension, ...] = Field(min_length=1)
    high_monetary_value: bool
    input_signals: tuple[AntiOverclaimSignal, ...]
    operator_visible_reason: str = Field(min_length=1)


class ConversionReadinessDecision(MatrixModel):
    """Result of evaluating a target family against available evidence."""

    target_family_id: TargetFamilyId
    requested_state: ReadinessState
    effective_state: ReadinessState
    allowed: bool
    missing_gate_dimensions: tuple[GateDimension, ...]
    operator_visible_reason: str


class ConversionTargetReadinessMatrix(MatrixModel):
    """Canonical matrix for target-family readiness thresholds."""

    schema_version: Literal[1]
    matrix_id: Literal["conversion_target_readiness_threshold_matrix"]
    declared_at: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    schema_ref: Literal["schemas/conversion-target-readiness-threshold-matrix.schema.json"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    readiness_states: tuple[ReadinessState, ...]
    minimum_evidence_chain: tuple[str, ...] = Field(min_length=8)
    anti_overclaim_policy: AntiOverclaimPolicy
    target_families: tuple[ConversionTargetThreshold, ...] = Field(min_length=8)
    failure_fixtures: tuple[FailureFixture, ...] = Field(min_length=5)

    @model_validator(mode="after")
    def validate_matrix_contract(self) -> Self:
        if self.readiness_states != READINESS_STATES:
            msg = f"readiness_states must be {READINESS_STATES!r}"
            raise ValueError(msg)

        family_ids = [target.target_family_id for target in self.target_families]
        duplicate_families = sorted(
            {family_id for family_id in family_ids if family_ids.count(family_id) > 1}
        )
        if duplicate_families:
            msg = f"duplicate target family ids: {duplicate_families!r}"
            raise ValueError(msg)

        family_id_set: set[TargetFamilyId] = set(family_ids)
        missing_families = REQUIRED_TARGET_FAMILIES - family_id_set
        if missing_families:
            msg = f"matrix missing target families: {sorted(missing_families)!r}"
            raise ValueError(msg)

        target_by_id = {target.target_family_id: target for target in self.target_families}
        for fixture in self.failure_fixtures:
            target = target_by_id[fixture.target_family_id]
            if fixture.requested_state not in target.allowed_states:
                msg = (
                    f"{fixture.fixture_id} requested state {fixture.requested_state} is not "
                    f"allowed for {fixture.target_family_id}"
                )
                raise ValueError(msg)
            required = target.required_dimensions_for_state(fixture.requested_state)
            if not (set(fixture.missing_gate_dimensions) & required):
                msg = f"{fixture.fixture_id} does not omit a required gate"
                raise ValueError(msg)
            if fixture.high_monetary_value and fixture.expected_state not in {"blocked", "refused"}:
                msg = f"{fixture.fixture_id} lets high monetary value upgrade readiness"
                raise ValueError(msg)
        return self

    def by_family_id(self) -> dict[TargetFamilyId, ConversionTargetThreshold]:
        """Return target rows keyed by target family id."""

        return {target.target_family_id: target for target in self.target_families}


def load_conversion_target_readiness_matrix(
    path: Path = DEFAULT_MATRIX_PATH,
) -> ConversionTargetReadinessMatrix:
    """Load and validate the canonical conversion target readiness matrix."""

    return ConversionTargetReadinessMatrix.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def decide_readiness_state(
    matrix: ConversionTargetReadinessMatrix,
    target_family_id: TargetFamilyId,
    requested_state: ReadinessState,
    satisfied_gate_dimensions: Iterable[GateDimension],
) -> ConversionReadinessDecision:
    """Evaluate one requested readiness state against available gate evidence."""

    target = matrix.by_family_id()[target_family_id]
    satisfied = frozenset(satisfied_gate_dimensions)
    if requested_state not in target.allowed_states:
        return ConversionReadinessDecision(
            target_family_id=target_family_id,
            requested_state=requested_state,
            effective_state="blocked",
            allowed=False,
            missing_gate_dimensions=(),
            operator_visible_reason=f"{requested_state} is not allowed for {target_family_id}",
        )

    if requested_state in PUBLIC_READINESS_STATES and not target.public_release_allowed:
        return ConversionReadinessDecision(
            target_family_id=target_family_id,
            requested_state=requested_state,
            effective_state="blocked",
            allowed=False,
            missing_gate_dimensions=(),
            operator_visible_reason=f"{target_family_id} is not public-release ready",
        )

    missing_dimensions = tuple(
        sorted(target.required_dimensions_for_state(requested_state) - satisfied)
    )
    if missing_dimensions:
        first_missing = missing_dimensions[0]
        reason = target.gate_requirements[first_missing].operator_visible_reason
        return ConversionReadinessDecision(
            target_family_id=target_family_id,
            requested_state=requested_state,
            effective_state="blocked",
            allowed=False,
            missing_gate_dimensions=missing_dimensions,
            operator_visible_reason=reason,
        )

    return ConversionReadinessDecision(
        target_family_id=target_family_id,
        requested_state=requested_state,
        effective_state=requested_state,
        allowed=requested_state not in {"blocked", "refused"},
        missing_gate_dimensions=(),
        operator_visible_reason="all required gate dimensions have evidence",
    )


def evaluate_failure_fixture(
    matrix: ConversionTargetReadinessMatrix,
    fixture: FailureFixture,
) -> ConversionReadinessDecision:
    """Evaluate a negative fixture by withholding its missing gate dimensions."""

    target = matrix.by_family_id()[fixture.target_family_id]
    required = target.required_dimensions_for_state(fixture.requested_state)
    satisfied = required - set(fixture.missing_gate_dimensions)
    return decide_readiness_state(
        matrix,
        fixture.target_family_id,
        fixture.requested_state,
        satisfied,
    )
