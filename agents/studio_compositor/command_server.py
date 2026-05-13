"""CommandServer — UDS newline-delimited JSON command handler for the compositor.

Phase 5 (parent task G20) of the reverie source registry completion epic.
Protocol: client sends one JSON line per request, server replies with one
JSON line per response. One request per connection.

Supported commands:

- ``compositor.surface.set_geometry`` ``{surface_id, x, y, w, h}``
- ``compositor.surface.set_z_order`` ``{surface_id, z_order}``
- ``compositor.assignment.set_opacity`` ``{source_id, surface_id, opacity}``
- ``compositor.layout.activate`` ``{layout_name}`` — activate a loaded bounded layout
- ``compositor.layout.save`` — flush :class:`LayoutAutoSaver` immediately
- ``compositor.layout.reload`` — force a fresh read from disk
- ``degraded.activate`` ``{reason, ttl_s?}`` — enter DEGRADED-STREAM mode
- ``degraded.deactivate`` — exit DEGRADED-STREAM mode (task #122)

Errors are structured: ``{status: "error", error: <code>, ...context}``.
Unknown IDs include a ``hint`` field built via :func:`difflib.get_close_matches`.
Invalid geometry is rejected up front (non-numeric, NaN, negative w/h).
``set_geometry`` on non-rect surfaces returns ``layout_immutable_kind``.

No silent failures. Every error path returns a structured response.
"""

from __future__ import annotations

import difflib
import json
import logging
import math
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents.studio_compositor.layout_fragment_guard import (
    segment_fragment_layout_error,
)
from agents.studio_compositor.layout_state import LayoutState
from shared.compositor_model import Layout

log = logging.getLogger(__name__)


