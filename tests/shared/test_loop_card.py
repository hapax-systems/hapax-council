from __future__ import annotations

from pydantic import ValidationError

from shared.loop_card import ControlLoopCard, LoopAdmissibility, validate_loop_cards


def _feedforward_card() -> dict:
    return {
        "loop_card_version": 1,
        "loop_id": "loop:segment:source-visible",
        "admissibility": "feedforward_plan",
        "plant_boundary": "future runtime segment beat",
        "controlled_variable": "source_visible",
        "reference_signal": "source card must be readable",
        "sensor_ref": "readback:source-visible",
        "actuator_ref": "runtime_layout_controller",
        "sample_period_s": 1.0,
        "latency_budget_s": 30.0,
        "readback_ref": "readback:source-visible",
        "fallback_mode": "narrow to spoken argument",
        "authority_boundary": "prep_prior_only_runtime_must_close_readback",
        "privacy_ceiling": "public_archive_candidate",
        "evidence_refs": ["source:fixture"],
        "disturbance_refs": ["stale_readback"],
        "failure_mode": "missing or mismatched readback",
        "limits": ["prepared artifact cannot command layout"],
    }


def test_feedforward_loop_card_marks_prep_as_prior_not_runtime_success() -> None:
    card = ControlLoopCard.model_validate(_feedforward_card())

    assert card.admissibility is LoopAdmissibility.FEEDFORWARD_PLAN
    assert card.readback_ref == "readback:source-visible"
    assert "prior" in card.authority_boundary


def test_closed_loop_card_requires_sensor_actuator_timing_and_readback() -> None:
    raw = _feedforward_card() | {
        "admissibility": "closed_loop",
        "sensor_ref": None,
        "actuator_ref": None,
        "sample_period_s": None,
        "latency_budget_s": None,
        "readback_ref": None,
    }

    try:
        ControlLoopCard.model_validate(raw)
    except ValidationError as exc:
        message = str(exc)
    else:
        raise AssertionError("closed-loop card without operational fields should fail")

    assert "sensor_ref" in message
    assert "actuator_ref" in message
    assert "readback_ref" in message


def test_analogy_only_card_requires_marked_limits() -> None:
    raw = _feedforward_card() | {
        "admissibility": "analogy_only",
        "authority_boundary": "analogy_only_no_runtime_authority",
        "evidence_refs": [],
        "limits": [],
    }

    report = validate_loop_cards([raw])

    assert report["ok"] is False
    assert report["violations"][0]["reason"] == "invalid_loop_card"
    assert "analogy-only loop card must state limits" in report["violations"][0]["error"]


def test_validate_loop_cards_rejects_duplicate_loop_ids() -> None:
    card = _feedforward_card()

    report = validate_loop_cards([card, card])

    assert report["ok"] is False
    assert report["violations"][0]["reason"] == "duplicate_loop_id"
