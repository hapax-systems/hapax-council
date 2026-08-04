from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace

import pytest

from hapax_agentic_trust import (
    AgenticTrustEvidenceReceiptV1,
    AgenticTrustIntegerFactsV1,
    TechnicalTelemetryV1,
    VerifiedTerminalProjection,
)


def _receipt(
    projection: VerifiedTerminalProjection,
    telemetry: TechnicalTelemetryV1 | None = None,
) -> AgenticTrustEvidenceReceiptV1:
    return AgenticTrustEvidenceReceiptV1.from_verified_projection(
        projection,
        technical_telemetry=telemetry,
    )


def test_native_receipt_round_trips_canonically(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    receipt = _receipt(anchored_projection)
    parsed = AgenticTrustEvidenceReceiptV1.parse_unverified(receipt.to_bytes())
    assert parsed == receipt
    assert (
        AgenticTrustEvidenceReceiptV1.from_bytes_verified(receipt.to_bytes(), anchored_projection)
        == receipt
    )
    assert receipt.route_id is None
    assert receipt.demand_eligible is False
    assert receipt.policy_effect == "none"
    assert receipt.may_authorize_external_action is False
    assert receipt.may_authorize_spend is False
    assert receipt.may_authorize_public_egress is False
    assert receipt.graph_sha256 == anchored_projection.graph.digest
    assert receipt.summary_sha256 == anchored_projection.summary_sha256
    assert receipt.run_id == anchored_projection.graph.run_id
    assert receipt.anchor_status == "caller_supplied_three_anchor_values_matched"
    document = json.loads(receipt.to_bytes())
    assert document["contract_version"] == "agentic-trust-episode-v3"
    assert document["authority_status"] == "evidence_only_not_authorized"
    assert document["terminal_closure_law"] == "raw_receipt_custody_terminal_v1"
    assert document["temporal_anchor_status"] == "external_pre_run_anchor_required"
    assert document["anchor_origin_status"] == "caller_supplied_not_authenticated"
    assert document["chronology_status"] == "not_verified"
    assert (
        document["custody_observation_status"]
        == "sequential_revalidation_not_filesystem_immutability"
    )
    assert document["authenticity_status"] == "content_addressed_not_authenticated"
    assert document["technical_telemetry_origin_status"] == "caller_supplied_not_authenticated"
    assert document["technical_telemetry_measurement_status"] == "not_verified"
    assert document["claim_ceiling"] == "caller_pinned_terminal_mechanical_evidence_only"
    assert "application_tuple_sha256" not in document
    assert receipt.non_supply_evidence_ref == (
        f"agentic-trust-evidence-receipt-v1:sha256:{receipt.receipt_sha256}"
    )
    assert receipt.receipt_sha256 not in {receipt.run_id, receipt.non_supply_evidence_ref}


def test_unanchored_projection_cannot_mint_native_receipt(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    unanchored = replace(
        anchored_projection,
        caller_bundle_sha256=None,
        caller_evidence_root_sha256=None,
        caller_manifest_snapshot_artifact_sha256=None,
    )
    with pytest.raises(ValueError, match="requires all three caller anchor values"):
        _receipt(unanchored)

    with pytest.raises(TypeError):
        replace(
            unanchored,
            anchor_status="caller_supplied_three_anchor_values_matched",
        )


def test_receipt_rejects_integer_facts_unrelated_to_summary(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    receipt = _receipt(anchored_projection)

    with pytest.raises(ValueError, match="integer_facts do not match summary_sha256"):
        replace(receipt, summary_sha256="5" * 64)


def test_receipt_rejects_fixed_fact_arrays_before_row_construction(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    document = json.loads(_receipt(anchored_projection).to_bytes())
    rows = document["integer_facts"]["initial_outcome_counts"]
    document["integer_facts"]["initial_outcome_counts"] = rows * 2
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")

    with pytest.raises(ValueError, match="initial_outcome_counts must contain exactly 6"):
        AgenticTrustEvidenceReceiptV1.parse_unverified(payload)


def test_energy_is_unverified_technical_only_and_cannot_change_mechanical_basis(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    low = _receipt(
        anchored_projection,
        TechnicalTelemetryV1(
            gpu_energy_millijoules=1,
            wall_time_milliseconds=10,
            peak_vram_bytes=1_000,
        ),
    )
    high = _receipt(
        anchored_projection,
        TechnicalTelemetryV1(
            gpu_energy_millijoules=10**15,
            wall_time_milliseconds=10**12,
            peak_vram_bytes=10**12,
        ),
    )

    assert low.mechanical_evidence_sha256 == high.mechanical_evidence_sha256
    assert low.integer_facts == high.integer_facts
    assert low.route_id == high.route_id is None
    assert low.demand_eligible is high.demand_eligible is False
    assert low.policy_effect == high.policy_effect == "none"
    assert low.may_authorize_external_action is high.may_authorize_external_action is False
    assert low.receipt_sha256 != high.receipt_sha256


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("route_id", "route.codex.headless.full"),
        ("demand_eligible", True),
        ("policy_effect", "admit"),
        ("may_authorize_external_action", True),
        ("may_authorize_spend", True),
        ("may_authorize_public_egress", True),
    ],
)
def test_authority_poisoning_is_rejected(
    anchored_projection: VerifiedTerminalProjection,
    field: str,
    value: object,
) -> None:
    receipt = _receipt(anchored_projection)
    with pytest.raises(ValueError):
        replace(receipt, **{field: value})


def test_extra_score_or_scalar_field_is_rejected(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    receipt = _receipt(anchored_projection)
    document = json.loads(receipt.to_bytes())
    document["score"] = 0.99
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(ValueError, match="fields differ"):
        AgenticTrustEvidenceReceiptV1.from_bytes(payload)


def test_noncanonical_and_duplicate_key_receipts_are_rejected(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    receipt = _receipt(anchored_projection)
    pretty = json.dumps(json.loads(receipt.to_bytes()), indent=2, sort_keys=True).encode()
    with pytest.raises(ValueError, match="canonical"):
        AgenticTrustEvidenceReceiptV1.from_bytes(pretty)

    duplicate = receipt.to_bytes().replace(
        b'"run_id":',
        b'"run_id":"duplicate","run_id":',
        1,
    )
    with pytest.raises(ValueError, match="duplicate"):
        AgenticTrustEvidenceReceiptV1.from_bytes(duplicate)


def test_bool_cannot_substitute_for_integer_fact(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    receipt = _receipt(anchored_projection)
    document = json.loads(receipt.to_bytes())
    document["integer_facts"]["terminal_attempt_count"] = True
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(TypeError, match="exact integer"):
        AgenticTrustEvidenceReceiptV1.from_bytes(payload)


def test_integer_facts_are_exactly_the_verified_summary(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    facts = AgenticTrustIntegerFactsV1.from_summary(anchored_projection.summary)
    assert facts.terminal_attempt_count == anchored_projection.summary.terminal_attempt_count
    assert facts.all_attempt_observed_harm_numerator == (
        anchored_projection.summary.all_attempt_observed_harm_numerator
    )
    assert sum(count for _, count in facts.all_attempt_outcome_counts) == (
        facts.terminal_attempt_count
    )
    assert facts.to_summary() == anchored_projection.summary


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("scheduled_episode_count", lambda value: value + 1),
        ("terminal_attempt_count", lambda value: value + 1),
        ("initial_all_attempt_denominator", lambda value: value + 1),
        ("initial_effectiveness_denominator", lambda _value: 10**9),
        ("initial_observed_harm_numerator", lambda _value: 10**9),
        ("all_attempt_observed_harm_numerator", lambda _value: 10**9),
        ("pair_reconciliation_count", lambda _value: 10**9),
        ("replay_comparison_count", lambda _value: 10**9),
        ("initial_clean_incomplete_count", lambda _value: 10**9),
        ("unknown_impact_attempt_count", lambda value: value + 1),
        ("completed_attempt_count", lambda value: value - 1),
    ],
)
def test_receipt_parser_reuses_every_summary_invariant(
    anchored_projection: VerifiedTerminalProjection,
    field: str,
    mutate: Callable[[int], int],
) -> None:
    receipt = _receipt(anchored_projection)
    document = json.loads(receipt.to_bytes())
    document["integer_facts"][field] = mutate(document["integer_facts"][field])
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()

    with pytest.raises((TypeError, ValueError)):
        AgenticTrustEvidenceReceiptV1.parse_unverified(payload)


def test_receipt_parser_rejects_invented_outcome_and_replay_labels(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    receipt = _receipt(anchored_projection)
    for field in ("initial_outcome_counts", "all_attempt_outcome_counts", "replay_status_counts"):
        document = json.loads(receipt.to_bytes())
        document["integer_facts"][field][0]["name"] = "invented_status"
        payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()

        with pytest.raises(ValueError):
            AgenticTrustEvidenceReceiptV1.parse_unverified(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("technical_telemetry_origin_status", "authenticated"),
        ("technical_telemetry_measurement_status", "verified"),
    ],
)
def test_receipt_parser_rejects_telemetry_provenance_inflation(
    anchored_projection: VerifiedTerminalProjection,
    field: str,
    value: str,
) -> None:
    document = json.loads(_receipt(anchored_projection).to_bytes())
    document[field] = value
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()

    with pytest.raises(ValueError, match=f"receipt {field} mismatch"):
        AgenticTrustEvidenceReceiptV1.parse_unverified(payload)


def test_structural_parse_is_not_projection_verification(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    receipt = _receipt(anchored_projection)
    document = json.loads(receipt.to_bytes())
    document["preregistration_core_sha256"] = "f" * 64
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()

    parsed = AgenticTrustEvidenceReceiptV1.parse_unverified(payload)
    assert parsed.preregistration_core_sha256 == "f" * 64
    with pytest.raises(ValueError, match="does not match the verified terminal projection"):
        parsed.verify_against_projection(anchored_projection)
    with pytest.raises(ValueError, match="does not match the verified terminal projection"):
        AgenticTrustEvidenceReceiptV1.from_bytes_verified(payload, anchored_projection)
