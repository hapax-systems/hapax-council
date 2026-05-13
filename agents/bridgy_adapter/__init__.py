"""Orchestrator adapter for V5 BridgyPublisher.

Translates a ``PreprintArtifact`` arriving from
``publish_orchestrator.SURFACE_REGISTRY`` into the V5 publisher's
``PublisherPayload`` shape, calls the publisher, and maps the
``PublisherResult`` back to the orchestrator's documented result
string vocabulary (``ok | denied | auth_error | error``).

No credentials needed at publish time — Bridgy was OAuth'd to the
operator's downstream silos at bootstrap and reads the source URL's
microformats at crawl time.

Wires the surface slug ``bridgy-webmention-publish`` per
``agents/publication_bus/wire_status.py`` for generic weblog artifacts.
Refusal-annex artifacts are blocked here until the committed path can
prove the omg-weblog source URL exists before issuing the webmention
POST.
"""

from __future__ import annotations

import logging

from agents.publication_bus.bridgy_publisher import BridgyPublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.preprint_artifact import PreprintArtifact

log = logging.getLogger(__name__)

WEBLOG_TARGET_URL = "https://hapax.omg.lol/weblog"
"""Allowlisted Bridgy webmention target. Refusal annexes are weblog
entries; if/when other surfaces (now, statuslog) need fanout, add a
target-by-slug-prefix dispatch here. Must match an entry in
``BridgyPublisher.allowlist.permitted``."""

REFUSAL_ANNEX_WEBMENTION_BLOCKER = (
    "refusal-annex Bridgy webmention is blocked until the omg-weblog source URL "
    "has a committed witness before POST"
)


def _source_url_for_artifact(artifact: PreprintArtifact) -> str:
    """Construct the source URL Bridgy will crawl for ``artifact``.

    omg-weblog publishes ``PreprintArtifact`` instances under their
    canonical slug at ``{address}.omg.lol/weblog/{slug}`` (per
    ``agents/omg_weblog_publisher/publisher.py::publish_artifact``,
    which now routes the weblog write through ``OmgLolWeblogPublisher``).
    Bridgy reads the h-entry microformats at that URL and forwards.
    """
    return f"{WEBLOG_TARGET_URL}/{artifact.slug}"


def publish_artifact(artifact: PreprintArtifact) -> str:
    """Dispatch a ``PreprintArtifact`` to Bridgy for POSSE fan-out.

    Returns one of the orchestrator's documented strings:
    ``ok | denied | error``. Never raises.

    Bridgy returns:
    - 200/201/202 → ``ok``
    - 4xx (unauthorized source URL, missing microformats) → ``denied``
    - 5xx / transport failure → ``error``
    """
    if _is_refusal_annex_artifact(artifact):
        log.warning(
            "publication_bus.bridgy: refusing refusal-annex %s: %s",
            artifact.slug,
            REFUSAL_ANNEX_WEBMENTION_BLOCKER,
        )
        return "denied"

    publisher = BridgyPublisher()
    payload = PublisherPayload(
        target=WEBLOG_TARGET_URL,
        text=_source_url_for_artifact(artifact),
        metadata={"slug": artifact.slug},
    )

    result = publisher.publish(payload)

    if result.ok:
        return "ok"
    if result.refused:
        return "denied"
    if result.error:
        return "error"
    log.warning("publication_bus.bridgy: result with no flag set: %r", result)
    return "error"


def _is_refusal_annex_artifact(artifact: PreprintArtifact) -> bool:
    """Return true for refusal-annex artifacts that are still dry-run only."""
    return artifact.slug.startswith("refusal-annex-")


__all__ = [
    "REFUSAL_ANNEX_WEBMENTION_BLOCKER",
    "WEBLOG_TARGET_URL",
    "publish_artifact",
]
