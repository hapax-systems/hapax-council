from __future__ import annotations

from pathlib import Path

import pytest

from shared.segment_candidate_selection import (
    LIVE_EVENT_GOOD_FLOOR,
    derive_excellence_receipt,
    derive_excellence_receipts,
    review_segment_candidate_set,
    selected_release_manifest,
    write_selected_release_manifest,
)


def _live_report(score: int, *, role: str = "rant", required: tuple[str, ...] = ()) -> dict:
    return {
        "live_event_rubric_version": 1,
        "score": score,
        "band": "good" if score >= LIVE_EVENT_GOOD_FLOOR else "thin",
        "ok": score >= LIVE_EVENT_GOOD_FLOOR,
        "dimensions": [
            {"name": "live_event_object", "passed": True, "points": 12, "observed": {}},
            {
                "name": "role_standard_fit",
                "passed": True,
                "points": 10,
                "observed": {"role": role, "required_action_kinds": list(required)},
            },
        ],
    }


def _scored_artifact(programme_id: str, *, score: int, role: str = "rant") -> dict:
    required = ("tier_chart",) if role == "tier_list" else ()
    return {
        "programme_id": programme_id,
        "role": role,
        "artifact_path": f"/tmp/{programme_id}.json",
        "artifact_sha256": programme_id.rjust(64, "0")[-64:],
        "segment_quality_report": {"overall": 4.2},
        "segment_live_event_report": _live_report(score, role=role, required=required),
    }


def _artifact(programme_id: str, *, score: int = 90) -> dict:
    return {
        "programme_id": programme_id,
        "artifact_path": f"/tmp/{programme_id}.json",
        "artifact_sha256": programme_id.rjust(64, "0")[-64:],
        "segment_quality_report": {"overall": 4.2},
        "segment_live_event_report": {"score": score, "band": "good"},
    }


def _receipt(artifact: dict) -> dict:
    return {
        "artifact_sha256": artifact["artifact_sha256"],
        "programme_id": artifact["programme_id"],
        "verdict": "approved",
        "reviewer": "test-reviewer",
        "checked_at": "2026-05-07T00:00:00Z",
        "receipt_id": f"receipt-{artifact['programme_id']}",
        "notes": "Structured test receipt for selected release.",
    }


def test_selected_release_manifest_refuses_missing_excellence_receipt() -> None:
    artifact = _artifact("prog-a")

    manifest = selected_release_manifest([artifact], [])

    assert manifest["ok"] is False
    assert manifest["programmes"] == []
    assert manifest["violations"][0]["reason"] == (
        "release_window_eligible_artifact_missing_excellence_receipt"
    )
    assert manifest["review_gaps"][0]["reason"] == "eligible_artifact_missing_excellence_receipt"


def test_selected_release_manifest_refuses_incomplete_excellence_receipt() -> None:
    artifact = _artifact("prog-a")
    receipt = {
        "artifact_sha256": artifact["artifact_sha256"],
        "verdict": "approved",
        "receipt_id": "thin-receipt",
    }

    manifest = selected_release_manifest([artifact], [receipt])

    assert manifest["ok"] is False
    assert manifest["programmes"] == []
    assert manifest["review_gaps"][0]["reason"] == "eligible_artifact_incomplete_excellence_receipt"
    assert "reviewer" in manifest["review_gaps"][0]["missing"]


def test_selected_release_manifest_selects_ranked_reviewed_artifacts() -> None:
    weak = _artifact("prog-a", score=83)
    strong = _artifact("prog-b", score=96)

    manifest = selected_release_manifest(
        [weak, strong],
        [_receipt(weak), _receipt(strong)],
        selected_count=1,
    )

    assert manifest["ok"] is True
    assert manifest["programmes"] == ["prog-b.json"]
    assert manifest["selected_artifacts"][0]["live_event_score"] == 96


def test_selected_release_manifest_does_not_block_on_unselected_missing_receipt() -> None:
    reviewed = _artifact("prog-reviewed", score=96)
    unreviewed = _artifact("prog-unreviewed", score=95)

    manifest = selected_release_manifest(
        [reviewed, unreviewed],
        [_receipt(reviewed)],
        selected_count=1,
    )

    assert manifest["ok"] is True
    assert manifest["programmes"] == ["prog-reviewed.json"]
    assert manifest["reviewed_candidate_count"] == 1
    assert manifest["review_gaps"][0]["reason"] == "eligible_artifact_missing_excellence_receipt"


