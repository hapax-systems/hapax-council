"""Tests for the Hapax Logos directive bridge."""

import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpit.api.routes.logos import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestDirectiveEndpoint:
    def test_post_directive_navigate(self, tmp_path: Path):
        directive_file = tmp_path / "directives.jsonl"
        with (
            patch("cockpit.api.routes.logos.DIRECTIVE_DIR", tmp_path),
            patch("cockpit.api.routes.logos.DIRECTIVE_FILE", directive_file),
        ):
            resp = client.post(
                "/api/logos/directive",
                json={"navigate": "/studio", "source": "test"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "accepted"
            assert "navigate" in body["fields"]

            lines = directive_file.read_text().strip().split("\n")
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["navigate"] == "/studio"
            assert record["source"] == "test"
            assert "_timestamp" in record

    def test_post_directive_toast(self, tmp_path: Path):
        directive_file = tmp_path / "directives.jsonl"
        with (
            patch("cockpit.api.routes.logos.DIRECTIVE_DIR", tmp_path),
            patch("cockpit.api.routes.logos.DIRECTIVE_FILE", directive_file),
        ):
            resp = client.post(
                "/api/logos/directive",
                json={
                    "toast": "Hello from agent",
                    "toast_level": "warning",
                    "source": "nudge-agent",
                },
            )
            assert resp.status_code == 200
            record = json.loads(directive_file.read_text().strip())
            assert record["toast"] == "Hello from agent"
            assert record["toast_level"] == "warning"

    def test_post_directive_composite(self, tmp_path: Path):
        directive_file = tmp_path / "directives.jsonl"
        with (
            patch("cockpit.api.routes.logos.DIRECTIVE_DIR", tmp_path),
            patch("cockpit.api.routes.logos.DIRECTIVE_FILE", directive_file),
        ):
            resp = client.post(
                "/api/logos/directive",
                json={
                    "navigate": "/visual",
                    "toast": "Switching to visual",
                    "visual_stance": "cautious",
                    "focus_window": True,
                    "source": "stimmung-agent",
                },
            )
            assert resp.status_code == 200
            record = json.loads(directive_file.read_text().strip())
            assert record["navigate"] == "/visual"
            assert record["visual_stance"] == "cautious"
            assert record["focus_window"] is True

    def test_post_directive_empty_is_valid(self, tmp_path: Path):
        directive_file = tmp_path / "directives.jsonl"
        with (
            patch("cockpit.api.routes.logos.DIRECTIVE_DIR", tmp_path),
            patch("cockpit.api.routes.logos.DIRECTIVE_FILE", directive_file),
        ):
            resp = client.post("/api/logos/directive", json={})
            assert resp.status_code == 200

    def test_get_schema(self):
        resp = client.get("/api/logos/directive/schema")
        assert resp.status_code == 200
        schema = resp.json()
        assert "properties" in schema
        assert "navigate" in schema["properties"]
        assert "toast" in schema["properties"]
        assert "visual_stance" in schema["properties"]
