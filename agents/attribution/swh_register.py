"""Software Heritage SWHID registration + ISO/IEC 18670:2025 archival.

Per cc-task ``leverage-attrib-swh-swhid-bibtex``. Software Heritage
provides ISO-standardized persistent identifiers (SWHIDs) for every
Git repository it archives. Citation crawlers (Semantic Scholar,
OpenAlex, Crossref) reach SWH; this propagates Hapax's repos into
the academic citation graph.

Critical property: SWH archive trigger is **unauthenticated**. No
operator credentials required. POST to the save-origin endpoint
queues the repository; SWH crawls within minutes-to-hours; the
SWHID becomes resolvable once the visit completes.

API surface:

- POST ``/api/1/origin/save/git/url/<encoded_url>/`` — queue archive
- GET ``/api/1/origin/save/git/url/<encoded_url>/`` — poll status
- GET ``/api/1/origin/<encoded_url>/`` — resolve to SWHID once visited

Reference: https://archive.softwareheritage.org/api/

Constitutional fit:
- Full-automation: no operator credentials; daemon-side trigger only
- Single-operator: repos are operator-owned via single GitHub account
- Refusal-as-data: any repo SWH refuses to archive (private, deleted)
  is logged to the refusal-brief annex
- Anti-anthropomorphization: SWHID is a structured identifier, not
  prose
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import quote

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

SWH_API_BASE: str = "https://archive.softwareheritage.org/api/1"
"""Software Heritage API root. ISO/IEC 18670:2025 standardized;
mirrored at multiple institutions for citation permanence."""

SWH_REQUEST_TIMEOUT_S: float = 30.0
"""Timeout for SWH API requests. Save-origin trigger is fast (queue);
poll/resolve may include archival lookup latency."""


class VisitStatus(Enum):
    """SWH save-request lifecycle states.

    Mirrors the values returned by the SWH save-origin API. ``QUEUED``
    is the default state immediately after registration; ``ONGOING``
    while the crawler is running; ``FAILED`` on persistent error;
    ``DONE`` (or ``FULL``/``PARTIAL``) once the visit completes and
    the SWHID is resolvable.
    """

    QUEUED = "queued"
    ONGOING = "ongoing"
    DONE = "done"
    FULL = "full"
    PARTIAL = "partial"
    FAILED = "failed"
    PENDING = "pending"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class SaveResult:
    """One save-request outcome.

    ``request_id`` is the SWH-issued identifier for the save request;
    ``visit_status`` reflects the current visit state; ``swhid`` is
    populated once the visit reaches ``DONE``/``FULL``/``PARTIAL`` and
    SWH resolves the snapshot identifier.
    """

    repo_url: str
    request_id: int | None = None
    visit_status: VisitStatus | None = None
    swhid: str | None = None
    error: str | None = None


def _encode_repo_url(repo_url: str) -> str:
    """URL-encode a Git repo URL for the SWH save-origin path.

    SWH expects the URL as a path segment with full URL-encoding
    (including the scheme and ``://`` separator). The ``:`` and ``/``
    in ``https://github.com/...`` must be escaped per RFC 3986.
    """
    return quote(repo_url, safe="")


def trigger_save(
    repo_url: str,
    *,
    api_base: str = SWH_API_BASE,
    timeout_s: float = SWH_REQUEST_TIMEOUT_S,
) -> SaveResult:
    """POST to SWH to queue a save request for ``repo_url``.

    Returns a :class:`SaveResult` with the initial visit status (most
    commonly ``QUEUED``). Does not poll or wait; callers wanting the
    SWHID call :func:`poll_visit` until the status is terminal.

    No authentication required; the SWH save-origin endpoint is open
    to anonymous POST.
    """
    if requests is None:
        return SaveResult(repo_url=repo_url, error="requests library not available")

    encoded = _encode_repo_url(repo_url)
    url = f"{api_base}/origin/save/git/url/{encoded}/"
    try:
        response = requests.post(url, timeout=timeout_s)
    except requests.RequestException as exc:
        log.warning("swh save trigger raised: %s", exc)
        return SaveResult(repo_url=repo_url, error=f"transport failure: {exc}")

    if response.status_code in (200, 201):
        data = response.json()
        return _parse_save_response(repo_url, data)
    if response.status_code == 403:
        return SaveResult(
            repo_url=repo_url,
            error=f"swh refused (403): {response.text[:200]}",
            visit_status=VisitStatus.FAILED,
        )
    return SaveResult(
        repo_url=repo_url,
        error=f"swh save HTTP {response.status_code}: {response.text[:200]}",
    )


def poll_visit(
    repo_url: str,
    *,
    api_base: str = SWH_API_BASE,
    timeout_s: float = SWH_REQUEST_TIMEOUT_S,
) -> SaveResult:
    """GET the latest save-request status for ``repo_url``.

    Returns the current visit status. Callers poll periodically (~5
    min cadence is appropriate; SWH crawls take minutes-to-hours)
    until ``visit_status`` is in ``{DONE, FULL, PARTIAL, FAILED}``.
    """
    if requests is None:
        return SaveResult(repo_url=repo_url, error="requests library not available")

    encoded = _encode_repo_url(repo_url)
    url = f"{api_base}/origin/save/git/url/{encoded}/"
    try:
        response = requests.get(url, timeout=timeout_s)
    except requests.RequestException as exc:
        log.warning("swh poll raised: %s", exc)
        return SaveResult(repo_url=repo_url, error=f"transport failure: {exc}")

    if response.status_code == 200:
        data = response.json()
        # The endpoint returns a list of save requests; take the most
        # recent one (or the only one for newly-registered repos).
        if isinstance(data, list):
            if data:
                return _parse_save_response(repo_url, data[-1])
            return SaveResult(
                repo_url=repo_url,
                error="swh poll returned no save-request entries",
                visit_status=VisitStatus.NOT_FOUND,
            )
        if isinstance(data, dict):
            return _parse_save_response(repo_url, data)
        return SaveResult(
            repo_url=repo_url,
            error="swh poll returned unexpected payload type",
            visit_status=VisitStatus.NOT_FOUND,
        )
    if response.status_code == 404:
        return SaveResult(
            repo_url=repo_url,
            visit_status=VisitStatus.NOT_FOUND,
            error="no save request registered yet (call trigger_save first)",
        )
    return SaveResult(
        repo_url=repo_url,
        error=f"swh poll HTTP {response.status_code}: {response.text[:200]}",
    )


def resolve_swhid(
    repo_url: str,
    *,
    api_base: str = SWH_API_BASE,
    timeout_s: float = SWH_REQUEST_TIMEOUT_S,
) -> SaveResult:
    """Resolve the SWHID for ``repo_url`` once SWH has completed the visit.

    Returns ``SaveResult(swhid=...)`` when the snapshot is resolvable;
    returns the current visit status when not yet ready.

    The resolved SWHID has the form
    ``swh:1:snp:<40-hex-char-snapshot-id>`` and is the citation-stable
    identifier propagated to academic crawlers.
    """
    if requests is None:
        return SaveResult(repo_url=repo_url, error="requests library not available")

    encoded = _encode_repo_url(repo_url)
    url = f"{api_base}/origin/{encoded}/visits/latest/"
    try:
        response = requests.get(url, timeout=timeout_s)
    except requests.RequestException as exc:
        log.warning("swh resolve raised: %s", exc)
        return SaveResult(repo_url=repo_url, error=f"transport failure: {exc}")

    if response.status_code == 200:
        data = response.json()
        snapshot = data.get("snapshot")
        if snapshot:
            return SaveResult(
                repo_url=repo_url,
                visit_status=VisitStatus.DONE,
                swhid=f"swh:1:snp:{snapshot}",
            )
        return SaveResult(
            repo_url=repo_url,
            visit_status=VisitStatus.ONGOING,
            error="visit completed but no snapshot returned",
        )
    if response.status_code == 404:
        return SaveResult(
            repo_url=repo_url,
            visit_status=VisitStatus.NOT_FOUND,
            error="origin not yet visited; call trigger_save + poll_visit",
        )
    return SaveResult(
        repo_url=repo_url,
        error=f"swh resolve HTTP {response.status_code}: {response.text[:200]}",
    )


def _parse_save_response(repo_url: str, data: dict[str, Any]) -> SaveResult:
    """Parse one SWH save-request entry into a :class:`SaveResult`.

    The save-origin endpoint returns one of two shapes — a single
    request object on POST, a list on GET. This helper consumes
    either after the caller unwraps to the single-entry view.
    """
    request_id = data.get("id")
    if not isinstance(request_id, int):
        request_id = None

    raw_status = data.get("save_task_status") or data.get("visit_status") or ""
    status: VisitStatus | None
    try:
        status = VisitStatus(raw_status) if raw_status else None
    except ValueError:
        status = None

    return SaveResult(
        repo_url=repo_url,
        request_id=request_id,
        visit_status=status,
    )


__all__ = [
    "SWH_API_BASE",
    "SWH_REQUEST_TIMEOUT_S",
    "SaveResult",
    "VisitStatus",
    "poll_visit",
    "resolve_swhid",
    "trigger_save",
]
