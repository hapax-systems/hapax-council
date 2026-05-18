from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cc-task-offer-ready"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _task_frontmatter(
    *,
    status: str = "ready",
    assigned_to: str = "null",
    depends_on: str = "dep",
    authority_level: str = "delegated",
    mutation_surface: str = "planning",
) -> str:
    return f"""\
---
type: cc-task
task_id: ready-task
title: "Ready task"
status: {status}
assigned_to: {assigned_to}
priority: p1
wsjf: 5.0
depends_on:
  - {depends_on}
created_at: 2026-05-17T00:00:00Z
updated_at: 2026-05-17T00:00:00Z
parent_request: request.md
authority_case: CASE-TEST-001
parent_spec: spec.md
quality_floor: deterministic_ok
mutation_surface: {mutation_surface}
authority_level: {authority_level}
route_metadata_schema: 1
kind: planning
---

# Ready Task
"""


def _write_ready_task(vault: Path, **kwargs: str) -> Path:
    return _write(vault / "active" / "ready-task.md", _task_frontmatter(**kwargs))


def _write_dep(vault: Path, *, status: str = "done") -> Path:
    return _write(
        vault / "closed" / "dep.md",
        f"""\
---
type: cc-task
task_id: dep
status: {status}
assigned_to: cx-test
pr: null
---

# Dep
""",
    )


def _run(vault: Path, task_id: str = "ready-task") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), task_id, "--vault-root", str(vault)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_promotes_dependency_satisfied_ready_task_to_offered(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault)
    _write_dep(vault)

    result = _run(vault)

    assert result.returncode == 0, result.stderr
    text = task.read_text(encoding="utf-8")
    assert "status: offered" in text
    assert "assigned_to: unassigned" in text
    assert "claimed_at: null" in text
    assert "authority_level: authoritative" in text
    assert "mutation_surface: vault_docs" in text
    assert "promoted ready -> offered by cc-task-offer-ready" in text


def test_blocks_ready_task_with_nonterminal_dependency(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault)
    _write_dep(vault, status="in_progress")

    result = _run(vault)

    assert result.returncode == 5
    assert "unmet dependencies" in result.stderr
    assert "status: in_progress" in result.stderr
    assert "status: ready" in task.read_text(encoding="utf-8")


def test_blocks_ready_task_with_concrete_assignee(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(vault, assigned_to="cx-other")
    _write_dep(vault)

    result = _run(vault)

    assert result.returncode == 4
    assert "assigned to 'cx-other'" in result.stderr
    assert "status: ready" in task.read_text(encoding="utf-8")


def test_blocks_ready_task_with_unrepairable_route_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    task = _write_ready_task(
        vault,
        authority_level="not-a-real-authority-level",
        mutation_surface="not-a-real-surface",
    )
    _write_dep(vault)

    result = _run(vault)

    assert result.returncode == 7
    assert "route metadata is not dispatchable" in result.stderr
    assert "status: ready" in task.read_text(encoding="utf-8")
