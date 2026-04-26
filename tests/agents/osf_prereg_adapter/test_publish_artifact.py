"""Tests for agents.osf_prereg_adapter."""

from __future__ import annotations

from unittest.mock import patch

from agents.osf_prereg_adapter import TOKEN_ENV, publish_artifact
from agents.publication_bus.publisher_kit import PublisherResult
from shared.preprint_artifact import PreprintArtifact


def _artifact():
    return PreprintArtifact(
        slug="hapax-presence-bayesian-2026-q2",
        title="Test prereg",
        abstract="abstract",
        body_md="body",
        surfaces_targeted=["osf-prereg"],
    )


class TestOsfAdapter:
    def test_missing_token(self, monkeypatch):
        monkeypatch.delenv(TOKEN_ENV, raising=False)
        assert publish_artifact(_artifact()) == "auth_error"

    def test_blank_token(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "  ")
        assert publish_artifact(_artifact()) == "auth_error"

    def test_ok(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "tok")
        with patch(
            "agents.osf_prereg_adapter.OSFPreregPublisher.publish",
            return_value=PublisherResult(ok=True),
        ):
            assert publish_artifact(_artifact()) == "ok"

    def test_refused_token_returns_auth_error(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "tok")
        with patch(
            "agents.osf_prereg_adapter.OSFPreregPublisher.publish",
            return_value=PublisherResult(refused=True, detail="missing OSF token"),
        ):
            assert publish_artifact(_artifact()) == "auth_error"

    def test_refused_other_returns_denied(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "tok")
        with patch(
            "agents.osf_prereg_adapter.OSFPreregPublisher.publish",
            return_value=PublisherResult(refused=True, detail="allowlist deny"),
        ):
            assert publish_artifact(_artifact()) == "denied"

    def test_error(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV, "tok")
        with patch(
            "agents.osf_prereg_adapter.OSFPreregPublisher.publish",
            return_value=PublisherResult(error=True, detail="HTTP 500"),
        ):
            assert publish_artifact(_artifact()) == "error"


class TestOsfWiring:
    def test_in_dispatch_map(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert SURFACE_REGISTRY["osf-prereg"].endswith(":publish_artifact")

    def test_wire_status_wired(self):
        from agents.publication_bus.wire_status import PUBLISHER_WIRE_REGISTRY

        entry = PUBLISHER_WIRE_REGISTRY["agents.publication_bus.osf_prereg_publisher"]
        assert entry.status == "WIRED"
