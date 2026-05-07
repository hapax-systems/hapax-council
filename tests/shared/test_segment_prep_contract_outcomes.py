from __future__ import annotations

from shared.segment_prep_contract import validate_segment_prep_outcome


def _outcome(**overrides):
    payload = {
        "segment_prep_outcome_version": 1,
        "outcome_type": "no_candidate",
        "authority": "diagnostic_only",
        "prep_session_id": "segment-prep-test",
        "model_id": "command-r-08-2024-exl3-5.0bpw",
        "reason_code": "completed_no_segments_saved",
        "blocking_gaps": [],
        "source_refs": [],
        "budget": {"elapsed_s": 12.0, "budget_s": 7200},
        "release_boundary": {
            "listed_in_manifest": False,
            "selected_release_eligible": False,
            "runtime_pool_eligible": False,
        },
        "outcome_sha256": "abc",
    }
    payload.update(overrides)
    return payload


def test_validate_segment_prep_outcome_accepts_no_candidate_diagnostic() -> None:
    assert validate_segment_prep_outcome(_outcome()) == []


def test_validate_segment_prep_outcome_accepts_refusal_brief_candidate_diagnostic() -> None:
    assert validate_segment_prep_outcome(_outcome(outcome_type="refusal_brief_candidate")) == []


def test_validate_segment_prep_outcome_accepts_no_release_diagnostic() -> None:
    assert validate_segment_prep_outcome(_outcome(outcome_type="no_release")) == []


def test_validate_segment_prep_outcome_accepts_refusal_diagnostic() -> None:
    assert validate_segment_prep_outcome(_outcome(outcome_type="refusal")) == []


def test_validate_segment_prep_outcome_rejects_loadable_artifact_fields() -> None:
    failures = validate_segment_prep_outcome(
        _outcome(
            prepared_script=["This must not become a loadable segment."],
            artifact_sha256="not-allowed",
            qdrant_upserted=True,
            selected_release_manifest={"ok": True},
            selected_release_publication={"ok": True},
            release_boundary={
                "listed_in_manifest": True,
                "selected_release_eligible": False,
                "runtime_pool_eligible": False,
            },
        )
    )

    assert "forbidden_outcome_field:prepared_script" in failures
    assert "forbidden_outcome_field:artifact_sha256" in failures
    assert "forbidden_outcome_field:qdrant_upserted" in failures
    assert "forbidden_outcome_field:selected_release_manifest" in failures
    assert "forbidden_outcome_field:selected_release_publication" in failures
    assert "release_boundary_not_closed:listed_in_manifest" in failures
