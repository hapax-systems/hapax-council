"""Tests for agents.philarchive_adapter."""

from __future__ import annotations

from unittest.mock import patch

from agents.philarchive_adapter import (
    AUTHOR_ID_ENV,
    SESSION_COOKIE_ENV,
    publish_artifact,
)
from agents.publication_bus.publisher_kit import PublisherResult
from shared.preprint_artifact import PreprintArtifact


def _artifact():
    return PreprintArtifact(
        slug="constitutional-brief-2026",
        title="Test deposit",
        abstract="abstract",
        body_md="body",
        surfaces_targeted=["philarchive-deposit"],
    )


class TestPhilArchiveAdapter:
    def test_missing_session_cookie(self, monkeypatch):
        monkeypatch.delenv(SESSION_COOKIE_ENV, raising=False)
        monkeypatch.setenv(AUTHOR_ID_ENV, "12345")
        assert publish_artifact(_artifact()) == "auth_error"

    def test_missing_author_id(self, monkeypatch):
        monkeypatch.setenv(SESSION_COOKIE_ENV, "sid=abc")
        monkeypatch.delenv(AUTHOR_ID_ENV, raising=False)
        assert publish_artifact(_artifact()) == "auth_error"

    def test_ok(self, monkeypatch):
        monkeypatch.setenv(SESSION_COOKIE_ENV, "sid=abc")
        monkeypatch.setenv(AUTHOR_ID_ENV, "12345")
        with patch(
            "agents.philarchive_adapter.PhilArchivePublisher.publish",
            return_value=PublisherResult(ok=True),
        ):
            assert publish_artifact(_artifact()) == "ok"

    def test_refused_creds_returns_auth_error(self, monkeypatch):
        monkeypatch.setenv(SESSION_COOKIE_ENV, "sid=abc")
        monkeypatch.setenv(AUTHOR_ID_ENV, "12345")
        with patch(
            "agents.philarchive_adapter.PhilArchivePublisher.publish",
            return_value=PublisherResult(refused=True, detail="missing PhilArchive credentials"),
        ):
            assert publish_artifact(_artifact()) == "auth_error"

    def test_error(self, monkeypatch):
        monkeypatch.setenv(SESSION_COOKIE_ENV, "sid=abc")
        monkeypatch.setenv(AUTHOR_ID_ENV, "12345")
        with patch(
            "agents.philarchive_adapter.PhilArchivePublisher.publish",
            return_value=PublisherResult(error=True, detail="HTTP 500"),
        ):
            assert publish_artifact(_artifact()) == "error"


class TestPhilArchiveWiring:
    def test_in_dispatch_map(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert SURFACE_REGISTRY["philarchive-deposit"].endswith(":publish_artifact")

    def test_wire_status_wired(self):
        from agents.publication_bus.wire_status import PUBLISHER_WIRE_REGISTRY

        entry = PUBLISHER_WIRE_REGISTRY["agents.publication_bus.philarchive_publisher"]
        assert entry.status == "WIRED"
