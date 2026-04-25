"""Tests for agents/osf_preprint_publisher/publisher.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.osf_preprint_publisher.publisher import (
    _build_create_payload,
    _compose_abstract_with_attribution,
    _interpret_response,
    publish_artifact,
)
from shared.co_author_model import ALL_CO_AUTHORS
from shared.preprint_artifact import PreprintArtifact


def _make_artifact(**overrides) -> PreprintArtifact:
    defaults = {
        "slug": "hapax-test-preprint",
        "title": "Hapax: Externalized Executive Function",
        "abstract": "Test abstract.",
        "body_md": "# Body\n\nTest content.",
        "co_authors": list(ALL_CO_AUTHORS),
        "surfaces_targeted": ["osf-preprint"],
    }
    defaults.update(overrides)
    return PreprintArtifact(**defaults)


# ── publish_artifact (top-level entry-point) ────────────────────────────


class TestPublishArtifactCredentialing:
    def test_no_token_returns_deferred(self, monkeypatch):
        """Per orchestrator contract, defer when token absent."""
        monkeypatch.delenv("HAPAX_OSF_TOKEN", raising=False)
        result = publish_artifact(_make_artifact())
        assert result == "deferred"

    def test_empty_token_returns_deferred(self, monkeypatch):
        """Whitespace-only tokens count as unset."""
        monkeypatch.setenv("HAPAX_OSF_TOKEN", "   ")
        result = publish_artifact(_make_artifact())
        assert result == "deferred"

    def test_token_present_attempts_post(self, monkeypatch):
        """With token present, the publisher attempts the OSF POST."""
        monkeypatch.setenv("HAPAX_OSF_TOKEN", "fake-pat-token")
        with patch("agents.osf_preprint_publisher.publisher.httpx") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_httpx.post.return_value = mock_response
            mock_httpx.RequestError = Exception
            result = publish_artifact(_make_artifact())
        assert result == "ok"
        mock_httpx.post.assert_called_once()
        kwargs = mock_httpx.post.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer fake-pat-token"
        assert kwargs["headers"]["Content-Type"] == "application/vnd.api+json"

    def test_request_error_returns_error(self, monkeypatch):
        """Network errors map to terminal ``"error"``."""
        monkeypatch.setenv("HAPAX_OSF_TOKEN", "fake-pat-token")
        with patch("agents.osf_preprint_publisher.publisher.httpx") as mock_httpx:
            mock_httpx.RequestError = type("RequestError", (Exception,), {})
            mock_httpx.post.side_effect = mock_httpx.RequestError("network down")
            result = publish_artifact(_make_artifact())
        assert result == "error"


# ── _interpret_response (HTTP status mapping) ───────────────────────────


class TestInterpretResponse:
    def test_2xx_returns_ok(self):
        for status in (200, 201, 202, 204):
            response = MagicMock()
            response.status_code = status
            response.text = ""
            assert _interpret_response(response, "test") == "ok"

    def test_401_returns_auth_error(self):
        response = MagicMock()
        response.status_code = 401
        response.text = "unauthorized"
        assert _interpret_response(response, "test") == "auth_error"

    def test_403_returns_auth_error(self):
        response = MagicMock()
        response.status_code = 403
        response.text = "forbidden"
        assert _interpret_response(response, "test") == "auth_error"

    def test_429_returns_rate_limited(self):
        response = MagicMock()
        response.status_code = 429
        response.text = "rate limited"
        assert _interpret_response(response, "test") == "rate_limited"

    def test_500_returns_error(self):
        response = MagicMock()
        response.status_code = 500
        response.text = "internal server error"
        assert _interpret_response(response, "test") == "error"

    def test_400_returns_error(self):
        response = MagicMock()
        response.status_code = 400
        response.text = "bad request"
        assert _interpret_response(response, "test") == "error"


# ── _build_create_payload (JSON:API shape) ──────────────────────────────


class TestBuildCreatePayload:
    def test_includes_title_and_description(self):
        artifact = _make_artifact(title="Test Title", abstract="Test abstract content.")
        payload = _build_create_payload(artifact, provider="osf")
        assert payload["data"]["type"] == "preprints"
        assert payload["data"]["attributes"]["title"] == "Test Title"
        assert "Test abstract content." in payload["data"]["attributes"]["description"]

    def test_is_published_starts_false(self):
        """Phase 1 ships as draft; publish-toggle is Part 2."""
        payload = _build_create_payload(_make_artifact(), provider="osf")
        assert payload["data"]["attributes"]["is_published"] is False

    def test_provider_relationship(self):
        payload = _build_create_payload(_make_artifact(), provider="psyarxiv")
        provider_rel = payload["data"]["relationships"]["provider"]["data"]
        assert provider_rel["type"] == "preprint-providers"
        assert provider_rel["id"] == "psyarxiv"


# ── _compose_abstract_with_attribution ──────────────────────────────────


class TestComposeAbstractWithAttribution:
    def test_attribution_block_takes_precedence(self):
        artifact = _make_artifact(
            attribution_block="Custom attribution here.",
            abstract="Original abstract.",
        )
        composed = _compose_abstract_with_attribution(artifact)
        assert composed.startswith("Custom attribution here.")
        assert "Original abstract." in composed

    def test_falls_back_to_co_author_byline(self):
        artifact = _make_artifact(attribution_block="", abstract="Body abstract.")
        composed = _compose_abstract_with_attribution(artifact)
        assert "Authors:" in composed
        assert "Body abstract." in composed

    def test_no_attribution_no_co_authors_returns_abstract(self):
        artifact = _make_artifact(
            attribution_block="",
            co_authors=[],
            abstract="Standalone abstract.",
        )
        composed = _compose_abstract_with_attribution(artifact)
        assert composed == "Standalone abstract."

    def test_empty_abstract_returns_attribution_only(self):
        artifact = _make_artifact(
            attribution_block="Attribution alone.",
            abstract="",
        )
        composed = _compose_abstract_with_attribution(artifact)
        assert composed == "Attribution alone."


# ── Orchestrator integration smoke test ─────────────────────────────────


class TestOrchestratorRegistryEntry:
    def test_registry_includes_osf_preprint(self):
        """SURFACE_REGISTRY includes the osf-preprint entry."""
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "osf-preprint" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["osf-preprint"] == (
            "agents.osf_preprint_publisher:publish_artifact"
        )

    def test_entry_point_resolves(self):
        """The registered entry-point can be imported."""
        from agents.osf_preprint_publisher import publish_artifact as entry

        assert callable(entry)
