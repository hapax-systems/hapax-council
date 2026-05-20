"""Atomic writer for request decompositions — all tasks or none."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agents.request_decomposer.models import RequestDecomposition, TaskSpec
from shared.frontmatter import parse_frontmatter

_log = logging.getLogger(__name__)

DEFAULT_TASK_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"


def _render_task_note(task: TaskSpec, blocks: list[str]) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    depends = "\n".join(f"  - {d}" for d in task.depends_on) if task.depends_on else "  []"
    blocks_yaml = "\n".join(f"  - {b}" for b in blocks) if blocks else "  []"
    scope_refs = [f"cc-task:{task.task_id}"]
    if task.parent_request:
        scope_refs.append(f"request:{task.parent_request}")
    if task.parent_spec:
        scope_refs.append(str(task.parent_spec))
    scope_yaml = "\n".join(f"  - {ref}" for ref in scope_refs)
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
mutation_scope_refs:
{scope_yaml}
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


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text or text in {"null", "None", "~"}:
        return []
    return [text]


def _render_note(frontmatter: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{body.rstrip()}\n"


def _render_parent_request_update(decomposition: RequestDecomposition) -> tuple[Path, str] | None:
    request_path = Path(decomposition.request_path).expanduser()
    if not request_path.is_file():
        return None

    raw = request_path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(raw)
    if not frontmatter:
        _log.warning(
            "parent request %s has no parseable frontmatter; not linking tasks", request_path
        )
        return None

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    task_ids = [task.task_id for task in decomposition.tasks]
    downstream_tasks = _as_string_list(frontmatter.get("downstream_tasks"))
    seen = set(downstream_tasks)
    for task_id in task_ids:
        if task_id not in seen:
            downstream_tasks.append(task_id)
            seen.add(task_id)

    updated = dict(frontmatter)
    updated["downstream_tasks"] = downstream_tasks
    updated["decomposed_at"] = frontmatter.get("decomposed_at") or now
    updated["decomposition_model"] = decomposition.decomposition_model
    updated["decomposition_task_count"] = len(task_ids)
    updated["updated_at"] = now

    return request_path, _render_note(updated, body)


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
    request_tmp: tuple[Path, Path] | None = None
    try:
        request_update = _render_parent_request_update(decomposition)
        if request_update is not None:
            request_path, request_content = request_update
            tmp = request_path.with_suffix(request_path.suffix + ".decompose-tmp")
            tmp.write_text(request_content, encoding="utf-8")
            request_tmp = (tmp, request_path)

        for path, content in staged.items():
            tmp = path.with_suffix(".md.decompose-tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp_paths.append((tmp, path))

        written: list[Path] = []
        for tmp, final in tmp_paths:
            tmp.rename(final)
            written.append(final)

        if request_tmp is not None:
            tmp, final = request_tmp
            tmp.replace(final)

    except Exception:
        for tmp, final in tmp_paths:
            if final.exists():
                final.unlink()
            if tmp.exists():
                tmp.unlink()
        if request_tmp is not None:
            tmp, _final = request_tmp
            if tmp.exists():
                tmp.unlink()
        raise

    _log.info(
        "Wrote %d tasks for request %s",
        len(written),
        decomposition.request_id,
    )
    return written
