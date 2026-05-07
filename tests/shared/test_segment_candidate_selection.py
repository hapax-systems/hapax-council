from __future__ import annotations

from pathlib import Path

import pytest

from shared.segment_candidate_selection import (
    selected_release_manifest,
    write_selected_release_manifest,
)


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
    }

    manifest = selected_release_manifest([artifact], [_receipt(artifact)])

    assert manifest["ok"] is True
    assert manifest["programmes"] == ["interview-a.json"]


def test_write_selected_release_manifest_refuses_failed_manifest(tmp_path: Path) -> None:
    artifact = _artifact("prog-a")
    manifest = selected_release_manifest([artifact], [])

    with pytest.raises(ValueError, match="ok=true with selected artifacts"):
        write_selected_release_manifest(tmp_path, manifest)

    assert not (tmp_path / "selected-release-manifest.json").exists()
