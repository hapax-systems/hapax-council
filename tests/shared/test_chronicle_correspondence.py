from __future__ import annotations

from shared.chronicle_correspondence import (
    annotate_chronicle_event,
    compute_correspondence_score,
)


class TestCorrespondenceScore:
    def test_critical_stimmung_with_matching_language(self) -> None:
        score = compute_correspondence_score(
            "I'm struggling with this issue",
            {"stimmung_region": "critical", "du_state": "REPAIR_1", "gqi": 0.2},
        )
        assert score > 0.5

    def test_nominal_stimmung_without_crisis_language(self) -> None:
        score = compute_correspondence_score(
            "Here's the analysis of the data",
            {"stimmung_region": "nominal", "du_state": "GROUNDED", "gqi": 0.9},
        )
        assert score > 0.8

    def test_empty_receipt_returns_zero(self) -> None:
        assert compute_correspondence_score("anything", {}) == 0.0


class TestAnnotateEvent:
    def test_adds_correspondence_fields(self) -> None:
        payload: dict = {"event_type": "voice.turn_end", "text": "test"}
        annotated = annotate_chronicle_event(payload, narration_text="test narration")
        assert "correspondence_score" in annotated
        assert "receipt_id" in annotated
        assert "correspondence_annotated_at" in annotated
