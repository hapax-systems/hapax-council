"""PhilArchive deposit publisher.

Per cc-task ``pub-bus-philarchive-deposit`` and V5 weave §2.2.
PhilArchive (https://philarchive.org/) is the philosophy-of-mind /
philosophy-of-tech preprint repository; it indexes drop-2 named-target
audience-vector authors (Yuk Hui, Wendy Chun, Helen Hester, etc.) and
is the primary academic-credible deposit surface for Hapax's
Constitutional Brief and Manifesto class artefacts.

This module ships the V5 Publisher ABC subclass with the three
load-bearing invariants (allowlist gate + canonical Counter; the
legal-name guard is *opted into* via ``requires_legal_name=True``
because PhilArchive's author field formally requires the operator's
legal name). Transport is form-POST to ``/deposit`` with a session
cookie obtained via one-time operator bootstrap.

The ``philarchive-deposit`` surface is registered as
``CONDITIONAL_ENGAGE`` because the credential bootstrap (creating an
account + extracting a session cookie from a logged-in browser) is a
one-time human action per the surface_registry definition. After
bootstrap, daemon dispatch is fully automated.

Orchestrator dispatch path (was previously called "Phase 2") has
shipped: ``agents/philarchive_adapter/`` is registered in
``surface_registry`` as the ``publish_artifact`` entry-point for
``philarchive-deposit``; the publish-orchestrator can dispatch a
``PreprintArtifact`` through the publisher via the standard surface
hand-off. The remaining (still-deferred) half is the Zenodo
``RelatedIdentifier`` ``IsAlternativeIdentifier`` cross-linkage —
when a Constitutional Brief lands at PhilArchive, it should be added
to the parallel Zenodo deposit's ``related_identifiers`` graph as
``IsAlternativeIdentifier``. No code path emits that edge today.

Endpoint: ``https://philarchive.org/deposit``
Authorization: session cookie (PHPSESSID-style) from logged-in browser
"""

from __future__ import annotations

import json
import logging
import re
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

PHILARCHIVE_SURFACE: str = "philarchive-deposit"
"""Stable surface identifier; mirrored in the canonical
:data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

PHILARCHIVE_DEPOSIT_ENDPOINT: str = "https://philarchive.org/deposit"
"""PhilArchive's deposit endpoint. PhilArchive does not publish a
documented JSON API; the deposit form is the canonical surface and
returns either JSON (when authenticated client requests it) or HTML
(default form response). The publisher parses both."""

PHILARCHIVE_REQUEST_TIMEOUT_S: float = 60.0
"""PhilArchive deposits include the full artefact body as a form
field; 60s is generous for typical Constitutional Brief / Manifesto
class lengths."""

DEFAULT_PHILARCHIVE_ALLOWLIST: AllowlistGate = load_allowlist(
    PHILARCHIVE_SURFACE,
    permitted=[],
)
"""Empty default allowlist — operator-curated artefact slugs added
via class-level reassignment (matches IA / Bluesky / OSF pattern)."""


class PhilArchivePublisher(Publisher):
    """Deposits one Constitutional Brief / Manifesto artefact to PhilArchive.

    ``payload.target`` is the artefact slug (e.g.,
    ``constitutional-brief-2026``); ``payload.text`` is the deposit
    body; ``payload.metadata`` may include ``title``.

    Refusal-as-data: missing session cookie or author ID emits
    ``refused`` with ``credentials`` in the detail string. The
    operator-action queue items are
    ``pass insert philarchive/session-cookie`` and
    ``pass insert philarchive/author-id``.

    ``requires_legal_name=True`` because PhilArchive's author field
    requires the operator's formal name per ORCID linkage; the
    legal-name leak guard in the Publisher ABC is therefore skipped
    for this surface.
    """

    surface_name: ClassVar[str] = PHILARCHIVE_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_PHILARCHIVE_ALLOWLIST
    requires_legal_name: ClassVar[bool] = True

    def __init__(self, *, session_cookie: str, author_id: str) -> None:
        self.session_cookie = session_cookie
        self.author_id = author_id

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not (self.session_cookie and self.author_id):
            return PublisherResult(
                refused=True,
                detail=(
                    "missing PhilArchive credentials "
                    "(operator-action queue: pass insert philarchive/session-cookie + author-id)"
                ),
            )
        if requests is None:
            return PublisherResult(error=True, detail="requests library not available")

        title = str(payload.metadata.get("title") or payload.target)
        form_data = {
            "title": title,
            "abstract": payload.text,
            "author_id": self.author_id,
            "category": "constitutional-brief",
        }
        headers = {
            "Cookie": self.session_cookie,
            "Accept": "application/json, text/html",
        }
        try:
            response = requests.post(
                PHILARCHIVE_DEPOSIT_ENDPOINT,
                data=form_data,
                headers=headers,
                timeout=PHILARCHIVE_REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            log.warning("PhilArchive deposit POST raised: %s", exc)
            return PublisherResult(error=True, detail=f"transport failure: {exc}")

        status = response.status_code
        if 200 <= status < 300:
            deposit_id = _parse_deposit_id(response.text)
            return PublisherResult(
                ok=True,
                detail=f"PhilArchive deposit {deposit_id or '<id-unparsed>'} accepted",
            )
        return PublisherResult(
            error=True,
            detail=f"PhilArchive deposit HTTP {status}: {response.text[:160]}",
        )


_HTML_REC_HREF_RE = re.compile(r'href="/rec/([A-Za-z0-9_-]+)"')
"""PhilArchive's HTML deposit-confirmation pages link the new record
via ``<a href="/rec/{id}">``. Used as fallback when the response is
HTML rather than JSON."""


def _parse_deposit_id(response_text: str) -> str | None:
    """Best-effort parse of a PhilArchive deposit ID from response text.

    PhilArchive returns JSON when the client signals ``Accept:
    application/json`` (preferred form); falls back to HTML when the
    server-side form-handler decides not to honor that. The publisher
    handles both shapes.
    """
    try:
        data = json.loads(response_text)
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            return data["id"]
    except (json.JSONDecodeError, ValueError):
        pass

    match = _HTML_REC_HREF_RE.search(response_text)
    if match:
        return match.group(1)
    return None


__all__ = [
    "DEFAULT_PHILARCHIVE_ALLOWLIST",
    "PHILARCHIVE_DEPOSIT_ENDPOINT",
    "PHILARCHIVE_REQUEST_TIMEOUT_S",
    "PHILARCHIVE_SURFACE",
    "PhilArchivePublisher",
]
