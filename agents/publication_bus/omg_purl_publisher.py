"""omg.lol PURL Publisher subclass."""

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

OMG_PURL_SURFACE = "omg-lol-purl"

DEFAULT_OMG_PURL_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_PURL_SURFACE,
    permitted=["hapax", "legomena"],
)


class OmgLolPurlPublisher(Publisher):
    """Create or overwrite an omg.lol PURL through the publication bus."""

    surface_name: ClassVar[str] = OMG_PURL_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_PURL_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, client: Any) -> None:
        self.client = client

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not getattr(self.client, "enabled", True):
            return PublisherResult(refused=True, detail="omg-lol client disabled")

        name = str(payload.metadata.get("name") or "").strip()
        if not name:
            return PublisherResult(refused=True, detail="missing purl name")
        result = self.client.create_purl(payload.target, name=name, url=payload.text)
        if result is None:
            log.warning("omg.lol purl create returned None")
            return PublisherResult(error=True, detail="create_purl returned None")
        return PublisherResult(ok=True, detail=f"purl:{payload.target}:{name}")


__all__ = [
    "DEFAULT_OMG_PURL_ALLOWLIST",
    "OMG_PURL_SURFACE",
    "OmgLolPurlPublisher",
]