def test_selected_release_manifest_blocks_when_higher_ranked_candidate_unreviewed() -> None:
    reviewed = _artifact("prog-reviewed", score=96)
    unreviewed = _artifact("prog-unreviewed", score=97)

    manifest = selected_release_manifest(
        [reviewed, unreviewed],
        [_receipt(reviewed)],
        selected_count=1,
    )

    assert manifest["ok"] is False
    assert manifest["programmes"] == []
    assert manifest["release_window_count"] == 1
    assert manifest["reviewed_candidate_count"] == 0
    assert manifest["violations"][0]["reason"] == (
        "release_window_eligible_artifact_missing_excellence_receipt"
    )


def test_selected_release_manifest_blocks_interview_without_release_receipts() -> None:
    artifact = _artifact("interview-a")
    artifact["role"] = "interview"

    manifest = selected_release_manifest([artifact], [_receipt(artifact)])

    assert manifest["ok"] is False
    assert manifest["programmes"] == []
    assert manifest["review_gaps"][0]["reason"] == (
        "interview_artifact_missing_selected_release_receipts"
    )


def test_selected_release_manifest_allows_interview_with_public_release_receipts() -> None:
    artifact = _artifact("interview-a")
    artifact["role"] = "interview"
    artifact["selected_release_interview_report"] = {
        "ok": True,
        "mode": "public_release",
        "topic_consent_receipt": "receipt:topic-consent",
        "answer_authority_receipt": "receipt:answer-authority",
        "release_scope_receipt": "receipt:release-scope",
        "layout_readback_receipt": "receipt:layout-readback",
        "question_ladder": [
            {
                "question_id": "q-1",
                "question": "What claim can be answered on record?",
            }
        ],
        "turn_receipts": [
            {
                "question_id": "q-1",
                "answer_receipt_id": "receipt:answer-q-1",
                "release_decision_id": "receipt:release-q-1",
                "layout_readback_receipt": "receipt:layout-q-1",
            }
        ],
    }

    manifest = selected_release_manifest([artifact], [_receipt(artifact)])

    assert manifest["ok"] is True
    assert manifest["programmes"] == ["interview-a.json"]


def test_selected_release_manifest_blocks_interview_with_missing_turn_receipt() -> None:
    artifact = _artifact("interview-a")
    artifact["role"] = "interview"
    artifact["selected_release_interview_report"] = {
        "ok": True,
        "mode": "public_release",
        "topic_consent_receipt": "receipt:topic-consent",
        "answer_authority_receipt": "receipt:answer-authority",
        "release_scope_receipt": "receipt:release-scope",
        "layout_readback_receipt": "receipt:layout-readback",
        "question_ladder": [
            {"question_id": "q-1", "question": "First?"},
            {"question_id": "q-2", "question": "Second?"},
        ],
        "turn_receipts": [
            {
                "question_id": "q-1",
                "answer_receipt_id": "receipt:answer-q-1",
                "release_decision_id": "receipt:release-q-1",
                "layout_readback_receipt": "receipt:layout-q-1",
            }
        ],
    }

    manifest = selected_release_manifest([artifact], [_receipt(artifact)])

    assert manifest["ok"] is False
    assert manifest["programmes"] == []
    assert manifest["review_gaps"][0]["reason"] == (
        "interview_artifact_missing_selected_release_receipts"
    )
    assert "turn_receipts:missing_question_ids" in manifest["review_gaps"][0]["missing"]


def test_review_segment_candidate_set_rejects_one_field_ledger_rows() -> None:
    artifact = _artifact("prog-a", score=96)
    receipt = _receipt(artifact)

    review = review_segment_candidate_set(
        [artifact],
        [{"artifact_sha256": artifact["artifact_sha256"]}],
        [receipt],
        selected_count=1,
    )

    assert review["ok"] is False
    failed = {item["name"] for item in review["criteria"] if item["passed"] is False}
    assert {
        "candidate_set.has_ledger",
        "candidate_set.selected_artifacts_have_ledger_rows",
    }.issubset(failed)


def test_write_selected_release_manifest_refuses_failed_manifest(tmp_path: Path) -> None:
    artifact = _artifact("prog-a")
    manifest = selected_release_manifest([artifact], [])

    with pytest.raises(ValueError, match="ok=true with selected artifacts"):
        write_selected_release_manifest(tmp_path, manifest)

    assert not (tmp_path / "selected-release-manifest.json").exists()


