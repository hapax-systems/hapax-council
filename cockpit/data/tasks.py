"""Task collector — research task management via filesystem-as-bus.

Tasks are markdown files with YAML frontmatter in data/tasks/.
Deterministic, no LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

_TASKS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "tasks"

VALID_STATUSES = {"pending", "active", "done", "blocked"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}


@dataclass
class Task:
    """A single research task."""

    id: str
    title: str
    status: str  # pending | active | done | blocked
    priority: str  # critical | high | medium | low
    created: str  # ISO date
    updated: str  # ISO datetime
    phase: str = ""  # A1 | B | A2
    session: int | None = None
    tags: list[str] = field(default_factory=list)
    github_issue: int | None = None
    blocked_by: str = ""
    notes: str = ""


@dataclass
class TaskSnapshot:
    """Aggregated task state."""

    tasks: list[Task] = field(default_factory=list)
    pending_count: int = 0
    active_count: int = 0
    blocked_count: int = 0
    done_count: int = 0


def _tasks_dir() -> Path:
    _TASKS_DIR.mkdir(parents=True, exist_ok=True)
    return _TASKS_DIR


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80]


def _parse_task(path: Path) -> Task | None:
    """Parse a task markdown file into a Task dataclass."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None

    task_id = fm.get("id", path.stem)
    notes = parts[2].strip()

    return Task(
        id=task_id,
        title=fm.get("title", task_id),
        status=fm.get("status", "pending"),
        priority=fm.get("priority", "medium"),
        created=fm.get("created", ""),
        updated=fm.get("updated", ""),
        phase=fm.get("phase", ""),
        session=fm.get("session"),
        tags=fm.get("tags", []),
        github_issue=fm.get("github_issue"),
        blocked_by=fm.get("blocked_by", ""),
        notes=notes,
    )


def collect_tasks() -> TaskSnapshot:
    """Read all task files and return a snapshot."""
    tasks_path = _tasks_dir()
    tasks: list[Task] = []

    for md in sorted(tasks_path.glob("*.md")):
        task = _parse_task(md)
        if task:
            tasks.append(task)

    return TaskSnapshot(
        tasks=tasks,
        pending_count=sum(1 for t in tasks if t.status == "pending"),
        active_count=sum(1 for t in tasks if t.status == "active"),
        blocked_count=sum(1 for t in tasks if t.status == "blocked"),
        done_count=sum(1 for t in tasks if t.status == "done"),
    )


def get_task(task_id: str) -> Task | None:
    """Read a single task by ID."""
    path = _tasks_dir() / f"{task_id}.md"
    if path.exists():
        return _parse_task(path)
    # Fallback: scan all files for matching id in frontmatter
    for md in _tasks_dir().glob("*.md"):
        task = _parse_task(md)
        if task and task.id == task_id:
            return task
    return None


def save_task(task: Task) -> Path:
    """Write a task as a markdown file with YAML frontmatter."""
    fm = {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "created": task.created,
        "updated": task.updated,
    }
    if task.phase:
        fm["phase"] = task.phase
    if task.session is not None:
        fm["session"] = task.session
    if task.tags:
        fm["tags"] = task.tags
    if task.github_issue is not None:
        fm["github_issue"] = task.github_issue
    if task.blocked_by:
        fm["blocked_by"] = task.blocked_by

    content = "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---\n"
    if task.notes:
        content += "\n" + task.notes + "\n"

    path = _tasks_dir() / f"{task.id}.md"
    path.write_text(content, encoding="utf-8")
    return path


def create_task(
    title: str,
    priority: str = "medium",
    phase: str = "",
    tags: list[str] | None = None,
    github_issue: int | None = None,
) -> Task:
    """Create a new task and persist it."""
    now = datetime.now(UTC)
    task = Task(
        id=_slugify(title),
        title=title,
        status="pending",
        priority=priority if priority in VALID_PRIORITIES else "medium",
        created=now.strftime("%Y-%m-%d"),
        updated=now.isoformat(),
        phase=phase,
        tags=tags or [],
        github_issue=github_issue,
    )
    save_task(task)
    return task


def update_task_status(task_id: str, status: str) -> Task | None:
    """Update a task's status and persist it."""
    if status not in VALID_STATUSES:
        return None
    task = get_task(task_id)
    if not task:
        return None
    task.status = status
    task.updated = datetime.now(UTC).isoformat()
    save_task(task)
    return task
