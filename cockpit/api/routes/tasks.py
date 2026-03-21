"""Task management endpoints — CRUD for research tasks."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreateRequest(BaseModel):
    title: str
    priority: str = "medium"
    phase: str = ""
    tags: list[str] = []
    github_issue: int | None = None


class TaskStatusRequest(BaseModel):
    status: str


@router.get("")
async def list_tasks(status: str | None = None) -> dict:
    """List all tasks, optionally filtered by status."""
    from cockpit.data.tasks import collect_tasks

    snapshot = collect_tasks()
    tasks = snapshot.tasks
    if status:
        tasks = [t for t in tasks if t.status == status]

    return {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "phase": t.phase,
                "session": t.session,
                "tags": t.tags,
                "github_issue": t.github_issue,
                "blocked_by": t.blocked_by,
                "created": t.created,
                "updated": t.updated,
            }
            for t in tasks
        ],
        "counts": {
            "pending": snapshot.pending_count,
            "active": snapshot.active_count,
            "blocked": snapshot.blocked_count,
            "done": snapshot.done_count,
        },
    }


@router.get("/{task_id}")
async def get_task(task_id: str) -> dict:
    """Get a single task by ID."""
    from cockpit.data.tasks import get_task as _get

    task = _get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "phase": task.phase,
        "session": task.session,
        "tags": task.tags,
        "github_issue": task.github_issue,
        "blocked_by": task.blocked_by,
        "notes": task.notes,
        "created": task.created,
        "updated": task.updated,
    }


@router.post("")
async def create_task(req: TaskCreateRequest) -> dict:
    """Create a new task."""
    from cockpit.data.tasks import create_task as _create

    task = _create(
        title=req.title,
        priority=req.priority,
        phase=req.phase,
        tags=req.tags,
        github_issue=req.github_issue,
    )
    return {"status": "created", "id": task.id, "title": task.title}


@router.put("/{task_id}/status")
async def update_status(task_id: str, req: TaskStatusRequest) -> dict:
    """Update a task's status."""
    from cockpit.data.tasks import VALID_STATUSES, update_task_status

    if req.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{req.status}'. Must be one of: {', '.join(VALID_STATUSES)}",
        )

    task = update_task_status(task_id, req.status)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"status": "updated", "id": task.id, "new_status": task.status}
