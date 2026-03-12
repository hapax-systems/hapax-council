"""Tests for demo generation API endpoints."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from cockpit.api.demo_jobs import DemoJobManager


@pytest.fixture
def manager(tmp_path):
    return DemoJobManager(jobs_dir=tmp_path / "jobs")


@pytest.fixture
def app(manager):
    from cockpit.api.app import app

    app.state.demo_jobs = manager
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestGenerateEndpoint:
    @patch("cockpit.api.demo_jobs.DemoJobManager._run_demo", new_callable=AsyncMock)
    def test_submit_returns_job_id(self, mock_run, client):
        resp = client.post("/api/demos/generate", json={"request": "demo for family"})
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    @patch("cockpit.api.demo_jobs.DemoJobManager._run_demo", new_callable=AsyncMock)
    def test_submit_with_format(self, mock_run, client):
        resp = client.post(
            "/api/demos/generate",
            json={"request": "video demo", "format": "video"},
        )
        assert resp.status_code == 200

    def test_concurrent_submit_returns_409(self, client, manager):
        # Simulate a running job by setting _current_task to a non-done future
        loop = asyncio.new_event_loop()
        fake_task = loop.create_task(asyncio.sleep(999))
        manager._current_task = fake_task
        manager._current_job_id = "fake-running-job"
        try:
            resp = client.post("/api/demos/generate", json={"request": "second"})
            assert resp.status_code == 409
        finally:
            fake_task.cancel()
            loop.close()

    def test_missing_request_returns_422(self, client):
        resp = client.post("/api/demos/generate", json={})
        assert resp.status_code == 422


class TestJobEndpoints:
    @patch("cockpit.api.demo_jobs.DemoJobManager._run_demo", new_callable=AsyncMock)
    def test_list_jobs(self, mock_run, client):
        client.post("/api/demos/generate", json={"request": "test"})
        resp = client.get("/api/demos/jobs")
        assert resp.status_code == 200
        jobs = resp.json()
        assert len(jobs) >= 1

    @patch("cockpit.api.demo_jobs.DemoJobManager._run_demo", new_callable=AsyncMock)
    def test_get_job(self, mock_run, client):
        resp = client.post("/api/demos/generate", json={"request": "test"})
        job_id = resp.json()["job_id"]

        resp2 = client.get(f"/api/demos/jobs/{job_id}")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["id"] == job_id
        assert data["request"] == "test"

    def test_get_missing_job_returns_404(self, client):
        resp = client.get("/api/demos/jobs/nonexistent")
        assert resp.status_code == 404

    def test_cancel_missing_job_returns_404(self, client):
        resp = client.delete("/api/demos/jobs/nonexistent")
        assert resp.status_code == 404

    @patch("cockpit.api.demo_jobs.DemoJobManager._run_demo", new_callable=AsyncMock)
    def test_cancel_completed_job_returns_409(self, mock_run, client, manager):
        resp = client.post("/api/demos/generate", json={"request": "test"})
        job_id = resp.json()["job_id"]
        # Wait for task to complete (mock returns immediately)
        import time

        time.sleep(0.1)

        resp2 = client.delete(f"/api/demos/jobs/{job_id}")
        assert resp2.status_code == 409


class TestExistingEndpoints:
    """Verify existing demo browsing endpoints still work."""

    def test_list_demos(self, client):
        resp = client.get("/api/demos")
        assert resp.status_code == 200

    def test_get_missing_demo_returns_404(self, client):
        resp = client.get("/api/demos/nonexistent-demo-id")
        assert resp.status_code == 404
