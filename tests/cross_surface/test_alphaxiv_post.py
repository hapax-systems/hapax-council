"""Tests for ``agents.cross_surface.alphaxiv_post``."""

from __future__ import annotations

from unittest import mock

import requests

from agents.cross_surface.alphaxiv_post import (
    ALPHAXIV_COMMENT_TEXT_LIMIT,
    publish_artifact,
)


class _FakeArtifact:
    """Minimal duck-type for ``publish_artifact`` tests.

    Mirrors the surface ``PreprintArtifact`` exposes today: ``slug``,
    ``title``, ``abstract``, ``attribution_block``, ``doi``. Pydantic
    isn't pulled in here so the test isn't coupled to model evolution.
    """

    def __init__(
        self,
        *,
        slug: str = "test",
        title: str = "",
        abstract: str = "",
        attribution_block: str = "",
        doi: str | None = None,
    ) -> None:
        self.slug = slug
        self.title = title
        self.abstract = abstract
        self.attribution_block = attribution_block
        self.doi = doi


def _ok_response() -> mock.Mock:
    response = mock.Mock()
    response.status_code = 201
    response.text = ""
    return response


# ── Credentials gate ─────────────────────────────────────────────────


class TestCredentialsGate:
    def test_no_credentials_returns_no_credentials(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "")
        artifact = _FakeArtifact(title="x", doi="10.48550/arXiv.2604.19965")
        assert publish_artifact(artifact) == "no_credentials"

    def test_only_token_set_returns_no_credentials(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "")
        artifact = _FakeArtifact(title="x", doi="10.48550/arXiv.2604.19965")
        assert publish_artifact(artifact) == "no_credentials"

    def test_only_url_set_returns_no_credentials(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org")
        artifact = _FakeArtifact(title="x", doi="10.48550/arXiv.2604.19965")
        assert publish_artifact(artifact) == "no_credentials"


# ── DOI gate (arXiv-mirror requirement) ──────────────────────────────


class TestDoiGate:
    def test_missing_doi_returns_dropped(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org")
        artifact = _FakeArtifact(title="x", abstract="y")
        assert publish_artifact(artifact) == "dropped"

    def test_zenodo_doi_returns_dropped(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org")
        artifact = _FakeArtifact(title="x", doi="10.5281/zenodo.1234567")
        assert publish_artifact(artifact) == "dropped"

    def test_arxiv_doi_proceeds_to_post(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org")
        artifact = _FakeArtifact(title="x", doi="10.48550/arXiv.2604.19965")
        with mock.patch("requests.post", return_value=_ok_response()) as posted:
            assert publish_artifact(artifact) == "ok"
        assert posted.called
        url = posted.call_args.args[0]
        assert "/papers/2604.19965/comments" in url


# ── HTTP outcome mapping ─────────────────────────────────────────────


class TestHttpOutcomes:
    def _setup(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org")

    def _artifact(self) -> _FakeArtifact:
        return _FakeArtifact(
            title="t",
            abstract="a",
            attribution_block="block",
            doi="10.48550/arXiv.2604.19965",
        )

    def test_201_yields_ok(self, monkeypatch):
        self._setup(monkeypatch)
        response = mock.Mock(status_code=201, text="")
        with mock.patch("requests.post", return_value=response):
            assert publish_artifact(self._artifact()) == "ok"

    def test_200_yields_ok(self, monkeypatch):
        self._setup(monkeypatch)
        response = mock.Mock(status_code=200, text="")
        with mock.patch("requests.post", return_value=response):
            assert publish_artifact(self._artifact()) == "ok"

    def test_401_yields_auth_error(self, monkeypatch):
        self._setup(monkeypatch)
        response = mock.Mock(status_code=401, text="unauthorized")
        with mock.patch("requests.post", return_value=response):
            assert publish_artifact(self._artifact()) == "auth_error"

    def test_403_yields_auth_error(self, monkeypatch):
        self._setup(monkeypatch)
        response = mock.Mock(status_code=403, text="forbidden")
        with mock.patch("requests.post", return_value=response):
            assert publish_artifact(self._artifact()) == "auth_error"

    def test_404_yields_denied(self, monkeypatch):
        self._setup(monkeypatch)
        response = mock.Mock(status_code=404, text="paper not found")
        with mock.patch("requests.post", return_value=response):
            assert publish_artifact(self._artifact()) == "denied"

    def test_422_yields_denied(self, monkeypatch):
        self._setup(monkeypatch)
        response = mock.Mock(status_code=422, text="malformed body")
        with mock.patch("requests.post", return_value=response):
            assert publish_artifact(self._artifact()) == "denied"

    def test_500_yields_error(self, monkeypatch):
        self._setup(monkeypatch)
        response = mock.Mock(status_code=500, text="internal")
        with mock.patch("requests.post", return_value=response):
            assert publish_artifact(self._artifact()) == "error"

    def test_request_exception_yields_error(self, monkeypatch):
        self._setup(monkeypatch)
        with mock.patch("requests.post", side_effect=requests.ConnectionError("down")):
            assert publish_artifact(self._artifact()) == "error"


# ── Body composition ─────────────────────────────────────────────────


class TestBodyComposition:
    def _setup(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org")

    def test_attribution_block_preferred(self, monkeypatch):
        self._setup(monkeypatch)
        artifact = _FakeArtifact(
            title="Title",
            abstract="Abstract.",
            attribution_block="Attribution Block",
            doi="10.48550/arXiv.2604.19965",
        )
        with mock.patch("requests.post", return_value=_ok_response()) as posted:
            assert publish_artifact(artifact) == "ok"
        assert posted.call_args.kwargs["json"]["body"] == "Attribution Block"

    def test_title_abstract_fallback(self, monkeypatch):
        self._setup(monkeypatch)
        artifact = _FakeArtifact(
            title="Title",
            abstract="Abstract.",
            doi="10.48550/arXiv.2604.19965",
        )
        with mock.patch("requests.post", return_value=_ok_response()) as posted:
            assert publish_artifact(artifact) == "ok"
        assert posted.call_args.kwargs["json"]["body"] == "Title — Abstract."

    def test_body_truncated_to_limit(self, monkeypatch):
        self._setup(monkeypatch)
        artifact = _FakeArtifact(
            attribution_block="x" * (ALPHAXIV_COMMENT_TEXT_LIMIT + 100),
            doi="10.48550/arXiv.2604.19965",
        )
        with mock.patch("requests.post", return_value=_ok_response()) as posted:
            assert publish_artifact(artifact) == "ok"
        assert len(posted.call_args.kwargs["json"]["body"]) == ALPHAXIV_COMMENT_TEXT_LIMIT

    def test_bare_artifact_uses_placeholder(self, monkeypatch):
        self._setup(monkeypatch)
        artifact = _FakeArtifact(doi="10.48550/arXiv.2604.19965")
        with mock.patch("requests.post", return_value=_ok_response()) as posted:
            assert publish_artifact(artifact) == "ok"
        assert posted.call_args.kwargs["json"]["body"] == "hapax — publication artifact"


# ── Auth header ──────────────────────────────────────────────────────


class TestAuthHeader:
    def test_bearer_token_in_header(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "shh-secret")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org")
        artifact = _FakeArtifact(title="t", attribution_block="b", doi="10.48550/arXiv.2604.19965")
        with mock.patch("requests.post", return_value=_ok_response()) as posted:
            publish_artifact(artifact)
        assert posted.call_args.kwargs["headers"]["Authorization"] == "Bearer shh-secret"

    def test_url_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("HAPAX_ALPHAXIV_TOKEN", "tok")
        monkeypatch.setenv("HAPAX_ALPHAXIV_API_URL", "https://api.alphaxiv.org/")
        artifact = _FakeArtifact(title="t", attribution_block="b", doi="10.48550/arXiv.2604.19965")
        with mock.patch("requests.post", return_value=_ok_response()) as posted:
            publish_artifact(artifact)
        assert posted.call_args.args[0] == "https://api.alphaxiv.org/papers/2604.19965/comments"
