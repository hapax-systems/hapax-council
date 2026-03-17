"""OpenAI-format tool definitions for the lightweight conversation pipeline.

Converts Pipecat FunctionSchema tools into OpenAI function-calling format
and wraps handlers to return string results instead of using result_callback.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class _FakeParams:
    """Shim that mimics Pipecat's handler params interface."""

    arguments: dict[str, Any]
    _result: str = ""

    async def result_callback(self, value: Any) -> None:
        if isinstance(value, str):
            self._result = value
        else:
            self._result = json.dumps(value)


def _schema_to_openai(schema) -> dict:
    """Convert a Pipecat FunctionSchema to OpenAI tool format."""
    properties = {}
    for name, prop in (schema.properties or {}).items():
        properties[name] = {k: v for k, v in prop.items()}

    return {
        "type": "function",
        "function": {
            "name": schema.name,
            "description": schema.description or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(schema.required or []),
            },
        },
    }


async def _wrap_handler(handler, args: dict) -> str:
    """Call a Pipecat-style handler and capture its result_callback output."""
    params = _FakeParams(arguments=args)
    try:
        await handler(params)
        return params._result or "Done."
    except Exception as exc:
        log.exception("Tool handler failed: %s", handler.__name__)
        return json.dumps({"error": str(exc)})


def _make_async_wrapper(handler) -> Callable:
    """Create a proper async wrapper that awaits _wrap_handler."""

    async def wrapper(args: dict) -> str:
        return await _wrap_handler(handler, args)

    wrapper.__name__ = getattr(handler, "__name__", "unknown")
    return wrapper


def get_openai_tools(
    guest_mode: bool = False,
    config=None,
    webcam_capturer=None,
    screen_capturer=None,
) -> tuple[list[dict], dict[str, Callable]]:
    """Return (tools_list, handler_map) in OpenAI function-calling format.

    tools_list: list of OpenAI tool definitions for the LLM
    handler_map: {name: async_handler} where handler takes dict args and returns str

    Args:
        guest_mode: If True, return empty tools (guests get no tools).
        config: VoiceConfig to initialize module-level tool state.
        webcam_capturer: WebcamCapturer instance for vision tools.
        screen_capturer: ScreenCapturer instance for vision tools.
    """
    if guest_mode:
        return [], {}

    from agents.hapax_voice.desktop_tools import (
        DESKTOP_TOOL_SCHEMAS,
        handle_close_window,
        handle_confirm_open_app,
        handle_focus_window,
        handle_get_desktop_state,
        handle_move_window,
        handle_open_app,
        handle_resize_window,
        handle_switch_workspace,
    )
    from agents.hapax_voice.tools import (
        TOOL_SCHEMAS,
        handle_analyze_scene,
        handle_check_consent_status,
        handle_check_governance_health,
        handle_confirm_send_sms,
        handle_describe_consent_flow,
        handle_generate_image,
        handle_get_briefing,
        handle_get_calendar_today,
        handle_get_current_time,
        handle_get_system_status,
        handle_get_weather,
        handle_search_documents,
        handle_search_drive,
        handle_search_emails,
        handle_send_sms,
        init_tool_state,
    )

    # Initialize module-level state for handlers that need config/capturers
    if config is not None:
        init_tool_state(config, webcam_capturer, screen_capturer)

    # Map handler names to functions
    _handlers = {
        "search_documents": handle_search_documents,
        "search_drive": handle_search_drive,
        "get_calendar_today": handle_get_calendar_today,
        "search_emails": handle_search_emails,
        "send_sms": handle_send_sms,
        "confirm_send_sms": handle_confirm_send_sms,
        "analyze_scene": handle_analyze_scene,
        "get_system_status": handle_get_system_status,
        "generate_image": handle_generate_image,
        "get_current_time": handle_get_current_time,
        "get_weather": handle_get_weather,
        "get_briefing": handle_get_briefing,
        "check_consent_status": handle_check_consent_status,
        "describe_consent_flow": handle_describe_consent_flow,
        "check_governance_health": handle_check_governance_health,
        "focus_window": handle_focus_window,
        "switch_workspace": handle_switch_workspace,
        "open_app": handle_open_app,
        "confirm_open_app": handle_confirm_open_app,
        "get_desktop_state": handle_get_desktop_state,
        "move_window": handle_move_window,
        "resize_window": handle_resize_window,
        "close_window": handle_close_window,
    }

    # Convert schemas to OpenAI format
    all_schemas = TOOL_SCHEMAS + DESKTOP_TOOL_SCHEMAS
    tools = [_schema_to_openai(s) for s in all_schemas]

    # Wrap handlers as proper async functions
    wrapped: dict[str, Callable] = {
        name: _make_async_wrapper(handler) for name, handler in _handlers.items()
    }

    return tools, wrapped