def test_derive_excellence_receipt_records_criterion_vector_and_scores() -> None:
    artifact = _scored_artifact("prog-a", score=90)

    receipt = derive_excellence_receipt(artifact, checked_at="2026-06-07T00:00:00Z")

    # Auditable: keyed by artifact_sha256, transparent (criterion vector + scores), not
    # a bare boolean.
    assert receipt["artifact_sha256"] == artifact["artifact_sha256"]
    assert receipt["verdict"] == "approved"
    assert receipt["auto_derived"] is True
    assert receipt["criterion_vector"]["role_standard_fit"] == {"passed": True, "points": 10}
    assert receipt["scores"]["live_event_score"] == 90.0
    assert receipt["scores"]["live_event_floor"] == LIVE_EVENT_GOOD_FLOOR
    assert receipt["scores"]["quality_overall"] == 4.2
    # Re-checkable: the receipt is self-hashed over its own body.
    assert isinstance(receipt["auto_excellence_receipt_sha256"], str)
    # Carries the identity fields the release-receipt gate requires.
    for field in ("receipt_id", "reviewer", "checked_at", "programme_id", "notes"):
        assert isinstance(receipt[field], str) and receipt[field]


def test_derive_excellence_receipt_rejects_below_live_event_floor() -> None:
    artifact = _scored_artifact("prog-weak", score=LIVE_EVENT_GOOD_FLOOR - 2)

    receipt = derive_excellence_receipt(artifact, checked_at="2026-06-07T00:00:00Z")

    assert receipt["verdict"] == "rejected"
    floor_criterion = next(
        c for c in receipt["criteria"] if c["name"] == "live_event_score_meets_floor"
    )
    assert floor_criterion["passed"] is False


def test_derive_excellence_receipt_flags_lecture_vacuous_role_standard_fit() -> None:
    # A lecture earns role_standard_fit vacuously (no role-required actions); the score
    # only clears the floor because of those vacuously-awarded points.
    artifact = _scored_artifact("lecture-a", score=LIVE_EVENT_GOOD_FLOOR, role="lecture")

    receipt = derive_excellence_receipt(artifact, checked_at="2026-06-07T00:00:00Z")

    assert receipt["role_standard_fit_vacuous"] is True
    assert receipt["clears_floor_without_vacuous_role_fit"] is False
    assert "role_standard_fit_points_awarded_vacuously" in receipt["anti_gaming_flags"]
    assert "clears_floor_only_via_vacuous_role_fit_points" in receipt["anti_gaming_flags"]
    # Flagged, not silently inflated — a floor-clearing artifact is still approved.
    assert receipt["verdict"] == "approved"


def test_derive_excellence_receipt_tier_list_role_fit_not_vacuous() -> None:
    artifact = _scored_artifact("tier-a", score=95, role="tier_list")

    receipt = derive_excellence_receipt(artifact, checked_at="2026-06-07T00:00:00Z")

    assert receipt["role_standard_fit_vacuous"] is False
    assert receipt["anti_gaming_flags"] == []


def test_selected_release_manifest_embeds_auto_excellence_receipt() -> None:
    artifact = _scored_artifact("prog-a", score=92)
    [receipt] = derive_excellence_receipts(
        [artifact],
        checked_at="2026-06-07T00:00:00Z",
    )

    # The auto receipt must carry the identity fields the manifest gate requires.
    receipt = {
        **receipt,
        "receipt_id": receipt["receipt_id"],
        "notes": "auto-derived",
    }
    manifest = selected_release_manifest([artifact], [receipt], selected_count=1)

    assert manifest["ok"] is True
    embedded = manifest["selected_artifacts"][0]["excellence_receipt"]
    assert embedded["auto_derived"] is True
    assert embedded["verdict"] == "approved"
    assert embedded["criterion_vector"]["live_event_object"]["points"] == 12
    assert embedded["scores"]["live_event_score"] == 92.0


def test_derive_excellence_receipts_skips_artifacts_without_hash() -> None:
    receipts = derive_excellence_receipts(
        [{"programme_id": "no-hash", "segment_live_event_report": _live_report(90)}],
        checked_at="2026-06-07T00:00:00Z",
    )

    assert receipts == []
