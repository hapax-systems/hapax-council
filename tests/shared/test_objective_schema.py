"""Tests for shared.objective_schema (LRR Phase 8 item 1)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.objective_schema import (
    Objective,
    ObjectivePriority,
    ObjectiveStatus,
    score_objective_advancement,
)


def _valid_kwargs(**overrides):
    base = {
        "objective_id": "obj-001",
        "title": "Establish OLMo-3 baseline on RIFTS",
        "status": ObjectiveStatus.active,
        "priority": ObjectivePriority.high,
        "opened_at": datetime(2026, 4, 16, tzinfo=UTC),
        "linked_claims": ["claim-shaikh"],
        "linked_conditions": ["olmo-3-7b-sft"],
        "success_criteria": ["RIFTS baseline rates recorded"],
        "activities_that_advance": ["study", "observe"],
    }
    base.update(overrides)
    return base


class TestObjectiveBasics:
    def test_minimal_valid_objective(self):
        obj = Objective(**_valid_kwargs())
        assert obj.objective_id == "obj-001"
        assert obj.status == ObjectiveStatus.active

    def test_rejects_malformed_id(self):
        with pytest.raises(ValidationError):
            Objective(**_valid_kwargs(objective_id="objective-001"))
        with pytest.raises(ValidationError):
            Objective(**_valid_kwargs(objective_id="obj-1"))

    def test_rejects_unknown_activity(self):
        with pytest.raises(ValidationError) as exc:
            Objective(**_valid_kwargs(activities_that_advance=["study", "sleep"]))
        assert "unknown activities" in str(exc.value)

    def test_requires_success_criteria(self):
        with pytest.raises(ValidationError):
            Objective(**_valid_kwargs(success_criteria=[]))

    def test_requires_activities(self):
        with pytest.raises(ValidationError):
            Objective(**_valid_kwargs(activities_that_advance=[]))

    def test_closed_at_requires_closed_status(self):
        with pytest.raises(ValidationError) as exc:
            Objective(
                **_valid_kwargs(
                    status=ObjectiveStatus.active,
                    closed_at=datetime(2026, 4, 20, tzinfo=UTC),
                )
            )
        assert "closed_at may only be set when status='closed'" in str(exc.value)

    def test_closed_status_allows_closed_at(self):
        obj = Objective(
            **_valid_kwargs(
                status=ObjectiveStatus.closed,
                closed_at=datetime(2026, 4, 20, tzinfo=UTC),
            )
        )
        assert obj.closed_at.day == 20


class TestObjectiveAdvancementScoring:
    def test_empty_active_list_returns_zero(self):
        assert score_objective_advancement("study", []) == 0.0

    def test_single_objective_advances(self):
        obj = Objective(**_valid_kwargs(activities_that_advance=["study"]))
        assert score_objective_advancement("study", [obj]) == 1.0
        assert score_objective_advancement("react", [obj]) == 0.0

    def test_multiple_objectives_averaged(self):
        o1 = Objective(**_valid_kwargs(objective_id="obj-001", activities_that_advance=["study"]))
        o2 = Objective(
            **_valid_kwargs(objective_id="obj-002", activities_that_advance=["study", "observe"])
        )
        o3 = Objective(**_valid_kwargs(objective_id="obj-003", activities_that_advance=["react"]))

        assert score_objective_advancement("study", [o1, o2, o3]) == pytest.approx(2 / 3)
        assert score_objective_advancement("observe", [o1, o2, o3]) == pytest.approx(1 / 3)
        assert score_objective_advancement("react", [o1, o2, o3]) == pytest.approx(1 / 3)
        assert score_objective_advancement("chat", [o1, o2, o3]) == 0.0
