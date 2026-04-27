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
``agents/publication_bus/wire_status.py``. Fan-out path: refusal
annexes published to omg-weblog become source URLs that Bridgy
crawls and forwards to the operator's authorized Mastodon + Bluesky.
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


def _source_url_for_artifact(artifact: PreprintArtifact) -> str:
    """Construct the source URL Bridgy will crawl for ``artifact``.

    omg-weblog publishes ``PreprintArtifact`` instances under their
    canonical slug at ``{address}.omg.lol/weblog/{slug}`` (per
    ``agents/omg_weblog_publisher/publisher.py::publish_artifact``,
    which calls ``OmgLolClient.set_entry(address, artifact.slug, ...)``).
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


__all__ = ["WEBLOG_TARGET_URL", "publish_artifact"]
