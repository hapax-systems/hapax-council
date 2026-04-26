"""Tests for ``agents.attribution.citation_feature`` BibTeX puller."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.attribution.citation_feature import (
    SWH_CITATION_ENDPOINT,
    fetch_bibtex,
)


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


class TestFetchBibtex:
    @patch("agents.attribution.citation_feature.requests")
    def test_200_returns_bibtex_text(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, text="@software{hapax-council, ...}")
        result = fetch_bibtex("swh:1:snp:" + "a" * 40)
        assert result == "@software{hapax-council, ...}"

    @patch("agents.attribution.citation_feature.requests")
    def test_404_returns_none(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(404, text="not found")
        result = fetch_bibtex("swh:1:snp:" + "b" * 40)
        assert result is None

    @patch("agents.attribution.citation_feature.requests")
    def test_request_exception_returns_none(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.get.side_effect = _requests_lib.RequestException("network down")
        mock_requests.RequestException = _requests_lib.RequestException
        result = fetch_bibtex("swh:1:snp:" + "c" * 40)
        assert result is None

    @patch("agents.attribution.citation_feature.requests")
    def test_url_includes_query_params(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, text="@software{x}")
        swhid = "swh:1:snp:" + "d" * 40
        fetch_bibtex(swhid)
        call_args = mock_requests.get.call_args
        url = call_args[0][0]
        assert url.startswith(SWH_CITATION_ENDPOINT)
        # The query params can come in either positional URL form or via params=
        # kwarg. Accept either.
        kwargs = call_args[1]
        if "params" in kwargs:
            assert kwargs["params"]["citation_format"] == "bibtex"
            assert kwargs["params"]["target_swhid"] == swhid
        else:
            assert "citation_format=bibtex" in url
            assert f"target_swhid={swhid}" in url

    @patch("agents.attribution.citation_feature.requests")
    def test_5xx_returns_none(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(503, text="service unavailable")
        result = fetch_bibtex("swh:1:snp:" + "e" * 40)
        assert result is None
