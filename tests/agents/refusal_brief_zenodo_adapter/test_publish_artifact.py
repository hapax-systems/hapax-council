"""Tests for ``agents.refusal_brief_zenodo_adapter.publish_artifact``.

Covers token resolution, PreprintArtifact → PublisherPayload mapping,
and PublisherResult → orchestrator-string mapping.
"""

from __future__ import annotations

from unittest.mock import patch

from agents.publication_bus.publisher_kit import PublisherResult
from agents.refusal_brief_zenodo_adapter import ZENODO_TOKEN_ENV, publish_artifact
from shared.preprint_artifact import PreprintArtifact


def _artifact(**overrides) -> PreprintArtifact:
    defaults = dict(
        slug="bandcamp-upload",
        title="Refused: Bandcamp upload",
        abstract="Vendor lock-in posture documented.",
        body_md="# Refusal\n\nFull rationale here.\n",
        surfaces_targeted=["zenodo-refusal-deposit"],
    )
    defaults.update(overrides)
    return PreprintArtifact(**defaults)


# ── Token resolution ─────────────────────────────────────────────────


class TestTokenResolution:
    def test_missing_token_returns_auth_error(self, monkeypatch):
        monkeypatch.delenv(ZENODO_TOKEN_ENV, raising=False)
        assert publish_artifact(_artifact()) == "auth_error"

    def test_blank_token_returns_auth_error(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "   ")
        assert publish_artifact(_artifact()) == "auth_error"


# ── Result mapping ───────────────────────────────────────────────────


class TestResultMapping:
    def test_ok_result_returns_ok(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "tok-fake")
        with patch(
            "agents.refusal_brief_zenodo_adapter.RefusalBriefPublisher.publish",
            return_value=PublisherResult(ok=True, detail="deposit-id 12345"),
        ):
            assert publish_artifact(_artifact()) == "ok"

    def test_refused_allowlist_returns_denied(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "tok-fake")
        with patch(
            "agents.refusal_brief_zenodo_adapter.RefusalBriefPublisher.publish",
            return_value=PublisherResult(refused=True, detail="allowlist deny"),
        ):
            assert publish_artifact(_artifact()) == "denied"

    def test_refused_no_credentials_returns_auth_error(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "tok-fake")
        with patch(
            "agents.refusal_brief_zenodo_adapter.RefusalBriefPublisher.publish",
            return_value=PublisherResult(refused=True, detail="missing Zenodo credentials"),
        ):
            assert publish_artifact(_artifact()) == "auth_error"

    def test_error_result_returns_error(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "tok-fake")
        with patch(
            "agents.refusal_brief_zenodo_adapter.RefusalBriefPublisher.publish",
            return_value=PublisherResult(error=True, detail="HTTP 500"),
        ):
            assert publish_artifact(_artifact()) == "error"


# ── Payload composition ─────────────────────────────────────────────


class TestPayloadComposition:
    def _capture_publish_payload(self, monkeypatch, artifact):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "tok-fake")
        captured = {}

        def fake_publish(self, payload):
            captured["payload"] = payload
            return PublisherResult(ok=True)

        with patch(
            "agents.refusal_brief_zenodo_adapter.RefusalBriefPublisher.publish",
            new=fake_publish,
        ):
            publish_artifact(artifact)
        return captured["payload"]

    def test_target_is_artifact_slug(self, monkeypatch):
        p = self._capture_publish_payload(monkeypatch, _artifact(slug="discogs-submission"))
        assert p.target == "discogs-submission"

    def test_text_is_body_md(self, monkeypatch):
        p = self._capture_publish_payload(monkeypatch, _artifact(body_md="custom body"))
        assert p.text == "custom body"

    def test_text_falls_back_to_abstract(self, monkeypatch):
        p = self._capture_publish_payload(
            monkeypatch, _artifact(body_md="", abstract="just the abstract")
        )
        assert p.text == "just the abstract"

    def test_metadata_carries_title(self, monkeypatch):
        p = self._capture_publish_payload(monkeypatch, _artifact(title="Refused: Custom Title"))
        assert p.metadata["title"] == "Refused: Custom Title"


# ── Orchestrator dispatch-map registration ───────────────────────────


class TestDispatchMapRegistration:
    def test_zenodo_refusal_deposit_in_dispatch_map(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "zenodo-refusal-deposit" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["zenodo-refusal-deposit"].endswith(":publish_artifact")


# ── Wire-status flip ────────────────────────────────────────────────


class TestWireStatusFlip:
    def test_refusal_brief_publisher_now_wired(self):
        from agents.publication_bus.wire_status import PUBLISHER_WIRE_REGISTRY

        entry = PUBLISHER_WIRE_REGISTRY["agents.publication_bus.refusal_brief_publisher"]
        assert entry.status == "WIRED"
        assert entry.pass_key_required is None  # no longer cred-blocked
