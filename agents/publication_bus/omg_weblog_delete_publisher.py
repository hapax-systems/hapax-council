"""Controlled omg.lol weblog-delete Publisher subclass."""

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

OMG_WEBLOG_DELETE_SURFACE = "omg-lol-weblog-delete"

DEFAULT_OMG_WEBLOG_DELETE_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_WEBLOG_DELETE_SURFACE,
    permitted=[],
)


class OmgLolWeblogDeletePublisher(Publisher):
    """Delete a tightly allowlisted omg.lol weblog entry through the bus."""

    surface_name: ClassVar[str] = OMG_WEBLOG_DELETE_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_WEBLOG_DELETE_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, client: Any, address: str = "hapax") -> None:
        self.client = client
        self.address = address

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not getattr(self.client, "enabled", True):
            return PublisherResult(refused=True, detail="omg-lol client disabled")

        address = str(payload.metadata.get("address") or self.address)
        result = self.client.delete_entry(address, payload.target)
        if result is None:
            log.warning("omg.lol weblog delete returned None")
            return PublisherResult(error=True, detail="delete_entry returned None")
        return PublisherResult(ok=True, detail=f"weblog-delete:{address}:{payload.target}")


__all__ = [
    "DEFAULT_OMG_WEBLOG_DELETE_ALLOWLIST",
    "OMG_WEBLOG_DELETE_SURFACE",
    "OmgLolWeblogDeletePublisher",
]
