"""Deterministic composability classification for request-decomposition DAGs.

This module intentionally uses only task topology. Decomposer-provided labels
such as routing_class or composition_tolerance are useful hints elsewhere, but
the topology guard must be deterministic: no dependency edges means the task set
is parallel-independent; any dependency edge means the set contains a sequential
chain and its weakest step must satisfy the chain floor.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import pow
from typing import Any, Final

DEFAULT_CHAIN_FLOOR: Final[float] = 0.95


class ComposabilityClass(StrEnum):
    """Topology-derived composability classes."""

    PARALLEL_INDEPENDENT = "parallel_independent"
    SEQUENTIAL = "sequential"


@dataclass(frozen=True, slots=True)
class TaskDependency:
    """One task id and the task ids it depends on."""

    task_id: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DagComposability:
    """Deterministic classification result for a dependency DAG."""

    classification: ComposabilityClass
    task_count: int
    edge_count: int
    root_task_ids: tuple[str, ...]
    sequential_task_ids: tuple[str, ...]
    longest_chain: tuple[str, ...]
    chain_floor: float
    required_step_probability: float

    @property
    def is_parallel_independent(self) -> bool:
        return self.classification is ComposabilityClass.PARALLEL_INDEPENDENT

    @property
    def is_sequential(self) -> bool:
        return self.classification is ComposabilityClass.SEQUENTIAL


class DagComposabilityError(ValueError):
    """Raised when a dependency graph is malformed."""


def required_step_probability(chain_floor: float, step_count: int) -> float:
    """Return the minimum per-step success probability for a chain floor.

    If a sequential chain has ``N`` steps and each step must independently pass
    with probability ``p``, the chain satisfies target floor ``Q`` when
    ``p ** N >= Q``. Therefore the deterministic floor for each step is
    ``p >= Q ** (1 / N)``.
    """

    if chain_floor < 0.0 or chain_floor > 1.0:
        raise ValueError("chain_floor must be between 0.0 and 1.0")
    if step_count < 1:
        raise ValueError("step_count must be at least 1")
    return pow(chain_floor, 1.0 / step_count)


def classify_dag_composability(
    tasks: Iterable[TaskDependency | Mapping[str, Any] | object],
    *,
    chain_floor: float = DEFAULT_CHAIN_FLOOR,
) -> DagComposability:
    """Classify a task DAG from task ids and ``depends_on`` edges.

    Accepted task shapes are:

    - ``TaskDependency`` instances
    - mappings with ``task_id`` and optional ``depends_on`` keys
    - objects with ``task_id`` and optional ``depends_on`` attributes

    Dependencies must point to task ids in the provided graph. Cycles and
    duplicate task ids are rejected because this classifier only speaks about a
    complete DAG.
    """

    graph = _normalize_task_graph(tasks)
    _validate_known_dependencies(graph)
    topological_order = _topological_order(graph)

    edge_count = sum(len(deps) for deps in graph.values())
    root_task_ids = tuple(task_id for task_id in topological_order if not graph[task_id])
    sequential_task_ids = tuple(
        task_id
        for task_id in topological_order
        if graph[task_id] or any(task_id in deps for deps in graph.values())
    )
    longest_chain = _longest_chain(graph, topological_order)
    classification = (
        ComposabilityClass.PARALLEL_INDEPENDENT
        if edge_count == 0
        else ComposabilityClass.SEQUENTIAL
    )

    return DagComposability(
        classification=classification,
        task_count=len(graph),
        edge_count=edge_count,
        root_task_ids=root_task_ids,
        sequential_task_ids=sequential_task_ids,
        longest_chain=longest_chain,
        chain_floor=chain_floor,
        required_step_probability=required_step_probability(
            chain_floor,
            max(1, len(longest_chain)),
        ),
    )


def _normalize_task_graph(
    tasks: Iterable[TaskDependency | Mapping[str, Any] | object],
) -> dict[str, tuple[str, ...]]:
    graph: dict[str, tuple[str, ...]] = {}
    for task in tasks:
        dependency = _coerce_task_dependency(task)
        if dependency.task_id in graph:
            raise DagComposabilityError(f"duplicate task_id: {dependency.task_id}")
        graph[dependency.task_id] = dependency.depends_on
    return graph


def _coerce_task_dependency(task: TaskDependency | Mapping[str, Any] | object) -> TaskDependency:
    if isinstance(task, TaskDependency):
        return task
    if isinstance(task, Mapping):
        task_id = task.get("task_id")
        depends_on = task.get("depends_on", ())
    else:
        task_id = getattr(task, "task_id", None)
        depends_on = getattr(task, "depends_on", ())

    if not isinstance(task_id, str) or not task_id.strip():
        raise DagComposabilityError("task must have a non-empty string task_id")
    return TaskDependency(
        task_id=task_id.strip(),
        depends_on=_normalize_depends_on(depends_on),
    )


def _normalize_depends_on(value: object) -> tuple[str, ...]:
    if value in (None, "", [], ()):
        return ()
    if isinstance(value, str):
        raise DagComposabilityError("depends_on must be an iterable of task id strings")
    try:
        items = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise DagComposabilityError("depends_on must be an iterable of task id strings") from exc

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise DagComposabilityError("depends_on entries must be non-empty strings")
        dep = item.strip()
        if dep not in seen:
            out.append(dep)
            seen.add(dep)
    return tuple(out)


def _validate_known_dependencies(graph: Mapping[str, tuple[str, ...]]) -> None:
    ids = set(graph)
    for task_id, deps in graph.items():
        missing = [dep for dep in deps if dep not in ids]
        if missing:
            raise DagComposabilityError(
                f"{task_id} depends_on unknown task(s): {', '.join(missing)}"
            )


def _topological_order(graph: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Return dependency-first topological order, raising on cycles."""

    dependents: dict[str, list[str]] = {task_id: [] for task_id in graph}
    indegree = {task_id: len(deps) for task_id, deps in graph.items()}
    for task_id, deps in graph.items():
        for dep in deps:
            dependents[dep].append(task_id)

    ready = deque(sorted(task_id for task_id, count in indegree.items() if count == 0))
    ordered: list[str] = []
    while ready:
        current = ready.popleft()
        ordered.append(current)
        for child in sorted(dependents[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(ordered) != len(graph):
        cyclic = sorted(task_id for task_id, count in indegree.items() if count > 0)
        raise DagComposabilityError(f"dependency cycle detected: {', '.join(cyclic)}")
    return tuple(ordered)


def _longest_chain(
    graph: Mapping[str, tuple[str, ...]],
    topological_order: tuple[str, ...],
) -> tuple[str, ...]:
    """Return one longest dependency-first task chain."""

    if not graph:
        return ()

    best_path_by_task: dict[str, tuple[str, ...]] = {}
    for task_id in topological_order:
        deps = graph[task_id]
        if not deps:
            best_path_by_task[task_id] = (task_id,)
            continue
        predecessor = max(
            deps,
            key=lambda dep: (len(best_path_by_task[dep]), best_path_by_task[dep]),
        )
        best_path_by_task[task_id] = (*best_path_by_task[predecessor], task_id)

    return max(
        best_path_by_task.values(),
        key=lambda path: (len(path), path),
    )
