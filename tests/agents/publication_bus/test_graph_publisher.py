"""Tests for ``agents.publication_bus.graph_publisher`` — Phase 2 minting."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agents.publication_bus.graph_publisher import (
    GRAPH_PUBLISHER_SURFACE,
    GraphPublisher,
    GraphPublisherError,
    mint_or_version,
    persist_graph_state,
)
from agents.publication_bus.publisher_kit import PublisherPayload

# === GraphPublisher class shape ===


def test_graph_publisher_surface_name():
    assert GraphPublisher.surface_name == "datacite-graphql-mirror"


def test_graph_publisher_requires_legal_name():
    # Zenodo creators array uses formal legal name
    assert GraphPublisher.requires_legal_name is True


def test_graph_publisher_allowlist_present():
    assert GraphPublisher.allowlist is not None


# === GraphPublisher._emit ===


def test_emit_refused_without_token(tmp_path: Path):
    pub = GraphPublisher(zenodo_token="", graph_dir=tmp_path)
    payload = PublisherPayload(
        target=GRAPH_PUBLISHER_SURFACE,
        text="snapshot description",
        metadata={"snapshot_path": str(tmp_path / "snap.json"), "fingerprint": "abc"},
    )
    result = pub._emit(payload)
    assert result.refused is True
    assert "Zenodo" in result.detail


def test_emit_ok_returns_dois_in_detail(tmp_path: Path):
    pub = GraphPublisher(zenodo_token="ztk", graph_dir=tmp_path)
    payload = PublisherPayload(
        target=GRAPH_PUBLISHER_SURFACE,
        text="snapshot description",
        metadata={
            "snapshot_path": str(tmp_path / "snap.json"),
            "fingerprint": "abc",
            "deposit_metadata": {"title": "Hapax constellation graph"},
        },
    )
    with patch(
        "agents.publication_bus.graph_publisher.mint_or_version",
        return_value=("10.x/concept", "10.x/v1", 100),
    ):
        result = pub._emit(payload)
    assert result.ok is True
    assert "10.x/concept" in result.detail
    assert "10.x/v1" in result.detail


def test_emit_returns_error_on_publisher_error(tmp_path: Path):
    pub = GraphPublisher(zenodo_token="ztk", graph_dir=tmp_path)
    payload = PublisherPayload(
        target=GRAPH_PUBLISHER_SURFACE,
        text="snapshot description",
        metadata={
            "snapshot_path": str(tmp_path / "snap.json"),
            "fingerprint": "abc",
        },
    )
    with patch(
        "agents.publication_bus.graph_publisher.mint_or_version",
        side_effect=GraphPublisherError("transport failure"),
    ):
        result = pub._emit(payload)
    assert result.error is True
    assert "transport failure" in result.detail


# === mint_or_version: first version path ===


def test_mint_or_version_first_call_creates_and_publishes(tmp_path: Path):
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")

    create_resp = Mock(status_code=201)
    create_resp.json.return_value = {"id": 100, "doi": "10.5281/zenodo.100"}
    publish_resp = Mock(status_code=202)
    publish_resp.json.return_value = {
        "id": 100,
        "doi": "10.5281/zenodo.100",
        "conceptdoi": "10.5281/zenodo.99",
    }

    with patch("agents.publication_bus.graph_publisher.requests") as mock_requests:
        mock_requests.post.side_effect = [create_resp, publish_resp]
        mock_requests.RequestException = Exception
        concept_doi, version_doi, deposit_id = mint_or_version(
            zenodo_token="ztk",
            graph_dir=tmp_path / "graph",
            snapshot_path=snapshot,
            fingerprint="fp1",
            metadata={"title": "graph"},
        )

    assert concept_doi == "10.5281/zenodo.99"
    assert version_doi == "10.5281/zenodo.100"
    assert deposit_id == 100
    # Two POSTs: deposit creation, then publish
    assert mock_requests.post.call_count == 2


def test_mint_or_version_first_call_no_concept_doi_in_response_uses_top_level(
    tmp_path: Path,
):
    """Some Zenodo responses omit conceptdoi; fall back to the top-level doi."""
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")

    create_resp = Mock(status_code=201)
    create_resp.json.return_value = {"id": 200, "doi": "10.5281/zenodo.200"}
    publish_resp = Mock(status_code=202)
    publish_resp.json.return_value = {"id": 200, "doi": "10.5281/zenodo.200"}

    with patch("agents.publication_bus.graph_publisher.requests") as mock_requests:
        mock_requests.post.side_effect = [create_resp, publish_resp]
        mock_requests.RequestException = Exception
        concept_doi, version_doi, _ = mint_or_version(
            zenodo_token="ztk",
            graph_dir=tmp_path / "graph",
            snapshot_path=snapshot,
            fingerprint="fp1",
            metadata={"title": "graph"},
        )

    # When conceptdoi missing, fall back to top-level doi (single-version concept)
    assert concept_doi == "10.5281/zenodo.200"
    assert version_doi == "10.5281/zenodo.200"


# === mint_or_version: new version path ===


def test_mint_or_version_uses_newversion_endpoint_when_state_present(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    (graph_dir / "concept-doi.txt").write_text("10.5281/zenodo.99\n", encoding="utf-8")
    (graph_dir / "last-deposit-id.txt").write_text("100\n", encoding="utf-8")

    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")

    newver_resp = Mock(status_code=201)
    newver_resp.json.return_value = {
        "id": 101,
        "doi": "10.5281/zenodo.101",
        "conceptdoi": "10.5281/zenodo.99",
    }
    put_resp = Mock(status_code=200)
    put_resp.json.return_value = {"id": 101}
    publish_resp = Mock(status_code=202)
    publish_resp.json.return_value = {
        "id": 101,
        "doi": "10.5281/zenodo.101",
        "conceptdoi": "10.5281/zenodo.99",
    }

    with patch("agents.publication_bus.graph_publisher.requests") as mock_requests:
        mock_requests.post.side_effect = [newver_resp, publish_resp]
        mock_requests.put.return_value = put_resp
        mock_requests.RequestException = Exception
        concept_doi, version_doi, deposit_id = mint_or_version(
            zenodo_token="ztk",
            graph_dir=graph_dir,
            snapshot_path=snapshot,
            fingerprint="fp2",
            metadata={"title": "graph v2"},
        )

    assert concept_doi == "10.5281/zenodo.99"
    assert version_doi == "10.5281/zenodo.101"
    assert deposit_id == 101
    # newversion POST + publish POST + metadata PUT
    assert mock_requests.post.call_count == 2
    assert mock_requests.put.call_count == 1


def test_mint_or_version_raises_on_transport_failure(tmp_path: Path):
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")

    class FakeReqExc(Exception):
        pass

    with patch("agents.publication_bus.graph_publisher.requests") as mock_requests:
        mock_requests.post.side_effect = FakeReqExc("connection refused")
        mock_requests.RequestException = FakeReqExc
        with pytest.raises(GraphPublisherError):
            mint_or_version(
                zenodo_token="ztk",
                graph_dir=tmp_path / "graph",
                snapshot_path=snapshot,
                fingerprint="fp1",
                metadata={"title": "graph"},
            )


def test_mint_or_version_raises_on_non_2xx_create(tmp_path: Path):
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")

    create_resp = Mock(status_code=403)
    create_resp.text = "forbidden"

    with patch("agents.publication_bus.graph_publisher.requests") as mock_requests:
        mock_requests.post.return_value = create_resp
        mock_requests.RequestException = Exception
        with pytest.raises(GraphPublisherError) as excinfo:
            mint_or_version(
                zenodo_token="ztk",
                graph_dir=tmp_path / "graph",
                snapshot_path=snapshot,
                fingerprint="fp1",
                metadata={"title": "graph"},
            )
    assert "403" in str(excinfo.value)


# === persist_graph_state ===


def test_persist_graph_state_writes_state_files(tmp_path: Path):
    persist_graph_state(
        graph_dir=tmp_path,
        concept_doi="10.x/concept",
        version_doi="10.x/v1",
        fingerprint="fp1",
        deposit_id=100,
    )
    assert (tmp_path / "concept-doi.txt").read_text().strip() == "10.x/concept"
    assert (tmp_path / "last-fingerprint.txt").read_text().strip() == "fp1"
    assert (tmp_path / "last-deposit-id.txt").read_text().strip() == "100"


def test_persist_graph_state_appends_history(tmp_path: Path):
    persist_graph_state(
        graph_dir=tmp_path,
        concept_doi="10.x/concept",
        version_doi="10.x/v1",
        fingerprint="fp1",
        deposit_id=100,
    )
    persist_graph_state(
        graph_dir=tmp_path,
        concept_doi="10.x/concept",
        version_doi="10.x/v2",
        fingerprint="fp2",
        deposit_id=101,
    )
    history = (tmp_path / "version-doi-history.jsonl").read_text().strip().splitlines()
    assert len(history) == 2
    entry1 = json.loads(history[0])
    entry2 = json.loads(history[1])
    assert entry1["version_doi"] == "10.x/v1"
    assert entry2["version_doi"] == "10.x/v2"
    assert entry1["fingerprint"] == "fp1"
    assert entry2["fingerprint"] == "fp2"
    assert entry1["deposit_id"] == 100
    assert entry2["deposit_id"] == 101


def test_persist_graph_state_creates_dir(tmp_path: Path):
    target = tmp_path / "subdir"
    persist_graph_state(
        graph_dir=target,
        concept_doi="x",
        version_doi="y",
        fingerprint="z",
        deposit_id=1,
    )
    assert target.is_dir()
    assert (target / "concept-doi.txt").is_file()
