"""Tests for agents.studio_compositor.camera_semantic_director."""

from __future__ import annotations

from agents.studio_compositor.camera_semantic_director import (
    CameraSalienceInput,
    CameraSemanticDirector,
    MoveReason,
    SemanticRole,
    classify_cameras_from_config,
)


def _make_input(
    role: str = "brio-operator",
    *,
    semantic: SemanticRole = SemanticRole.OPERATOR_FACE,
    salience: float = 0.8,
    person: bool = False,
) -> CameraSalienceInput:
    return CameraSalienceInput(
        camera_role=role,
        semantic_role=semantic,
        salience=salience,
        person_detected=person,
        evidence_refs=("test-ref",),
    )


def test_propose_move_picks_highest_salience() -> None:
    director = CameraSemanticDirector()
    candidates = [
        _make_input("cam-a", salience=0.3),
        _make_input("cam-b", salience=0.9),
        _make_input("cam-c", salience=0.5),
    ]
    move = director.propose_move(candidates)
    assert move is not None
    assert move.camera_role == "cam-b"
    assert move.salience_score == 0.9


def test_manual_override_wins() -> None:
    director = CameraSemanticDirector()
    director.set_manual_override("cam-a")
    candidates = [
        _make_input("cam-a", salience=0.1),
        _make_input("cam-b", salience=0.9),
    ]
    move = director.propose_move(candidates)
    assert move is not None
    assert move.camera_role == "cam-a"
    assert move.reason == MoveReason.MANUAL_OVERRIDE


def test_cooldown_reduces_score() -> None:
    director = CameraSemanticDirector(cooldown_s=100.0)
    candidates = [
        _make_input("cam-a", salience=0.8),
        _make_input("cam-b", salience=0.7),
    ]
    move_a = director.propose_move(candidates)
    assert move_a is not None
    director.apply_move(move_a)

    move_next = director.propose_move(candidates)
    assert move_next is not None
    assert move_next.camera_role == "cam-b"


def test_apply_move_updates_hero() -> None:
    director = CameraSemanticDirector()
    move = director.propose_move([_make_input("cam-x", salience=0.9)])
    assert move is not None
    record = director.apply_move(move)
    assert record.applied
    assert director.current_hero == "cam-x"


def test_reject_move_records_reason() -> None:
    director = CameraSemanticDirector()
    move = director.propose_move([_make_input()])
    assert move is not None
    record = director.reject_move(move, "wcs_not_public_safe")
    assert not record.applied
    assert record.rejected_reason == "wcs_not_public_safe"


def test_person_detected_reason() -> None:
    director = CameraSemanticDirector()
    move = director.propose_move([_make_input(person=True)])
    assert move is not None
    assert move.reason == MoveReason.PERSON_DETECTED


def test_empty_candidates_returns_none() -> None:
    director = CameraSemanticDirector()
    assert director.propose_move([]) is None


def test_history_bounded() -> None:
    director = CameraSemanticDirector()
    for i in range(60):
        move = director.propose_move([_make_input(f"cam-{i}", salience=0.8)])
        assert move is not None
        director.apply_move(move)
    assert len(director.history) <= 50


def test_stale_classification_fallback() -> None:
    classifications = classify_cameras_from_config(
        [
            {"role": "cam-a", "semantic_role": "operator-face"},
            {"role": "cam-b"},
            {"role": "cam-c", "semantic_role": "invalid-role"},
        ]
    )
    assert classifications["cam-a"] == SemanticRole.OPERATOR_FACE
    assert classifications["cam-b"] == SemanticRole.UNSPECIFIED
    assert classifications["cam-c"] == SemanticRole.UNSPECIFIED


def test_role_repair_from_defaults() -> None:
    classifications = classify_cameras_from_config(
        [
            {"role": "brio-operator", "semantic_role": "operator-face"},
            {"role": "c920-desk", "semantic_role": "operator-hands"},
            {"role": "c920-room", "semantic_role": "room-wide"},
        ]
    )
    assert classifications["brio-operator"] == SemanticRole.OPERATOR_FACE
    assert classifications["c920-desk"] == SemanticRole.OPERATOR_HANDS
    assert classifications["c920-room"] == SemanticRole.ROOM_WIDE
