"""CommandServer tests — Phase 5 / parent task G20."""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import pytest

from agents.studio_compositor.command_server import CommandServer
from agents.studio_compositor.layout_state import LayoutState
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)


def _minimal_layout() -> Layout:
    return Layout(
        name="t",
        sources=[
            SourceSchema(
                id="src1",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            )
        ],
        surfaces=[
            SurfaceSchema(
                id="pip-ul",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=100, h=100),
                z_order=1,
            ),
            SurfaceSchema(
                id="fx-in",
                geometry=SurfaceGeometry(kind="fx_chain_input"),
                z_order=0,
            ),
        ],
        assignments=[Assignment(source="src1", surface="pip-ul")],
    )


def _alternate_layout() -> Layout:
    return Layout(
        name="segment-tier",
        sources=[
            SourceSchema(
                id="tier-panel",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            )
        ],
        surfaces=[
            SurfaceSchema(
                id="tier-panel-surface",
                geometry=SurfaceGeometry(kind="rect", x=10, y=20, w=300, h=200),
                z_order=20,
            )
        ],
        assignments=[Assignment(source="tier-panel", surface="tier-panel-surface")],
    )


def _call(sock_path: Path, payload: dict) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(str(sock_path))
    s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf.decode("utf-8").split("\n", 1)[0])


@pytest.fixture
def server_and_state(tmp_path: Path):
    state = LayoutState(_minimal_layout())
    sock_path = tmp_path / "compositor.sock"
    server = CommandServer(state, sock_path)
    server.start()
    time.sleep(0.05)  # give the accept loop a tick to enter the blocking accept
    try:
        yield server, state, sock_path
    finally:
        server.stop()


def test_set_geometry_mutates_layout(server_and_state) -> None:
    _server, state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.surface.set_geometry",
            "args": {"surface_id": "pip-ul", "x": 500, "y": 300, "w": 200, "h": 200},
        },
    )
    assert resp == {"status": "ok"}
    surface = state.get().surface_by_id("pip-ul")
    assert surface is not None
    assert surface.geometry.x == 500
    assert surface.geometry.y == 300
    assert surface.geometry.w == 200
    assert surface.geometry.h == 200


def test_unknown_surface_returns_error_with_hint(server_and_state) -> None:
    _server, _state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.surface.set_geometry",
            "args": {"surface_id": "pip-u", "x": 0, "y": 0, "w": 10, "h": 10},
        },
    )
    assert resp["status"] == "error"
    assert resp["error"] == "unknown_surface"
    assert "pip-ul" in resp["hint"]


def test_invalid_geometry_rejected_negative(server_and_state) -> None:
    _server, _state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.surface.set_geometry",
            "args": {"surface_id": "pip-ul", "x": 0, "y": 0, "w": -5, "h": 10},
        },
    )
    assert resp["status"] == "error"
    assert resp["error"] == "invalid_geometry"


def test_invalid_geometry_rejected_nan(server_and_state) -> None:
    _server, _state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.surface.set_geometry",
            "args": {
                "surface_id": "pip-ul",
                "x": float("nan"),
                "y": 0,
                "w": 10,
                "h": 10,
            },
        },
    )
    assert resp["status"] == "error"
    assert resp["error"] == "invalid_geometry"


def test_set_geometry_rejects_non_rect_surface(server_and_state) -> None:
    _server, _state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.surface.set_geometry",
            "args": {"surface_id": "fx-in", "x": 0, "y": 0, "w": 10, "h": 10},
        },
    )
    assert resp["status"] == "error"
    assert resp["error"] == "layout_immutable_kind"
    assert resp["kind"] == "fx_chain_input"


def test_set_z_order_mutates(server_and_state) -> None:
    _server, state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.surface.set_z_order",
            "args": {"surface_id": "pip-ul", "z_order": 99},
        },
    )
    assert resp == {"status": "ok"}
    assert state.get().surface_by_id("pip-ul").z_order == 99


def test_set_opacity_mutates(server_and_state) -> None:
    _server, state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.assignment.set_opacity",
            "args": {"source_id": "src1", "surface_id": "pip-ul", "opacity": 0.5},
        },
    )
    assert resp == {"status": "ok"}
    assignments = state.get().assignments
    assert assignments[0].opacity == 0.5


