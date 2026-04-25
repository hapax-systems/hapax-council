"""alphaXiv comments publisher (PUB-P3 — arXiv-downstream comment loop).

Single orchestrator entry-point that POSTs an artifact's
attribution-block to the alphaXiv comment endpoint for a given
arXiv-mirrored paper. alphaXiv comments are the lowest-friction
arXiv-downstream amplification surface in the Refusal-Brief
FULL_AUTO tier (Agent A academic synthesis 2026-04-25): the comment
attaches discussion to a paper that already exists on arXiv, so no
write-API on arXiv itself is required.

## Auth

Bearer-token authentication. Operator generates a token via alphaXiv
account settings and exports via hapax-secrets:

  HAPAX_ALPHAXIV_TOKEN     # bearer token, opaque
  HAPAX_ALPHAXIV_API_URL   # base API URL, e.g. https://api.alphaxiv.org

Without either, ``publish_artifact`` returns ``no_credentials`` and
the orchestrator records the per-surface log entry without retrying.
The base URL is operator-overridable so the publisher continues to
work if alphaXiv changes its API host (the public API is undocumented
as of 2026-04 — the exposed env-var lets the operator pin to whatever
endpoint the surface lands on).

## Targeting

The comment endpoint is keyed on an arXiv paper ID. The publisher
extracts the ID from the artifact's DOI when it matches the canonical
``10.48550/arXiv.<id>`` form (the arXiv-minted-DOI shape registered
with Crossref); artifacts whose DOI is not an arXiv-mirrored paper
return ``dropped``, which is terminal in the orchestrator (no retry,
no surface-error counter).
"""

from __future__ import annotations

import logging
import os
import re

import requests

log = logging.getLogger(__name__)

ALPHAXIV_COMMENT_TIMEOUT_S: float = float(os.environ.get("HAPAX_ALPHAXIV_TIMEOUT_S", "10"))
ALPHAXIV_COMMENT_TEXT_LIMIT = 4096

_ARXIV_DOI_RE = re.compile(r"^10\.48550/arXiv\.([0-9a-zA-Z./_-]+)$")


def publish_artifact(artifact) -> str:  # type: ignore[no-untyped-def]
    """Dispatch a ``PreprintArtifact`` to alphaXiv as a paper comment.

    Static entry-point consumed by ``agents/publish_orchestrator``'s
    surface registry. Returns one of: ``ok | denied | auth_error |
    error | no_credentials | dropped``. Never raises.

    ``dropped`` covers the structural case where the artifact has no
    arXiv-mirrored DOI; alphaXiv comments are paper-attached and
    artifacts without an arXiv ID have nowhere to land. Distinct from
    ``denied`` (allowlist refusal) or ``error`` (transient failure).
    """
    token, base_url = _credentials_from_env()
    if not (token and base_url):
        return "no_credentials"

    arxiv_id = _arxiv_id_from_artifact(artifact)
    if arxiv_id is None:
        return "dropped"

    body = _compose_comment_body(artifact)
    if not body:
        return "error"

    try:
        return _post_comment(base_url, token, arxiv_id, body)
    except requests.RequestException:
        log.exception("alphaxiv POST raised for artifact %s", getattr(artifact, "slug", "?"))
        return "error"


def _arxiv_id_from_artifact(artifact) -> str | None:  # type: ignore[no-untyped-def]
    """Extract an arXiv ID from the artifact's DOI, if present.

    Recognises the canonical Crossref form ``10.48550/arXiv.<id>``.
    Returns ``None`` when the artifact carries no DOI or carries a
    non-arXiv DOI (e.g. Zenodo).
    """
    doi = getattr(artifact, "doi", None)
    if not doi:
        return None
    match = _ARXIV_DOI_RE.match(doi.strip())
    return match.group(1) if match else None


def _compose_comment_body(artifact) -> str:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to alphaXiv comment text.

    Prefers the artifact's ``attribution_block`` so per-artifact
    framing (Refusal Brief clause + ORCID + co-publisher line) stays
    authoritative. Falls back to ``"{title} — {abstract}"``. Truncated
    to ``ALPHAXIV_COMMENT_TEXT_LIMIT`` (4096) to mirror the other
    publishers' single-block sizing.
    """
    title = getattr(artifact, "title", "") or ""
    abstract = getattr(artifact, "abstract", "") or ""
    attribution = getattr(artifact, "attribution_block", "") or ""

    if attribution:
        body = attribution
    elif abstract:
        body = f"{title} — {abstract}"
    else:
        body = title or "hapax — publication artifact"

    return body[:ALPHAXIV_COMMENT_TEXT_LIMIT]


def _post_comment(base_url: str, token: str, arxiv_id: str, body: str) -> str:
    """POST a comment to alphaXiv. Maps HTTP outcomes to result codes.

    The endpoint shape ``{base_url}/papers/{arxiv_id}/comments`` is
    derived from the public alphaXiv URL convention
    (``alphaxiv.org/abs/<arxiv_id>``); the operator pins the actual
    base via ``HAPAX_ALPHAXIV_API_URL`` so a change in alphaXiv's API
    host or routing shape can be absorbed without a code change.

    Maps:
    - 200/201 → ``ok``
    - 401/403 → ``auth_error`` (token rejected)
    - 4xx other → ``denied`` (e.g. 404 unknown paper, 422 malformed)
    - 5xx     → ``error`` (transient)
    """
    url = f"{base_url.rstrip('/')}/papers/{arxiv_id}/comments"
    response = requests.post(
        url,
        json={"body": body},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=ALPHAXIV_COMMENT_TIMEOUT_S,
    )

    if response.status_code in (200, 201):
        return "ok"
    if response.status_code in (401, 403):
        log.warning("alphaxiv auth rejected (status=%d)", response.status_code)
        return "auth_error"
    if 400 <= response.status_code < 500:
        log.warning(
            "alphaxiv refused comment for %s (status=%d, body=%s)",
            arxiv_id,
            response.status_code,
            response.text[:200],
        )
        return "denied"
    log.warning("alphaxiv server error for %s (status=%d)", arxiv_id, response.status_code)
    return "error"


def _credentials_from_env() -> tuple[str | None, str | None]:
    token = os.environ.get("HAPAX_ALPHAXIV_TOKEN", "").strip() or None
    url = os.environ.get("HAPAX_ALPHAXIV_API_URL", "").strip() or None
    return token, url


__all__ = [
    "ALPHAXIV_COMMENT_TEXT_LIMIT",
    "publish_artifact",
]
