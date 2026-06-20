"""Tests for the operator mental-state content-class detector (cross-boundary egress)."""

from __future__ import annotations

import pytest

from shared.governance.mental_state_redaction import operator_mental_state_present


@pytest.mark.parametrize(
    "text",
    [
        "the operator is overwhelmed lately",
        "I am exhausted and burned out",
        "operator anxiety is rising again",
        "my mental health has been poor",
        "the operator felt frustrated with the gate",
        "Oudepode is demoralized about the backlog",
        "OTO's mood has been low this week",
    ],
)
def test_operator_mental_state_present_positive(text: str) -> None:
    assert operator_mental_state_present(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "anxiety detection feature for the dashboard",
        "the operator approved the PR",
        "operator-patterns collection is dead schema",
        "the deploy faces danger in production",
        "add a mood_shift visual affordance",
        "refactor the stress-test harness for CI",
    ],
)
def test_operator_mental_state_present_negative(text: str) -> None:
    assert not operator_mental_state_present(text)


def test_standalone_operator_affect_phrase_flags_without_nearby_affect_term() -> None:
    # "operator's mental state" is itself the content class.
    assert operator_mental_state_present("preamble ... the operator's mental state ... trailing")


def test_proximity_window_bounds_detection() -> None:
    # Self-referent and affect term far apart (> window) do not flag.
    far = "the operator " + ("x " * 60) + "anxiety"
    assert not operator_mental_state_present(far, window=40)
    assert operator_mental_state_present("the operator is anxious", window=40)


def test_first_person_over_detection_is_intended_fail_closed() -> None:
    # Conservative egress bias (review finding, pinned): a bare first-person
    # token near an affect term flags even when the affect describes a third
    # party. This is INTENDED over-detection — fail-closed → operator review.
    # A missed operator-affect leak is worse than an over-block, so the detector
    # errs toward flagging. This test pins the boundary the reviewer flagged.
    assert operator_mental_state_present("Bob said it worries him; I logged it")
