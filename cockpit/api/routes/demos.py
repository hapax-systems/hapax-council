"""Demo history and management API endpoints."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from pathlib import Path

from agents.demo_pipeline.history import list_demos, get_demo

# OUTPUT_DIR defined here to avoid importing agents.demo which pulls in playwright
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "demos"

router = APIRouter(prefix="/api/demos", tags=["demos"])


def _validate_demo_id(demo_id: str) -> None:
    """Reject demo IDs with path separators or traversal sequences."""
    if "/" in demo_id or "\\" in demo_id or ".." in demo_id:
        raise HTTPException(status_code=400, detail="Invalid demo ID")


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
