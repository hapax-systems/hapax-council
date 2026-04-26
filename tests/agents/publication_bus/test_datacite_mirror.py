"""Tests for ``agents.publication_bus.datacite_mirror`` GraphQL daemon."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.publication_bus.datacite_mirror import (
    DATACITE_GRAPHQL_ENDPOINT,
    compute_diff,
    fetch_orcid_works,
    mirror_works,
)


def _mock_response(status_code: int, json_data=None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.json = MagicMock(return_value={} if json_data is None else json_data)
    return response


_SAMPLE_RESPONSE = {
    "data": {
        "person": {
            "id": "https://orcid.org/0000-0001-2345-6789",
            "works": {
                "totalCount": 2,
                "nodes": [
                    {
                        "id": "doi:10.5281/zenodo.111",
                        "doi": "10.5281/zenodo.111",
                        "relatedIdentifiers": [
                            {
                                "relatedIdentifier": "10.5281/zenodo.999",
                                "relationType": "IsCitedBy",
                            }
                        ],
                        "citations": {"totalCount": 3},
                    },
                    {
                        "id": "doi:10.5281/zenodo.222",
                        "doi": "10.5281/zenodo.222",
                        "relatedIdentifiers": [],
                        "citations": {"totalCount": 0},
                    },
                ],
            },
        }
    }
}


class TestFetchOrcidWorks:
    @patch("agents.publication_bus.datacite_mirror.requests")
    def test_200_returns_response_body(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(200, _SAMPLE_RESPONSE)
        result = fetch_orcid_works("0000-0001-2345-6789")
        assert result is not None
        assert result["data"]["person"]["works"]["totalCount"] == 2

    @patch("agents.publication_bus.datacite_mirror.requests")
    def test_5xx_returns_none(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(503, text="boom")
        result = fetch_orcid_works("0000-0001-2345-6789")
        assert result is None

    @patch("agents.publication_bus.datacite_mirror.requests")
    def test_request_exception_returns_none(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.post.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        result = fetch_orcid_works("0000-0001-2345-6789")
        assert result is None

    @patch("agents.publication_bus.datacite_mirror.requests")
    def test_endpoint_is_datacite_graphql(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(200, _SAMPLE_RESPONSE)
        fetch_orcid_works("0000-0001-2345-6789")
        url = mock_requests.post.call_args[0][0]
        assert url == DATACITE_GRAPHQL_ENDPOINT


class TestMirrorWorks:
    @patch("agents.publication_bus.datacite_mirror.fetch_orcid_works")
    def test_writes_response_to_mirror_dir(
        self,
        mock_fetch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_fetch.return_value = _SAMPLE_RESPONSE
        path = mirror_works(
            orcid_id="0000-0001-2345-6789",
            mirror_dir=tmp_path,
            now=datetime(2026, 4, 26, 4, 0, tzinfo=UTC),
        )
        assert path is not None
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["data"]["person"]["works"]["totalCount"] == 2

    @patch("agents.publication_bus.datacite_mirror.fetch_orcid_works")
    def test_filename_is_iso_date(
        self,
        mock_fetch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_fetch.return_value = _SAMPLE_RESPONSE
        path = mirror_works(
            orcid_id="0000-0001-2345-6789",
            mirror_dir=tmp_path,
            now=datetime(2026, 4, 26, 4, 0, tzinfo=UTC),
        )
        assert "2026-04-26" in path.name
        assert path.suffix == ".json"

    @patch("agents.publication_bus.datacite_mirror.fetch_orcid_works")
    def test_returns_none_when_fetch_fails(
        self,
        mock_fetch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_fetch.return_value = None
        path = mirror_works(orcid_id="0000-0001-2345-6789", mirror_dir=tmp_path)
        assert path is None

    @patch("agents.publication_bus.datacite_mirror.fetch_orcid_works")
    def test_creates_mirror_dir(
        self,
        mock_fetch: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_fetch.return_value = _SAMPLE_RESPONSE
        target = tmp_path / "deep" / "mirror"
        path = mirror_works(orcid_id="0000-0001-2345-6789", mirror_dir=target)
        assert path is not None
        assert path.exists()


class TestComputeDiff:
    def test_added_dois(self, tmp_path: Path) -> None:
        prev = {"data": {"person": {"works": {"nodes": [{"doi": "10.x/1"}]}}}}
        curr = {
            "data": {
                "person": {
                    "works": {
                        "nodes": [
                            {"doi": "10.x/1"},
                            {"doi": "10.x/2"},
                        ]
                    }
                }
            }
        }
        diff = compute_diff(prev, curr)
        assert diff["added_dois"] == {"10.x/2"}
        assert diff["removed_dois"] == set()

    def test_removed_dois(self) -> None:
        prev = {
            "data": {
                "person": {
                    "works": {
                        "nodes": [
                            {"doi": "10.x/1"},
                            {"doi": "10.x/2"},
                        ]
                    }
                }
            }
        }
        curr = {"data": {"person": {"works": {"nodes": [{"doi": "10.x/1"}]}}}}
        diff = compute_diff(prev, curr)
        assert diff["removed_dois"] == {"10.x/2"}
        assert diff["added_dois"] == set()

    def test_no_change_returns_empty_diff(self) -> None:
        snap = {"data": {"person": {"works": {"nodes": [{"doi": "10.x/1"}]}}}}
        diff = compute_diff(snap, snap)
        assert diff["added_dois"] == set()
        assert diff["removed_dois"] == set()

    def test_handles_missing_data_blocks(self) -> None:
        diff = compute_diff({}, {"data": {"person": None}})
        assert diff["added_dois"] == set()
        assert diff["removed_dois"] == set()

    def test_citation_count_change(self) -> None:
        prev = {
            "data": {
                "person": {
                    "works": {
                        "nodes": [
                            {"doi": "10.x/1", "citations": {"totalCount": 1}},
                        ]
                    }
                }
            }
        }
        curr = {
            "data": {
                "person": {
                    "works": {
                        "nodes": [
                            {"doi": "10.x/1", "citations": {"totalCount": 5}},
                        ]
                    }
                }
            }
        }
        diff = compute_diff(prev, curr)
        assert diff["citation_count_delta"]["10.x/1"] == 4
