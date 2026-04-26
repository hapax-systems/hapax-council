"""omg.lol weblog Publisher ABC subclass — V5 publication-bus integration.

Per cc-task ``pub-bus-omg-rss`` (Phase 1b — sibling to the
fanout helper). Wraps :class:`shared.omg_lol_client.OmgLolClient` with
the V5 publication-bus invariants: AllowlistGate (per entry-id),
legal-name-leak guard, and the canonical Counter.

Use:

    client = OmgLolClient(...)
    publisher = OmgLolWeblogPublisher(client=client, address="hapax")
    result = publisher.publish(PublisherPayload(target="entry-1", text=body))

The ``target`` is the weblog entry ID; the ``address`` is set on the
publisher (one publisher instance per omg.lol address).
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

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

OMG_WEBLOG_SURFACE: str = "omg-lol-weblog-bearer-fanout"
"""Stable surface identifier; mirrored in
:data:`agents.publication_bus.surface_registry.SURFACE_REGISTRY`."""

DEFAULT_OMG_WEBLOG_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_WEBLOG_SURFACE,
    permitted=[],
)
"""Empty default allowlist — operator-curated entry IDs added via
class-level reassignment (matches the BridgyPublisher convention).
Future: dynamic allowlist sourced from a registered weblog manifest."""


class OmgLolWeblogPublisher(Publisher):
    """Publishes a single weblog entry to one operator-owned omg.lol address.

    ``payload.target`` is the weblog entry ID; ``payload.text`` is the
    raw markdown body (omg.lol expects ``Content-Type: text/markdown``).
    The address is set on the publisher (one instance per omg.lol
    address); this lets the V5 chain dispatch to multiple addresses by
    composing multiple instances rather than threading address through
    every payload.
    """

    surface_name: ClassVar[str] = OMG_WEBLOG_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_WEBLOG_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, client: Any, address: str) -> None:
        self.client = client
        self.address = address

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not getattr(self.client, "enabled", True):
            return PublisherResult(
                refused=True,
                detail="omg-lol client disabled — no operator bearer-token",
            )
        result = self.client.set_entry(self.address, payload.target, content=payload.text)
        if result is None:
            return PublisherResult(error=True, detail="omg-lol set_entry returned None")
        entry_id = result.get("id") if isinstance(result, dict) else payload.target
        return PublisherResult(ok=True, detail=str(entry_id))


__all__ = [
    "DEFAULT_OMG_WEBLOG_ALLOWLIST",
    "OMG_WEBLOG_SURFACE",
    "OmgLolWeblogPublisher",
]
