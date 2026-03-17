"""Hapax Logos directive bridge.

Agents POST directives here; the Tauri app watches the shm file and executes them.
This is the agent-side entry point for all UI manipulation.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logos", tags=["logos"])

DIRECTIVE_DIR = Path("/dev/shm/hapax-logos")
DIRECTIVE_FILE = DIRECTIVE_DIR / "directives.jsonl"


class UiDirective(BaseModel):
    """A directive for the Hapax Logos UI.

    All fields are optional — include only the actions you want.
    """

    # Navigation
    navigate: str | None = None
    open_panel: str | None = None
    close_panel: str | None = None

    # Content
    toast: str | None = None
    toast_level: str | None = Field(None, pattern="^(info|warning|error)$")
    toast_duration_ms: int | None = None

    modal_title: str | None = None
    modal_content: str | None = None
    dismiss_modal: bool = False

    highlight: str | None = None
    highlight_duration_ms: int | None = None

    status: str | None = None
    status_level: str | None = None

    # Window
    focus_window: bool = False
    fullscreen: bool | None = None
    always_on_top: bool | None = None
    window_x: int | None = None
    window_y: int | None = None
    window_width: int | None = None
    window_height: int | None = None

    # Visual surface
    visual_stance: str | None = None
    visual_ping_x: float | None = None
    visual_ping_y: float | None = None
    visual_ping_energy: float | None = None

    # Metadata
    source: str | None = Field(None, description="Agent name or source identifier")


@router.post("/directive")
async def post_directive(directive: UiDirective) -> dict[str, Any]:
    """Accept a UI directive from an agent and write it to shm for the Tauri app."""
    DIRECTIVE_DIR.mkdir(parents=True, exist_ok=True)

    record = directive.model_dump(exclude_none=True)
    record["_timestamp"] = time.time()

    with open(DIRECTIVE_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

    _log.info("Directive from %s: %s", directive.source or "unknown", list(record.keys()))
    return {"status": "accepted", "fields": list(record.keys())}


@router.get("/directive/schema")
async def get_directive_schema() -> dict[str, Any]:
    """Return the directive JSON schema for agent consumption."""
    return UiDirective.model_json_schema()
