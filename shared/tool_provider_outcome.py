"""Typed outcome envelope for tool/model/provider calls.

This contract sits below action receipts and above provider/tool health. It
records what a route actually returned, what evidence it acquired or was
given, and the maximum claim authority downstream code may infer from it.
It does not wire any runtime callsite.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PROVIDER_OUTCOME_FIXTURES = REPO_ROOT / "config" / "tool-provider-outcome-fixtures.json"

REQUIRED_TOOL_PROVIDER_FIXTURE_CASES = frozenset(
    {
        "source_acquired",
        "supplied_evidence",
        "redacted",
        "blocked",
        "error",
        "unsupported_claim",
    }
)

TOOL_PROVIDER_OUTCOME_REQUIRED_FIELDS = (
    "schema_version",
    "outcome_id",
    "created_at",
    "provider_id",
    "provider_kind",
    "model_id",
    "tool_id",
    "route_id",
    "route_ref",
    "result_status",
    "acquisition_mode",
    "source_acquired",
    "source_acquisition_evidence_refs",
    "acquired_source_refs",
    "supplied_evidence_refs",
    "evidence_refs",
    "redaction_privacy_state",
    "redaction_applied",
    "redaction_evidence_refs",
    "error",
    "authority_ceiling",
    "claim_support",
    "fresh_source_claim_supported",
    "supplied_evidence_claim_supported",
    "public_claim_supported",
    "witnessed_world_truth",
    "unsupported_claim_reasons",
    "blocked_reasons",
    "operator_visible_summary",
    "fixture_case",
)


class ToolProviderOutcomeError(ValueError):
    """Raised when tool/provider outcome fixtures fail closed."""


class ProviderKind(StrEnum):
    MODEL_PROVIDER = "model_provider"
    SEARCH_PROVIDER = "search_provider"
    MCP_TOOL = "mcp_tool"
    LOCAL_TOOL = "local_tool"
    PUBLICATION_ENDPOINT = "publication_endpoint"
    LOCAL_API = "local_api"


class ResultStatus(StrEnum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"
    UNSUPPORTED_CLAIM = "unsupported_claim"


class SourceAcquisitionMode(StrEnum):
    SOURCE_ACQUIRED = "source_acquired"
    SUPPLIED_EVIDENCE = "supplied_evidence"
    NO_SOURCE_ACQUISITION = "no_source_acquisition"
    SOURCE_ACQUISITION_FAILED = "source_acquisition_failed"


class RedactionPrivacyState(StrEnum):
    PUBLIC_SAFE = "public_safe"
    REDACTED = "redacted"
    REDACTION_REQUIRED = "redaction_required"
    PRIVATE_ONLY = "private_only"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ProviderErrorKind(StrEnum):
    POLICY_BLOCK = "policy_block"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    SOURCE_ACQUISITION_FAILED = "source_acquisition_failed"
    UNSUPPORTED_CLAIM = "unsupported_claim"


class AuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    SPECULATIVE = "speculative"
    EVIDENCE_BOUND = "evidence_bound"
    POSTERIOR_BOUND = "posterior_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class ClaimSupport(StrEnum):
    NOT_CLAIM_BEARING = "not_claim_bearing"
    FRESH_SOURCE = "fresh_source"
    SUPPLIED_EVIDENCE = "supplied_evidence"
    UNSUPPORTED = "unsupported"


class ToolProviderFixtureCase(StrEnum):
    SOURCE_ACQUIRED = "source_acquired"
    SUPPLIED_EVIDENCE = "supplied_evidence"
    REDACTED = "redacted"
    BLOCKED = "blocked"
    ERROR = "error"
    UNSUPPORTED_CLAIM = "unsupported_claim"


class ToolProviderError(BaseModel):
    """Structured provider/tool failure evidence."""

    model_config = ConfigDict(extra="forbid")

    kind: ProviderErrorKind
    message: str = Field(min_length=1)
    retryable: bool
    evidence_refs: list[str] = Field(min_length=1)


class ToolProviderOutcomeEnvelope(BaseModel):
    """Outcome of one tool/model/provider call before action-receipt use."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    outcome_id: str = Field(pattern=r"^tpo:[a-z0-9_.:-]+$")
    created_at: str
    provider_id: str = Field(min_length=1)
    provider_kind: ProviderKind
    model_id: str | None = None
    tool_id: str | None = None
    route_id: str = Field(min_length=1)
    route_ref: str = Field(min_length=1)
    result_status: ResultStatus
    acquisition_mode: SourceAcquisitionMode
    source_acquired: bool
    source_acquisition_evidence_refs: list[str] = Field(default_factory=list)
    acquired_source_refs: list[str] = Field(default_factory=list)
    supplied_evidence_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    redaction_privacy_state: RedactionPrivacyState
    redaction_applied: bool
    redaction_evidence_refs: list[str] = Field(default_factory=list)
    error: ToolProviderError | None = None
    authority_ceiling: AuthorityCeiling
    claim_support: ClaimSupport
    fresh_source_claim_supported: bool
    supplied_evidence_claim_supported: bool
    public_claim_supported: bool
    witnessed_world_truth: Literal[False] = False
    unsupported_claim_reasons: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    operator_visible_summary: str = Field(min_length=1)
    fixture_case: ToolProviderFixtureCase

    @model_validator(mode="after")
    def _validate_source_acquisition_mode(self) -> Self:
        if self.acquisition_mode is SourceAcquisitionMode.SOURCE_ACQUIRED:
            if not self.source_acquired:
                raise ValueError(f"{self.outcome_id} source-acquired mode requires true flag")
            if not self.acquired_source_refs or not self.source_acquisition_evidence_refs:
                raise ValueError(
                    f"{self.outcome_id} source-acquired mode requires source and "
                    "acquisition evidence refs"
                )
            if self.supplied_evidence_refs:
                raise ValueError(
                    f"{self.outcome_id} source-acquired mode cannot also be supplied evidence"
                )
        elif self.acquisition_mode is SourceAcquisitionMode.SUPPLIED_EVIDENCE:
            if self.source_acquired or self.acquired_source_refs:
                raise ValueError(
                    f"{self.outcome_id} supplied evidence cannot claim source acquisition"
                )
            if self.source_acquisition_evidence_refs:
                raise ValueError(
                    f"{self.outcome_id} supplied evidence cannot carry acquisition evidence refs"
                )
            if not self.supplied_evidence_refs:
                raise ValueError(f"{self.outcome_id} supplied evidence mode requires refs")
        elif self.acquisition_mode is SourceAcquisitionMode.NO_SOURCE_ACQUISITION:
            if (
                self.source_acquired
                or self.acquired_source_refs
                or self.source_acquisition_evidence_refs
            ):
                raise ValueError(f"{self.outcome_id} no-source mode cannot carry acquisition refs")
        elif self.acquisition_mode is SourceAcquisitionMode.SOURCE_ACQUISITION_FAILED:
            if self.source_acquired or self.acquired_source_refs:
                raise ValueError(f"{self.outcome_id} failed acquisition cannot acquire sources")
        return self

    @model_validator(mode="after")
    def _validate_status_error_and_authority(self) -> Self:
        if self.result_status is ResultStatus.SUCCESS:
            if self.error is not None:
                raise ValueError(f"{self.outcome_id} successful outcome cannot carry error")
            if self.blocked_reasons:
                raise ValueError(f"{self.outcome_id} successful outcome cannot be blocked")
            if not self.evidence_refs:
                raise ValueError(f"{self.outcome_id} successful outcome requires evidence refs")
            if self.authority_ceiling is AuthorityCeiling.NO_CLAIM:
                raise ValueError(f"{self.outcome_id} bare success requires an authority ceiling")
            if self.claim_support in {
                ClaimSupport.NOT_CLAIM_BEARING,
                ClaimSupport.UNSUPPORTED,
            }:
                raise ValueError(f"{self.outcome_id} success requires bounded claim support")
        if self.result_status is ResultStatus.BLOCKED:
            if not self.blocked_reasons:
                raise ValueError(f"{self.outcome_id} blocked outcome requires blocked_reasons")
            if self.error and self.error.kind is not ProviderErrorKind.POLICY_BLOCK:
                raise ValueError(f"{self.outcome_id} blocked outcome error must be policy_block")
        if self.result_status is ResultStatus.ERROR:
            if self.error is None:
                raise ValueError(f"{self.outcome_id} error outcome requires error")
            if self.public_claim_supported:
                raise ValueError(f"{self.outcome_id} error outcome cannot support public claims")
        if self.result_status is ResultStatus.UNSUPPORTED_CLAIM:
            if not self.unsupported_claim_reasons:
                raise ValueError(
                    f"{self.outcome_id} unsupported claim requires unsupported_claim_reasons"
                )
            if self.public_claim_supported or self.fresh_source_claim_supported:
                raise ValueError(f"{self.outcome_id} unsupported claim cannot support claims")
        return self

    @model_validator(mode="after")
    def _validate_claim_support(self) -> Self:
        if self.fresh_source_claim_supported:
            if self.claim_support is not ClaimSupport.FRESH_SOURCE:
                raise ValueError(f"{self.outcome_id} fresh-source support needs claim_support")
            if self.acquisition_mode is not SourceAcquisitionMode.SOURCE_ACQUIRED:
                raise ValueError(
                    f"{self.outcome_id} fresh-source support requires source acquisition"
                )
            if not self.source_acquisition_evidence_refs or not self.acquired_source_refs:
                raise ValueError(
                    f"{self.outcome_id} fresh-source support requires acquisition evidence"
                )
            if self.authority_ceiling not in {
                AuthorityCeiling.EVIDENCE_BOUND,
                AuthorityCeiling.POSTERIOR_BOUND,
                AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            }:
                raise ValueError(
                    f"{self.outcome_id} fresh-source support has insufficient authority ceiling"
                )
        if self.supplied_evidence_claim_supported:
            if self.claim_support is not ClaimSupport.SUPPLIED_EVIDENCE:
                raise ValueError(f"{self.outcome_id} supplied support needs claim_support")
            if self.acquisition_mode is not SourceAcquisitionMode.SUPPLIED_EVIDENCE:
                raise ValueError(
                    f"{self.outcome_id} supplied support requires supplied evidence mode"
                )
            if not self.supplied_evidence_refs:
                raise ValueError(f"{self.outcome_id} supplied support requires supplied refs")
            if self.fresh_source_claim_supported:
                raise ValueError(
                    f"{self.outcome_id} supplied evidence cannot be fresh source support"
                )
        if self.claim_support is ClaimSupport.UNSUPPORTED:
            if (
                self.fresh_source_claim_supported
                or self.supplied_evidence_claim_supported
                or self.public_claim_supported
            ):
                raise ValueError(f"{self.outcome_id} unsupported support must not support claims")
        return self

    @model_validator(mode="after")
    def _validate_redaction_and_public_claims(self) -> Self:
        if self.redaction_applied and not self.redaction_evidence_refs:
            raise ValueError(f"{self.outcome_id} redaction applied requires evidence refs")
        if self.redaction_privacy_state in {
            RedactionPrivacyState.REDACTED,
            RedactionPrivacyState.REDACTION_REQUIRED,
            RedactionPrivacyState.PRIVATE_ONLY,
            RedactionPrivacyState.BLOCKED,
        }:
            if not self.redaction_evidence_refs:
                raise ValueError(f"{self.outcome_id} non-public privacy state needs evidence")
            if self.public_claim_supported:
                raise ValueError(
                    f"{self.outcome_id} redacted/private/blocked output cannot support "
                    "public claims"
                )
        if self.public_claim_supported:
            if self.redaction_privacy_state is not RedactionPrivacyState.PUBLIC_SAFE:
                raise ValueError(f"{self.outcome_id} public claim needs public-safe privacy")
            if not (self.fresh_source_claim_supported or self.supplied_evidence_claim_supported):
                raise ValueError(f"{self.outcome_id} public claim needs bounded evidence support")
            if self.authority_ceiling not in {
                AuthorityCeiling.EVIDENCE_BOUND,
                AuthorityCeiling.POSTERIOR_BOUND,
                AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            }:
                raise ValueError(f"{self.outcome_id} public claim authority ceiling too low")
        return self

    def can_support_fresh_source_claim(self) -> bool:
        """Return true only for fresh-source claims backed by acquired sources."""

        return (
            self.result_status is ResultStatus.SUCCESS
            and self.fresh_source_claim_supported
            and self.acquisition_mode is SourceAcquisitionMode.SOURCE_ACQUIRED
            and bool(self.source_acquisition_evidence_refs)
            and bool(self.acquired_source_refs)
        )

    def can_support_supplied_evidence_claim(self) -> bool:
        """Return true when the result is bounded to explicitly supplied refs."""

        return (
            self.result_status is ResultStatus.SUCCESS
            and self.supplied_evidence_claim_supported
            and self.acquisition_mode is SourceAcquisitionMode.SUPPLIED_EVIDENCE
            and bool(self.supplied_evidence_refs)
            and not self.source_acquired
        )

    def can_support_public_claim(self) -> bool:
        """Return true when public consumers may use the result as claim evidence."""

        return self.public_claim_supported and self.redaction_privacy_state is (
            RedactionPrivacyState.PUBLIC_SAFE
        )

    def action_receipt_consumption_refs(self) -> list[str]:
        """Evidence refs a future action receipt may cite without runtime wiring."""

        refs = [
            *self.evidence_refs,
            *self.source_acquisition_evidence_refs,
            *self.acquired_source_refs,
            *self.supplied_evidence_refs,
            *self.redaction_evidence_refs,
        ]
        if self.error is not None:
            refs.extend(self.error.evidence_refs)
        return list(dict.fromkeys(refs))


class ToolProviderOutcomeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_outcomes: int = Field(ge=0)
    by_fixture_case: dict[str, int]
    fresh_source_claim_supported_count: int = Field(ge=0)
    supplied_evidence_claim_supported_count: int = Field(ge=0)
    public_claim_supported_count: int = Field(ge=0)
    blocked_or_error_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)


class ToolProviderOutcomeFixtureSet(BaseModel):
    """Fixture set for typed tool/provider outcomes."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/tool-provider-outcome-envelope.schema.json"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    outcome_envelope_required_fields: list[str] = Field(min_length=1)
    fixture_cases: list[ToolProviderFixtureCase] = Field(min_length=1)
    outcomes: list[ToolProviderOutcomeEnvelope] = Field(min_length=1)
    summary: ToolProviderOutcomeSummary
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_fixture_set_contract(self) -> Self:
        if set(self.outcome_envelope_required_fields) != set(TOOL_PROVIDER_OUTCOME_REQUIRED_FIELDS):
            raise ValueError("outcome_envelope_required_fields does not match typed contract")

        cases = {case.value for case in self.fixture_cases}
        missing_cases = REQUIRED_TOOL_PROVIDER_FIXTURE_CASES - cases
        if missing_cases:
            raise ValueError(
                "missing tool/provider fixture cases: " + ", ".join(sorted(missing_cases))
            )

        outcome_cases = {outcome.fixture_case.value for outcome in self.outcomes}
        missing_outcome_cases = REQUIRED_TOOL_PROVIDER_FIXTURE_CASES - outcome_cases
        if missing_outcome_cases:
            raise ValueError(
                "outcomes do not cover fixture cases: " + ", ".join(sorted(missing_outcome_cases))
            )

        if self.fail_closed_policy != {
            "model_tool_success_is_witnessed_world_truth": False,
            "supplied_evidence_counts_as_source_acquisition": False,
            "source_claim_without_acquisition_evidence_allowed": False,
            "redacted_output_can_support_public_claim": False,
            "error_or_blocked_route_counts_as_success": False,
            "unsupported_claim_can_update_action_receipt": False,
        }:
            raise ValueError("tool/provider fail_closed_policy must pin gates false")

        expected_summary = ToolProviderOutcomeSummary(
            total_outcomes=len(self.outcomes),
            by_fixture_case={
                case.value: [outcome.fixture_case for outcome in self.outcomes].count(case)
                for case in sorted({outcome.fixture_case for outcome in self.outcomes})
            },
            fresh_source_claim_supported_count=sum(
                outcome.can_support_fresh_source_claim() for outcome in self.outcomes
            ),
            supplied_evidence_claim_supported_count=sum(
                outcome.can_support_supplied_evidence_claim() for outcome in self.outcomes
            ),
            public_claim_supported_count=sum(
                outcome.can_support_public_claim() for outcome in self.outcomes
            ),
            blocked_or_error_count=sum(
                outcome.result_status in {ResultStatus.BLOCKED, ResultStatus.ERROR}
                for outcome in self.outcomes
            ),
            unsupported_claim_count=sum(
                outcome.result_status is ResultStatus.UNSUPPORTED_CLAIM for outcome in self.outcomes
            ),
        )
        if self.summary != expected_summary:
            raise ValueError("summary does not match tool/provider outcomes")
        return self

    def require_outcome(self, outcome_id: str) -> ToolProviderOutcomeEnvelope:
        """Return one fixture outcome by id or fail closed."""

        for outcome in self.outcomes:
            if outcome.outcome_id == outcome_id:
                return outcome
        raise ToolProviderOutcomeError(f"missing tool/provider outcome fixture {outcome_id}")

    def rows_for_fixture_case(
        self, fixture_case: ToolProviderFixtureCase
    ) -> list[ToolProviderOutcomeEnvelope]:
        """Return all rows for a fixture case."""

        return [outcome for outcome in self.outcomes if outcome.fixture_case is fixture_case]


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ToolProviderOutcomeError(f"{path} did not contain a JSON object")
    return payload


def load_tool_provider_outcome_fixtures(
    path: Path = TOOL_PROVIDER_OUTCOME_FIXTURES,
) -> ToolProviderOutcomeFixtureSet:
    """Load typed tool/provider outcome fixtures, failing closed on drift."""

    try:
        return ToolProviderOutcomeFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ToolProviderOutcomeError(
            f"invalid tool/provider outcome fixtures at {path}: {exc}"
        ) from exc


__all__ = [
    "REQUIRED_TOOL_PROVIDER_FIXTURE_CASES",
    "TOOL_PROVIDER_OUTCOME_FIXTURES",
    "TOOL_PROVIDER_OUTCOME_REQUIRED_FIELDS",
    "AuthorityCeiling",
    "ClaimSupport",
    "ProviderErrorKind",
    "ProviderKind",
    "RedactionPrivacyState",
    "ResultStatus",
    "SourceAcquisitionMode",
    "ToolProviderError",
    "ToolProviderFixtureCase",
    "ToolProviderOutcomeEnvelope",
    "ToolProviderOutcomeError",
    "ToolProviderOutcomeFixtureSet",
    "load_tool_provider_outcome_fixtures",
]
