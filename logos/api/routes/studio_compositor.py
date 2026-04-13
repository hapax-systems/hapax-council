"""Studio compositor command bridge — proxies the frontend / MCP / voice
surfaces into the compositor's UDS command server.

Phase 5 of the reverie source-registry completion epic shipped
``agents/studio_compositor/command_server.py`` with five commands
(``compositor.surface.set_geometry``, ``compositor.surface.set_z_order``,
``compositor.assignment.set_opacity``, ``compositor.layout.save``,
``compositor.layout.reload``). Delta's retirement handoff item #5
flagged that those commands were unreachable from ``window.__logos``,
MCP, and voice. This router closes that gap on the backend side: it
accepts HTTP POSTs from the logos frontend, validates the arg shapes
with Pydantic, and proxies the call into
:class:`agents.studio_compositor.command_client.CompositorCommandClient`.

The client opens a fresh Unix socket per request and speaks the same
newline-JSON protocol the compositor's ``_handle_connection`` loop
accepts. Server-side errors bubble back as 4xx responses with the
structured error dict in the body so the frontend can surface the
same hints (``unknown_surface``, ``invalid_geometry``, etc.) the
CommandServer already emits.

Frontend registrations (``compositor.*`` domain in
``hapax-logos/src/lib/commands/``) are a follow-up PR.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.studio_compositor.command_client import (
    CommandClientError,
    CompositorCommandClient,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studio/compositor", tags=["studio-compositor"])


def _default_socket_path() -> Path:
    """Match the path the compositor picks in StudioCompositor.start_layout_only."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(runtime_dir) / "hapax-compositor-commands.sock"


def _client() -> CompositorCommandClient:
    return CompositorCommandClient(socket_path=_default_socket_path())


def _execute(command: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a command against the compositor and translate failures to HTTP.

    Success → the response dict (minus ``status``).
    ``socket_missing`` / ``connection_refused`` → 503 (compositor down).
    ``timeout`` → 504.
    Any other ``status=error`` → 400 with the structured error as the
    response body, preserving the CommandServer's hint fields.
    """
    try:
        response = _client().execute(command, args)
    except CommandClientError as exc:
        payload = exc.payload
        error_code = payload.get("error", "unknown")
        if error_code in ("socket_missing", "connection_refused"):
            raise HTTPException(status_code=503, detail=payload) from exc
        if error_code == "timeout":
            raise HTTPException(status_code=504, detail=payload) from exc
        raise HTTPException(status_code=400, detail=payload) from exc

    # Strip the ``status`` key so the returned dict is just the
    # command-specific payload. Callers that need the envelope can
    # reconstruct it trivially.
    return {k: v for k, v in response.items() if k != "status"}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class SetGeometryRequest(BaseModel):
    surface_id: str = Field(..., description="Layout surface id (e.g. 'pip-lr')")
    x: float = Field(..., description="X origin in pixels")
    y: float = Field(..., description="Y origin in pixels")
    w: float = Field(..., gt=0.0, description="Width in pixels (must be > 0)")
    h: float = Field(..., gt=0.0, description="Height in pixels (must be > 0)")


class SetZOrderRequest(BaseModel):
    surface_id: str
    z_order: int


class SetOpacityRequest(BaseModel):
    source_id: str
    surface_id: str
    opacity: float = Field(..., ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/surface/geometry")
async def set_surface_geometry(req: SetGeometryRequest) -> dict[str, Any]:
    return _execute(
        "compositor.surface.set_geometry",
        {
            "surface_id": req.surface_id,
            "x": req.x,
            "y": req.y,
            "w": req.w,
            "h": req.h,
        },
    )


@router.post("/surface/z-order")
async def set_surface_z_order(req: SetZOrderRequest) -> dict[str, Any]:
    return _execute(
        "compositor.surface.set_z_order",
        {"surface_id": req.surface_id, "z_order": req.z_order},
    )


@router.post("/assignment/opacity")
async def set_assignment_opacity(req: SetOpacityRequest) -> dict[str, Any]:
    return _execute(
        "compositor.assignment.set_opacity",
        {
            "source_id": req.source_id,
            "surface_id": req.surface_id,
            "opacity": req.opacity,
        },
    )


@router.post("/layout/save")
async def save_layout() -> dict[str, Any]:
    return _execute("compositor.layout.save")


@router.post("/layout/reload")
async def reload_layout() -> dict[str, Any]:
    return _execute("compositor.layout.reload")
