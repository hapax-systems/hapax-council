"""Tests for ``agents.attribution.datacite_graphql_snapshot``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.attribution.datacite_graphql_snapshot import (
    DATACITE_GRAPHQL_ENDPOINT,
    DEFAULT_SNAPSHOT_DIR,
    extract_citation_count,
    query_doi_citation_graph,
    snapshot_attribution_graph,
)


def _mock_response(status_code: int, json_data=None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.json = MagicMock(return_value={} if json_data is None else json_data)
    return response


_DOI_RESPONSE = {
    "data": {
        "doi": {
            "id": "10.5281/zenodo.111",
            "doi": "10.5281/zenodo.111",
            "citationCount": 7,
            "relatedIdentifiers": [
                {"relatedIdentifier": "10.5281/zenodo.222", "relationType": "IsCitedBy"},
            ],
            "citations": {
                "totalCount": 7,
                "nodes": [{"id": "doi:10.5281/zenodo.333"}],
            },
        }
    }
}


class TestQueryDoiCitationGraph:
    @patch("agents.attribution.datacite_graphql_snapshot.requests")
    def test_200_returns_response_body(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(200, _DOI_RESPONSE)
        result = query_doi_citation_graph("10.5281/zenodo.111")
        assert result is not None
        assert result["data"]["doi"]["citationCount"] == 7

    @patch("agents.attribution.datacite_graphql_snapshot.requests")
    def test_5xx_returns_none(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(503)
        assert query_doi_citation_graph("10.5281/zenodo.111") is None

    @patch("agents.attribution.datacite_graphql_snapshot.requests")
    def test_request_exception_returns_none(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.post.side_effect = _requests_lib.RequestException("offline")
        mock_requests.RequestException = _requests_lib.RequestException
        assert query_doi_citation_graph("10.5281/zenodo.111") is None

    @patch("agents.attribution.datacite_graphql_snapshot.requests")
    def test_endpoint_is_datacite_graphql(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(200, _DOI_RESPONSE)
        query_doi_citation_graph("10.5281/zenodo.111")
        url = mock_requests.post.call_args[0][0]
        assert url == DATACITE_GRAPHQL_ENDPOINT


class TestExtractCitationCount:
    def test_returns_count_from_doi_response(self) -> None:
        assert extract_citation_count(_DOI_RESPONSE) == 7

    def test_missing_doi_returns_zero(self) -> None:
        assert extract_citation_count({"data": {}}) == 0

    def test_no_data_returns_zero(self) -> None:
        assert extract_citation_count({}) == 0

    def test_handles_malformed_payload(self) -> None:
        assert extract_citation_count({"data": "not-a-dict"}) == 0


class TestSnapshotAttributionGraph:
    @patch("agents.attribution.datacite_graphql_snapshot.query_doi_citation_graph")
    def test_writes_snapshot_to_iso_date_file(
        self,
        mock_query: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_query.return_value = _DOI_RESPONSE
        path = snapshot_attribution_graph(
            dois=["10.5281/zenodo.111"],
            swhids=[],
            orcids=[],
            snapshot_dir=tmp_path,
            now=datetime(2026, 4, 26, tzinfo=UTC),
        )
        assert path is not None
        assert "2026-04-26" in path.name
        loaded = json.loads(path.read_text())
        assert "dois" in loaded
        assert loaded["dois"]["10.5281/zenodo.111"]["data"]["doi"]["citationCount"] == 7

    @patch("agents.attribution.datacite_graphql_snapshot.query_doi_citation_graph")
    def test_skips_failed_queries(
        self,
        mock_query: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_query.side_effect = [None, _DOI_RESPONSE]
        path = snapshot_attribution_graph(
            dois=["10.5281/zenodo.bad", "10.5281/zenodo.111"],
            swhids=[],
            orcids=[],
            snapshot_dir=tmp_path,
        )
        loaded = json.loads(path.read_text())
        # Failed query is omitted from snapshot
        assert "10.5281/zenodo.bad" not in loaded["dois"]
        assert "10.5281/zenodo.111" in loaded["dois"]

    def test_default_snapshot_dir_under_hapax_state(self) -> None:
        assert "hapax-state" in DEFAULT_SNAPSHOT_DIR.parts
        assert "attribution" in DEFAULT_SNAPSHOT_DIR.parts

    @patch("agents.attribution.datacite_graphql_snapshot.query_doi_citation_graph")
    def test_empty_inputs_writes_empty_snapshot(
        self,
        mock_query: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = snapshot_attribution_graph(dois=[], swhids=[], orcids=[], snapshot_dir=tmp_path)
        loaded = json.loads(path.read_text())
        assert loaded["dois"] == {}
        assert "snapshot_at" in loaded
