"""Tests for the format WCS requirement matrix contract."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from pydantic import ValidationError

from shared.format_wcs_requirement_matrix import (
    REQUIRED_FORMAT_IDS,
    FormatWCSRequirementMatrix,
    decide_format_wcs_readiness,
    director_projection,
    load_format_wcs_requirement_matrix,
    opportunity_gate_projection,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "config" / "format-wcs-requirement-matrix.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "format-wcs-requirement-matrix.schema.json"


def test_matrix_fixture_validates_against_json_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_matrix_covers_all_initial_formats_with_required_and_optional_surfaces() -> None:
    matrix = load_format_wcs_requirement_matrix()

    assert set(matrix.by_format_id()) == REQUIRED_FORMAT_IDS
    for row in matrix.rows:
        required_families = {block.family for block in row.required_surface_blocks}
        assert {"source", "rights", "claim_gate", "evidence", "public_event"} <= required_families
        assert row.optional_surface_blocks
        assert row.grounding_question_ref.endswith(".grounding_question")
        assert row.permitted_claim_shape_ref.endswith(".permitted_claim_shape")
        assert row.matrix_grants_public_authority is False
        assert row.matrix_grants_monetization_authority is False


def test_tier_list_missing_evidence_downgrades_to_dry_run() -> None:
    row = load_format_wcs_requirement_matrix().require_row("tier_list")
    required = row.required_surfaces_for_mode("public_archive")
    available = {block.surface_id for block in required} - {"tier_list.evidence_trace"}

    decision = decide_format_wcs_readiness(
        row,
        requested_mode="public_archive",
        available_surface_ids=available,
    )

    assert decision.allowed is False
    assert decision.effective_mode == "dry_run"
    assert decision.missing_surface_ids == ("tier_list.evidence_trace",)
    assert "missing_evidence_trace" in decision.blocked_reason_codes
    assert decision.public_claim_authorized is False


def test_react_commentary_blocks_public_and_monetized_uncleared_media() -> None:
    row = load_format_wcs_requirement_matrix().require_row("react_commentary")
    required = row.required_surfaces_for_mode("public_monetizable")
    available = {
        block.surface_id
        for block in required
        if block.surface_id
        not in {"react_commentary.rights_provenance", "react_commentary.media_route"}
    }

    decision = decide_format_wcs_readiness(
        row,
        requested_mode="public_monetizable",
        available_surface_ids=available,
    )

    assert decision.allowed is False
    assert decision.effective_mode == "blocked"
    assert set(decision.missing_surface_ids) == {
        "react_commentary.rights_provenance",
        "react_commentary.media_route",
    }
    assert decision.monetization_authorized is False


def test_ranking_projection_is_consumable_by_director_and_opportunity_gate() -> None:
    row = load_format_wcs_requirement_matrix().require_row("ranking")
    director = director_projection(row)
    opportunity = opportunity_gate_projection(row)

    assert "ranking.evidence_trace" in director.required_surface_ids
    assert "foreground" in director.director_moves
    assert opportunity.safe_private_mode is True
    assert opportunity.safe_dry_run_mode is True
    assert opportunity.public_live_requires_egress is True
    assert opportunity.matrix_grants_monetization_authority is False


def test_refusal_breakdown_emits_artifact_without_validating_blocked_claim() -> None:
    row = load_format_wcs_requirement_matrix().require_row("refusal_breakdown")
    required = row.required_surfaces_for_mode("public_archive")
    available = {block.surface_id for block in required}
    decision = decide_format_wcs_readiness(
        row,
        requested_mode="public_archive",
        available_surface_ids=available,
    )

    assert decision.allowed is True
    assert decision.effective_mode == "public_archive"
    assert row.refusal_correction_policy.public_safe_refusal_artifact_allowed is True
    assert row.refusal_correction_policy.blocked_claim_validated_by_aesthetic_emphasis is False
    assert "public_refusal_artifact" in row.conversion_paths


def test_contract_rejects_format_without_public_event_gate() -> None:
    row = load_format_wcs_requirement_matrix().require_row("review")
    invalid = row.model_copy(
        update={
            "required_surface_blocks": tuple(
                block for block in row.required_surface_blocks if block.family != "public_event"
            )
        }
    )

    try:
        FormatWCSRequirementMatrix.model_validate(
            {
                **load_format_wcs_requirement_matrix().model_dump(),
                "rows": (invalid,),
            }
        )
    except ValidationError as exc:
        assert "missing initial format ids" in str(exc) or "missing required WCS families" in str(
            exc
        )
    else:  # pragma: no cover - assertion guard
        raise AssertionError("matrix row without public-event gate should be rejected")
