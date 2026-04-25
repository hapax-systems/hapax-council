"""OSF preprint publisher — Phase 2 PUB-P2-A.

Receives ``PreprintArtifact`` instances dispatched from
``agents.publish_orchestrator`` and creates an OSF preprint via the v2
REST API at ``https://api.osf.io/v2/``.

## Why OSF

OSF (Open Science Framework, hosted by the Center for Open Science) is
the canonical open-archival venue for preprints across multiple
disciplinary mirrors (PsyArXiv, SocArXiv, EarthArXiv, etc.). DOI-minting
on accept; durable archival URL; bot-permissive culture as long as
attribution is honest. Cleanly-scoped engineering target — token-based
auth, 10k req/day, no human-in-the-loop captcha.

## Auth

Personal Access Token authentication. Operator generates a token at
``https://accounts.osf.io/applications/`` and exports via hapax-secrets:

  HAPAX_OSF_TOKEN              # PAT, opaque string
  HAPAX_OSF_PROVIDER           # default ``"osf"``; can be ``"psyarxiv"`` etc.

Without the token, the publisher returns ``"deferred"`` — the
orchestrator will re-queue the artifact each tick until the token
appears. Mirrors the omg.lol publisher pattern from ``ytb-OMG2``.

## Dispatch contract

``publish_artifact(artifact)`` returns one of:

- ``"ok"``        — preprint created, response captured
- ``"deferred"``  — no token / retry next tick
- ``"auth_error"`` — 401/403 from API
- ``"rate_limited"`` — 429 from API (re-queue)
- ``"error"``     — anything else (terminal; orchestrator gives up)

Per ``agents.publish_orchestrator.orchestrator._TERMINAL_RESULTS``,
``deferred`` and ``rate_limited`` re-queue; the rest move the surface
to terminal state.

## Composition

The artifact's ``title`` + ``abstract`` + ``body_md`` map directly to
OSF's preprint fields. ``co_authors`` are rendered into the abstract
preamble until the OSF contributors API supports auto-create from
strings (today it requires existing OSF user IDs, which the operator
hasn't provisioned — Phase 2.B.2 will wire up the contributors lookup).

## Phase 2 scope

This Part 1 ships the PreprintArtifact → OSF API skeleton with a
single create-preprint POST. Multi-step file upload (POST to
``preprints/<id>/files/``) + publish-toggle (PATCH the ``published``
attribute) ship in subsequent parts as the operator validates the
preprint flow end-to-end with real tokens.
"""

from __future__ import annotations

import logging
import os

import httpx

from shared.preprint_artifact import PreprintArtifact

log = logging.getLogger(__name__)

OSF_API_BASE = os.environ.get("HAPAX_OSF_API_BASE", "https://api.osf.io/v2")
OSF_TOKEN_ENV = "HAPAX_OSF_TOKEN"
OSF_PROVIDER_ENV = "HAPAX_OSF_PROVIDER"
DEFAULT_PROVIDER = "osf"

REQUEST_TIMEOUT_S = 30.0


def publish_artifact(artifact: PreprintArtifact) -> str:
    """Create an OSF preprint from a ``PreprintArtifact``.

    See module docstring for return-string semantics.
    """
    token = os.environ.get(OSF_TOKEN_ENV, "").strip()
    provider = os.environ.get(OSF_PROVIDER_ENV, "").strip() or DEFAULT_PROVIDER

    if not token:
        log.info(
            "%s not set; deferring OSF preprint dispatch for %s",
            OSF_TOKEN_ENV,
            artifact.slug,
        )
        return "deferred"

    payload = _build_create_payload(artifact, provider=provider)

    try:
        response = httpx.post(
            f"{OSF_API_BASE}/preprints/",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/vnd.api+json",
            },
            timeout=REQUEST_TIMEOUT_S,
        )
    except httpx.RequestError:
        log.exception("OSF API request failed for %s", artifact.slug)
        return "error"

    return _interpret_response(response, artifact.slug)


def _build_create_payload(artifact: PreprintArtifact, *, provider: str) -> dict:
    """Render ``PreprintArtifact`` into OSF v2 JSON:API payload.

    OSF v2 takes JSON:API documents — ``data.type`` + ``data.attributes``
    + ``data.relationships`` shape. The provider relationship is
    required at create time; tags + license can land later.
    """
    composed_abstract = _compose_abstract_with_attribution(artifact)
    return {
        "data": {
            "type": "preprints",
            "attributes": {
                "title": artifact.title,
                "description": composed_abstract,
                "is_published": False,
            },
            "relationships": {
                "provider": {
                    "data": {
                        "type": "preprint-providers",
                        "id": provider,
                    },
                },
            },
        },
    }


def _compose_abstract_with_attribution(artifact: PreprintArtifact) -> str:
    """Prepend attribution byline + co-authors to the abstract.

    Until OSF's contributors API supports auto-create from string names
    (today requires existing OSF user IDs), the co-author cluster is
    surfaced in the abstract preamble. The ``attribution_block`` field
    of the artifact takes precedence when set.
    """
    if artifact.attribution_block:
        prefix = artifact.attribution_block
    else:
        names = ", ".join(co.name for co in artifact.co_authors)
        prefix = f"Authors: {names}." if names else ""

    if not prefix:
        return artifact.abstract
    if not artifact.abstract:
        return prefix
    return f"{prefix}\n\n{artifact.abstract}"


def _interpret_response(response: httpx.Response, slug: str) -> str:
    """Map HTTP status → orchestrator result string."""
    status = response.status_code
    if 200 <= status < 300:
        log.info("OSF preprint created for %s (status=%d)", slug, status)
        return "ok"
    if status in (401, 403):
        log.warning("OSF auth error for %s (status=%d)", slug, status)
        return "auth_error"
    if status == 429:
        log.warning("OSF rate-limited for %s; will retry next tick", slug)
        return "rate_limited"
    log.error(
        "OSF preprint create failed for %s (status=%d body=%s)",
        slug,
        status,
        response.text[:500],
    )
    return "error"


__all__ = ["publish_artifact"]
