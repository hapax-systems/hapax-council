"""Tests for ``agents.zenodo_publisher.publisher``."""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from agents.zenodo_publisher.publisher import (
    DEFAULT_ACCESS_RIGHT,
    DEFAULT_LICENSE,
    DEFAULT_PUBLICATION_TYPE,
    DEFAULT_UPLOAD_TYPE,
    ZENODO_API_BASE_DEFAULT,
    ZENODO_TOKEN_ENV,
    publish_artifact,
)
from shared.preprint_artifact import PreprintArtifact


def _make_artifact(
    *,
    slug: str = "test-zenodo",
    title: str = "Test artifact",
    abstract: str = "Brief.",
    body_md: str = "Body.",
    attribution_block: str = "",
    co_authors=None,
) -> PreprintArtifact:
    kwargs: dict = {
        "slug": slug,
        "title": title,
        "abstract": abstract,
        "body_md": body_md,
        "attribution_block": attribution_block,
    }
    if co_authors is not None:
        kwargs["co_authors"] = co_authors
    return PreprintArtifact(**kwargs)


def _make_response(status_code: int, json_body: dict | None = None, text: str = "") -> mock.Mock:
    resp = mock.Mock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or (str(json_body) if json_body else "")
    if json_body is not None:
        resp.json = mock.Mock(return_value=json_body)
    else:
        resp.json = mock.Mock(side_effect=ValueError("no json"))
    return resp


# ── No-credentials terminal path ─────────────────────────────────────


class TestNoCredentials:
    def test_missing_token_returns_no_credentials(self, monkeypatch):
        monkeypatch.delenv(ZENODO_TOKEN_ENV, raising=False)
        artifact = _make_artifact()
        assert publish_artifact(artifact) == "no_credentials"

    def test_empty_token_returns_no_credentials(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "   ")
        artifact = _make_artifact()
        assert publish_artifact(artifact) == "no_credentials"


# ── Two-step happy path ──────────────────────────────────────────────


class TestHappyPath:
    def test_create_then_publish_ok(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        create_resp = _make_response(201, {"id": 12345})
        publish_resp = _make_response(202, {"id": 12345, "doi": "10.5281/zenodo.12345"})

        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            side_effect=[create_resp, publish_resp],
        ) as post_mock:
            result = publish_artifact(_make_artifact())

        assert result == "ok"
        assert post_mock.call_count == 2
        create_call = post_mock.call_args_list[0]
        publish_call = post_mock.call_args_list[1]

        assert create_call.args[0] == f"{ZENODO_API_BASE_DEFAULT}/deposit/depositions"
        assert publish_call.args[0] == (
            f"{ZENODO_API_BASE_DEFAULT}/deposit/depositions/12345/actions/publish"
        )
        assert create_call.kwargs["headers"]["Authorization"] == "Bearer test-token"

    def test_create_payload_shape(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        artifact = _make_artifact(
            title="Hapax — refusal-brief",
            abstract="Constitutional thesis.",
            attribution_block="Hapax + CC. Oudepode (operator).",
        )
        create_resp = _make_response(201, {"id": 1})
        publish_resp = _make_response(202, {"id": 1})
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            side_effect=[create_resp, publish_resp],
        ) as post_mock:
            publish_artifact(artifact)

        sent = post_mock.call_args_list[0].kwargs["json"]
        meta = sent["metadata"]
        assert meta["title"] == "Hapax — refusal-brief"
        assert meta["upload_type"] == DEFAULT_UPLOAD_TYPE
        assert meta["publication_type"] == DEFAULT_PUBLICATION_TYPE
        assert meta["access_right"] == DEFAULT_ACCESS_RIGHT
        assert meta["license"] == DEFAULT_LICENSE
        # Description carries attribution_block prefix.
        assert meta["description"].startswith("Hapax + CC. Oudepode (operator).")
        assert "Constitutional thesis." in meta["description"]
        # Creators populated from default ALL_CO_AUTHORS.
        assert isinstance(meta["creators"], list)
        assert len(meta["creators"]) >= 1
        assert "name" in meta["creators"][0]
        # publication_date is ISO YYYY-MM-DD.
        assert len(meta["publication_date"]) == 10
        assert meta["publication_date"][4] == "-"

    def test_attribution_block_omitted_uses_abstract_only(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        artifact = _make_artifact(
            title="t",
            abstract="just abstract.",
            attribution_block="",
        )
        create_resp = _make_response(201, {"id": 1})
        publish_resp = _make_response(202, {"id": 1})
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            side_effect=[create_resp, publish_resp],
        ) as post_mock:
            publish_artifact(artifact)
        meta = post_mock.call_args_list[0].kwargs["json"]["metadata"]
        assert meta["description"] == "just abstract."

    def test_empty_artifact_falls_back_to_title(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        artifact = _make_artifact(title="Only title", abstract="", attribution_block="")
        create_resp = _make_response(201, {"id": 1})
        publish_resp = _make_response(202, {"id": 1})
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            side_effect=[create_resp, publish_resp],
        ) as post_mock:
            publish_artifact(artifact)
        meta = post_mock.call_args_list[0].kwargs["json"]["metadata"]
        # Empty description falls back to title (Zenodo requires non-empty).
        assert meta["description"] == "Only title"


# ── Error paths ──────────────────────────────────────────────────────


class TestAuthError:
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_error_on_create(self, monkeypatch, status):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        create_resp = _make_response(status, {"message": "denied"})
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            return_value=create_resp,
        ):
            assert publish_artifact(_make_artifact()) == "auth_error"

    def test_auth_error_on_publish(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        create_resp = _make_response(201, {"id": 99})
        publish_resp = _make_response(401, {"message": "denied"})
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            side_effect=[create_resp, publish_resp],
        ):
            assert publish_artifact(_make_artifact()) == "auth_error"


class TestRateLimit:
    def test_rate_limited_on_create(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        create_resp = _make_response(429, {"message": "slow down"})
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            return_value=create_resp,
        ):
            assert publish_artifact(_make_artifact()) == "rate_limited"


class TestServerError:
    def test_500_yields_error(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        create_resp = _make_response(500, text="boom")
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            return_value=create_resp,
        ):
            assert publish_artifact(_make_artifact()) == "error"

    def test_network_failure_yields_error(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            side_effect=httpx.ConnectError("network down"),
        ):
            assert publish_artifact(_make_artifact()) == "error"

    def test_create_returns_no_id_yields_error(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        # Successful 201 but missing 'id' field.
        create_resp = _make_response(201, {"links": {}})
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            return_value=create_resp,
        ):
            assert publish_artifact(_make_artifact()) == "error"


# ── Sandbox / API base override ──────────────────────────────────────


class TestApiBaseOverride:
    def test_sandbox_url_via_env(self, monkeypatch):
        monkeypatch.setenv(ZENODO_TOKEN_ENV, "test-token")
        monkeypatch.setenv("HAPAX_ZENODO_API_BASE", "https://sandbox.zenodo.org/api")
        create_resp = _make_response(201, {"id": 7})
        publish_resp = _make_response(202, {"id": 7})
        with mock.patch(
            "agents.zenodo_publisher.publisher.httpx.post",
            side_effect=[create_resp, publish_resp],
        ) as post_mock:
            publish_artifact(_make_artifact())

        assert post_mock.call_args_list[0].args[0] == (
            "https://sandbox.zenodo.org/api/deposit/depositions"
        )