class _CommandError(Exception):
    """Internal error carrying the structured payload to return to the client."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error", "error"))
        self.payload = payload


class CommandServer:
    """Unix-domain-socket server exposing layout mutation commands.

    One thread. Non-blocking accept with a 0.5s timeout so :meth:`stop`
    can unblock the loop promptly. ``flush_callback`` is invoked when
    ``compositor.layout.save`` arrives; ``reload_callback`` on
    ``compositor.layout.reload``. Both default to no-ops so callers that
    don't wire an autosaver / filewatcher still get structured
    acknowledgements instead of ``unknown_command`` errors.
    """

    def __init__(
        self,
        state: LayoutState,
        socket_path: Path,
        *,
        flush_callback: Callable[[], None] | None = None,
        reload_callback: Callable[[], None] | None = None,
        layout_resolver: Callable[[str], Layout | None] | None = None,
        layout_names_provider: Callable[[], list[str]] | None = None,
        layout_activation_callback: Callable[[str, Layout], None] | None = None,
    ) -> None:
        self._state = state
        self._socket_path = Path(socket_path)
        self._flush_callback = flush_callback
        self._reload_callback = reload_callback
        self._layout_resolver = layout_resolver
        self._layout_names_provider = layout_names_provider
        self._layout_activation_callback = layout_activation_callback
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except OSError:
                pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self._socket_path))
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="compositor-cmdsrv",
        )
        self._thread.start()
        log.info("compositor command server listening on %s", self._socket_path)

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except OSError:
                pass

    def _loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            try:
                self._handle_connection(conn)
            except Exception:
                log.exception("compositor command handler raised")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle_connection(self, conn: socket.socket) -> None:
        conn.settimeout(2.0)
        buf = b""
        while b"\n" not in buf:
            try:
                chunk = conn.recv(4096)
            except TimeoutError:
                self._reply(conn, {"status": "error", "error": "read_timeout"})
                return
            if not chunk:
                return
            buf += chunk
            if len(buf) > 65536:
                self._reply(conn, {"status": "error", "error": "payload_too_large"})
                return

        line, _ = buf.split(b"\n", 1)
        try:
            request = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._reply(conn, {"status": "error", "error": "invalid_json"})
            return

        if not isinstance(request, dict):
            self._reply(conn, {"status": "error", "error": "invalid_request"})
            return

        command = request.get("command")
        args = request.get("args") or {}
        handler = _COMMANDS.get(command)
        if handler is None:
            self._reply(
                conn,
                {
                    "status": "error",
                    "error": "unknown_command",
                    "command": command,
                },
            )
            return
        try:
            result = handler(self, args) or {}
            self._reply(conn, {"status": "ok", **result})
        except _CommandError as e:
            self._reply(conn, {"status": "error", **e.payload})

    @staticmethod
    def _reply(conn: socket.socket, payload: dict[str, Any]) -> None:
        try:
            conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError:
            pass


def _did_you_mean(needle: str, haystack: list[str]) -> str:
    matches = difflib.get_close_matches(needle, haystack, n=3, cutoff=0.6)
    return ", ".join(matches)


def _validate_geometry_field(name: str, value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise _CommandError({"error": "invalid_geometry", "field": name})
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise _CommandError({"error": "invalid_geometry", "field": name})
    return float(value)


def _handle_set_geometry(server: CommandServer, args: dict[str, Any]) -> dict[str, Any]:
    sid = args.get("surface_id")
    x = _validate_geometry_field("x", args.get("x"))
    y = _validate_geometry_field("y", args.get("y"))
    w = _validate_geometry_field("w", args.get("w"))
    h = _validate_geometry_field("h", args.get("h"))
    if w <= 0 or h <= 0:
        raise _CommandError({"error": "invalid_geometry", "field": "w_or_h_nonpositive"})

    layout = server._state.get()
    surface = layout.surface_by_id(sid) if isinstance(sid, str) else None
    if surface is None:
        hint = _did_you_mean(
            sid if isinstance(sid, str) else "",
            [s.id for s in layout.surfaces],
        )
        raise _CommandError({"error": "unknown_surface", "surface_id": sid, "hint": hint})
    if surface.geometry.kind != "rect":
        raise _CommandError(
            {
                "error": "layout_immutable_kind",
                "kind": surface.geometry.kind,
                "surface_id": sid,
            }
        )

    def mutator(layout: Layout) -> Layout:
        new_surfaces = []
        for s in layout.surfaces:
            if s.id != sid:
                new_surfaces.append(s)
                continue
            new_geom = s.geometry.model_copy(
                update={"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
            )
            new_surfaces.append(s.model_copy(update={"geometry": new_geom}))
        return layout.model_copy(update={"surfaces": new_surfaces})

    server._state.mutate(mutator)
    return {}


def _handle_set_z_order(server: CommandServer, args: dict[str, Any]) -> dict[str, Any]:
    sid = args.get("surface_id")
    z = args.get("z_order")
    if not isinstance(z, int) or isinstance(z, bool):
        raise _CommandError({"error": "invalid_z_order"})
    layout = server._state.get()
    surface = layout.surface_by_id(sid) if isinstance(sid, str) else None
    if surface is None:
        hint = _did_you_mean(
            sid if isinstance(sid, str) else "",
            [s.id for s in layout.surfaces],
        )
        raise _CommandError({"error": "unknown_surface", "surface_id": sid, "hint": hint})

    def mutator(layout: Layout) -> Layout:
        new_surfaces = [
            s.model_copy(update={"z_order": z}) if s.id == sid else s for s in layout.surfaces
        ]
        return layout.model_copy(update={"surfaces": new_surfaces})

    server._state.mutate(mutator)
    return {}


def _handle_set_opacity(server: CommandServer, args: dict[str, Any]) -> dict[str, Any]:
    source_id = args.get("source_id")
    surface_id = args.get("surface_id")
    opacity = args.get("opacity")
    if not isinstance(opacity, (int, float)) or isinstance(opacity, bool):
        raise _CommandError({"error": "invalid_opacity"})
    if not 0.0 <= float(opacity) <= 1.0:
        raise _CommandError({"error": "invalid_opacity", "reason": "out_of_range"})

    def mutator(layout: Layout) -> Layout:
        new_assignments = []
        touched = False
        for a in layout.assignments:
            if a.source == source_id and a.surface == surface_id:
                new_assignments.append(a.model_copy(update={"opacity": float(opacity)}))
                touched = True
            else:
                new_assignments.append(a)
        if not touched:
            raise _CommandError(
                {
                    "error": "unknown_assignment",
                    "source_id": source_id,
                    "surface_id": surface_id,
                }
            )
        return layout.model_copy(update={"assignments": new_assignments})

    server._state.mutate(mutator)
    return {}


def _handle_save(server: CommandServer, args: dict[str, Any]) -> dict[str, Any]:
    del args
    if server._flush_callback is not None:
        server._flush_callback()
    return {}


def _handle_reload(server: CommandServer, args: dict[str, Any]) -> dict[str, Any]:
    del args
    if server._reload_callback is not None:
        server._reload_callback()
    return {}


def _layout_name_hint(server: CommandServer, name: str) -> str:
    if server._layout_names_provider is None:
        return ""
    try:
        return _did_you_mean(name, server._layout_names_provider())
    except Exception:
        log.debug("layout names provider failed", exc_info=True)
        return ""


def _director_segment_fragment_error(
    args: dict[str, Any],
    *,
    layout_name: str,
    layout: Layout,
) -> dict[str, Any] | None:
    source = args.get("source")
    return segment_fragment_layout_error(
        layout_name=layout_name,
        layout=layout,
        source=source if isinstance(source, str) else None,
    )


def _handle_activate_layout(server: CommandServer, args: dict[str, Any]) -> dict[str, Any]:
    """Activate a loaded layout through the compositor control plane.

    This is intentionally a whole-layout command, not arbitrary geometry
    authority. Runtime components such as the director segment runner can
    request one bounded layout selected by the responsibility controller;
    free-form surface coordinates remain rejected by the proposal adapter.
    """

    raw_name = args.get("layout_name") or args.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise _CommandError({"error": "invalid_layout_name"})
    layout_name = raw_name.strip()
    if server._layout_resolver is None:
        current = server._state.get()
        if current.name == layout_name:
            return {"layout_name": layout_name, "already_active": True}
        raise _CommandError(
            {
                "error": "layout_activation_unavailable",
                "layout_name": layout_name,
                "hint": "command server was not wired with a layout resolver",
            }
        )

    try:
        layout = server._layout_resolver(layout_name)
    except Exception as exc:
        raise _CommandError(
            {
                "error": "layout_resolver_failed",
                "layout_name": layout_name,
                "detail": str(exc),
            }
        ) from exc
    if layout is None:
        raise _CommandError(
            {
                "error": "unknown_layout",
                "layout_name": layout_name,
                "hint": _layout_name_hint(server, layout_name),
            }
        )
    fragment_error = _director_segment_fragment_error(
        args,
        layout_name=layout_name,
        layout=layout,
    )
    if fragment_error is not None:
        raise _CommandError(fragment_error)

    if server._layout_activation_callback is not None:
        try:
            server._layout_activation_callback(layout_name, layout)
        except Exception as exc:
            raise _CommandError(
                {
                    "error": "layout_activation_callback_failed",
                    "layout_name": layout_name,
                    "detail": str(exc),
                }
            ) from exc

    server._state.mutate(lambda _previous: layout)
    return {"layout_name": layout_name}


def _handle_degraded_activate(server: CommandServer, args: dict[str, Any]) -> dict[str, Any]:
    """Task #122 — enter DEGRADED-STREAM mode.

    ``args.reason`` is recorded verbatim (operator-facing label).
    ``args.ttl_s`` is an optional float; defaults to the controller's
    built-in ``DEFAULT_TTL_S``.
    """
    del server  # controller is process-global
    reason = args.get("reason")
    if not isinstance(reason, str) or not reason:
        raise _CommandError({"error": "invalid_reason", "reason": "must be a non-empty string"})
    ttl_raw = args.get("ttl_s")
    ttl_kwargs: dict[str, Any] = {}
    if ttl_raw is not None:
        if not isinstance(ttl_raw, (int, float)) or isinstance(ttl_raw, bool):
            raise _CommandError({"error": "invalid_ttl", "reason": "ttl_s must be numeric"})
        ttl_kwargs["ttl_s"] = float(ttl_raw)
    from agents.studio_compositor.degraded_mode import get_controller

    try:
        get_controller().activate(reason, **ttl_kwargs)
    except ValueError as exc:
        raise _CommandError({"error": "invalid_ttl", "reason": str(exc)}) from exc
    return {"state": "degraded", "reason": reason}


def _handle_degraded_deactivate(server: CommandServer, args: dict[str, Any]) -> dict[str, Any]:
    """Task #122 — exit DEGRADED-STREAM mode."""
    del server, args
    from agents.studio_compositor.degraded_mode import get_controller

    get_controller().deactivate()
    return {"state": "normal"}


_COMMANDS: dict[str, Callable[[CommandServer, dict[str, Any]], dict[str, Any] | None]] = {
    "compositor.surface.set_geometry": _handle_set_geometry,
    "compositor.surface.set_z_order": _handle_set_z_order,
    "compositor.assignment.set_opacity": _handle_set_opacity,
    "compositor.layout.activate": _handle_activate_layout,
    "compositor.layout.save": _handle_save,
    "compositor.layout.reload": _handle_reload,
    "degraded.activate": _handle_degraded_activate,
    "degraded.deactivate": _handle_degraded_deactivate,
}
