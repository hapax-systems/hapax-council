"""Desktop management tools for the voice assistant.

Exposes Hyprland window management as LLM function-calling tools:
focus_window, switch_workspace, open_app, confirm_open_app, get_desktop_state.
"""

from __future__ import annotations

import logging
import time

from pipecat.adapters.schemas.function_schema import FunctionSchema

from shared.hyprland import HyprlandIPC

log = logging.getLogger(__name__)

_PENDING_OPEN_TTL_S = 120  # Pending app launch expires after 2 minutes

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

_move_window = FunctionSchema(
    name="move_window",
    description=(
        "Move the active window to a position on screen or to a workspace. "
        "Examples: move to workspace 3, move to left half, move to center."
    ),
    properties={
        "workspace": {
            "type": "integer",
            "description": "Target workspace number (moves window to that workspace)",
        },
        "position": {
            "type": "string",
            "description": "Position: 'left', 'right', 'center', 'top-left', 'top-right', 'bottom-left', 'bottom-right'",
        },
    },
    required=[],
)

_resize_window = FunctionSchema(
    name="resize_window",
    description="Resize the active window. Use 'fullscreen', 'half', or pixel adjustments.",
    properties={
        "mode": {
            "type": "string",
            "description": "'fullscreen', 'maximize', 'half-left', 'half-right', 'float', or 'restore'",
        },
    },
    required=["mode"],
)

_close_window = FunctionSchema(
    name="close_window",
    description="Close the active window or a window by class name.",
    properties={
        "target": {
            "type": "string",
            "description": "Optional: application class name to close. If omitted, closes active window.",
        },
    },
    required=[],
)

DESKTOP_TOOL_SCHEMAS = [
    _focus_window,
    _switch_workspace,
    _open_app,
    _confirm_open_app,
    _get_desktop_state,
    _move_window,
    _resize_window,
    _close_window,
]


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

    _pending_open = {"command": command, "workspace": workspace, "created_at": time.monotonic()}
    await params.result_callback(
        {
            "status": "pending_confirmation",
            "message": f"Ready to launch: {command}. Say 'confirm' to proceed.",
        }
    )


async def handle_confirm_open_app(params) -> None:
    global _pending_open
    if _pending_open is None:
        await params.result_callback({"status": "error", "message": "No pending app launch."})
        return

    # Check expiry
    if time.monotonic() - _pending_open.get("created_at", 0) > _PENDING_OPEN_TTL_S:
        _pending_open = None
        await params.result_callback(
            {"status": "error", "message": "Pending app launch expired. Please try again."}
        )
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


async def handle_move_window(params) -> None:
    workspace = params.arguments.get("workspace")
    position = params.arguments.get("position")

    if workspace:
        ok = _ipc.dispatch("movetoworkspacesilent", str(workspace))
        status = "moved" if ok else "failed"
        await params.result_callback({"status": status, "workspace": workspace})
        return

    # Position-based moves using Hyprland layout
    position_dispatches = {
        "left": ("movefocus", "l"),
        "right": ("movefocus", "r"),
        "center": ("centerwindow", ""),
    }

    if position and position in position_dispatches:
        cmd, arg = position_dispatches[position]
        ok = _ipc.dispatch(cmd, arg)
    else:
        ok = False
    status = "moved" if ok else "failed"
    await params.result_callback({"status": status, "position": position})


async def handle_resize_window(params) -> None:
    mode = params.arguments["mode"]

    dispatch_map = {
        "fullscreen": ("fullscreen", "0"),
        "maximize": ("fullscreen", "1"),
        "half-left": ("splitratio", "-0.5"),
        "half-right": ("splitratio", "0.5"),
        "float": ("togglefloating", ""),
        "restore": ("fullscreen", "0"),  # toggle back
    }

    cmd, arg = dispatch_map.get(mode, ("fullscreen", "0"))
    ok = _ipc.dispatch(cmd, arg)
    status = "resized" if ok else "failed"
    await params.result_callback({"status": status, "mode": mode})


async def handle_close_window(params) -> None:
    target = params.arguments.get("target")

    if target:
        # Focus first, then close
        _ipc.dispatch("focuswindow", f"class:{target}")
    ok = _ipc.dispatch("killactive", "")
    status = "closed" if ok else "failed"
    await params.result_callback({"status": status, "target": target or "active"})


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
            {"id": ws.id, "name": ws.name, "windows": ws.window_count} for ws in workspaces
        ],
    }
    await params.result_callback(result)
