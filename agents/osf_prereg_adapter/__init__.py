"""Orchestrator adapter for V5 OSFPreregPublisher."""

from __future__ import annotations

import logging
import os

from agents.publication_bus.osf_prereg_publisher import OSFPreregPublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.preprint_artifact import PreprintArtifact

log = logging.getLogger(__name__)

TOKEN_ENV = "HAPAX_OSF_TOKEN"


def publish_artifact(artifact: PreprintArtifact) -> str:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        log.info("OSF token not in env; refusing dispatch for %s", artifact.slug)
        return "auth_error"

    publisher = OSFPreregPublisher(token=token)
    payload = PublisherPayload(
        target=artifact.slug,
        text=artifact.body_md or artifact.abstract,
        metadata={"title": artifact.title},
    )
    result = publisher.publish(payload)

    if result.ok:
        return "ok"
    if result.refused:
        if (
            "credentials" in (result.detail or "").lower()
            or "token" in (result.detail or "").lower()
        ):
            return "auth_error"
        return "denied"
    if result.error:
        return "error"
    return "error"


__all__ = ["TOKEN_ENV", "publish_artifact"]
