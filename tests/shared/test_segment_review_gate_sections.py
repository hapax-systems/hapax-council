from __future__ import annotations

from shared.segment_review_gate_sections import (
    ADVISORY_EXCELLENCE_REPORT,
    HARD_AUTHORITY_GATE,
    KNOWN_CURRENT_REVIEW_CRITERIA,
    STRUCTURAL_READOUT,
    project_review_gate_sections,
)


def _receipt(criteria: list[tuple[str, bool]]) -> dict:
    return {
        "automated_gate": {
            "passed": all(passed for _name, passed in criteria),
            "criteria": [{"name": name, "passed": passed} for name, passed in criteria],
        }
    }


def test_projection_splits_existing_review_criteria_without_weakening_gate() -> None:
    projection = project_review_gate_sections(
        _receipt(
            [
                ("artifact.command_r_model", True),
                ("script.ideal_livestream_bit", False),
                ("actionability.visible_or_doable_counterpart", False),
            ]
        )
    )

    assert projection[HARD_AUTHORITY_GATE]["passed"] is True
    assert projection[ADVISORY_EXCELLENCE_REPORT]["failed"] == ["script.ideal_livestream_bit"]
    assert projection[STRUCTURAL_READOUT]["failed"] == [
        "actionability.visible_or_doable_counterpart"
    ]
    assert projection["migration_guard"]["current_automated_gate_passed"] is False
    assert projection["migration_guard"]["current_release_gate_unchanged"] is True
    assert projection["migration_guard"][
        "advisory_or_structural_failures_still_block_current_release"
    ] == [
        "actionability.visible_or_doable_counterpart",
        "script.ideal_livestream_bit",
    ]


def test_projection_classifies_all_current_review_criteria() -> None:
    projection = project_review_gate_sections(
        _receipt([(name, True) for name in KNOWN_CURRENT_REVIEW_CRITERIA])
    )

    assert projection["migration_guard"]["unknown_criteria"] == []
    assert (
        projection[HARD_AUTHORITY_GATE]["criterion_count"]
        > projection[ADVISORY_EXCELLENCE_REPORT]["criterion_count"]
    )
    assert projection[STRUCTURAL_READOUT]["criterion_count"] == 3
    assert projection[ADVISORY_EXCELLENCE_REPORT]["failed"] == []


def test_unknown_future_criteria_default_to_hard_authority() -> None:
    projection = project_review_gate_sections(
        _receipt([("future.unclassified_authority_gate", False)])
    )

    assert projection[HARD_AUTHORITY_GATE]["failed"] == ["future.unclassified_authority_gate"]
    assert projection["migration_guard"]["unknown_criteria"] == [
        "future.unclassified_authority_gate"
    ]
    assert projection["migration_guard"]["unknown_criteria_default_to_hard_authority"] is True
