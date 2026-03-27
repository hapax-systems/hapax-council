"""Tests for the WebSocket command relay endpoint at /ws/commands."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from logos.api.routes.commands import _state, router


@pytest.fixture(autouse=True)
def reset_state():
    """Reset relay state between tests."""
    _state.reset()
    yield
    _state.reset()


@pytest.fixture()
def app():
    _app = FastAPI()
    _app.include_router(router)
    return _app


def test_execute_without_frontend_returns_error(app):
    """External client gets error when no frontend is connected."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/commands") as ws:
            ws.send_json(
                {
                    "type": "execute",
                    "id": "abc-123",
                    "path": "terrain.focus",
                    "args": {"region": "ground"},
                }
            )
            msg = ws.receive_json()
            assert msg["type"] == "result"
            assert msg["id"] == "abc-123"
            assert msg["data"]["ok"] is False
            assert "frontend not connected" in msg["data"]["error"]


def test_frontend_registration(app):
    """Frontend connects, external sends command, frontend gets it, sends result, external gets result."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/commands?role=frontend") as frontend:
            with client.websocket_connect("/ws/commands") as external:
                external.send_json(
                    {
                        "type": "execute",
                        "id": "exec-001",
                        "path": "terrain.focus",
                        "args": {"region": "ground"},
                    }
                )
                # Frontend should receive the forwarded command
                forwarded = frontend.receive_json()
                assert forwarded["type"] == "execute"
                assert forwarded["id"] == "exec-001"
                assert forwarded["path"] == "terrain.focus"

                # Frontend sends result back
                frontend.send_json(
                    {
                        "type": "result",
                        "id": "exec-001",
                        "data": {"ok": True, "state": "ground"},
                    }
                )

                # External client receives the result
                result = external.receive_json()
                assert result["type"] == "result"
                assert result["id"] == "exec-001"
                assert result["data"]["ok"] is True
                assert result["data"]["state"] == "ground"


def test_query_forwarded(app):
    """Query is forwarded to frontend and result returned to external client."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/commands?role=frontend") as frontend:
            with client.websocket_connect("/ws/commands") as external:
                external.send_json(
                    {
                        "type": "query",
                        "id": "qry-001",
                        "path": "terrain.focusedRegion",
                    }
                )
                forwarded = frontend.receive_json()
                assert forwarded["type"] == "query"
                assert forwarded["id"] == "qry-001"
                assert forwarded["path"] == "terrain.focusedRegion"

                frontend.send_json(
                    {
                        "type": "result",
                        "id": "qry-001",
                        "data": {"ok": True, "value": "ground"},
                    }
                )

                result = external.receive_json()
                assert result["type"] == "result"
                assert result["id"] == "qry-001"
                assert result["data"]["ok"] is True


def test_list_forwarded(app):
    """List command is forwarded to frontend and result returned to external client."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/commands?role=frontend") as frontend:
            with client.websocket_connect("/ws/commands") as external:
                external.send_json(
                    {
                        "type": "list",
                        "id": "lst-001",
                        "domain": "terrain",
                    }
                )
                forwarded = frontend.receive_json()
                assert forwarded["type"] == "list"
                assert forwarded["id"] == "lst-001"
                assert forwarded["domain"] == "terrain"

                frontend.send_json(
                    {
                        "type": "result",
                        "id": "lst-001",
                        "data": {"ok": True, "commands": ["terrain.focus", "terrain.reset"]},
                    }
                )

                result = external.receive_json()
                assert result["type"] == "result"
                assert result["id"] == "lst-001"
                assert result["data"]["ok"] is True
