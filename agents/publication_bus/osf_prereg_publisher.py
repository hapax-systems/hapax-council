"""OSF preregistration publisher — Phase 1.

Per cc-task ``cold-contact-osf-preregistration``. OSF (Open Science
Framework) preregistrations are pre-analysis commitments to a research
plan; per drop 2 §3 mechanic #4, they accept a "related works" section
that allows daemon-tractable cross-referencing of named-target outputs
in the cold-contact candidate registry.

Distinction from :mod:`agents.osf_preprint_publisher`: the preprint
publisher mints OSF preprint DOIs (``/v2/preprints/``); this publisher
files OSF preregistrations (``/v2/registrations/``). Different OSF
endpoint, different content semantics, distinct surface_name in the
publication-bus.

Phase 1 (this module) ships the V5 Publisher ABC subclass with the
three load-bearing invariants (allowlist gate + legal-name leak guard +
canonical Counter), a minimal ``requests``-based POST against the OSF
v2 API, and surface-registry entry. The ``osf-prereg`` surface is
``FULL_AUTO`` once the operator provisions ``HAPAX_OSF_TOKEN`` (one-
time bootstrap action).

Phase 2 will wire the preregistration daemon
(``agents/osf_prereg_publisher/``) that drafts preregistration body +
auto-populates ``## Related works`` from the cold-contact candidate
registry and dispatches via this publisher.

Endpoint: ``https://api.osf.io/v2/registrations/``
Authorization: ``Bearer <PAT>`` (OSF Personal Access Token)
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

OSF_PREREG_SURFACE: str = "osf-prereg"
"""Stable surface identifier; mirrored in
:data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

OSF_API_BASE: str = "https://api.osf.io/v2"
"""OSF v2 REST API root. Preregistrations under ``/registrations/``."""

OSF_REQUEST_TIMEOUT_S: float = 30.0
"""Preregistration POSTs are small JSON payloads; 30s is generous."""

DEFAULT_OSF_PREREG_ALLOWLIST: AllowlistGate = load_allowlist(
    OSF_PREREG_SURFACE,
    permitted=[],
)
"""Empty default allowlist — operator-curated preregistration slugs
added via class-level reassignment (matches IA / Bluesky convention)."""


class OSFPreregPublisher(Publisher):
    """Files one OSF preregistration via the v2 REST API.

    ``payload.target`` is the preregistration slug (e.g.,
    ``hapax-presence-bayesian-2026-q2``). ``payload.text`` is the
    preregistration body (markdown-ish; OSF stores as plain text in
    description). ``payload.metadata`` may include ``title`` —
    rendered into the JSON:API attributes envelope.

    Refusal-as-data: missing ``HAPAX_OSF_TOKEN`` emits ``refused`` with
    ``credentials`` / ``token`` in the detail string. The Phase 1
    daemon path is structurally complete; the operator-action queue
    item is ``pass insert osf/api-token``.
    """

    surface_name: ClassVar[str] = OSF_PREREG_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OSF_PREREG_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, token: str) -> None:
        self.token = token

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not self.token:
            return PublisherResult(
                refused=True,
                detail=(
                    "missing OSF credentials (operator-action queue: pass insert osf/api-token)"
                ),
            )
        if requests is None:
            return PublisherResult(error=True, detail="requests library not available")

        url = f"{OSF_API_BASE}/registrations/"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/vnd.api+json",
        }
        title = str(payload.metadata.get("title") or payload.target)
        body = {
            "data": {
                "type": "registrations",
                "attributes": {
                    "title": title,
                    "description": payload.text,
                    "category": "project",
                },
            },
        }
        try:
            response = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=OSF_REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            log.warning("OSF prereg POST raised: %s", exc)
            return PublisherResult(error=True, detail=f"transport failure: {exc}")

        status = response.status_code
        if 200 <= status < 300:
            return PublisherResult(
                ok=True, detail=f"prereg {payload.target!r} filed (HTTP {status})"
            )
        if status in (401, 403):
            return PublisherResult(
                error=True,
                detail=f"OSF auth error HTTP {status}: {response.text[:160]}",
            )
        if status == 429:
            return PublisherResult(
                error=True,
                detail=f"OSF rate limited HTTP 429: {response.text[:160]}",
            )
        return PublisherResult(
            error=True,
            detail=f"OSF prereg POST HTTP {status}: {response.text[:160]}",
        )


__all__ = [
    "DEFAULT_OSF_PREREG_ALLOWLIST",
    "OSF_API_BASE",
    "OSF_PREREG_SURFACE",
    "OSF_REQUEST_TIMEOUT_S",
    "OSFPreregPublisher",
]
