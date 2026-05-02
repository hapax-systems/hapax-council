"""Tests for typed tool/provider outcome envelopes."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from shared.tool_provider_outcome import (
    REQUIRED_TOOL_PROVIDER_FIXTURE_CASES,
    TOOL_PROVIDER_OUTCOME_FIXTURES,
    TOOL_PROVIDER_OUTCOME_REQUIRED_FIELDS,
    AuthorityCeiling,
    RedactionPrivacyState,
    ResultStatus,
    SourceAcquisitionMode,
    ToolProviderOutcomeEnvelope,
    ToolProviderOutcomeError,
    ToolProviderOutcomeFixtureSet,
    load_tool_provider_outcome_fixtures,
)


def _json(path: Path = TOOL_PROVIDER_OUTCOME_FIXTURES) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _outcome(outcome_id: str) -> ToolProviderOutcomeEnvelope:
    return load_tool_provider_outcome_fixtures().require_outcome(outcome_id)


def test_loader_covers_required_fields_cases_and_summary() -> None:
    fixtures = load_tool_provider_outcome_fixtures()

    assert {case.value for case in fixtures.fixture_cases} == REQUIRED_TOOL_PROVIDER_FIXTURE_CASES
    assert set(fixtures.outcome_envelope_required_fields) == set(
        TOOL_PROVIDER_OUTCOME_REQUIRED_FIELDS
    )
    assert {outcome.fixture_case.value for outcome in fixtures.outcomes} == (
        REQUIRED_TOOL_PROVIDER_FIXTURE_CASES
    )
    assert fixtures.summary.total_outcomes == 6
    assert fixtures.summary.public_claim_supported_count == 1
    assert fixtures.summary.blocked_or_error_count == 2


def test_source_acquired_outcome_supports_fresh_source_but_not_world_truth() -> None:
    outcome = _outcome("tpo:search.tavily:source-acquired")

    assert outcome.result_status is ResultStatus.SUCCESS
    assert outcome.acquisition_mode is SourceAcquisitionMode.SOURCE_ACQUIRED
    assert outcome.source_acquired is True
    assert outcome.can_support_fresh_source_claim() is True
    assert outcome.can_support_public_claim() is True
    assert outcome.witnessed_world_truth is False
    assert outcome.source_acquisition_evidence_refs
    assert outcome.acquired_source_refs


def test_supplied_evidence_preserves_ceiling_without_fresh_source_claim() -> None:
    outcome = _outcome("tpo:model.command-r:supplied-evidence")

    assert outcome.result_status is ResultStatus.SUCCESS
    assert outcome.source_acquired is False
    assert outcome.source_acquisition_evidence_refs == []
    assert outcome.can_support_supplied_evidence_claim() is True
    assert outcome.can_support_fresh_source_claim() is False
    assert outcome.can_support_public_claim() is False
    assert outcome.authority_ceiling is AuthorityCeiling.INTERNAL_ONLY


def test_redacted_outcome_is_consumable_but_not_public_claim_support() -> None:
    outcome = _outcome("tpo:tool.gmail-summary:redacted")

    assert outcome.result_status is ResultStatus.SUCCESS
    assert outcome.redaction_privacy_state is RedactionPrivacyState.REDACTED
    assert outcome.redaction_applied is True
    assert outcome.redaction_evidence_refs
    assert outcome.can_support_supplied_evidence_claim() is True
    assert outcome.can_support_public_claim() is False
    assert "redaction:gmail_recent_summary:body-stripped" in (
        outcome.action_receipt_consumption_refs()
    )


def test_blocked_error_and_unsupported_claim_do_not_support_action_receipts() -> None:
    fixtures = load_tool_provider_outcome_fixtures()
    blocked = fixtures.require_outcome("tpo:publication.bridgy:block-missing-source-url")
    errored = fixtures.require_outcome("tpo:search.web:error-source-acquisition")
    unsupported = fixtures.require_outcome("tpo:model.general:unsupported-latest-claim")

    assert blocked.result_status is ResultStatus.BLOCKED
    assert blocked.blocked_reasons
    assert blocked.can_support_public_claim() is False
    assert errored.result_status is ResultStatus.ERROR
    assert errored.error is not None
    assert errored.can_support_fresh_source_claim() is False
    assert unsupported.result_status is ResultStatus.UNSUPPORTED_CLAIM
    assert unsupported.unsupported_claim_reasons
    assert unsupported.can_support_public_claim() is False


@pytest.mark.parametrize(
    "outcome_id",
    [
        "tpo:publication.bridgy:block-missing-source-url",
        "tpo:search.web:error-source-acquisition",
        "tpo:model.general:unsupported-latest-claim",
    ],
)
def test_failure_like_outcomes_have_no_claim_authority(outcome_id: str) -> None:
    outcome = _outcome(outcome_id)

    assert outcome.authority_ceiling is AuthorityCeiling.NO_CLAIM
    assert outcome.public_claim_supported is False
    assert outcome.fresh_source_claim_supported is False
    assert outcome.supplied_evidence_claim_supported is False


def test_source_acquisition_claim_without_evidence_fails_closed() -> None:
    payload = _outcome("tpo:search.tavily:source-acquired").model_dump(mode="json")
    payload["source_acquisition_evidence_refs"] = []

    with pytest.raises(ValidationError, match="source-acquired mode requires source"):
        ToolProviderOutcomeEnvelope.model_validate(payload)


def test_supplied_evidence_cannot_claim_source_acquisition() -> None:
    payload = _outcome("tpo:model.command-r:supplied-evidence").model_dump(mode="json")
    payload["source_acquired"] = True
    payload["acquired_source_refs"] = ["source:forged"]

    with pytest.raises(ValidationError, match="supplied evidence cannot claim"):
        ToolProviderOutcomeEnvelope.model_validate(payload)


def test_bare_success_without_authority_or_evidence_fails_closed() -> None:
    payload = _outcome("tpo:model.command-r:supplied-evidence").model_dump(mode="json")
    payload["authority_ceiling"] = "no_claim"

    with pytest.raises(ValidationError, match="bare success requires an authority ceiling"):
        ToolProviderOutcomeEnvelope.model_validate(payload)


def test_redacted_payload_cannot_be_mutated_into_public_claim_support() -> None:
    payload = _outcome("tpo:tool.gmail-summary:redacted").model_dump(mode="json")
    payload["public_claim_supported"] = True

    with pytest.raises(ValidationError, match="cannot support public claims"):
        ToolProviderOutcomeEnvelope.model_validate(payload)


def test_error_status_requires_error_object() -> None:
    payload = _outcome("tpo:search.web:error-source-acquisition").model_dump(mode="json")
    payload["error"] = None

    with pytest.raises(ValidationError, match="error outcome requires error"):
        ToolProviderOutcomeEnvelope.model_validate(payload)


def test_unsupported_claim_cannot_be_mutated_into_public_claim_support() -> None:
    payload = _outcome("tpo:model.general:unsupported-latest-claim").model_dump(mode="json")
    payload["public_claim_supported"] = True

    with pytest.raises(ValidationError, match="unsupported claim cannot support claims"):
        ToolProviderOutcomeEnvelope.model_validate(payload)


def test_fixture_summary_mismatch_fails_closed(tmp_path: Path) -> None:
    payload = deepcopy(_json())
    payload["summary"]["public_claim_supported_count"] = 99
    path = tmp_path / "bad-tool-provider-outcome-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ToolProviderOutcomeError, match="summary does not match"):
        load_tool_provider_outcome_fixtures(path)


def test_fixture_set_rejects_missing_required_case() -> None:
    payload = deepcopy(_json())
    payload["fixture_cases"].remove("error")

    with pytest.raises(ValidationError, match="missing tool/provider fixture cases"):
        ToolProviderOutcomeFixtureSet.model_validate(payload)
