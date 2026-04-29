from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "conative-impingement-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "conative-impingement-fixtures.json"


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _fixtures() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def test_conative_impingement_schema_is_valid() -> None:
    jsonschema.Draft202012Validator.check_schema(_schema())


def test_conative_fixtures_validate_against_schema() -> None:
    schema = _schema()
    validator = jsonschema.Draft202012Validator(schema)
    fixtures = _fixtures()

    assert fixtures["schema_ref"] == "schemas/conative-impingement-envelope.schema.json"
    assert {item["case_id"] for item in fixtures["fixtures"]} == {
        "healthy-public-narration-speak",
        "too-low-hold-pressure",
        "too-high-withhold",
        "missing-execution-evidence-inhibits",
    }
    for item in fixtures["fixtures"]:
        validator.validate(item["envelope"])


def test_schema_rejects_raw_drive_text_spoken_true() -> None:
    schema = _schema()
    fixture = _fixtures()["fixtures"][0]["envelope"] | {"raw_drive_text_spoken": True}

    validator = jsonschema.Draft202012Validator(schema)

    with pytest.raises(jsonschema.ValidationError):
        validator.validate(fixture)