def test_set_opacity_rejects_out_of_range(server_and_state) -> None:
    _server, _state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.assignment.set_opacity",
            "args": {"source_id": "src1", "surface_id": "pip-ul", "opacity": 1.5},
        },
    )
    assert resp["status"] == "error"
    assert resp["error"] == "invalid_opacity"


def test_activate_layout_resolves_and_mutates_state(tmp_path: Path) -> None:
    state = LayoutState(_minimal_layout())
    alt = _alternate_layout()
    sock_path = tmp_path / "compositor.sock"
    activated: list[str] = []
    server = CommandServer(
        state,
        sock_path,
        layout_resolver=lambda name: alt if name == "segment-tier" else None,
        layout_names_provider=lambda: ["default", "segment-tier"],
        layout_activation_callback=lambda name, _layout: activated.append(name),
    )
    server.start()
    time.sleep(0.05)
    try:
        resp = _call(
            sock_path,
            {
                "command": "compositor.layout.activate",
                "args": {"layout_name": "segment-tier"},
            },
        )
        assert resp == {"status": "ok", "layout_name": "segment-tier"}
        assert state.get().name == "segment-tier"
        assert activated == ["segment-tier"]
    finally:
        server.stop()


def test_activate_layout_reports_unknown_with_hint(tmp_path: Path) -> None:
    state = LayoutState(_minimal_layout())
    sock_path = tmp_path / "compositor.sock"
    server = CommandServer(
        state,
        sock_path,
        layout_resolver=lambda _name: None,
        layout_names_provider=lambda: ["segment-tier"],
    )
    server.start()
    time.sleep(0.05)
    try:
        resp = _call(
            sock_path,
            {"command": "compositor.layout.activate", "args": {"layout_name": "segment-tire"}},
        )
        assert resp["status"] == "error"
        assert resp["error"] == "unknown_layout"
        assert "segment-tier" in resp["hint"]
    finally:
        server.stop()


def test_unknown_assignment_reports_error(server_and_state) -> None:
    _server, _state, sock_path = server_and_state
    resp = _call(
        sock_path,
        {
            "command": "compositor.assignment.set_opacity",
            "args": {"source_id": "ghost", "surface_id": "pip-ul", "opacity": 0.3},
        },
    )
    assert resp["status"] == "error"
    assert resp["error"] == "unknown_assignment"


def test_unknown_command_reports_error(server_and_state) -> None:
    _server, _state, sock_path = server_and_state
    resp = _call(sock_path, {"command": "compositor.nope", "args": {}})
    assert resp["status"] == "error"
    assert resp["error"] == "unknown_command"
    assert resp["command"] == "compositor.nope"


def test_invalid_json_reports_error(tmp_path: Path) -> None:
    state = LayoutState(_minimal_layout())
    sock_path = tmp_path / "compositor.sock"
    server = CommandServer(state, sock_path)
    server.start()
    time.sleep(0.05)
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(str(sock_path))
        s.sendall(b"not json\n")
        buf = s.recv(4096)
        s.close()
        resp = json.loads(buf.decode("utf-8").split("\n", 1)[0])
        assert resp["status"] == "error"
        assert resp["error"] == "invalid_json"
    finally:
        server.stop()


def test_save_invokes_flush_callback(tmp_path: Path) -> None:
    state = LayoutState(_minimal_layout())
    sock_path = tmp_path / "compositor.sock"
    calls: list[int] = []
    server = CommandServer(
        state,
        sock_path,
        flush_callback=lambda: calls.append(1),
    )
    server.start()
    time.sleep(0.05)
    try:
        resp = _call(sock_path, {"command": "compositor.layout.save"})
        assert resp == {"status": "ok"}
        assert calls == [1]
    finally:
        server.stop()


def test_reload_invokes_reload_callback(tmp_path: Path) -> None:
    state = LayoutState(_minimal_layout())
    sock_path = tmp_path / "compositor.sock"
    calls: list[int] = []
    server = CommandServer(
        state,
        sock_path,
        reload_callback=lambda: calls.append(1),
    )
    server.start()
    time.sleep(0.05)
    try:
        resp = _call(sock_path, {"command": "compositor.layout.reload"})
        assert resp == {"status": "ok"}
        assert calls == [1]
    finally:
        server.stop()


def test_stop_removes_socket(tmp_path: Path) -> None:
    state = LayoutState(_minimal_layout())
    sock_path = tmp_path / "compositor.sock"
    server = CommandServer(state, sock_path)
    server.start()
    assert sock_path.exists()
    server.stop()
    assert not sock_path.exists()
