"""Zenodo publisher — Phase 2 PUB-P2-B (cleanest fully-automated DOI surface).

Receives ``PreprintArtifact`` instances dispatched from
``agents.publish_orchestrator`` and creates+publishes a Zenodo
deposition (record) at ``https://zenodo.org/api/``, minting a DOI on
publish.

## Why Zenodo

Per the 2026-04-25 4-cluster automation-tractability audit, Zenodo is
the **cleanest fully-automated DOI minter** that survives the
full-automation-or-no-engagement directive:

- REST API at ``https://zenodo.org/api/`` — no captcha, no editorial
  intake, no per-deposition human review
- Free OAuth-style PAT, 100 req/min (authenticated), 5000 req/hour
- Full versioning, GitHub integration, DataCite-backed DOI minting
  on publish
- One-time-human only at PAT issuance + community claim — both fold
  cleanly into the directive's bootstrap allowance

Per ``feedback_full_automation_or_no_engagement.md``: this is the
primary academic-citation backbone target.

## Auth

Personal Access Token authentication. Operator generates a token at
``https://zenodo.org/account/settings/applications/tokens/new/`` with
scopes ``deposit:write`` + ``deposit:actions`` and exports via
hapax-secrets:

  HAPAX_ZENODO_TOKEN          # PAT, opaque string
  HAPAX_ZENODO_API_BASE       # default ``"https://zenodo.org/api"``
                              # (use sandbox.zenodo.org for staging)

Without the token, the publisher returns ``"no_credentials"`` (the
orchestrator treats this as terminal per ``_TERMINAL_RESULTS``).

## Dispatch contract

``publish_artifact(artifact)`` returns one of:

- ``"ok"``            — deposition created + DOI minted, response captured
- ``"no_credentials"`` — env var not set; terminal
- ``"auth_error"``    — 401/403 from API
- ``"rate_limited"``  — 429 from API (re-queue)
- ``"error"``         — anything else (terminal)

## Composition

Default ``upload_type=publication`` + ``publication_type=preprint``
since the workflow targets research-preprint shape. The artifact's
``co_authors`` map to Zenodo's ``creators`` array. ``attribution_block``
(when set) is prepended to ``description`` so V5 byline framing
travels with the DOI metadata. ``access_right=open`` + a default
license (CC-BY-4.0) so the DOI is immediately citable. Operator
overrides any field via per-artifact metadata (Phase 2.B.2).

## Phase 2 scope

This Part 1 ships the metadata-only create+publish path. File upload
(POST to ``depositions/<id>/files`` with the artifact's body_md as
``<slug>.md``) is the Phase 2.B.2 follow-up — Zenodo allows publish
without files when the deposition is metadata-only, with the DOI
landing as a citable record either way.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import httpx

from shared.preprint_artifact import PreprintArtifact

log = logging.getLogger(__name__)

ZENODO_API_BASE_DEFAULT = "https://zenodo.org/api"
ZENODO_TOKEN_ENV = "HAPAX_ZENODO_TOKEN"
ZENODO_API_BASE_ENV = "HAPAX_ZENODO_API_BASE"

DEFAULT_UPLOAD_TYPE = "publication"
DEFAULT_PUBLICATION_TYPE = "preprint"
DEFAULT_ACCESS_RIGHT = "open"
DEFAULT_LICENSE = "cc-by-4.0"

REQUEST_TIMEOUT_S = 30.0


def publish_artifact(artifact: PreprintArtifact) -> str:
    """Create + publish a Zenodo deposition from a ``PreprintArtifact``.

    Two-step API: POST create, POST publish action. The publish step
    mints the DOI. Returns the orchestrator-recognized result string.

    See module docstring for return-string semantics.
    """
    token = os.environ.get(ZENODO_TOKEN_ENV, "").strip()
    api_base = os.environ.get(ZENODO_API_BASE_ENV, "").strip() or ZENODO_API_BASE_DEFAULT

    if not token:
        log.info(
            "%s not set; refusing Zenodo dispatch for %s",
            ZENODO_TOKEN_ENV,
            artifact.slug,
        )
        return "no_credentials"

    payload = _build_create_payload(artifact)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        create_resp = httpx.post(
            f"{api_base}/deposit/depositions",
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT_S,
        )
    except httpx.RequestError:
        log.exception("Zenodo create-deposition request failed for %s", artifact.slug)
        return "error"

    create_verdict = _interpret_response(create_resp, artifact.slug, action="create")
    if create_verdict != "ok":
        return create_verdict

    deposition_id = _extract_deposition_id(create_resp, artifact.slug)
    if deposition_id is None:
        return "error"

    try:
        publish_resp = httpx.post(
            f"{api_base}/deposit/depositions/{deposition_id}/actions/publish",
            headers=headers,
            timeout=REQUEST_TIMEOUT_S,
        )
    except httpx.RequestError:
        log.exception("Zenodo publish request failed for %s", artifact.slug)
        return "error"

    publish_verdict = _interpret_response(publish_resp, artifact.slug, action="publish")
    if publish_verdict == "ok":
        log.info(
            "Zenodo DOI minted for %s (deposition_id=%d)",
            artifact.slug,
            deposition_id,
        )
    return publish_verdict


def _build_create_payload(artifact: PreprintArtifact) -> dict:
    """Render ``PreprintArtifact`` into Zenodo metadata schema.

    Defaults: ``upload_type=publication`` + ``publication_type=preprint``,
    ``access_right=open`` + ``license=cc-by-4.0``. Operator overrides via
    per-artifact metadata (Phase 2.B.2).
    """
    description = _compose_description_with_attribution(artifact)
    creators = _render_creators(artifact)
    publication_date = datetime.now(UTC).strftime("%Y-%m-%d")

    metadata: dict = {
        "title": artifact.title,
        "upload_type": DEFAULT_UPLOAD_TYPE,
        "publication_type": DEFAULT_PUBLICATION_TYPE,
        "description": description or artifact.title,
        "creators": creators,
        "publication_date": publication_date,
        "access_right": DEFAULT_ACCESS_RIGHT,
        "license": DEFAULT_LICENSE,
    }

    return {"metadata": metadata}


def _compose_description_with_attribution(artifact: PreprintArtifact) -> str:
    """Prepend ``attribution_block`` (V5 byline) onto the description.

    Per the co-publishing + unsettled-contribution constitutional
    directive, the V5 byline travels with the DOI metadata so future
    citations carry the framing. ``abstract`` follows the byline
    block.
    """
    attribution = artifact.attribution_block or ""
    abstract = artifact.abstract or ""

    if attribution and abstract:
        return f"{attribution}\n\n{abstract}"
    return attribution or abstract


def _render_creators(artifact: PreprintArtifact) -> list[dict]:
    """Map ``co_authors`` to Zenodo's ``creators`` array.

    Each creator: ``{"name": str}`` minimum, with optional ``url`` field
    when the CoAuthor carries one. Falls back to a single Hapax-named
    creator when the artifact carries no co-authors (defensive — the
    Pydantic default populates ALL_CO_AUTHORS).

    Note: the canonical ``CoAuthor`` model in ``shared.co_author_model``
    does not yet carry ``affiliation`` or ``orcid`` fields; both are
    Zenodo-optional. Add them here once the model gains those fields.
    """
    creators: list[dict] = []
    for co in artifact.co_authors:
        entry: dict = {"name": co.name}
        creators.append(entry)

    if not creators:
        creators.append({"name": "Hapax (entity)"})

    return creators


def _extract_deposition_id(response: httpx.Response, slug: str) -> int | None:
    """Pull the deposition id from a successful create response."""
    try:
        body = response.json()
    except ValueError:
        log.error("Zenodo create returned non-JSON for %s: %s", slug, response.text[:200])
        return None
    deposition_id = body.get("id")
    if not isinstance(deposition_id, int):
        log.error(
            "Zenodo create returned no integer id for %s: %s",
            slug,
            str(body)[:200],
        )
        return None
    return deposition_id


def _interpret_response(response: httpx.Response, slug: str, *, action: str) -> str:
    """Map HTTP status → orchestrator result string."""
    status = response.status_code
    if 200 <= status < 300:
        log.info("Zenodo %s succeeded for %s (status=%d)", action, slug, status)
        return "ok"
    if status in (401, 403):
        log.warning("Zenodo auth error on %s for %s (status=%d)", action, slug, status)
        return "auth_error"
    if status == 429:
        log.warning(
            "Zenodo rate-limited on %s for %s; will retry next tick",
            action,
            slug,
        )
        return "rate_limited"
    log.error(
        "Zenodo %s failed for %s (status=%d body=%s)",
        action,
        slug,
        status,
        response.text[:500],
    )
    return "error"


__all__ = ["publish_artifact"]
