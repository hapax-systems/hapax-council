"""Tests for deterministic DAG composability classification."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from shared.dag_composability import (
    ComposabilityClass,
    DagComposabilityError,
    TaskDependency,
    classify_dag_composability,
    required_step_probability,
)


@dataclass
class ObjectTask:
    task_id: str
    depends_on: list[str]


class TestDagComposabilityCanaries:
    def test_parallel_set_classifies_parallel_independent(self) -> None:
        result = classify_dag_composability(
            [
                {"task_id": "task-a", "depends_on": []},
                {"task_id": "task-b", "depends_on": []},
                {"task_id": "task-c", "depends_on": []},
            ]
        )

        assert result.classification is ComposabilityClass.PARALLEL_INDEPENDENT
        assert result.is_parallel_independent
        assert not result.is_sequential
        assert result.edge_count == 0
        assert result.root_task_ids == ("task-a", "task-b", "task-c")
        assert result.sequential_task_ids == ()

    def test_chain_classifies_sequential(self) -> None:
        result = classify_dag_composability(
            [
                TaskDependency("task-a"),
                TaskDependency("task-b", ("task-a",)),
                TaskDependency("task-c", ("task-b",)),
            ]
        )

        assert result.classification is ComposabilityClass.SEQUENTIAL
        assert result.is_sequential
        assert not result.is_parallel_independent
        assert result.edge_count == 2
        assert result.longest_chain == ("task-a", "task-b", "task-c")
        assert result.sequential_task_ids == ("task-a", "task-b", "task-c")


class TestDagComposabilityDetails:
    def test_any_dependency_edge_is_sequential_even_with_parallel_branches(self) -> None:
        result = classify_dag_composability(
            [
                ObjectTask("root", []),
                ObjectTask("branch-a", ["root"]),
                ObjectTask("branch-b", ["root"]),
                ObjectTask("independent", []),
            ]
        )

        assert result.classification is ComposabilityClass.SEQUENTIAL
        assert result.edge_count == 2
        assert result.root_task_ids == ("independent", "root")
        assert result.longest_chain in {
            ("root", "branch-a"),
            ("root", "branch-b"),
        }
        assert result.sequential_task_ids == ("root", "branch-a", "branch-b")

    def test_empty_graph_is_parallel_independent(self) -> None:
        result = classify_dag_composability([])

        assert result.classification is ComposabilityClass.PARALLEL_INDEPENDENT
        assert result.task_count == 0
        assert result.edge_count == 0
        assert result.longest_chain == ()

    def test_duplicate_depends_on_edges_are_deduplicated(self) -> None:
        result = classify_dag_composability(
            [
                {"task_id": "a", "depends_on": []},
                {"task_id": "b", "depends_on": ["a", "a"]},
            ]
        )

        assert result.edge_count == 1
        assert result.longest_chain == ("a", "b")

    def test_task_without_depends_on_key_is_root(self) -> None:
        result = classify_dag_composability([{"task_id": "a"}])

        assert result.root_task_ids == ("a",)
        assert result.classification is ComposabilityClass.PARALLEL_INDEPENDENT

    def test_unknown_dependency_is_rejected(self) -> None:
        with pytest.raises(DagComposabilityError, match="unknown task"):
            classify_dag_composability([TaskDependency("task-a", ("missing",))])

    def test_cycle_is_rejected(self) -> None:
        with pytest.raises(DagComposabilityError, match="dependency cycle"):
            classify_dag_composability(
                [
                    TaskDependency("task-a", ("task-c",)),
                    TaskDependency("task-b", ("task-a",)),
                    TaskDependency("task-c", ("task-b",)),
                ]
            )

    def test_duplicate_task_id_is_rejected(self) -> None:
        with pytest.raises(DagComposabilityError, match="duplicate task_id"):
            classify_dag_composability([TaskDependency("task-a"), TaskDependency("task-a")])

    @pytest.mark.parametrize(
        "action, error_type",
        [
            (
                lambda: classify_dag_composability([{"task_id": ""}]),
                DagComposabilityError,
            ),
            (
                lambda: classify_dag_composability([{"task_id": "a", "depends_on": "b"}]),
                DagComposabilityError,
            ),
            (
                lambda: classify_dag_composability([{"task_id": "a", "depends_on": [" "]}]),
                DagComposabilityError,
            ),
            (
                lambda: classify_dag_composability([TaskDependency("task-a", ("missing",))]),
                DagComposabilityError,
            ),
            (
                lambda: classify_dag_composability(
                    [
                        TaskDependency("task-a", ("task-c",)),
                        TaskDependency("task-b", ("task-a",)),
                        TaskDependency("task-c", ("task-b",)),
                    ]
                ),
                DagComposabilityError,
            ),
            (
                lambda: classify_dag_composability(
                    [TaskDependency("task-a"), TaskDependency("task-a")]
                ),
                DagComposabilityError,
            ),
            (
                lambda: required_step_probability(-0.01, 1),
                ValueError,
            ),
            (
                lambda: required_step_probability(0.95, 0),
                ValueError,
            ),
        ],
    )
    def test_malformed_graph_errors_include_next_actions(
        self,
        action,
        error_type: type[Exception],
    ) -> None:
        with pytest.raises(error_type, match="next action"):
            action()


class TestRequiredStepProbability:
    def test_chain_floor_is_distributed_across_steps(self) -> None:
        required = required_step_probability(0.95, 3)

        assert required == pytest.approx(0.95 ** (1 / 3))
        assert required**3 == pytest.approx(0.95)

    def test_classifier_reports_requirement_for_longest_chain(self) -> None:
        result = classify_dag_composability(
            [
                TaskDependency("a"),
                TaskDependency("b", ("a",)),
                TaskDependency("c", ("b",)),
                TaskDependency("d", ("a",)),
            ],
            chain_floor=0.90,
        )

        assert result.longest_chain == ("a", "b", "c")
        assert result.required_step_probability == pytest.approx(0.90 ** (1 / 3))

    @pytest.mark.parametrize("chain_floor", [-0.01, 1.01])
    def test_invalid_chain_floor_rejected(self, chain_floor: float) -> None:
        with pytest.raises(ValueError, match="chain_floor"):
            required_step_probability(chain_floor, 1)

    def test_step_count_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="step_count"):
            required_step_probability(0.95, 0)
