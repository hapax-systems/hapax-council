"""Zenodo repository-snapshot deposit helper.

This module is intentionally narrower than ``publisher.py``: it mints a
software DOI for the repository itself, uploads a prepared source snapshot,
and publishes the deposit. It exists for launch/archive work where the DOI
must be known before the snapshot is uploaded so README and CITATION metadata
can be included in the archived tree.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from agents.zenodo_publisher.publisher import (
    REQUEST_TIMEOUT_S,
    ZENODO_API_BASE_DEFAULT,
    ZENODO_API_BASE_ENV,
    ZENODO_TOKEN_ENV,
)

log = logging.getLogger(__name__)

DEFAULT_REPOSITORY_LICENSE = "other-closed"
"""Zenodo vocabulary ID used when the repository license is source-available
rather than OSI-open. The canonical repo license remains CITATION.cff/LICENSE.
"""


@dataclass(frozen=True)
class ZenodoDraftDeposit:
    """Unpublished Zenodo deposit with a reserved DOI."""

    deposition_id: int
    doi: str
    bucket_url: str
    html_url: str | None = None


@dataclass(frozen=True)
class ZenodoPublishedDeposit:
    """Published Zenodo deposit result."""

    deposition_id: int
    doi: str
    concept_doi: str | None
    record_url: str | None = None


class ZenodoRepositoryDepositError(RuntimeError):
    """Repository-snapshot deposit failed before publish completed."""


def load_repository_metadata(metadata_path: Path, *, publication_date: str | None = None) -> dict:
    """Load ``.zenodo.json`` and fill fields required by Zenodo software deposits."""
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ZenodoRepositoryDepositError(f"cannot load Zenodo metadata: {exc}") from exc
    if not isinstance(raw, dict):
        raise ZenodoRepositoryDepositError("Zenodo metadata root must be a JSON object")
    return build_repository_metadata(raw, publication_date=publication_date)


def build_repository_metadata(
    base: dict[str, Any], *, publication_date: str | None = None
) -> dict[str, Any]:
    """Return a Zenodo metadata block for a repository software snapshot."""
    metadata = dict(base)
    metadata.pop("doi", None)
    metadata.pop("conceptdoi", None)
    metadata.setdefault("upload_type", "software")
    metadata.setdefault(
        "publication_date", publication_date or datetime.now(UTC).strftime("%Y-%m-%d")
    )
    metadata.setdefault("access_right", "open")
    metadata.setdefault("license", DEFAULT_REPOSITORY_LICENSE)
    metadata.setdefault(
        "notes",
        (
            "Repository license: PolyForm Strict 1.0.0 "
            "(https://polyformproject.org/licenses/strict/1.0.0)."
        ),
    )
    metadata["prereserve_doi"] = True
    _validate_required_metadata(metadata)
    return metadata


def reserve_repository_doi(
    metadata: dict[str, Any],
    *,
    token: str,
    api_base: str = ZENODO_API_BASE_DEFAULT,
) -> ZenodoDraftDeposit:
    """Create an unpublished deposit and reserve its DOI."""
    response = _post_json(
        f"{api_base}/deposit/depositions",
        token=token,
        json_payload={"metadata": metadata},
        action="reserve repository DOI",
    )
    if response.status_code != 201:
        _raise_response_error(response, "reserve repository DOI")
    body = _response_json(response, "reserve repository DOI")
    draft = _parse_draft(body)
    if not draft.doi:
        raise ZenodoRepositoryDepositError("Zenodo reserve response did not include a DOI")
    if not draft.bucket_url:
        raise ZenodoRepositoryDepositError("Zenodo reserve response did not include a bucket URL")
    log.info("Zenodo repository DOI reserved (deposition_id=%d)", draft.deposition_id)
    return draft


def upload_repository_snapshot(
    draft: ZenodoDraftDeposit,
    snapshot_path: Path,
    *,
    token: str,
    filename: str | None = None,
) -> None:
    """Upload a source snapshot file into a draft deposit's bucket."""
    if not snapshot_path.is_file():
        raise ZenodoRepositoryDepositError(f"snapshot file not found: {snapshot_path}")
    upload_name = filename or snapshot_path.name
    upload_url = f"{draft.bucket_url.rstrip('/')}/{quote(upload_name)}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }
    try:
        with snapshot_path.open("rb") as fh:
            response = httpx.put(
                upload_url,
                content=fh,
                headers=headers,
                timeout=REQUEST_TIMEOUT_S,
            )
    except (OSError, httpx.RequestError) as exc:
        raise ZenodoRepositoryDepositError(f"upload repository snapshot failed: {exc}") from exc
    if response.status_code not in (200, 201):
        _raise_response_error(response, "upload repository snapshot")
    log.info("Zenodo repository snapshot uploaded to deposition_id=%d", draft.deposition_id)


