"""omg.lol statuslog Publisher subclass for awareness fanout.

This is the publication-bus adapter for the live
``agents.operator_awareness.omg_lol_fanout`` systemd path. The fanout
renderer still owns public filtering and hash-dedupe; this publisher owns
the irreversible egress invariants: allowlist gate, legal-name guard,
counter/witness, and the omg.lol REST call.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import requests

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)

log = logging.getLogger(__name__)

OMG_STATUSLOG_SURFACE = "omg-lol-statuslog"
OMG_STATUSLOG_API_URL = "https://api.omg.lol/address/{address}/statuses"

DEFAULT_OMG_STATUSLOG_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_STATUSLOG_SURFACE,
    permitted=["hapax"],
)


class OmgLolStatuslogPublisher(Publisher):
    """Publish a single statuslog entry through the publication bus."""

    surface_name: ClassVar[str] = OMG_STATUSLOG_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_STATUSLOG_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, session: Any = requests) -> None:
        self.session = session

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        token = str(payload.metadata.get("token") or "")
        if not token:
            return PublisherResult(refused=True, detail="missing bearer token")

        skip_mastodon = bool(payload.metadata.get("skip_mastodon_post", True))
        try:
            timeout_s = float(payload.metadata.get("timeout_s", 10.0))
        except (TypeError, ValueError):
            log.warning("invalid omg.lol statuslog timeout; falling back to 10s")
            timeout_s = 10.0
        url = OMG_STATUSLOG_API_URL.format(address=payload.target)
        try:
            response = self.session.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"content": payload.text, "skip_mastodon_post": skip_mastodon},
                timeout=timeout_s,
            )
        except requests.exceptions.RequestException:
            log.warning("omg.lol statuslog network error", exc_info=True)
            return PublisherResult(error=True, detail="network_error")

        if 200 <= response.status_code < 300:
            return PublisherResult(ok=True, detail="ok")
        log.warning("omg.lol statuslog HTTP %s", response.status_code)
        return PublisherResult(error=True, detail=f"http_error:{response.status_code}")


__all__ = [
    "DEFAULT_OMG_STATUSLOG_ALLOWLIST",
    "OMG_STATUSLOG_API_URL",
    "OMG_STATUSLOG_SURFACE",
    "OmgLolStatuslogPublisher",
]
