"""Logos API routes for working mode switching (research/rnd)."""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from logos._working_mode import WORKING_MODE_FILE, WorkingMode

router = APIRouter(prefix="/api", tags=["system"])

# Resolve hapax-working-mode script path (used on host only)
_SCRIPT = Path(__file__).parent.parent.parent.parent / "scripts" / "hapax-working-mode"


class WorkingModeRequest(BaseModel):
    mode: WorkingMode

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("research", "rnd"):
            raise ValueError("mode must be 'research' or 'rnd'")
        return v


async def _run_hapax_working_mode(mode: str) -> tuple[int, str]:
    """Run hapax-working-mode script if available, otherwise write mode file directly."""
    script = shutil.which("hapax-working-mode") or str(_SCRIPT)
    if Path(script).exists():
        proc = await asyncio.create_subprocess_exec(
            script,
            mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode or 0, stdout.decode()

    # Fallback: write mode file directly (works inside Docker container)
    WORKING_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKING_MODE_FILE.write_text(mode)
    return 0, f"Mode set to {mode} (direct write)"


def _read_mode() -> dict:
    try:
        mode = WorkingMode(WORKING_MODE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        mode = WorkingMode.RND

    try:
        mtime = WORKING_MODE_FILE.stat().st_mtime
        switched_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    except FileNotFoundError:
        switched_at = None

    return {"mode": mode.value, "switched_at": switched_at}


@router.get("/working-mode")
async def get_working_mode():
    return _read_mode()


@router.put("/working-mode")
async def put_working_mode(body: WorkingModeRequest):
    returncode, output = await _run_hapax_working_mode(body.mode.value)
    if returncode != 0:
        raise HTTPException(status_code=500, detail=f"hapax-working-mode failed: {output}")
    return _read_mode()


# Deprecated aliases — remove after all consumers migrate
@router.get("/cycle-mode", deprecated=True)
async def get_cycle_mode_compat():
    return _read_mode()


@router.put("/cycle-mode", deprecated=True)
async def put_cycle_mode_compat(body: WorkingModeRequest):
    return await put_working_mode(body)
