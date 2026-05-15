from __future__ import annotations

from shared.segment_prep_contract import validate_return_to_prep


def _full_dossier(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "identified_gap": "script beat 3 missing source packet for ranking claim",
        "bounded_work_item": "recruit vault:ranking-methodology-2026 into beat 3 grounds",
        "budget_authority": "1 prep cycle, cloud model, no new source recruitment",
        "expected_observable": "beat 3 claim_map entry gains source_evidence_ref ground",
        "falsification_criterion": "if recruited source does not alter ranking, terminal outcome",
    }
    payload.update(overrides)
    return payload


def test_valid_return_with_full_dossier() -> None:
    result = validate_return_to_prep(_full_dossier())
    assert result["ok"] is True
    assert result["missing_fields"] == []
    assert result["terminal_recommended"] is False


def test_unbounded_return_rejected() -> None:
    result = validate_return_to_prep({})
    assert result["ok"] is False
    assert len(result["missing_fields"]) == 5
    assert result["terminal_recommended"] is True


def test_partial_dossier_rejected() -> None:
    partial = _full_dossier()
    del partial["budget_authority"]
    del partial["falsification_criterion"]
    result = validate_return_to_prep(partial)
    assert result["ok"] is False
    assert sorted(result["missing_fields"]) == ["budget_authority", "falsification_criterion"]
    assert result["terminal_recommended"] is True


def test_terminal_recommended_when_thin() -> None:
    result = validate_return_to_prep({"identified_gap": "some gap"})
    assert result["ok"] is False
    assert result["terminal_recommended"] is True
    assert len(result["missing_fields"]) == 4
    assert "identified_gap" not in result["missing_fields"]


def test_empty_string_fields_rejected() -> None:
    empty = _full_dossier(
        identified_gap="",
        bounded_work_item="   ",
        budget_authority="",
        expected_observable="valid observable",
        falsification_criterion="valid criterion",
    )
    result = validate_return_to_prep(empty)
    assert result["ok"] is False
    assert "identified_gap" in result["missing_fields"]
    assert "bounded_work_item" in result["missing_fields"]
    assert "budget_authority" in result["missing_fields"]
    assert "expected_observable" not in result["missing_fields"]
    assert "falsification_criterion" not in result["missing_fields"]
    assert result["terminal_recommended"] is True
