"""Bluesky ATProto Publisher.

Per cc-task ``pub-bus-bluesky-atproto-multi-identity``. Direct ATProto
posting to the operator's Bluesky DID. Drop 5 §3 ranked this lower
than Bridgy (which handles the common case), but the direct path is
needed for posts that need different framing per identity (academic
conference threads from operator vs infrastructure-facts from hapax).

This module ships the V5 publication-bus keystone subclass with the
canonical invariants (allowlist gate + legal-name leak guard +
Counter) and a 2-step ATProto auth flow:

  1. POST createSession with handle + app-password → accessJwt + did
  2. POST createRecord with Bearer accessJwt → at:// URI + cid

Both steps are bare-`requests` HTTP — no `atproto` Python lib
dependency. ATProto's XRPC API is straightforward HTTP+JSON; adding
the lib would expand runtime surface for marginal ergonomic gain.

Endpoint: ``https://bsky.social/xrpc/`` (public-facing PDS proxy).

Orchestrator dispatch (was previously called part of "Phase 2") has
shipped: ``agents/bluesky_atproto_adapter/`` is registered in
``surface_registry`` under the ``bluesky-atproto-multi-identity``
surface_name as the ``publish_artifact`` entry-point; the
publish-orchestrator can dispatch a ``PreprintArtifact`` through the
publisher via the standard surface hand-off.

The remaining (still-deferred) follow-on:

- Per-identity rate limiting (≤1 post / 5 min) — no rate-limit code
  path exists today.
- Identity → DID resolution from ``config/bluesky-identities.yaml`` —
  config file does not exist; the adapter currently dispatches a
  single configured handle.
- Multi-DID dispatch via composed publisher instances — depends on
  the identities config above.

Until those land, the publisher dispatches a single configured DID
through the adapter.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

BLUESKY_SURFACE: str = "bluesky-atproto-multi-identity"
"""Stable surface identifier; mirrored in
:data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

BLUESKY_POST_SURFACE: str = "bluesky-post"
"""Legacy/public-event Bluesky surface, now backed by this bus publisher."""

BLUESKY_ATPROTO_ENDPOINT: str = "https://bsky.social/xrpc"
"""Public Bluesky PDS XRPC endpoint root."""

BLUESKY_REQUEST_TIMEOUT_S: float = 30.0

DEFAULT_BLUESKY_ALLOWLIST: AllowlistGate = load_allowlist(
    BLUESKY_SURFACE,
    permitted=[],
)
"""Empty default allowlist — operator-curated identity strings
(e.g., ``operator``, ``hapax``) added via class-level reassignment."""

DEFAULT_BLUESKY_POST_ALLOWLIST: AllowlistGate = load_allowlist(
    BLUESKY_POST_SURFACE,
    permitted=["hapax"],
)
"""Default allowlist for the operator-owned public-event Bluesky account."""


class BlueskyPublisher(Publisher):
    """Posts a single record to one Bluesky DID via ATProto XRPC.

    ``payload.target`` is the identity string (mapped to a DID via
    operator config); ``payload.text`` is the post body. The publisher
    does its own session establishment per call (no token caching in
    Phase 1; Phase 2 may add session reuse + ≤1-post/5-min rate limit).
    """

    surface_name: ClassVar[str] = BLUESKY_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_BLUESKY_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, handle: str, app_password: str) -> None:
        self.handle = handle
        self.app_password = app_password

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not (self.handle and self.app_password):
            return PublisherResult(
                refused=True,
                detail=(
                    "missing Bluesky credentials "
                    "(operator-action queue: pass insert bluesky/operator-app-password)"
                ),
            )
        if requests is None:
            return PublisherResult(error=True, detail="requests library not available")

        login_result = self._create_session()
        if login_result.error or login_result.refused:
            return login_result

        # Stash the parsed session payload on the result for forwarding to
        # the createRecord step. We deliberately keep this in-method local
        # so we don't hold ATProto state across publish calls in Phase 1.
        return self._create_post(login_result, payload.text)

    def _create_session(self) -> PublisherResult:
        url = f"{BLUESKY_ATPROTO_ENDPOINT}/com.atproto.server.createSession"
        try:
            response = requests.post(
                url,
                json={"identifier": self.handle, "password": self.app_password},
                timeout=BLUESKY_REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            log.warning("Bluesky createSession raised: %s", exc)
            return PublisherResult(error=True, detail=f"transport failure: {exc}")

        if response.status_code != 200:
            return PublisherResult(
                error=True,
                detail=f"createSession HTTP {response.status_code}: {response.text[:160]}",
            )
        try:
            data = response.json()
        except ValueError:
            return PublisherResult(error=True, detail="createSession returned non-JSON body")

        access_jwt = data.get("accessJwt")
        did = data.get("did")
        if not (access_jwt and did):
            return PublisherResult(
                error=True, detail="createSession response missing accessJwt or did"
            )
        # Encode session into the result.detail; _create_post unpacks via parameters.
        return PublisherResult(ok=True, detail=f"{did}|{access_jwt}")

    def _create_post(self, session: PublisherResult, text: str) -> PublisherResult:
        did, access_jwt = session.detail.split("|", 1)
        url = f"{BLUESKY_ATPROTO_ENDPOINT}/com.atproto.repo.createRecord"
        record = {
            "repo": did,
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": _now_iso(),
            },
        }
        try:
            response = requests.post(
                url,
                json=record,
                headers={"Authorization": f"Bearer {access_jwt}"},
                timeout=BLUESKY_REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            log.warning("Bluesky createRecord raised: %s", exc)
            return PublisherResult(error=True, detail=f"transport failure: {exc}")

        if response.status_code in (200, 201):
            try:
                data = response.json()
                return PublisherResult(ok=True, detail=str(data.get("uri", "")))
            except ValueError:
                return PublisherResult(ok=True, detail="post created")
        return PublisherResult(
            error=True,
            detail=f"createRecord HTTP {response.status_code}: {response.text[:160]}",
        )


class BlueskyPostPublisher(BlueskyPublisher):
    """Bus-backed publisher for the ``bluesky-post`` public-event surface."""

    surface_name: ClassVar[str] = BLUESKY_POST_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_BLUESKY_POST_ALLOWLIST


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "BLUESKY_ATPROTO_ENDPOINT",
    "BLUESKY_POST_SURFACE",
    "BLUESKY_REQUEST_TIMEOUT_S",
    "BLUESKY_SURFACE",
    "BlueskyPostPublisher",
    "BlueskyPublisher",
    "DEFAULT_BLUESKY_ALLOWLIST",
    "DEFAULT_BLUESKY_POST_ALLOWLIST",
]