def publish_repository_deposit(
    draft: ZenodoDraftDeposit,
    *,
    token: str,
    api_base: str = ZENODO_API_BASE_DEFAULT,
) -> ZenodoPublishedDeposit:
    """Publish a draft repository deposit and return its DOI metadata."""
    response = _post_json(
        f"{api_base}/deposit/depositions/{draft.deposition_id}/actions/publish",
        token=token,
        json_payload=None,
        action="publish repository deposit",
    )
    if response.status_code != 202:
        _raise_response_error(response, "publish repository deposit")
    body = _response_json(response, "publish repository deposit")
    published = _parse_published(body, fallback_draft=draft)
    log.info("Zenodo repository DOI published (deposition_id=%d)", draft.deposition_id)
    return published


def doi_badge_markdown(doi: str) -> str:
    """Return the standard Zenodo DOI badge markdown for ``doi``."""
    return f"[![DOI](https://zenodo.org/badge/DOI/{doi}.svg)](https://doi.org/{doi})"


def token_from_env() -> str:
    """Return the configured Zenodo token, or raise without revealing secrets."""
    import os

    token = os.environ.get(ZENODO_TOKEN_ENV, "").strip()
    if not token:
        raise ZenodoRepositoryDepositError(f"{ZENODO_TOKEN_ENV} is not set")
    return token


def api_base_from_env() -> str:
    """Return the configured Zenodo API base URL."""
    import os

    return os.environ.get(ZENODO_API_BASE_ENV, "").strip() or ZENODO_API_BASE_DEFAULT


def _validate_required_metadata(metadata: dict[str, Any]) -> None:
    required = ("title", "upload_type", "publication_date", "description", "creators")
    missing = [key for key in required if not metadata.get(key)]
    if missing:
        raise ZenodoRepositoryDepositError(
            "Zenodo metadata missing required field(s): " + ", ".join(missing)
        )


def _post_json(
    url: str,
    *,
    token: str,
    json_payload: dict[str, Any] | None,
    action: str,
) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        return httpx.post(
            url,
            json=json_payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT_S,
        )
    except httpx.RequestError as exc:
        raise ZenodoRepositoryDepositError(f"{action} transport failure: {exc}") from exc


def _parse_draft(body: dict[str, Any]) -> ZenodoDraftDeposit:
    deposition_id = _require_int(body.get("id"), "reserve response id")
    metadata = body.get("metadata")
    doi = ""
    if isinstance(metadata, dict):
        prereserve = metadata.get("prereserve_doi")
        if isinstance(prereserve, dict):
            doi = str(prereserve.get("doi") or "")
    doi = doi or str(body.get("doi") or "")
    links = body.get("links") if isinstance(body.get("links"), dict) else {}
    return ZenodoDraftDeposit(
        deposition_id=deposition_id,
        doi=doi,
        bucket_url=str(links.get("bucket") or ""),
        html_url=str(links.get("html") or "") or None,
    )


def _parse_published(
    body: dict[str, Any], *, fallback_draft: ZenodoDraftDeposit
) -> ZenodoPublishedDeposit:
    deposition_id = _require_int(
        body.get("id", fallback_draft.deposition_id), "publish response id"
    )
    doi = str(body.get("doi") or fallback_draft.doi)
    concept_doi = str(body.get("conceptdoi") or "") or None
    links = body.get("links") if isinstance(body.get("links"), dict) else {}
    record_url = str(links.get("record") or links.get("html") or "") or None
    return ZenodoPublishedDeposit(
        deposition_id=deposition_id,
        doi=doi,
        concept_doi=concept_doi,
        record_url=record_url,
    )


def _response_json(response: httpx.Response, action: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise ZenodoRepositoryDepositError(f"{action} returned non-JSON response") from exc
    if not isinstance(body, dict):
        raise ZenodoRepositoryDepositError(f"{action} returned unexpected JSON shape")
    return body


def _require_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int):
        raise ZenodoRepositoryDepositError(f"Zenodo {field_name} was not an integer")
    return value


def _raise_response_error(response: httpx.Response, action: str) -> None:
    body = response.text[:500]
    raise ZenodoRepositoryDepositError(f"{action} failed with HTTP {response.status_code}: {body}")


__all__ = [
    "DEFAULT_REPOSITORY_LICENSE",
    "ZenodoDraftDeposit",
    "ZenodoPublishedDeposit",
    "ZenodoRepositoryDepositError",
    "api_base_from_env",
    "build_repository_metadata",
    "doi_badge_markdown",
    "load_repository_metadata",
    "publish_repository_deposit",
    "reserve_repository_doi",
    "token_from_env",
    "upload_repository_snapshot",
]
