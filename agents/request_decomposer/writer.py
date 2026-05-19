"""Atomic writer for request decompositions — all tasks or none."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from agents.request_decomposer.models import RequestDecomposition, TaskSpec

_log = logging.getLogger(__name__)

DEFAULT_TASK_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"


def _render_task_note(task: TaskSpec, blocks: list[str]) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    depends = "\n".join(f"  - {d}" for d in task.depends_on) if task.depends_on else "  []"
    blocks_yaml = "\n".join(f"  - {b}" for b in blocks) if blocks else "  []"
    ac_lines = "\n".join(f"- [ ] {c}" for c in task.acceptance_criteria)

    return f"""---
type: cc-task
task_id: {task.task_id}
title: "{task.title}"
status: {task.status}
blocked_reason: {task.blocked_reason or "null"}
assigned_to: unassigned
priority: {task.priority}
wsjf: {task.wsjf}
effort_class: {task.effort_class}
quality_floor: {task.quality_floor}
mutation_surface: {task.mutation_surface}
authority_level: {task.authority_level}
route_metadata_schema: 1
kind: {task.kind}
risk_tier: T2
depends_on:
{depends}
blocks:
{blocks_yaml}
branch: null
pr: null
created_at: {now}
updated_at: {now}
claimed_at: null
completed_at: null
parent_request: {task.parent_request}
parent_spec: {task.parent_spec or "null"}
authority_case: {task.authority_case}
tags:
  - cc-task
  - {task.priority}
  - auto-decomposed
---

# {task.title}

{task.intent}

## Acceptance Criteria

{ac_lines}
"""


def _compute_blocks(tasks: list[TaskSpec]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {t.task_id: [] for t in tasks}
    for task in tasks:
        for dep in task.depends_on:
            if dep in blocks:
                blocks[dep].append(task.task_id)
    return blocks


def write_decomposition(
    decomposition: RequestDecomposition,
    task_root: Path = DEFAULT_TASK_ROOT,
    *,
    dry_run: bool = False,
) -> list[Path]:
    active_dir = task_root / "active"
    active_dir.mkdir(parents=True, exist_ok=True)

    blocks_map = _compute_blocks(decomposition.tasks)

    staged: dict[Path, str] = {}
    for task in decomposition.tasks:
        path = active_dir / f"{task.task_id}.md"
        content = _render_task_note(task, blocks_map.get(task.task_id, []))
        staged[path] = content

    for path in staged:
        if path.exists():
            msg = f"refusing to overwrite existing task {path.name}"
            raise FileExistsError(msg)

    if dry_run:
        return list(staged.keys())

    tmp_paths: list[tuple[Path, Path]] = []
    try:
        for path, content in staged.items():
            tmp = path.with_suffix(".md.decompose-tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp_paths.append((tmp, path))

        written: list[Path] = []
        for tmp, final in tmp_paths:
            tmp.rename(final)
            written.append(final)

    except Exception:
        for tmp, final in tmp_paths:
            if final.exists():
                final.unlink()
            if tmp.exists():
                tmp.unlink()
        raise

    _log.info(
        "Wrote %d tasks for request %s",
        len(written),
        decomposition.request_id,
    )
    return written
