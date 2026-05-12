"""omg.lol web-page Publisher subclass."""

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

OMG_WEB_SURFACE = "omg-lol-web"

DEFAULT_OMG_WEB_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_WEB_SURFACE,
    permitted=["hapax"],
)


class OmgLolWebPublisher(Publisher):
    """Publish the operator profile HTML page through the publication bus."""

    surface_name: ClassVar[str] = OMG_WEB_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_WEB_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, client: Any) -> None:
        self.client = client

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not getattr(self.client, "enabled", True):
            return PublisherResult(refused=True, detail="omg-lol client disabled")

        publish = bool(payload.metadata.get("publish", True))
        result = self.client.set_web(payload.target, content=payload.text, publish=publish)
        if result is None:
            log.warning("omg.lol web publish returned None")
            return PublisherResult(error=True, detail="set_web returned None")
        return PublisherResult(ok=True, detail=f"web:{payload.target}")


__all__ = [
    "DEFAULT_OMG_WEB_ALLOWLIST",
    "OMG_WEB_SURFACE",
    "OmgLolWebPublisher",
]
