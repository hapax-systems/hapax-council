"""Orchestrator adapter for V5 RefusalBriefPublisher (Zenodo refusal-deposit).

Translates a ``PreprintArtifact`` arriving from
``publish_orchestrator._DISPATCH_MAP`` into the V5 publisher's
``PublisherPayload`` shape, calls the publisher, and maps the
``PublisherResult`` back to the orchestrator's documented result
string vocabulary (``ok | denied | auth_error | error``).

Token resolution mirrors the legacy ``agents/zenodo_publisher``:
read ``HAPAX_ZENODO_TOKEN`` from env (set by hapax-secrets.service
from pass-store ``zenodo/api-token``).

Wires the surface slug ``zenodo-refusal-deposit`` per
``agents/publication_bus/wire_status.py``.
"""

from __future__ import annotations

import logging
import os

from agents.publication_bus.publisher_kit import PublisherPayload
from agents.publication_bus.refusal_brief_publisher import RefusalBriefPublisher
from shared.preprint_artifact import PreprintArtifact

log = logging.getLogger(__name__)

ZENODO_TOKEN_ENV = "HAPAX_ZENODO_TOKEN"


def publish_artifact(artifact: PreprintArtifact) -> str:
    """Dispatch a refusal-shaped artifact to Zenodo via V5 publisher.

    Returns one of: ``ok | denied | auth_error | error``.

    The artifact's ``surfaces_targeted`` must include the surface this
    adapter is registered under (``zenodo-refusal-deposit``); routing
    happens upstream in the orchestrator. This function does not
    re-check.

    Refusal-as-data: missing token returns ``auth_error`` rather than
    raising, so the operator-action queue surfaces the gap without
    crash-restarting the orchestrator. Allowlist denial / legal-name-
    leak (the latter cannot fire here — RefusalBriefPublisher sets
    ``requires_legal_name=True``) return ``denied``.
    """
    token = os.environ.get(ZENODO_TOKEN_ENV, "").strip()
    if not token:
        log.info(
            "%s not set; refusing zenodo-refusal-deposit dispatch for %s",
            ZENODO_TOKEN_ENV,
            artifact.slug,
        )
        return "auth_error"

    publisher = RefusalBriefPublisher(zenodo_token=token)

    related_identifiers: list = []

    payload = PublisherPayload(
        target=artifact.slug,
        text=artifact.body_md or artifact.abstract,
        metadata={
            "title": artifact.title,
            "related_identifiers": related_identifiers,
        },
    )

    result = publisher.publish(payload)

    if result.ok:
        return "ok"
    if result.refused:
        # Distinguish missing-creds from allowlist/legal-name. The
        # publisher's ``_emit`` returns refused+"missing Zenodo
        # credentials" only on no-token, but the env-var check above
        # short-circuits that path; this branch covers allowlist denial.
        if "credentials" in (result.detail or "").lower():
            return "auth_error"
        return "denied"
    if result.error:
        return "error"
    log.warning("publication_bus.refusal_brief: result with no flag set: %r", result)
    return "error"


__all__ = ["ZENODO_TOKEN_ENV", "publish_artifact"]
