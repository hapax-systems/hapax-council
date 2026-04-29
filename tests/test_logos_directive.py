"""Tests for the retired Hapax Logos directive bridge."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from logos.api.routes.logos import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestDirectiveEndpoint:
    def test_post_directive_is_gone_with_replacement_paths(self):
        resp = client.post(
            "/api/logos/directive",
            json={"navigate": "/studio", "source": "test"},
        )

        assert resp.status_code == 410
        detail = resp.json()["detail"]
        assert detail["status"] == "decommissioned"
        assert detail["fields"] == ["navigate", "source"]
        assert "logos-api :8051" in detail["replacement"]["control"]
        assert "/dev/video42" in detail["replacement"]["frames"]

    def test_post_browser_directive_is_also_gone(self):
        resp = client.post(
            "/api/logos/directive",
            json={
                "browser_navigate": "https://github.com/ryanklee/hapax-council/pull/145",
                "source": "browser-agent",
            },
        )

        assert resp.status_code == 410
        detail = resp.json()["detail"]
        assert detail["status"] == "decommissioned"
        assert detail["fields"] == ["browser_navigate", "source"]

    def test_get_schema_remains_available_for_legacy_clients(self):
        resp = client.get("/api/logos/directive/schema")
        assert resp.status_code == 200
        schema = resp.json()
        assert "properties" in schema
        assert "navigate" in schema["properties"]
        assert "toast" in schema["properties"]
        assert "visual_stance" in schema["properties"]
        assert "browser_navigate" in schema["properties"]
        assert "browser_click" in schema["properties"]
