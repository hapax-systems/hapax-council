"""Desktop management tools for the voice assistant.

Exposes Hyprland window management as LLM function-calling tools:
focus_window, switch_workspace, open_app, confirm_open_app, get_desktop_state.
"""
from __future__ import annotations

import logging

from pipecat.adapters.schemas.function_schema import FunctionSchema

from shared.hyprland import HyprlandIPC

log = logging.getLogger(__name__)

_ipc = HyprlandIPC()

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_focus_window = FunctionSchema(
    name="focus_window",
    description=(
        "Bring a window to focus by its application name. "
        "Examples: 'google-chrome', 'foot', 'obsidian', 'code'."
    ),
    properties={
        "target": {
            "type": "string",
            "description": "Application class name to focus",
        },
    },
    required=["target"],
)

_switch_workspace = FunctionSchema(
    name="switch_workspace",
    description="Switch to a workspace by number (1-10).",
    properties={
        "workspace": {
            "type": "integer",
            "description": "Workspace number to switch to",
        },
    },
    required=["workspace"],
)

_open_app = FunctionSchema(
    name="open_app",
    description=(
        "Launch an application. Optionally place it on a specific workspace. "
        "Examples: 'foot' (terminal), 'google-chrome-stable https://example.com', "
        "'flatpak run md.obsidian.Obsidian'."
    ),
    properties={
        "command": {
            "type": "string",
            "description": "Shell command to launch the application",
        },
        "workspace": {
            "type": "integer",
            "description": "Optional workspace number to place the window on",
        },
    },
    required=["command"],
)

_confirm_open_app = FunctionSchema(
    name="confirm_open_app",
    description="Confirm a pending app launch. Call after open_app returns pending_confirmation.",
    properties={},
    required=[],
)

_get_desktop_state = FunctionSchema(
    name="get_desktop_state",
    description=(
        "Get the current desktop state: all open windows, their workspaces, "
        "and which window is focused. Use this to understand the desktop layout."
    ),
    properties={},
    required=[],
)

DESKTOP_TOOL_SCHEMAS = [_focus_window, _switch_workspace, _open_app, _confirm_open_app, _get_desktop_state]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

# Pending open_app commands awaiting confirmation
_pending_open: dict | None = None


async def handle_focus_window(params) -> None:
    target = params.arguments["target"]
    ok = _ipc.dispatch("focuswindow", f"class:{target}")
    status = "focused" if ok else "failed"
    await params.result_callback({"status": status, "target": target})


async def handle_switch_workspace(params) -> None:
    ws = params.arguments["workspace"]
    ok = _ipc.dispatch("workspace", str(ws))
    status = "switched" if ok else "failed"
    await params.result_callback({"status": status, "workspace": ws})


async def handle_open_app(params) -> None:
    global _pending_open
    command = params.arguments["command"]
    workspace = params.arguments.get("workspace")

    _pending_open = {"command": command, "workspace": workspace}
    await params.result_callback({
        "status": "pending_confirmation",
        "message": f"Ready to launch: {command}. Say 'confirm' to proceed.",
    })


async def handle_confirm_open_app(params) -> None:
    global _pending_open
    if _pending_open is None:
        await params.result_callback({"status": "error", "message": "No pending app launch."})
        return

    command = _pending_open["command"]
    workspace = _pending_open["workspace"]
    _pending_open = None

    if workspace:
        ok = _ipc.dispatch("exec", f"[workspace {workspace} silent] {command}")
    else:
        ok = _ipc.dispatch("exec", command)

    status = "launched" if ok else "failed"
    await params.result_callback({"status": status, "command": command})


async def handle_get_desktop_state(params) -> None:
    active = _ipc.get_active_window()
    clients = _ipc.get_clients()
    workspaces = _ipc.get_workspaces()

    def _win_dict(w):
        return {"class": w.app_class, "title": w.title, "workspace": w.workspace_id}

    result = {
        "active_window": _win_dict(active) if active else None,
        "windows": [_win_dict(c) for c in clients],
        "workspaces": [
            {"id": ws.id, "name": ws.name, "windows": ws.window_count}
            for ws in workspaces
        ],
    }
    await params.result_callback(result)
