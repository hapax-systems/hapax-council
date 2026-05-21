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


def _run_reconcile(vault: Path, *, dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [str(SCRIPT), "--reconcile", "--vault-root", str(vault)]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _write_task(vault: Path, task_id: str, *, status: str, depends_on: str) -> Path:
    return _write(
        vault / "active" / f"{task_id}.md",
        f"""\
---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: {status}
assigned_to: null
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
mutation_surface: vault_docs
authority_level: authoritative
route_metadata_schema: 1
kind: planning
---

# {task_id}
""",
    )


def test_reconcile_promotes_satisfied_and_skips_unsatisfied(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    _write_dep(vault, status="done")
    t1 = _write_task(vault, "task-satisfied", status="ready", depends_on="dep")
    t2 = _write_task(vault, "task-blocked", status="ready", depends_on="missing-dep")
    t3 = _write_task(vault, "task-offered", status="offered", depends_on="dep")

    result = _run_reconcile(vault)

    assert result.returncode == 0
    assert "1 promoted, 1 skipped" in result.stdout
    assert "status: offered" in t1.read_text(encoding="utf-8")
    assert "status: ready" in t2.read_text(encoding="utf-8")
    assert "status: offered" in t3.read_text(encoding="utf-8")


def test_reconcile_dry_run_does_not_modify(tmp_path: Path) -> None:
    vault = tmp_path / "tasks"
    _write_dep(vault, status="done")
    t1 = _write_task(vault, "task-ready", status="ready", depends_on="dep")

    result = _run_reconcile(vault, dry_run=True)

    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert "status: ready" in t1.read_text(encoding="utf-8")
