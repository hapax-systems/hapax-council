"""Demo history, management, and generation API endpoints."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agents.demo_pipeline.history import get_demo, list_demos

# OUTPUT_DIR defined here to avoid importing agents.demo which pulls in playwright
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "demos"

router = APIRouter(prefix="/api/demos", tags=["demos"])


def _validate_demo_id(demo_id: str) -> None:
    """Reject demo IDs with path separators or traversal sequences."""
    if "/" in demo_id or "\\" in demo_id or ".." in demo_id:
        raise HTTPException(status_code=400, detail="Invalid demo ID")


def _get_manager(request: Request):
    """Get the DemoJobManager from app state."""
    manager = getattr(request.app.state, "demo_jobs", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Demo job manager not initialized")
    return manager


# ── Generation endpoints ──────────────────────────────────────────


class GenerateRequest(BaseModel):
    request: str = Field(description="Natural language demo request")
    format: str = Field(default="slides", description="Output format: slides, video, markdown-only")


@router.post("/generate")
async def generate_demo(body: GenerateRequest, request: Request):
    """Submit a new demo generation job. Returns immediately with job ID."""
    manager = _get_manager(request)
    try:
        job = manager.submit(body.request, format=body.format)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs")
async def list_jobs(request: Request, limit: int = 20):
    """List recent demo generation jobs, newest first."""
    manager = _get_manager(request)
    return manager.list_jobs(limit=limit)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    """Get current state of a demo generation job."""
    manager = _get_manager(request)
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict()


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request):
    """SSE stream of progress events for a demo generation job."""
    import json

    manager = _get_manager(request)
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    async def event_generator():
        async for event in manager.stream(job_id):
            yield {
                "event": event.get("event", "message"),
                "data": json.dumps(event.get("data", {})),
            }

    return EventSourceResponse(event_generator())


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str, request: Request):
    """Cancel a running demo generation job."""
    manager = _get_manager(request)
    cancelled = await manager.cancel(job_id)
    if not cancelled:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        raise HTTPException(
            status_code=409, detail=f"Job '{job_id}' is not running (status: {job.status})"
        )
    return {"cancelled": job_id}


# ── Existing demo browsing endpoints ─────────────────────────────


@router.get("")
async def list_all_demos():
    """List all generated demos, newest first."""
    return list_demos(OUTPUT_DIR)


@router.get("/{demo_id}")
async def get_demo_detail(demo_id: str):
    """Get metadata and file listing for a specific demo."""
    _validate_demo_id(demo_id)
    demo_dir = OUTPUT_DIR / demo_id
    result = get_demo(demo_dir)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")
    return result


@router.get("/{demo_id}/files/{file_path:path}")
async def serve_demo_file(demo_id: str, file_path: str):
    """Serve a specific file from a demo output directory."""
    _validate_demo_id(demo_id)
    full_path = (OUTPUT_DIR / demo_id / file_path).resolve()
    demo_root = (OUTPUT_DIR / demo_id).resolve()
    if not full_path.is_relative_to(demo_root):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(full_path)


@router.delete("/{demo_id}")
async def delete_demo(demo_id: str):
    """Delete a demo and all its files."""
    _validate_demo_id(demo_id)
    demo_dir = OUTPUT_DIR / demo_id
    if not demo_dir.exists():
        raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not found")
    shutil.rmtree(demo_dir)
    return {"deleted": demo_id}
