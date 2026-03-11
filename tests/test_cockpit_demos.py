"""Tests for cockpit demo API endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from cockpit.api.app import app


class TestDemoEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def mock_demos(self, tmp_path):
        """Create fake demo dirs."""
        d = tmp_path / "20260304-120000-test"
        d.mkdir()
        meta = {"title": "Test Demo", "audience": "family", "format": "slides", "scenes": 2, "duration": 15.0}
        (d / "metadata.json").write_text(json.dumps(meta))
        (d / "script.json").write_text("{}")
        (d / "slides.md").write_text("# slides")
        return tmp_path

    def test_list_demos_endpoint_exists(self, client):
        response = client.get("/api/demos")
        assert response.status_code == 200

    def test_list_demos_returns_data(self, client, mock_demos):
        with patch("cockpit.api.routes.demos.OUTPUT_DIR", mock_demos):
            response = client.get("/api/demos")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Demo"

    def test_get_demo_detail(self, client, mock_demos):
        with patch("cockpit.api.routes.demos.OUTPUT_DIR", mock_demos):
            response = client.get("/api/demos/20260304-120000-test")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Demo"
        assert "script.json" in data["files"]

    def test_get_demo_not_found(self, client):
        response = client.get("/api/demos/nonexistent-demo")
        assert response.status_code == 404

    def test_serve_file(self, client, mock_demos):
        with patch("cockpit.api.routes.demos.OUTPUT_DIR", mock_demos):
            response = client.get("/api/demos/20260304-120000-test/files/slides.md")
        assert response.status_code == 200
        assert b"# slides" in response.content

    def test_serve_file_not_found(self, client):
        response = client.get("/api/demos/nonexistent/files/test.txt")
        assert response.status_code == 404

    def test_validate_demo_id_rejects_traversal(self):
        """Verify _validate_demo_id rejects path traversal attempts."""
        from cockpit.api.routes.demos import _validate_demo_id

        # Clean IDs should pass
        _validate_demo_id("20260304-120000-test")

        # Traversal attempts should raise
        with pytest.raises(HTTPException) as exc_info:
            _validate_demo_id("../../../etc/passwd")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            _validate_demo_id("foo/bar")
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException) as exc_info:
            _validate_demo_id("foo\\bar")
        assert exc_info.value.status_code == 400

    def test_delete_demo(self, client, mock_demos):
        with patch("cockpit.api.routes.demos.OUTPUT_DIR", mock_demos):
            response = client.delete("/api/demos/20260304-120000-test")
        assert response.status_code == 200
        assert not (mock_demos / "20260304-120000-test").exists()

    def test_delete_nonexistent_demo(self, client):
        response = client.delete("/api/demos/nonexistent")
        assert response.status_code == 404
