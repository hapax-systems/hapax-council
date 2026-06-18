from __future__ import annotations

import pytest

from shared.segment_grounding_efficacy import (
    AXIS_A_GROUNDING_EFFICACY_RULER_VERSION,
    compare_grounding_efficacy,
    evaluate_dyad_grounding_efficacy,
)


def test_strong_dyad_evidence_scores_excellent() -> None:
    report = evaluate_dyad_grounding_efficacy(
        {
            "turn_pair_coherence": 0.86,
            "operator_grounded": True,
            "audience_context_cued": True,
            "shared_reference_public": True,
            "overhearer_readback_present": True,
            "peer_floor_share_ratio": 0.52,
            "repair_opportunities": 2,
            "repair_successes": 2,
        }
    )

    assert report["ruler_version"] == AXIS_A_GROUNDING_EFFICACY_RULER_VERSION
    assert report["axis_id"] == "A"
    assert report["leg"] == "dyad"
    assert report["ok"] is True
    assert report["band"] == "excellent"
    assert report["score_0_100"] >= 95
    assert report["coverage"]["ok"] is True
    assert {item["name"] for item in report["capability_scores"]} == {
        "turn_pair_coherence",
        "dual_addressee_legibility",
        "peer_floor_share",
        "on_air_repair",
    }


def test_missing_dual_addressee_legibility_caps_otherwise_high_score() -> None:
    report = evaluate_dyad_grounding_efficacy(
        {
            "turn_pair_coherence": 0.95,
            "peer_floor_share_ratio": 0.5,
            "repair_opportunities": 0,
        }
    )

    assert report["ok"] is False
    assert report["band"] == "invalid"
    assert report["coverage"]["ok"] is False
    assert report["coverage"]["missing_required"] == ["dual_addressee_legibility"]
    assert report["score_0_100"] < 75
    assert {item["reason"] for item in report["violations"]} == {
        "missing_dual_addressee_legibility"
    }


def test_peer_floor_share_penalizes_deference_or_domination() -> None:
    balanced = evaluate_dyad_grounding_efficacy(
        {
            "turn_pair_coherence": 0.8,
            "dual_addressee_legibility": 1.0,
            "peer_floor_share_ratio": 0.5,
            "repair_opportunities": 0,
        }
    )
    deferential = evaluate_dyad_grounding_efficacy(
        {
            "turn_pair_coherence": 0.8,
            "dual_addressee_legibility": 1.0,
            "peer_floor_share_ratio": 0.95,
            "repair_opportunities": 0,
        }
    )

    assert balanced["score_0_100"] > deferential["score_0_100"]
    floor_score = next(
        item for item in deferential["capability_scores"] if item["name"] == "peer_floor_share"
    )
    assert floor_score["score"] < 0.25
    assert compare_grounding_efficacy(balanced, deferential) == 1


def test_repair_success_rate_scores_when_opportunities_occur() -> None:
    report = evaluate_dyad_grounding_efficacy(
        {
            "turn_pair_coherence": 0.8,
            "dual_addressee_legibility": 0.9,
            "peer_floor_share_ratio": 0.5,
            "repair_opportunities": 5,
            "repair_successes": 2,
        }
    )

    repair = next(item for item in report["capability_scores"] if item["name"] == "on_air_repair")
    assert repair["not_applicable"] is False
    assert repair["score"] == pytest.approx(0.4)
    assert report["score_0_100"] == 78


def test_no_repair_opportunities_are_explicitly_not_applicable() -> None:
    report = evaluate_dyad_grounding_efficacy(
        {
            "turn_pair_coherence": 0.8,
            "dual_addressee_legibility": 1.0,
            "peer_floor_share_ratio": 0.5,
            "repair_opportunities": 0,
        }
    )

    repair = next(item for item in report["capability_scores"] if item["name"] == "on_air_repair")
    assert repair["not_applicable"] is True
    assert repair["score"] is None
    assert report["coverage"]["not_applicable"] == ["on_air_repair"]
    assert report["coverage"]["ok"] is True
    assert report["score_0_100"] == 93


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("turn_pair_coherence", 1.2),
        ("dual_addressee_legibility", -0.1),
        ("peer_floor_share_ratio", 2.0),
        ("on_air_repair_success_rate", "yes"),
    ],
)
def test_unit_inputs_reject_out_of_range_or_non_numeric_values(field: str, value: object) -> None:
    evidence = {
        "turn_pair_coherence": 0.8,
        "dual_addressee_legibility": 0.8,
        "peer_floor_share_ratio": 0.5,
        "repair_opportunities": 0,
        field: value,
    }

    with pytest.raises(ValueError):
        evaluate_dyad_grounding_efficacy(evidence)


def test_repair_successes_cannot_exceed_opportunities() -> None:
    with pytest.raises(ValueError, match="repair_successes cannot exceed"):
        evaluate_dyad_grounding_efficacy(
            {
                "turn_pair_coherence": 0.8,
                "dual_addressee_legibility": 0.8,
                "peer_floor_share_ratio": 0.5,
                "repair_opportunities": 1,
                "repair_successes": 2,
            }
        )
