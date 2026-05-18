"""Central operator-control dispatch for decommissioned Tauri relay callers.

The old hapax-logos Tauri runtime hosted a WebSocket command relay on
``:8052``. Production callers must not dial that retired port. This module is
the small replacement surface used by Stream Deck and KDEConnect adapters:
supported commands route to Logos API ``:8051`` or an explicit local
compositor/control handler; unsupported frontend-only commands fail closed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

DEFAULT_LOGOS_API_BASE_URL = "http://127.0.0.1:8051"

Transport = Literal["logos-api", "local-vinyl", "local-quality-feedback", "compositor-uds"]
HttpRequest = Callable[[str, str, dict[str, Any]], Awaitable[Any]]


class UnsupportedLogosControlCommand(ValueError):
    """Raised when a retired Tauri-only command has no production route."""


@dataclass(frozen=True)
class LogosControlAction:
    """Resolved dispatch target for one command-registry style command."""

    transport: Transport
    command: str
    method: str | None = None
    path: str | None = None
    payload: dict[str, Any] | None = None


_CAMERA_PROFILE_TO_LAYOUT: dict[str, str] = {
    "balanced": "balanced",
    "hero_operator": "hero/brio-operator",
    "hero_turntable": "hero/c920-desk",
    "hero_screen": "hero/c920-room",
}


def route_logos_control_command(command: str, args: dict[str, Any]) -> LogosControlAction:
    """Resolve a command to the supported production control surface.

    The resolver is intentionally conservative. If a command only existed in
    the Tauri frontend registry and has no Logos API, compositor UDS, or local
    handler equivalent, callers get ``UnsupportedLogosControlCommand`` instead
    of a best-effort no-op.
    """

    if command == "studio.hero.set":
        role = _require_str_arg(command, args, "camera_role")
        return _logos_api("POST", "/api/studio/layout", {"mode": f"hero/{role}"}, command)

    if command == "studio.hero.clear":
        return _logos_api("POST", "/api/studio/layout", {"mode": "balanced"}, command)

    if command == "studio.camera_profile.set":
        profile = _require_str_arg(command, args, "profile")
        try:
            mode = _CAMERA_PROFILE_TO_LAYOUT[profile]
        except KeyError as exc:
            raise UnsupportedLogosControlCommand(
                f"{command} profile {profile!r} has no production layout route"
            ) from exc
        return _logos_api("POST", "/api/studio/layout", {"mode": mode}, command)

    if command in {"studio.private.enable", "stream.mode.set"}:
        mode = (
            "private"
            if command == "studio.private.enable"
            else _require_str_arg(command, args, "mode")
        )
        return _logos_api("PUT", "/api/stream/mode", {"mode": mode}, command)

    if command == "studio.stream_mode.toggle":
        from shared.stream_mode import StreamMode, get_stream_mode, set_stream_mode

        current = get_stream_mode()
        toggled = (
            StreamMode.PRIVATE
            if current in (StreamMode.PUBLIC, StreamMode.PUBLIC_RESEARCH)
            else StreamMode.PUBLIC_RESEARCH
        )
        set_stream_mode(toggled)
        return _logos_api("PUT", "/api/stream/mode", {"mode": toggled.value}, command)

    if command == "mode.set":
        return _logos_api(
            "PUT",
            "/api/working-mode",
            {"mode": _require_str_arg(command, args, "mode")},
            command,
        )

    if command == "fx.chain.set":
        return _logos_api(
            "POST",
            "/api/studio/effect/select",
            {"preset": _require_str_arg(command, args, "chain")},
            command,
        )

    if command == "audio.vinyl.rate_preset":
        return LogosControlAction(
            transport="local-vinyl",
            command=command,
            payload={"preset": _require_str_arg(command, args, "preset")},
        )

    if command == "operator.quality.rate":
        return LogosControlAction(
            transport="local-quality-feedback",
            command=command,
            payload=dict(args),
        )

    if command in {"degraded.activate", "degraded.deactivate"} or command.startswith("compositor."):
        return LogosControlAction(
            transport="compositor-uds",
            command=command,
            payload=dict(args),
        )

    raise UnsupportedLogosControlCommand(
        f"{command!r} has no supported production route after Tauri relay decommission"
    )


async def dispatch_logos_control(
    command: str,
    args: dict[str, Any],
    *,
    base_url: str = DEFAULT_LOGOS_API_BASE_URL,
    request: HttpRequest | None = None,
    compositor_client: Any | None = None,
) -> Any:
    """Dispatch one operator command through the replacement control surface."""

    action = route_logos_control_command(command, args)
    if action.transport == "logos-api":
        assert action.method is not None
        assert action.path is not None
        payload = action.payload or {}
        url = base_url.rstrip("/") + action.path
        if request is not None:
            return await request(action.method, url, payload)

        import httpx

        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.request(action.method, url, json=payload)
            response.raise_for_status()
            return response.json() if response.content else None

    if action.transport == "local-vinyl":
        from agents.stream_deck.commands.vinyl import handle_vinyl_rate_preset

        return handle_vinyl_rate_preset(action.payload or {})

    if action.transport == "local-quality-feedback":
        from shared.operator_quality_feedback import append_operator_quality_rating_from_args

        event = append_operator_quality_rating_from_args(
            action.payload or {},
            default_source_surface="streamdeck",
        )
        return event.model_dump(mode="json")

    if action.transport == "compositor-uds":
        if compositor_client is None:
            import os
            from pathlib import Path

            from agents.studio_compositor.command_client import CompositorCommandClient

            runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            compositor_client = CompositorCommandClient(
                socket_path=Path(runtime_dir) / "hapax-compositor-commands.sock"
            )
        return compositor_client.execute(action.command, action.payload or {})

    raise AssertionError(f"unknown transport: {action.transport}")


def _logos_api(method: str, path: str, payload: dict[str, Any], command: str) -> LogosControlAction:
    return LogosControlAction(
        transport="logos-api",
        command=command,
        method=method,
        path=path,
        payload=payload,
    )


def _require_str_arg(command: str, args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value:
        raise UnsupportedLogosControlCommand(
            f"{command} requires non-empty string arg {name!r}; got {args!r}"
        )
    return value
