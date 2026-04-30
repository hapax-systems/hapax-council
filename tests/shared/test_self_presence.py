"""Typed contract tests for the self-presence ontology fixtures."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from shared.self_presence import (
    PROMPT_ONLY_NON_WITNESS_STATES,
    REQUIRED_FIXTURE_CASES,
    REQUIRED_ONTOLOGY_TERMS,
    AllowedOutcome,
    AuthorityCeiling,
    EventSuccessState,
    RoleState,
    SelfPresenceEnvelope,
    SelfPresenceFixtureSet,
    fixture_set,
    load_self_presence_fixture_set,
)


def test_fixture_set_loads_and_covers_required_terms_and_cases() -> None:
    fixtures = fixture_set()

    assert fixtures.schema_version == 1
    assert {row.term for row in fixtures.ontology_term_mappings} == REQUIRED_ONTOLOGY_TERMS
    assert {row.fixture_case for row in fixtures.envelopes} == REQUIRED_FIXTURE_CASES


def test_roles_are_validated_as_offices_not_masks() -> None:
    fixtures = load_self_presence_fixture_set()

    for envelope in fixtures.envelopes:
        role = envelope.role_state
        assert isinstance(role, RoleState)
        assert role.roles_are_offices_not_masks is True
        assert role.office.value not in {"mask", "persona", "activity"}


def test_prompt_only_support_cannot_be_witnessed_success() -> None:
    fixtures = load_self_presence_fixture_set()
    payload = fixtures.model_dump(mode="json")
    public_candidate = next(
        row for row in payload["envelopes"] if row["fixture_case"] == "public_speech_candidate"
    )
    public_candidate["aperture_events"][0]["success_state"] = EventSuccessState.WITNESSED.value

    with pytest.raises(ValidationError, match="prompt-only states cannot be witnessed"):
        SelfPresenceEnvelope.model_validate(public_candidate)


def test_prompt_only_claim_binding_cannot_gain_evidence_bearing_authority() -> None:
    fixtures = load_self_presence_fixture_set()
    payload = fixtures.model_dump(mode="json")
    blocked = next(row for row in payload["envelopes"] if row["fixture_case"] == "blocked_route")
    blocked["claim_bindings"][0]["authority_ceiling"] = AuthorityCeiling.EVIDENCE_BOUND.value

    with pytest.raises(ValidationError, match="prompt-only support states"):
        SelfPresenceEnvelope.model_validate(blocked)


def test_public_speech_allowed_requires_all_public_witness_gates() -> None:
    fixtures = load_self_presence_fixture_set()
    payload = fixtures.model_dump(mode="json")
    candidate = next(
        row for row in payload["envelopes"] if row["fixture_case"] == "public_speech_candidate"
    )
    candidate["allowed_outcomes"] = [AllowedOutcome.PUBLIC_SPEECH_ALLOWED.value]

    with pytest.raises(ValidationError, match="public speech allowed without"):
        SelfPresenceEnvelope.model_validate(candidate)


def test_private_risk_source_context_blocks_public_speech_even_with_gates() -> None:
    fixtures = load_self_presence_fixture_set()
    payload = fixtures.model_dump(mode="json")
    live = deepcopy(
        next(row for row in payload["envelopes"] if row["fixture_case"] == "livestream_referent")
    )
    live["private_risk_flags"] = ["private-source-context"]

    with pytest.raises(ValidationError, match="private-risk source context"):
        SelfPresenceEnvelope.model_validate(live)


def test_fixture_set_rejects_missing_required_fixture_case() -> None:
    fixtures = load_self_presence_fixture_set()
    payload = fixtures.model_dump(mode="json")
    payload["envelopes"] = [
        row for row in payload["envelopes"] if row["fixture_case"] != "blocked_route"
    ]

    with pytest.raises(ValidationError, match="missing self-presence fixture cases"):
        SelfPresenceFixtureSet.model_validate(payload)


def test_prompt_only_non_witness_states_match_runtime_constant() -> None:
    fixtures = load_self_presence_fixture_set()

    assert set(fixtures.prompt_only_non_witness_states) == PROMPT_ONLY_NON_WITNESS_STATES
