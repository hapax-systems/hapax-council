"""Orchestrator adapter for V5 PhilArchivePublisher."""

from __future__ import annotations

import logging
import os

from agents.publication_bus.philarchive_publisher import PhilArchivePublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.preprint_artifact import PreprintArtifact

log = logging.getLogger(__name__)

SESSION_COOKIE_ENV = "HAPAX_PHILARCHIVE_SESSION_COOKIE"
AUTHOR_ID_ENV = "HAPAX_PHILARCHIVE_AUTHOR_ID"


def publish_artifact(artifact: PreprintArtifact) -> str:
    session_cookie = os.environ.get(SESSION_COOKIE_ENV, "").strip()
    author_id = os.environ.get(AUTHOR_ID_ENV, "").strip()

    if not session_cookie or not author_id:
        log.info(
            "PhilArchive creds not in env (session-cookie + author-id); refusing dispatch for %s",
            artifact.slug,
        )
        return "auth_error"

    publisher = PhilArchivePublisher(session_cookie=session_cookie, author_id=author_id)
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


__all__ = ["AUTHOR_ID_ENV", "SESSION_COOKIE_ENV", "publish_artifact"]
