"""Tests for recording enable/disable endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from fastapi import FastAPI

    from logos.api.routes.studio import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_enable_recording(client: TestClient):
    mock_path = MagicMock()
    mock_path.parent = MagicMock()

    with patch("logos.api.routes.studio.RECORDING_CONTROL", mock_path):
        response = client.post("/api/studio/recording/enable")

    assert response.status_code == 200
    assert response.json() == {"recording": True}
    mock_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_path.write_text.assert_called_once_with("1")


def test_disable_recording(client: TestClient):
    mock_path = MagicMock()
    mock_path.parent = MagicMock()

    with patch("logos.api.routes.studio.RECORDING_CONTROL", mock_path):
        response = client.post("/api/studio/recording/disable")

    assert response.status_code == 200
    assert response.json() == {"recording": False}
    mock_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_path.write_text.assert_called_once_with("0")
