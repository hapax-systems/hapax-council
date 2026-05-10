"""Tests for Zenodo repository-snapshot deposits."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import httpx
import pytest

from agents.zenodo_publisher.repository_snapshot import (
    DEFAULT_REPOSITORY_LICENSE,
    ZenodoDraftDeposit,
    ZenodoRepositoryDepositError,
    build_repository_metadata,
    doi_badge_markdown,
    publish_repository_deposit,
    reserve_repository_doi,
    upload_repository_snapshot,
)


def _make_response(status_code: int, json_body: dict | None = None, text: str = "") -> mock.Mock:
    resp = mock.Mock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or (str(json_body) if json_body else "")
    if json_body is not None:
        resp.json = mock.Mock(return_value=json_body)
    else:
        resp.json = mock.Mock(side_effect=ValueError("no json"))
    return resp


def _base_metadata() -> dict:
    return {
        "title": "hapax-council",
        "description": "Research infrastructure published as artifact.",
        "creators": [{"name": "Kleeberger, Ryan", "orcid": "0009-0001-5146-4548"}],
        "keywords": ["research-software"],
    }


def test_build_repository_metadata_sets_software_defaults() -> None:
    base = _base_metadata() | {
        "doi": "10.5281/zenodo.existing",
        "conceptdoi": "10.5281/zenodo.concept",
    }
    metadata = build_repository_metadata(base, publication_date="2026-05-10")

    assert metadata["upload_type"] == "software"
    assert metadata["publication_date"] == "2026-05-10"
    assert metadata["access_right"] == "open"
    assert metadata["license"] == DEFAULT_REPOSITORY_LICENSE
    assert metadata["prereserve_doi"] is True
    assert "doi" not in metadata
    assert "conceptdoi" not in metadata
    assert "PolyForm Strict" in metadata["notes"]


def test_build_repository_metadata_requires_core_fields() -> None:
    with pytest.raises(ZenodoRepositoryDepositError, match="description"):
        build_repository_metadata({"title": "x", "creators": [{"name": "n"}]})


def test_reserve_repository_doi_posts_prereserve_metadata() -> None:
    create_resp = _make_response(
        201,
        {
            "id": 123,
            "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.123"}},
            "links": {
                "bucket": "https://zenodo.org/api/files/bucket-id",
                "html": "https://zenodo.org/deposit/123",
            },
        },
    )
    metadata = build_repository_metadata(_base_metadata(), publication_date="2026-05-10")

    with mock.patch(
        "agents.zenodo_publisher.repository_snapshot.httpx.post",
        return_value=create_resp,
    ) as post_mock:
        draft = reserve_repository_doi(metadata, token="test-token")

    assert draft.deposition_id == 123
    assert draft.doi == "10.5281/zenodo.123"
    assert draft.bucket_url == "https://zenodo.org/api/files/bucket-id"
    post_mock.assert_called_once()
    sent = post_mock.call_args.kwargs["json"]
    assert sent["metadata"]["prereserve_doi"] is True
    assert post_mock.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"


def test_upload_repository_snapshot_puts_zip_to_bucket(tmp_path: Path) -> None:
    snapshot = tmp_path / "hapax-council.zip"
    snapshot.write_bytes(b"zip bytes")
    draft = ZenodoDraftDeposit(
        deposition_id=123,
        doi="10.5281/zenodo.123",
        bucket_url="https://zenodo.org/api/files/bucket-id",
    )
    upload_resp = _make_response(201, {"key": "hapax-council.zip"})

    with mock.patch(
        "agents.zenodo_publisher.repository_snapshot.httpx.put",
        return_value=upload_resp,
    ) as put_mock:
        upload_repository_snapshot(draft, snapshot, token="test-token")

    assert put_mock.call_args.args[0] == "https://zenodo.org/api/files/bucket-id/hapax-council.zip"
    assert put_mock.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"
    assert put_mock.call_args.kwargs["headers"]["Content-Type"] == "application/octet-stream"


def test_publish_repository_deposit_returns_doi() -> None:
    draft = ZenodoDraftDeposit(
        deposition_id=123,
        doi="10.5281/zenodo.123",
        bucket_url="https://zenodo.org/api/files/bucket-id",
    )
    publish_resp = _make_response(
        202,
        {
            "id": 123,
            "doi": "10.5281/zenodo.123",
            "conceptdoi": "10.5281/zenodo.122",
            "links": {"record": "https://zenodo.org/records/123"},
        },
    )

    with mock.patch(
        "agents.zenodo_publisher.repository_snapshot.httpx.post",
        return_value=publish_resp,
    ) as post_mock:
        published = publish_repository_deposit(draft, token="test-token")

    assert published.doi == "10.5281/zenodo.123"
    assert published.concept_doi == "10.5281/zenodo.122"
    assert published.record_url == "https://zenodo.org/records/123"
    assert post_mock.call_args.args[0].endswith("/deposit/depositions/123/actions/publish")


def test_doi_badge_markdown() -> None:
    assert doi_badge_markdown("10.5281/zenodo.123") == (
        "[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.123.svg)]"
        "(https://doi.org/10.5281/zenodo.123)"
    )
