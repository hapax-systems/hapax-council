"""Orchestrator adapter for V5 BlueskyPublisher (operator + oudepode identities).

Translates a ``PreprintArtifact`` arriving from
``publish_orchestrator.SURFACE_REGISTRY`` into the V5 publisher's
``PublisherPayload`` shape, calls the publisher, and maps the
``PublisherResult`` back to the orchestrator's documented result
string vocabulary (``ok | denied | auth_error | error``).

## Identity routing

Two entry-points, one per identity (mirrors
``agents/omg_weblog_publisher`` operator + oudepode pattern):

- ``publish_artifact(artifact)`` — operator identity. Resolves
  ``HAPAX_BLUESKY_HANDLE`` (preferred) / ``HAPAX_BLUESKY_DID``
  (fallback — atproto createSession accepts either) plus
  ``HAPAX_BLUESKY_APP_PASSWORD`` (sourced from
  ``pass bluesky/operator-app-password``).
- ``publish_artifact_oudepode(artifact)`` — oudepode identity (per
  operator-referent-policy ``project_operator_referent_policy.md``,
  Oudepode is the canonical non-formal alias). Resolves
  ``HAPAX_BLUESKY_OUDEPODE_HANDLE`` / ``HAPAX_BLUESKY_OUDEPODE_DID``
  plus ``HAPAX_BLUESKY_OUDEPODE_APP_PASSWORD`` (sourced from
  ``pass bluesky/oudepode-app-password``).

Both share the same dispatch / payload composition logic. Identity
selection happens at the orchestrator layer (per surface_registry slug)
or per-VOD via ``shared.operator_referent.OperatorReferentPicker``
when integrated downstream.

cc-task ``bluesky-atproto-oudepode-identity-followup`` (WSJF 4.5)
closes the multi-identity gap left by Phase 1: the originally-named
slug ``bluesky-atproto-multi-identity`` carried the multi-identity
contract but only the operator identity was wired. The oudepode entry
adopts the established pattern from ``omg_weblog_publisher`` (PR #1441).
"""

from __future__ import annotations

import logging
import os

from agents.publication_bus.bluesky_publisher import BlueskyPublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.preprint_artifact import PreprintArtifact

log = logging.getLogger(__name__)

# Operator identity env vars.
HANDLE_ENV = "HAPAX_BLUESKY_HANDLE"
DID_ENV = "HAPAX_BLUESKY_DID"
APP_PASSWORD_ENV = "HAPAX_BLUESKY_APP_PASSWORD"

# Oudepode identity env vars (per operator-referent-policy parallel rail).
OUDEPODE_HANDLE_ENV = "HAPAX_BLUESKY_OUDEPODE_HANDLE"
OUDEPODE_DID_ENV = "HAPAX_BLUESKY_OUDEPODE_DID"
OUDEPODE_APP_PASSWORD_ENV = "HAPAX_BLUESKY_OUDEPODE_APP_PASSWORD"


def _resolve_identifier(handle_env: str, did_env: str) -> str:
    handle = os.environ.get(handle_env, "").strip()
    if handle:
        return handle
    return os.environ.get(did_env, "").strip()


def _publish_via_identity(
    artifact: PreprintArtifact,
    *,
    handle_env: str,
    did_env: str,
    app_password_env: str,
    identity_label: str,
) -> str:
    """Common dispatch path for any identity. ``identity_label`` is
    used in log lines so cred-missing refusals identify which identity
    failed."""
    identifier = _resolve_identifier(handle_env, did_env)
    app_password = os.environ.get(app_password_env, "").strip()

    if not identifier or not app_password:
        log.info(
            "Bluesky %s creds not in env (handle/DID + app-password); refusing dispatch for %s",
            identity_label,
            artifact.slug,
        )
        return "auth_error"

    publisher = BlueskyPublisher(handle=identifier, app_password=app_password)

    payload = PublisherPayload(
        target=artifact.slug,
        text=_compose_post_text(artifact),
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
    log.warning("publication_bus.bluesky[%s]: result with no flag set: %r", identity_label, result)
    return "error"


def publish_artifact(artifact: PreprintArtifact) -> str:
    """Dispatch via the operator identity (system-side surface)."""
    return _publish_via_identity(
        artifact,
        handle_env=HANDLE_ENV,
        did_env=DID_ENV,
        app_password_env=APP_PASSWORD_ENV,
        identity_label="operator",
    )


def publish_artifact_oudepode(artifact: PreprintArtifact) -> str:
    """Dispatch via the oudepode identity (music-side / non-formal surface).

    Sibling entry-point for the operator's oudepode identity per the
    referent policy. The hapax/operator account carries the system-side
    surface (Manifesto, Refusal Brief, governance disclosures); the
    oudepode account carries the music-side surface (cohort disclosures,
    release-window companion notes). Cross-linking happens at artifact
    authorship time, not at publish time — this function is just the
    credential + identity selector.
    """
    return _publish_via_identity(
        artifact,
        handle_env=OUDEPODE_HANDLE_ENV,
        did_env=OUDEPODE_DID_ENV,
        app_password_env=OUDEPODE_APP_PASSWORD_ENV,
        identity_label="oudepode",
    )


def _compose_post_text(artifact: PreprintArtifact) -> str:
    title = (artifact.title or "").strip()
    abstract = (artifact.abstract or "").strip()
    if title and abstract:
        candidate = f"{title}\n\n{abstract}"
    else:
        candidate = title or abstract or artifact.slug

    if len(candidate) > 280:
        candidate = candidate[:277].rstrip() + "..."
    return candidate


__all__ = [
    "APP_PASSWORD_ENV",
    "DID_ENV",
    "HANDLE_ENV",
    "OUDEPODE_APP_PASSWORD_ENV",
    "OUDEPODE_DID_ENV",
    "OUDEPODE_HANDLE_ENV",
    "publish_artifact",
    "publish_artifact_oudepode",
]
