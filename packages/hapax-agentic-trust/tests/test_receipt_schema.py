from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from hapax_agentic_trust import AgenticTrustEvidenceReceiptV1, VerifiedTerminalProjection

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "agentic-trust-evidence-receipt-v1.schema.json"
)


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _document(projection: VerifiedTerminalProjection) -> dict[str, object]:
    receipt = AgenticTrustEvidenceReceiptV1.from_verified_projection(projection)
    return json.loads(receipt.to_bytes())


def test_receipt_schema_is_valid_and_accepts_native_receipt(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    schema = _schema()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(_document(anchored_projection))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document["integer_facts"].pop("scheduled_pair_count"),
        lambda document: document["integer_facts"].update({"invented_fact": 1}),
        lambda document: document["integer_facts"]["initial_outcome_counts"][0].update(
            {"name": "invented_outcome"}
        ),
        lambda document: document.update({"score": 0.9}),
        lambda document: document.update({"authority_status": "authorized"}),
        lambda document: document.update({"chronology_status": "verified"}),
        lambda document: document.update({"technical_telemetry_origin_status": "authenticated"}),
        lambda document: document.update({"technical_telemetry_measurement_status": "verified"}),
    ],
)
def test_schema_rejects_structural_receipt_poisoning(
    anchored_projection: VerifiedTerminalProjection,
    mutation: object,
) -> None:
    schema = _schema()
    document = _document(anchored_projection)
    mutation(document)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(document)


def test_python_parser_enforces_cross_field_arithmetic_beyond_json_schema(
    anchored_projection: VerifiedTerminalProjection,
) -> None:
    document = _document(anchored_projection)
    document["integer_facts"]["scheduled_episode_count"] += 1
    payload = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()

    # JSON Schema establishes the exact structural vocabulary. The native parser
    # additionally reuses AgenticRunSummary for cross-field reconciliation.
    jsonschema.Draft202012Validator(_schema()).validate(document)
    with pytest.raises(ValueError):
        AgenticTrustEvidenceReceiptV1.parse_unverified(payload)
