"""Self-contained tests for the intake demand-plumb (requirement_vector into Task).

The demand-shape (8-dim requirement_vector + routing_class) is written by the
decomposer and was previously invisible to dispatch. This slice parses it into
Task/QueueTask so the SdlcRouter shadow scorer can consume it (the fit_scorer is
a follow-on sub-slice). Tests _parse_requirement_vector + _parse_task end-to-end.
"""

from __future__ import annotations

from pathlib import Path

from agents.coordinator.core import _parse_requirement_vector, _parse_task
from shared.dispatch_service_time import QueueTask

# --------------------------------------------------------- _parse_requirement_vector


def test_parse_requirement_vector_valid() -> None:
    rv = {"context_length": 4, "mutation_risk": 5, "quality_floor": 3}
    assert _parse_requirement_vector(rv) == rv


def test_parse_requirement_vector_absent_or_empty() -> None:
    assert _parse_requirement_vector(None) is None
    assert _parse_requirement_vector({}) is None
    assert _parse_requirement_vector("not-a-dict") is None
    assert _parse_requirement_vector(["a", "b"]) is None


def test_parse_requirement_vector_rejects_non_int_and_bool() -> None:
    # bool is a subclass of int but must be rejected (strict int scores).
    assert _parse_requirement_vector({"context_length": True}) is None
    assert _parse_requirement_vector({"context_length": 4.0}) is None  # float, not int
    assert _parse_requirement_vector({"context_length": "4"}) is None  # str
    assert _parse_requirement_vector({4: 4}) is None  # non-str key


def test_parse_requirement_vector_zero_is_valid() -> None:
    # all-zero is a VALID low-complexity vector (the fit_scorer treats it as neutral,
    # not absent). The parser must pass it through (None = absent/unparsed).
    rv = {"context_length": 0, "mutation_risk": 0}
    assert _parse_requirement_vector(rv) == rv


# --------------------------------------------------------- _parse_task (end-to-end)


_FRONTMATTER = """---
type: cc-task
task_id: T-demand
title: demand-plumb test
status: offered
assigned_to: unassigned
wsjf: 8.0
effort_class: standard
platform_suitability:
  - codex
quality_floor: deterministic_ok
requirement_vector:
  context_length: 4
  mutation_risk: 5
  verification_demand: 3
  quality_floor: 3
routing_class: codex-headless-full
mutation_surface: source
authority_level: support_non_authoritative
created_at: 2026-07-04T00:00:00Z
---

# body
"""


def test_parse_task_reads_demand_shape(tmp_path: Path) -> None:
    path = tmp_path / "T-demand.md"
    path.write_text(_FRONTMATTER, encoding="utf-8")
    task = _parse_task(path)
    assert task is not None
    assert task.requirement_vector == {
        "context_length": 4,
        "mutation_risk": 5,
        "verification_demand": 3,
        "quality_floor": 3,
    }
    assert task.routing_class == "codex-headless-full"
    assert task.mutation_surface == "source"
    assert task.authority_level == "support_non_authoritative"


def test_parse_task_demand_shape_absent_is_none(tmp_path: Path) -> None:
    path = tmp_path / "T-plain.md"
    path.write_text(
        "---\ntype: cc-task\ntask_id: T-plain\ntitle: plain\nstatus: offered\n"
        "assigned_to: unassigned\nwsjf: 1.0\neffort_class: standard\n"
        "platform_suitability:\n  - claude\nquality_floor: deterministic_ok\n---\n\n# body\n",
        encoding="utf-8",
    )
    task = _parse_task(path)
    assert task is not None
    assert task.requirement_vector is None  # honest-DARK
    assert task.routing_class is None
    assert task.mutation_surface is None
    assert task.authority_level is None


def test_parse_task_rejects_invalid_requirement_vector(tmp_path: Path) -> None:
    path = tmp_path / "T-bad.md"
    path.write_text(
        "---\ntype: cc-task\ntask_id: T-bad\ntitle: bad rv\nstatus: offered\n"
        "assigned_to: unassigned\nwsjf: 1.0\neffort_class: standard\n"
        "platform_suitability:\n  - codex\nquality_floor: deterministic_ok\n"
        "requirement_vector: not-a-mapping\n---\n\n# body\n",
        encoding="utf-8",
    )
    task = _parse_task(path)
    assert task is not None
    assert task.requirement_vector is None  # invalid -> honest-DARK, not a crash


# --------------------------------------------------------- QueueTask threading


def test_queue_task_carries_demand_shape() -> None:
    rv = {"context_length": 4}
    qt = QueueTask(
        task_id="T",
        wsjf=8.0,
        platform_suitability=("codex",),
        age_s=0.0,
        requirement_vector=rv,
        routing_class="codex-headless-full",
    )
    assert qt.requirement_vector == rv
    assert qt.routing_class == "codex-headless-full"


def test_queue_task_demand_shape_defaults_none() -> None:
    # backward-compat: existing constructions (no demand shape) get None.
    qt = QueueTask(task_id="T", wsjf=1.0, platform_suitability=("claude",))
    assert qt.requirement_vector is None
    assert qt.routing_class is None
