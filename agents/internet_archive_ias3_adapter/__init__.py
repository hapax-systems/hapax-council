"""Orchestrator adapter for V5 InternetArchiveS3Publisher."""

from __future__ import annotations

import logging
import os

from agents.publication_bus.internet_archive_publisher import InternetArchiveS3Publisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.preprint_artifact import PreprintArtifact

log = logging.getLogger(__name__)

ACCESS_KEY_ENV = "HAPAX_IA_ACCESS_KEY"
SECRET_KEY_ENV = "HAPAX_IA_SECRET_KEY"


def publish_artifact(artifact: PreprintArtifact) -> str:
    access_key = os.environ.get(ACCESS_KEY_ENV, "").strip()
    secret_key = os.environ.get(SECRET_KEY_ENV, "").strip()

    if not access_key or not secret_key:
        log.info("IA S3 creds not in env; refusing dispatch for %s", artifact.slug)
        return "auth_error"

    publisher = InternetArchiveS3Publisher(access_key=access_key, secret_key=secret_key)
    payload = PublisherPayload(
        target=artifact.slug,
        text=artifact.body_md or artifact.abstract,
        metadata={"title": artifact.title},
    )
    result = publisher.publish(payload)

    if result.ok:
        return "ok"
    if result.refused:
        if "credentials" in (result.detail or "").lower():
            return "auth_error"
        return "denied"
    if result.error:
        return "error"
    return "error"


__all__ = ["ACCESS_KEY_ENV", "SECRET_KEY_ENV", "publish_artifact"]
