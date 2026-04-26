"""Tests for agents.internet_archive_ias3_adapter."""

from __future__ import annotations

from unittest.mock import patch

from agents.internet_archive_ias3_adapter import (
    ACCESS_KEY_ENV,
    SECRET_KEY_ENV,
    publish_artifact,
)
from agents.publication_bus.publisher_kit import PublisherResult
from shared.preprint_artifact import PreprintArtifact


def _artifact():
    return PreprintArtifact(
        slug="test-item",
        title="Test artefact",
        abstract="abstract",
        body_md="body",
        surfaces_targeted=["internet-archive-ias3"],
    )


class TestIaAdapter:
    def test_missing_access_key(self, monkeypatch):
        monkeypatch.delenv(ACCESS_KEY_ENV, raising=False)
        monkeypatch.setenv(SECRET_KEY_ENV, "secret")
        assert publish_artifact(_artifact()) == "auth_error"

    def test_missing_secret_key(self, monkeypatch):
        monkeypatch.setenv(ACCESS_KEY_ENV, "access")
        monkeypatch.delenv(SECRET_KEY_ENV, raising=False)
        assert publish_artifact(_artifact()) == "auth_error"

    def test_ok(self, monkeypatch):
        monkeypatch.setenv(ACCESS_KEY_ENV, "access")
        monkeypatch.setenv(SECRET_KEY_ENV, "secret")
        with patch(
            "agents.internet_archive_ias3_adapter.InternetArchiveS3Publisher.publish",
            return_value=PublisherResult(ok=True),
        ):
            assert publish_artifact(_artifact()) == "ok"

    def test_refused_creds_returns_auth_error(self, monkeypatch):
        monkeypatch.setenv(ACCESS_KEY_ENV, "access")
        monkeypatch.setenv(SECRET_KEY_ENV, "secret")
        with patch(
            "agents.internet_archive_ias3_adapter.InternetArchiveS3Publisher.publish",
            return_value=PublisherResult(refused=True, detail="missing IA S3 credentials"),
        ):
            assert publish_artifact(_artifact()) == "auth_error"

    def test_error(self, monkeypatch):
        monkeypatch.setenv(ACCESS_KEY_ENV, "access")
        monkeypatch.setenv(SECRET_KEY_ENV, "secret")
        with patch(
            "agents.internet_archive_ias3_adapter.InternetArchiveS3Publisher.publish",
            return_value=PublisherResult(error=True, detail="HTTP 500"),
        ):
            assert publish_artifact(_artifact()) == "error"


class TestIaWiring:
    def test_in_dispatch_map(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert SURFACE_REGISTRY["internet-archive-ias3"].endswith(":publish_artifact")

    def test_wire_status_wired(self):
        from agents.publication_bus.wire_status import PUBLISHER_WIRE_REGISTRY

        entry = PUBLISHER_WIRE_REGISTRY["agents.publication_bus.internet_archive_publisher"]
        assert entry.status == "WIRED"
