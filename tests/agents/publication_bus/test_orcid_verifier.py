"""Tests for ``agents.publication_bus.orcid_verifier``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.publication_bus.orcid_verifier import (
    ORCID_PUBLIC_API_BASE,
    extract_dois,
    fetch_orcid_works,
    verify_dois_present,
)


def _mock_response(status_code: int, json_data=None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.json = MagicMock(return_value={} if json_data is None else json_data)
    return response


_WORKS_RESPONSE = {
    "group": [
        {
            "external-ids": {
                "external-id": [
                    {"external-id-type": "doi", "external-id-value": "10.5281/zenodo.111"},
                ]
            }
        },
        {
            "external-ids": {
                "external-id": [
                    {"external-id-type": "doi", "external-id-value": "10.5281/zenodo.222"},
                    {"external-id-type": "uri", "external-id-value": "https://x.org/y"},
                ]
            }
        },
    ]
}


class TestFetchOrcidWorks:
    @patch("agents.publication_bus.orcid_verifier.requests")
    def test_200_returns_body(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, _WORKS_RESPONSE)
        result = fetch_orcid_works("0000-0001-2345-6789")
        assert result is not None
        assert "group" in result

    @patch("agents.publication_bus.orcid_verifier.requests")
    def test_404_returns_none(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(404)
        assert fetch_orcid_works("0000-0001-2345-6789") is None

    @patch("agents.publication_bus.orcid_verifier.requests")
    def test_request_exception_returns_none(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.get.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        assert fetch_orcid_works("0000-0001-2345-6789") is None

    @patch("agents.publication_bus.orcid_verifier.requests")
    def test_url_includes_works_path(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, _WORKS_RESPONSE)
        fetch_orcid_works("0000-0001-2345-6789")
        url = mock_requests.get.call_args[0][0]
        assert url.startswith(ORCID_PUBLIC_API_BASE)
        assert "/0000-0001-2345-6789/works" in url


class TestExtractDois:
    def test_returns_only_doi_external_ids(self) -> None:
        result = extract_dois(_WORKS_RESPONSE)
        assert result == {"10.5281/zenodo.111", "10.5281/zenodo.222"}

    def test_empty_response_returns_empty_set(self) -> None:
        assert extract_dois({}) == set()

    def test_missing_group_returns_empty_set(self) -> None:
        assert extract_dois({"other": []}) == set()

    def test_handles_malformed_external_ids(self) -> None:
        malformed = {"group": [{"external-ids": "not-a-dict"}]}
        result = extract_dois(malformed)
        assert result == set()


class TestVerifyDoisPresent:
    def test_returns_empty_when_all_present(self) -> None:
        missing = verify_dois_present(
            expected_dois={"10.5281/zenodo.111"},
            fetched_dois={"10.5281/zenodo.111", "10.5281/zenodo.222"},
        )
        assert missing == set()

    def test_returns_missing_dois(self) -> None:
        missing = verify_dois_present(
            expected_dois={"10.5281/zenodo.111", "10.5281/zenodo.999"},
            fetched_dois={"10.5281/zenodo.111"},
        )
        assert missing == {"10.5281/zenodo.999"}

    def test_extra_fetched_dois_ignored(self) -> None:
        missing = verify_dois_present(
            expected_dois={"10.5281/zenodo.111"},
            fetched_dois={"10.5281/zenodo.111", "10.5281/zenodo.extra"},
        )
        assert missing == set()

    def test_normalises_doi_case_insensitive(self) -> None:
        missing = verify_dois_present(
            expected_dois={"10.5281/Zenodo.111"},
            fetched_dois={"10.5281/zenodo.111"},
        )
        assert missing == set()
