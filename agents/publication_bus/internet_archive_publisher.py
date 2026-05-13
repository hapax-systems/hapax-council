"""Internet Archive ias3 (S3-compatible) Publisher.

Per cc-task ``pub-bus-internet-archive-ias3``. Auto-syndicate operator-
owned (oudepode) musical artefacts to Internet Archive's S3-compatible
endpoint. Per drop 5's analysis, IA `ias3` is the ONLY daemon-tractable
academic-credible music syndication path — Bandcamp/Discogs/RYM are all
REFUSED.

This module ships the Publisher ABC subclass with the V5 invariants
(allowlist gate + legal-name leak guard + canonical Counter) and a
minimal `requests`-based PUT against the S3 endpoint. The
``internetarchive`` Python lib is intentionally NOT a dependency —
the S3 endpoint is straightforward HTTP and adding the lib would
expand runtime surface unnecessarily for the daemon path.

Orchestrator dispatch path (was previously called part of "Phase 2")
has shipped: ``agents/internet_archive_ias3_adapter/`` is registered
in ``surface_registry`` as the ``publish_artifact`` entry-point for
``internet-archive-ias3``; the publish-orchestrator can dispatch a
``PreprintArtifact`` through the publisher via the standard surface
hand-off. The remaining (still-deferred) half is the music-publisher
daemon — ``agents/music_publisher/`` does NOT exist today; when it
ships it will scan the oudepode-mastered queue and feed PreprintArtifacts
into the publish-orchestrator. Until then, the publisher dispatches
whatever artifacts arrive through the existing orchestrator surface.

Endpoint: ``https://s3.us.archive.org/{item-id}/{filename}``
Authorization: ``LOW <access>:<secret>`` (IA's S3-compat header style)
"""

from __future__ import annotations

import logging
from typing import ClassVar

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

IA_S3_SURFACE: str = "internet-archive-ias3"
"""Stable surface identifier; mirrored in
:data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

IA_S3_ENDPOINT: str = "https://s3.us.archive.org"
"""Internet Archive S3-compatible upload endpoint root.
Items are addressed as ``{IA_S3_ENDPOINT}/{item-id}/{filename}``."""

IA_S3_REQUEST_TIMEOUT_S: float = 300.0
"""IA uploads can take time for larger audio files; 5-minute timeout
is generous but not unbounded."""

DEFAULT_IA_S3_ALLOWLIST: AllowlistGate = load_allowlist(
    IA_S3_SURFACE,
    permitted=[],
)
"""Empty default allowlist — operator-curated item-id permissions
added via class-level reassignment (matches BridgyPublisher convention)."""


class InternetArchiveS3Publisher(Publisher):
    """Publishes one item file to Internet Archive's S3-compatible endpoint.

    ``payload.target`` is the IA item ID (e.g., ``oudepode-track-2026-04``);
    ``payload.text`` is the file content (audio bytes encoded as a
    string for the V5 contract — Phase 2 may add a binary-payload variant).

    Refusal-as-data: missing operator credentials emit a ``refused``
    result with ``credentials`` in the detail string. The Phase 1
    daemon path is structurally complete; the operator-action queue
    item is the IA S3 keys via ``pass``.
    """

    surface_name: ClassVar[str] = IA_S3_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_IA_S3_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, access_key: str, secret_key: str) -> None:
        self.access_key = access_key
        self.secret_key = secret_key

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not (self.access_key and self.secret_key):
            return PublisherResult(
                refused=True,
                detail="missing IA S3 credentials (operator-action queue: pass insert ia/access-key + ia/secret-key)",
            )
        if requests is None:
            return PublisherResult(error=True, detail="requests library not available")

        # IA S3 supports a "single-file item" pattern where the item-id
        # is the URL path's first segment and the filename is implied by
        # metadata; for Phase 1 we use a single bucket path per target.
        url = f"{IA_S3_ENDPOINT}/{payload.target}/{payload.target}.dat"
        headers = {
            "Authorization": f"LOW {self.access_key}:{self.secret_key}",
            "Content-Type": "application/octet-stream",
        }

        data = getattr(payload, "binary", None)
        if data is None:
            data = payload.text.encode("utf-8") if payload.text else b""

        try:
            response = requests.put(
                url,
                data=data,
                headers=headers,
                timeout=IA_S3_REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            log.warning("IA S3 PUT raised: %s", exc)
            return PublisherResult(error=True, detail=f"transport failure: {exc}")

        if response.status_code in (200, 201):
            return PublisherResult(ok=True, detail=f"item {payload.target!r} uploaded")
        return PublisherResult(
            error=True,
            detail=f"IA S3 PUT HTTP {response.status_code}: {response.text[:160]}",
        )


__all__ = [
    "DEFAULT_IA_S3_ALLOWLIST",
    "IA_S3_ENDPOINT",
    "IA_S3_REQUEST_TIMEOUT_S",
    "IA_S3_SURFACE",
    "InternetArchiveS3Publisher",
]
